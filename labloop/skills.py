"""Skills: frozen, evidence-backed pipelines saved as versioned JSON.

A skill lives at `skills/<name>/skill.json`, with every earlier version kept
write-once under `skills/<name>/versions/`. Standing is computed from evidence
alone each time it is read, and is never stored as a field a writer could set.
A skill is a draft after one passing run, validated once it has passed on a
second task with different inputs, and retired only when a human says so.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SCHEMA = "labloop.skill/v1"
NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
MAX_LESSONS = 20


class SkillError(RuntimeError):
    pass


def standing(skill: dict[str, Any]) -> str:
    if skill.get("retired"):
        return "retired"
    passing = [e for e in skill.get("evidence", []) if e.get("verdict") == "PASS"]
    if len({e["inputs_digest"] for e in passing}) >= 2:
        return "validated"
    if passing:
        return "draft"
    return "unproven"


def tools_of(skill: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for step in skill["pipeline"]["steps"]:
        if step["tool"] not in seen:
            seen.append(step["tool"])
    return seen


def card(skill: dict[str, Any]) -> dict[str, Any]:
    evidence = skill.get("evidence", [])
    return {
        "name": skill["name"],
        "title": skill["title"],
        "description": skill["description"],
        "tools": tools_of(skill),
        "inputs": [{"name": k, **v} for k, v in skill.get("input_schema", {}).items()],
        "standing": standing(skill),
        "runs": len(evidence),
        "passes": sum(1 for e in evidence if e.get("verdict") == "PASS"),
        "version": skill["version"],
        "updated_at": skill.get("updated_at"),
        "created_by_run": skill.get("created_by_run"),
        "invocations": sum(1 for e in evidence if e.get("invocation")),
    }


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", (name or "").lower()).strip("_")
    if not text or not text[0].isalpha():
        text = f"skill_{text}".strip("_")
    return text[:64]


class SkillStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, name: str) -> Path:
        if not NAME.match(name):
            raise SkillError(f"invalid skill name {name!r}")
        return self.root / name

    def get(self, name: str) -> dict[str, Any] | None:
        try:
            path = self._dir(name) / "skill.json"
        except SkillError:
            return None
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    def list(self, include_retired: bool = True) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        skills = []
        for path in sorted(self.root.glob("*/skill.json")):
            skill = json.loads(path.read_text("utf-8"))
            if include_retired or not skill.get("retired"):
                skills.append(skill)
        return skills

    def _write(self, skill: dict[str, Any]) -> dict[str, Any]:
        directory = self._dir(skill["name"])
        versions = directory / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        snapshot = versions / f"v{skill['version']:04d}.json"
        if snapshot.exists():
            raise SkillError(f"version {skill['version']} of {skill['name']} already exists")
        body = json.dumps(skill, indent=2, sort_keys=True) + "\n"
        snapshot.write_text(body, "utf-8")
        snapshot.chmod(0o444)
        tmp = directory / "skill.json.tmp"
        tmp.write_text(body, "utf-8")
        tmp.replace(directory / "skill.json")
        return skill

    def create(self, *, meta: dict[str, Any], pipeline: dict[str, Any], input_schema: dict[str, Any],
               sources: list[Any], lessons: list[str], evidence: dict[str, Any],
               plan_digest: str, run_id: str, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        base = slug(meta.get("name", ""))
        name, n = base, 2
        while self.get(name) is not None:
            name, n = f"{base[:60]}_{n}", n + 1
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        skill = {
            "schema": SCHEMA,
            "name": name,
            "version": 1,
            "title": meta.get("title") or name,
            "description": meta.get("description", ""),
            "applies_when": list(meta.get("applies_when", [])),
            "not_for": list(meta.get("not_for", [])),
            "pipeline": {"steps": pipeline["steps"], "checks": pipeline["checks"]},
            "input_schema": input_schema,
            "lessons": lessons[:MAX_LESSONS],
            "sources": sources,
            "evidence": [evidence],
            "plan_digest": plan_digest,
            "created_by_run": run_id,
            "provenance": provenance or {},
            "created_at": now,
            "updated_at": now,
            "retired": None,
        }
        return self._write(skill)

    def append_evidence(self, name: str, evidence: dict[str, Any], lessons: list[str] = ()) -> dict[str, Any]:
        skill = self.get(name)
        if skill is None:
            raise SkillError(f"no skill named {name}")
        if any(e["run_id"] == evidence["run_id"] for e in skill["evidence"]):
            raise SkillError(f"run {evidence['run_id']} is already evidence for {name}")
        skill["evidence"].append(evidence)
        skill["lessons"] = (skill["lessons"] + [l for l in lessons if l not in skill["lessons"]])[-MAX_LESSONS:]
        skill["version"] += 1
        skill["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return self._write(skill)

    def consult(self, name: str, record: dict[str, Any]) -> None:
        """Log that a skill was considered for a run, and whether it was invoked or declined.

        The log is append-only and outside the versioned skill file, because being considered is
        not evidence and must not change a skill's version or standing.
        """
        path = self._dir(name) / "consultations.jsonl"
        if not path.parent.exists():
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **record},
                                    sort_keys=True, default=str) + "\n")

    def consultations(self, name: str) -> list[dict[str, Any]]:
        try:
            path = self._dir(name) / "consultations.jsonl"
        except SkillError:
            return []
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]

    def retire(self, name: str, *, by: str, reason: str) -> dict[str, Any]:
        """Retire a skill. Only a person may call this, and must say who and why."""
        if not by or not reason:
            raise SkillError("retiring a skill needs the name of the person and a reason")
        skill = self.get(name)
        if skill is None:
            raise SkillError(f"no skill named {name}")
        skill["retired"] = {"by": by, "reason": reason,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        skill["version"] += 1
        return self._write(skill)
