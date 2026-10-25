"""Model calls by role, all in the Anthropic Messages format.

Each role has a fixed system prompt (see `prompts.py`) and a default provider
and model, written `provider:model` or `provider:model@effort` and overridable
with the environment variable `LABLOOP_MODEL_<ROLE>`. The effort, one of low,
medium, high, xhigh and max, is sent as `output_config.effort`. The gateway groups calls with the same model
and the same instructions into one task, so the instructions never carry
task-specific text and each role keeps one model unless it is overridden.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from labloop import prompts

PROVIDERS: dict[str, dict[str, Any]] = {
    "mubit": {"base_url": "https://api.mubit.ai/anthropic", "key_env": ("MUBIT_API_KEY", "MUBIT_API_TOKEN")},
    "zai": {"base_url": "https://api.z.ai/api/anthropic", "key_env": ("ZAI_API_KEY",)},
}

ROLE_DEFAULTS = {
    "planner": "mubit:claude-opus-4-8@high",
    "researcher": "mubit:claude-haiku-5-5",
    "extractor": "mubit:claude-haiku-5-5",
    "applicability": "mubit:claude-haiku-5-5",
    "reviewer": "mubit:claude-opus-4-8@high",
    "corrector": "mubit:claude-haiku-5-5",
}

# GLM models that always reason; the rest take `thinking: disabled` and answer directly.
ZAI_ALWAYS_THINKS = {"glm-5.3"}

# List prices in USD per million input and output tokens, for the cost column of the call ledger.
# A model missing here has its cost left blank rather than guessed; LABLOOP_PRICE_<MODEL> ("in,out")
# adds one, with the model id upper-cased and its dots and dashes written as underscores.
PRICES = {"claude-opus-4-8": (5.0, 25.0), "claude-opus-5": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0),
          "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50)}


def price(model: str) -> tuple[float, float] | None:
    override = os.environ.get("LABLOOP_PRICE_" + re.sub(r"[^A-Za-z0-9]", "_", model).upper())
    if override:
        try:
            a, b = (float(x) for x in override.split(","))
            return a, b
        except ValueError:
            return None
    return PRICES.get(model)


def prompt_digest(role: str) -> str:
    """Identifies a role's fixed instructions; the gateway groups calls into one task by them."""
    return hashlib.sha256(prompts.SYSTEM[role].encode()).hexdigest()[:12]


