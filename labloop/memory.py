"""Lessons across runs.

Memory is context, never authority. What is recalled here is shown to the
planner as advisory text. Nothing in this module can change a frozen plan or a
skill's standing, and the orchestrator never reads it while grading.

`LocalMemory` keeps lessons and outcomes in JSONL files and is used for tests
and when no Mubit key is set. `MubitMemory` writes every lesson to Mubit through
the explicit `mubit.Client` and to a local copy, and reads from Mubit with the
local copy as the fallback, so a Mubit outage costs recall quality and never a
run.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

AGENT_ID = "labloop"
_WORD = re.compile(r"[a-z0-9]+")


class Memory(Protocol):
    def remember(self, content: str, *, lesson_type: str, run_id: str,
                 metadata: dict[str, Any] | None = None) -> str: ...

    def context(self, query: str, *, run_id: str, limit: int = 5) -> list[dict[str, Any]]: ...

    def record_outcome(self, reference_id: str, *, outcome: str, signal: float,
                       rationale: str, run_id: str) -> None: ...

    def mirror_skill(self, skill: dict[str, Any]) -> None: ...


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


class LocalMemory:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.lessons = self.root / "lessons.jsonl"
        self.outcomes = self.root / "outcomes.jsonl"
        self.skills = self.root / "skill_mirror.jsonl"

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]

    def remember(self, content, *, lesson_type, run_id, metadata=None, item_id=None) -> str:
        item_id = item_id or f"lesson-{uuid.uuid4().hex[:12]}"
        self._append(self.lessons, {"id": item_id, "content": content, "lesson_type": lesson_type,
                                    "run_id": run_id, "metadata": metadata or {}, "at": time.time()})
        return item_id

    def context(self, query, *, run_id, limit=5):
        wanted = _words(query)
        scored = []
        for lesson in self._read(self.lessons):
            overlap = len(wanted & _words(lesson["content"]))
            if overlap:
                scored.append((overlap, lesson["at"], lesson))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [{"id": l["id"], "content": l["content"], "lesson_type": l["lesson_type"],
                 "source": "local"} for _, _, l in scored[:limit]]

    def record_outcome(self, reference_id, *, outcome, signal, rationale, run_id) -> None:
        self._append(self.outcomes, {"reference_id": reference_id, "outcome": outcome, "signal": signal,
                                     "rationale": rationale, "run_id": run_id, "at": time.time()})

    def mirror_skill(self, skill) -> None:
        self._append(self.skills, {"name": skill["name"], "version": skill["version"],
                                   "description": skill["description"], "at": time.time()})


def _entries(response: Any) -> list[dict[str, Any]]:
    """Find the list of recalled items in a Mubit response of unknown shape."""
    if isinstance(response, list):
        return [r for r in response if isinstance(r, dict)]
    if isinstance(response, dict):
        for key in ("entries", "items", "lessons", "results", "memories", "context"):
            if isinstance(response.get(key), list):
                return [r for r in response[key] if isinstance(r, dict)]
        for value in response.values():
            found = _entries(value) if isinstance(value, (dict, list)) else []
            if found:
                return found
    return []


class MubitMemory:
    def __init__(self, local: LocalMemory, *, endpoint: str | None = None,
                 project_id: str | None = None) -> None:
        import mubit

        self.local = local
        self.project_id = project_id or os.environ.get("MUBIT_PROJECT_ID")
        key = os.environ.get("MUBIT_API_KEY") or os.environ.get("MUBIT_API_TOKEN")
        kwargs: dict[str, Any] = {"run_id": "labloop", "api_key": key}
        if endpoint or os.environ.get("MUBIT_ENDPOINT"):
            kwargs["endpoint"] = endpoint or os.environ["MUBIT_ENDPOINT"]
        if os.environ.get("MUBIT_TRANSPORT"):
            kwargs["transport"] = os.environ["MUBIT_TRANSPORT"]
        self.client = mubit.Client(**kwargs)
        self.errors: list[str] = []
        self.remote = True

    def _note(self, action: str, error: Exception) -> None:
        self.errors.append(f"{action}: {type(error).__name__}: {str(error)[:200]}")
        if "unknown_route" in str(error) or type(error).__name__ == "AuthError":
            # The endpoint does not serve the memory API for this key; stop asking for the rest of the process.
            self.remote = False

    def remember(self, content, *, lesson_type, run_id, metadata=None) -> str:
        item_id = self.local.remember(content, lesson_type=lesson_type, run_id=run_id, metadata=metadata)
        if not self.remote:
            return item_id
        try:
            self.client.remember(content=content, session_id=run_id, agent_id=AGENT_ID, item_id=item_id,
                                 intent="lesson", lesson_type=lesson_type, lesson_scope="global",
                                 metadata={"run_id": run_id, **(metadata or {})})
        except Exception as error:
            self._note("remember", error)
        return item_id

    def context(self, query, *, run_id, limit=5):
        if not self.remote:
            return self.local.context(query, run_id=run_id, limit=limit)
        try:
            response = self.client.get_context(session_id=run_id, query=query, limit=limit,
                                               format="structured")
            found = []
            for entry in _entries(response)[:limit]:
                text = entry.get("content") or entry.get("text") or entry.get("summary")
                if text:
                    found.append({"id": entry.get("id") or entry.get("item_id"), "content": text,
                                  "lesson_type": entry.get("lesson_type"), "source": "mubit"})
            if found:
                return found
        except Exception as error:
            self._note("get_context", error)
        return self.local.context(query, run_id=run_id, limit=limit)

    def record_outcome(self, reference_id, *, outcome, signal, rationale, run_id) -> None:
        self.local.record_outcome(reference_id, outcome=outcome, signal=signal, rationale=rationale,
                                  run_id=run_id)
        if not self.remote:
            return
        try:
            self.client.record_outcome(reference_id=reference_id, outcome=outcome, session_id=run_id,
                                       signal=signal, rationale=rationale, agent_id=AGENT_ID)
        except Exception as error:
            self._note("record_outcome", error)

    def mirror_skill(self, skill) -> None:
        self.local.mirror_skill(skill)
        if not self.project_id or not self.remote:
            return
        try:
            self.client.create_skill({
                "project_id": self.project_id, "agent_id": "", "name": skill["name"],
                "description": skill["description"], "skill_type": "playbook",
                "parameters_schema": json.dumps(skill.get("input_schema", {})),
                "instructions": json.dumps({"applies_when": skill["applies_when"],
                                            "not_for": skill["not_for"],
                                            "version": skill["version"]}),
            })
        except Exception as error:
            self._note("create_skill", error)


def from_env(root: Path) -> Memory:
    local = LocalMemory(root)
    if os.environ.get("LABLOOP_MEMORY", "auto") == "local":
        return local
    if not (os.environ.get("MUBIT_API_KEY") or os.environ.get("MUBIT_API_TOKEN")):
        return local
    try:
        return MubitMemory(local)
    except Exception:
        return local
