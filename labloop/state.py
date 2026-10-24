"""The state root and each run's directory.

The state root holds `runs/`, `skills/` and `memory/`. On Modal it is the
`labloop-state` Volume, and `commit` and `reload` are wired to the Volume so
that every phase of a run is visible to the API container as soon as it is
written. Locally both are no-ops.

A run directory copies the harness-experiments state layout (`STATE.md`,
`ASSUMPTIONS.md`, `DECISIONS.jsonl`, `EXPERIMENTS.jsonl`, `RESULTS.json`) and
adds `task.json`, `match.json`, `research/`, `plan.json` with `plan.sha256`,
and `run.json`, the mutable status record the API reads.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Callable

TEMPLATE = Path(__file__).parent / "template"
RUN_ID = re.compile(r"^r-\d{8}-\d{6}-[0-9a-f]{6}$")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_run_id() -> str:
    return time.strftime("r-%Y%m%d-%H%M%S-", time.gmtime()) + secrets.token_hex(3)


class WriteOnceError(RuntimeError):
    pass


class StateRoot:
    def __init__(self, root: Path, commit: Callable[[], None] | None = None,
                 reload: Callable[[], None] | None = None, create: bool = True) -> None:
        self.root = Path(root)
        self._commit = commit
        self._reload = reload
        if create:
            for sub in ("runs", "skills", "memory"):
                (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def skills(self) -> Path:
        return self.root / "skills"

    @property
    def memory(self) -> Path:
        return self.root / "memory"

    def commit(self) -> None:
        if self._commit:
            self._commit()

    def reload(self) -> None:
        if self._reload:
            self._reload()

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise ValueError(f"invalid run id {run_id!r}")
        return self.runs / run_id


def from_env() -> StateRoot:
    return StateRoot(Path(os.environ.get("LABLOOP_STATE", "state")))


class RunDir:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def create(cls, path: Path, task: dict[str, Any]) -> "RunDir":
        if path.exists():
            raise WriteOnceError(f"run directory {path} already exists")
        shutil.copytree(TEMPLATE, path)
        run = cls(path)
        run.write_json("task.json", task, once=True)
        return run

    def write_json(self, name: str, document: Any, *, once: bool = False) -> Path:
        target = self.path / name
        if once and target.exists() and target.read_text("utf-8").strip() not in ("", "{}"):
            raise WriteOnceError(f"{target} is write-once and already written")
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
        tmp.replace(target)
        return target

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.path / name
        return json.loads(target.read_text("utf-8")) if target.exists() else default

    def append(self, name: str, record: dict[str, Any]) -> None:
        with (self.path / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": now(), **record}, sort_keys=True, default=str) + "\n")

    def read_jsonl(self, name: str) -> list[dict[str, Any]]:
        target = self.path / name
        if not target.exists():
            return []
        return [json.loads(l) for l in target.read_text("utf-8").splitlines() if l.strip()]

    def status(self, phase: str, **fields: Any) -> dict[str, Any]:
        record = self.read_json("run.json", {}) or {}
        record.update(fields)
        record["phase"] = phase
        record.setdefault("history", []).append({"phase": phase, "at": now()})
        self.write_json("run.json", record)
        return record

    def state_md(self, now_line: str, plan: list[tuple[str, str]], findings: list[str]) -> None:
        marks = {"todo": "[ ]", "doing": "[>]", "done": "[x]", "dropped": "[-]"}
        lines = ["# State", "", "Read this first in every session. The operator watches this file live.", "",
                 "## Now", "", now_line, "", "## Plan", ""]
        lines += [f"{marks[state]} {item}" for item, state in plan]
        lines += ["", "## Findings", ""] + [f"- {f}" for f in findings] + ["", "## Session log", "",
                                                                            f"- {now()} {now_line}", ""]
        (self.path / "STATE.md").write_text("\n".join(lines), "utf-8")

    def assume(self, text: str) -> None:
        with (self.path / "ASSUMPTIONS.md").open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {text}")
