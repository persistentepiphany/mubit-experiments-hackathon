"""Everything recorded about one run, as one document.

The API returns it from `GET /runs/{id}` and the report generator reads it, so
both describe a run from the same files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from labloop.events import read as read_events
from labloop.state import RunDir


def run_bundle(path: Path) -> dict[str, Any]:
    run = RunDir(path)
    return {
        "run_id": path.name,
        "status": run.read_json("run.json", {}),
        "task": run.read_json("task.json"),
        "match": run.read_json("match.json"),
        "plan": run.read_json("plan.json"),
        "plan_sha256": (path / "plan.sha256").read_text().split()[0] if (path / "plan.sha256").exists() else None,
        "inputs": run.read_json("inputs.json"),
        "experiments": run.read_jsonl("EXPERIMENTS.jsonl"),
        "decisions": run.read_jsonl("DECISIONS.jsonl"),
        "results": run.read_json("RESULTS.json"),
        "research": run.read_json("research/extractions.json"),
        "events": read_events(path / "EVENTS.jsonl"),
    }