class Ledger:
    """Every model call a client makes, kept until drained into a run's CALLS.jsonl."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # Called with each call as it is recorded; returns True when it stored the call itself.
        self.sink: Callable[[dict[str, Any]], bool] | None = None

    def record(self, role: str, run_id: str, provider: str, model: str, started: float, *, ok: bool,
               input_tokens: int = 0, output_tokens: int = 0, error: str | None = None,
               stop_reason: str | None = None) -> None:
        rates = price(model)
        cost = (input_tokens * rates[0] + output_tokens * rates[1]) / 1e6 if rates else None
        call = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "role": role,
                "run_id": run_id, "provider": provider, "model": model,
                "recorded_by_mubit": provider == "mubit", "prompt_digest": prompt_digest(role),
                "latency_s": round(time.time() - started, 2), "input_tokens": input_tokens,
                "output_tokens": output_tokens, "cost_usd": round(cost, 6) if cost is not None else None,
                "ok": ok, "stop_reason": stop_reason, "error": error}
        if not (self.sink and self.sink(call)):
            self.calls.append(call)

    def drain(self, run_id: str | None = None) -> list[dict[str, Any]]:
        taken = [c for c in self.calls if run_id is None or c["run_id"] == run_id]
        self.calls = [c for c in self.calls if c not in taken]
        return taken


EFFORTS = {"low", "medium", "high", "xhigh", "max"}
# Models that take the server-side refusal fallback, which reroutes a declined request by refusal category.
FALLBACK_MODELS = {"claude-opus-5", "claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class Models(Protocol):
    def complete(self, role: str, user: str, *, run_id: str, max_tokens: int = 4096) -> Reply: ...


def role_target(role: str) -> tuple[str, str, str | None]:
    spec = os.environ.get(f"LABLOOP_MODEL_{role.upper()}") or ROLE_DEFAULTS[role]
    provider, _, model = spec.partition(":")
    model, _, effort = model.partition("@")
    if effort and effort not in EFFORTS:
        raise ModelError(f"effort {effort!r} for role {role} must be one of {sorted(EFFORTS)}")
    if provider not in PROVIDERS or not model:
        raise ModelError(f"model spec {spec!r} for role {role} must be provider:model, provider one of {sorted(PROVIDERS)}")
    return provider, model, effort or None


def _key(provider: str) -> str | None:
    for name in PROVIDERS[provider]["key_env"]:
        if os.environ.get(name):
            return os.environ[name]
    return None


class AnthropicModels:
    """Calls each role's provider with the `anthropic` SDK."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self.ledger = Ledger()

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
        provider, model, effort = role_target(role)
        started = time.time()
        try:
            try:
                reply = self._complete(role, user, run_id, provider, model, effort, max_tokens)
            except ModelError as error:
                fallback = os.environ.get("LABLOOP_ZAI_FALLBACK", "glm-5.1")
                if provider != "zai" or model == fallback or "tokens before answering" not in str(error):
                    raise
                # A reasoning model spent its whole budget thinking; ask a model that answers directly.
                self.ledger.record(role, run_id, provider, model, started, ok=False, error=str(error)[:200])
                started, model = time.time(), fallback
                reply = self._complete(role, user, run_id, provider, model, effort, max_tokens)
        except Exception as error:
            self.ledger.record(role, run_id, provider, model, started, ok=False,
                               error=f"{type(error).__name__}: {str(error)[:200]}")
            raise
        self.ledger.record(role, run_id, provider, reply.model, started, ok=True, input_tokens=reply.input_tokens,
                           output_tokens=reply.output_tokens, stop_reason=reply.stop_reason)
        return reply

    def _complete(self, role, user, run_id, provider, model, effort, max_tokens) -> Reply:
        kwargs: dict[str, Any] = {}
        if provider == "mubit":
            kwargs["metadata"] = {"user_id": run_id}  # the gateway's session key on Anthropic calls
        if effort and provider != "zai":
            kwargs["output_config"] = {"effort": effort}
            max_tokens = max(max_tokens, 16000)  # thinking at higher effort shares this budget with the answer
        if provider == "zai":
            if model in ZAI_ALWAYS_THINKS:
                # These cannot turn reasoning off; a capped budget and a large limit leave room for the answer.
                max_tokens = max(max_tokens, 64000)
                kwargs["thinking"] = {"type": "enabled",
                                      "budget_tokens": int(os.environ.get("LABLOOP_ZAI_THINKING_BUDGET", "16000"))}
            else:
                kwargs["thinking"] = {"type": "disabled"}
        messages = self._client(provider).messages
        if provider != "zai" and model in FALLBACK_MODELS:
            messages = self._client(provider).beta.messages
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        # Streamed, because large budgets exceed the SDK's limit for a single blocking request.
        with messages.stream(model=model, max_tokens=max_tokens, system=prompts.SYSTEM[role],
                             messages=[{"role": "user", "content": user}], **kwargs) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise ModelError(f"{model} declined the {role} request: {getattr(response, 'stop_details', None)}")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if not text.strip() and response.stop_reason == "max_tokens":
            raise ModelError(f"{model} used all {max_tokens} tokens before answering the {role} request")
        usage = getattr(response, "usage", None)
        return Reply(text=text, provider=provider, model=getattr(response, "model", model),
                     input_tokens=getattr(usage, "input_tokens", 0) or 0,
                     output_tokens=getattr(usage, "output_tokens", 0) or 0, stop_reason=response.stop_reason)


class ScriptedModels:
    """Replays scripted answers per role, for offline tests.

    A script entry is a string, a JSON-serialisable object, or a callable that
    receives the user message. Every call is kept in `calls`.
    """

    def __init__(self, script: dict[str, list[Any] | Callable[[str], Any]]) -> None:
        self.script = {role: (list(v) if isinstance(v, list) else v) for role, v in script.items()}
        self.calls: list[dict[str, str]] = []
        self.ledger = Ledger()

    def complete(self, role: str, user: str, *, run_id: str, max_tokens: int = 4096) -> Reply:
        self.calls.append({"role": role, "user": user, "run_id": run_id})
        self.ledger.record(role, run_id, "scripted", "scripted", time.time(), ok=role in self.script)
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
