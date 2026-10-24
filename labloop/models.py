"""Model calls by role, all in the Anthropic Messages format.

Each role has a fixed system prompt (see `prompts.py`) and a default provider
and model, written `provider:model` and overridable with the environment
variable `LABLOOP_MODEL_<ROLE>`. The gateway groups calls with the same model
and the same instructions into one task, so the instructions never carry
task-specific text and each role keeps one model unless it is overridden.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from labloop import prompts

PROVIDERS: dict[str, dict[str, Any]] = {
    "mubit": {"base_url": "https://api.mubit.ai/anthropic", "key_env": ("MUBIT_API_KEY", "MUBIT_API_TOKEN")},
    "zai": {"base_url": "https://api.z.ai/api/anthropic", "key_env": ("ZAI_API_KEY",)},
    "moonshot": {"base_url": "https://api.moonshot.ai/anthropic", "key_env": ("MOONSHOT_API_KEY",)},
}

ROLE_DEFAULTS = {
    "planner": "mubit:claude-sonnet-5-5",
    "researcher": "mubit:claude-haiku-5-5",
    "extractor": "mubit:claude-haiku-5-5",
    "applicability": "mubit:claude-haiku-5-5",
    "reviewer": "zai:glm-5.3",
}


class ModelError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class Models(Protocol):
    def complete(self, role: str, user: str, *, run_id: str, max_tokens: int = 4096) -> Reply: ...


def role_target(role: str) -> tuple[str, str]:
    spec = os.environ.get(f"LABLOOP_MODEL_{role.upper()}") or ROLE_DEFAULTS[role]
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or not model:
        raise ModelError(f"model spec {spec!r} for role {role} must be provider:model, provider one of {sorted(PROVIDERS)}")
    if provider == "zai" and "[" in model:
        raise ModelError(f"Z.AI takes plain model ids; {model!r} carries a bracket suffix")
    return provider, model


def _key(provider: str) -> str | None:
    for name in PROVIDERS[provider]["key_env"]:
        if os.environ.get(name):
            return os.environ[name]
    return None


class AnthropicModels:
    """Calls each role's provider with the `anthropic` SDK."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _client(self, provider: str):
        if provider not in self._clients:
            import anthropic

            key = _key(provider)
            if not key:
                raise ModelError(f"no key for provider {provider}; set one of {PROVIDERS[provider]['key_env']}")
            headers = {}
            if provider == "mubit":
                headers["x-middleware-record"] = os.environ.get("LABLOOP_MUBIT_RECORD", "full")
                headers["x-middleware-store"] = os.environ.get("LABLOOP_MUBIT_STORE", "true")
            self._clients[provider] = anthropic.Anthropic(
                base_url=PROVIDERS[provider]["base_url"], api_key=key, default_headers=headers,
                timeout=float(os.environ.get("LABLOOP_MODEL_TIMEOUT_S", "300")), max_retries=2)
        return self._clients[provider]

    def complete(self, role: str, user: str, *, run_id: str, max_tokens: int = 4096) -> Reply:
        provider, model = role_target(role)
        kwargs: dict[str, Any] = {}
        if provider == "mubit":
            kwargs["metadata"] = {"user_id": run_id}  # the gateway's session key on Anthropic calls
        response = self._client(provider).messages.create(
            model=model, max_tokens=max_tokens, system=prompts.SYSTEM[role],
            messages=[{"role": "user", "content": user}], **kwargs)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        usage = getattr(response, "usage", None)
        return Reply(text=text, provider=provider, model=model,
                     input_tokens=getattr(usage, "input_tokens", 0) or 0,
                     output_tokens=getattr(usage, "output_tokens", 0) or 0)


class ScriptedModels:
    """Replays scripted answers per role, for offline tests.

    A script entry is a string, a JSON-serialisable object, or a callable that
    receives the user message. Every call is kept in `calls`.
    """

    def __init__(self, script: dict[str, list[Any] | Callable[[str], Any]]) -> None:
        self.script = {role: (list(v) if isinstance(v, list) else v) for role, v in script.items()}
        self.calls: list[dict[str, str]] = []

    def complete(self, role: str, user: str, *, run_id: str, max_tokens: int = 4096) -> Reply:
        self.calls.append({"role": role, "user": user, "run_id": run_id})
        source = self.script.get(role)
        if source is None:
            raise ModelError(f"no scripted answer for role {role}")
        if callable(source):
            answer = source(user)
        elif source:
            answer = source.pop(0)
        else:
            raise ModelError(f"scripted answers for role {role} are exhausted")
        if callable(answer):
            answer = answer(user)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return Reply(text=text, provider="scripted", model="scripted",
                     input_tokens=len(user) // 4, output_tokens=len(text) // 4)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> Any:
    """The first JSON object in a model's answer, fenced or bare."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for candidate in candidates:
        start = candidate.find("{")
        if start < 0:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
            return obj
        except json.JSONDecodeError:
            continue
    raise ModelError(f"no JSON object in the answer: {text[:200]!r}")


def ask_json(models: Models, role: str, user: str, *, run_id: str, max_tokens: int = 4096,
             check: Callable[[Any], list[str]] | None = None, retries: int = 1) -> tuple[Any, list[Reply]]:
    """Ask a role for JSON, re-asking once with the errors when it is malformed."""
    replies: list[Reply] = []
    message = user
    for attempt in range(retries + 1):
        reply = models.complete(role, message, run_id=run_id, max_tokens=max_tokens)
        replies.append(reply)
        try:
            obj = parse_json(reply.text)
            errors = check(obj) if check else []
        except ModelError as error:
            obj, errors = None, [str(error)]
        if not errors:
            return obj, replies
        if attempt == retries:
            raise ModelError(f"{role} answer rejected: {'; '.join(errors)}")
        message = (user + "\n\n<previous_answer>\n" + reply.text[:6000] + "\n</previous_answer>\n"
                   "<errors>\n" + "\n".join(f"- {e}" for e in errors) + "\n</errors>\n"
                   "Answer again with one corrected JSON object.")
    raise AssertionError("unreachable")
