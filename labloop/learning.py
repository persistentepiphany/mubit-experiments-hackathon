"""What the system has learned, read back from state for the Learning view.

Four questions, each answered from files the orchestrator wrote. Which
corrections from people changed later runs, and how. Which failed runs were
followed by a passing run of the same task, and what changed in between. How
each recurring model role is routed and how its calls compare across models on
latency, tokens and cost. How fast knowledge, skills and lessons are refreshed.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from labloop import prompts
from labloop.state import RunDir, StateRoot


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def _checks(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [{k: c.get(k) for k in ("id", "metric", "op", "value", "reference", "tolerance", "source")}
            for c in (plan or {}).get("checks", [])]


def _diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """How the frozen plan changed between two runs of one task."""
    b, a = _checks(before), _checks(after)
    bm = {c["metric"]: c for c in b}
    am = {c["metric"]: c for c in a}
    changed = [{"metric": m, "before": bm[m], "after": am[m]} for m in bm.keys() & am.keys()
               if (bm[m].get("op"), bm[m].get("value"), bm[m].get("reference"))
               != (am[m].get("op"), am[m].get("value"), am[m].get("reference"))]
    return {"steps_before": [s["tool"] for s in (before or {}).get("steps", [])],
            "steps_after": [s["tool"] for s in (after or {}).get("steps", [])],
            "checks_changed": changed,
            "checks_added": [am[m] for m in am.keys() - bm.keys()],
            "checks_removed": [bm[m] for m in bm.keys() - am.keys()]}


def _runs(state: StateRoot) -> list[dict[str, Any]]:
    out = []
    # Run ids have one-second resolution, so order by when each run directory's task file was written.
    paths = sorted(state.runs.glob("r-*"), key=lambda p: ((p / "task.json").stat().st_mtime_ns
                                                          if (p / "task.json").exists() else 0, p.name)) \
        if state.runs.exists() else []
    for path in paths:
        run = RunDir(path)
        status = run.read_json("run.json", {}) or {}
        out.append({"run_id": path.name, "task": run.read_json("task.json", {}) or {}, "status": status,
                    "plan": run.read_json("plan.json"), "match": run.read_json("match.json") or {},
                    "calls": _jsonl(path / "CALLS.jsonl"), "corrections": _jsonl(path / "CORRECTIONS.jsonl"),
                    "started": (status.get("history") or [{}])[0].get("at")})
    return out


def _brief(r: dict[str, Any]) -> dict[str, Any]:
    st = r["status"]
    return {"run_id": r["run_id"], "verdict": st.get("verdict"), "phase": st.get("phase"), "at": r["started"],
            "description": r["task"].get("description")}


def corrections(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in runs:
        for c in r["corrections"]:
            follow = [x for x in runs if x["task"].get("corrects") == r["run_id"]]
            out.append({**c, "run": _brief(r), "followups": [
                {**_brief(f), "diff": _diff(r["plan"], f["plan"]),
                 "applied": [d for d in (f["plan"] or {}).get("decisions", [])
                             if c.get("rule", "")[:40].lower() in json.dumps(d).lower()
                             or "correction" in json.dumps(d).lower()]} for f in follow]})
    return out


def fixups(runs: list[dict[str, Any]], lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A non-passing run followed by a passing run of the same task, with the lessons in between."""
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        by_task[r["task"].get("description", "")].append(r)
    lesson_by_id = {l["id"]: l for l in lessons}
    out = []
    for task, group in by_task.items():
        group = [g for g in group if g["status"].get("phase") in ("done", "error")]
        for earlier, later in zip(group, group[1:]):
            if earlier["status"].get("verdict") != "PASS" and later["status"].get("verdict") == "PASS":
                bridged = [lesson_by_id[i]["content"] for i in later["match"].get("lessons", []) or []
                           if i in lesson_by_id and lesson_by_id[i].get("run_id") == earlier["run_id"]]
                out.append({"task": task, "before": _brief(earlier), "after": _brief(later),
                            "error": earlier["status"].get("error"), "lessons_carried": bridged,
                            "diff": _diff(earlier["plan"], later["plan"])})
    return out


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 2) if xs else None


def roles(calls: list[dict[str, Any]], runs: list[dict[str, Any]], routing: dict[str, str]) -> list[dict[str, Any]]:
    verdict = {r["run_id"]: r["status"].get("verdict") for r in runs}
    out = []
    for role in prompts.SYSTEM:
        mine = [c for c in calls if c["role"] == role]
        models = defaultdict(list)
        for c in mine:
            models[(c["provider"], c["model"])].append(c)
        out.append({
            "role": role, "routed_to": routing.get(role), "calls": len(mine),
            "recorded_by_mubit": sum(1 for c in mine if c.get("recorded_by_mubit")),
            "prompt_digests": sorted({c["prompt_digest"] for c in mine if c.get("prompt_digest")}),
            "by_model": [{
                "provider": p, "model": m, "calls": len(cs), "ok_rate": round(sum(c["ok"] for c in cs) / len(cs), 3),
                "median_latency_s": _median([c["latency_s"] for c in cs]),
                "median_input_tokens": _median([c["input_tokens"] for c in cs]),
                "median_output_tokens": _median([c["output_tokens"] for c in cs]),
                "cost_per_call_usd": (round(sum(c["cost_usd"] for c in cs) / len(cs), 5)
                                      if all(c.get("cost_usd") is not None for c in cs) else None),
                "recorded_by_mubit": p == "mubit",
                "runs_passed": sum(1 for c in cs if verdict.get(c["run_id"]) == "PASS"),
                "runs": len({c["run_id"] for c in cs}),
            } for (p, m), cs in sorted(models.items())],
        })
    return out


def refresh(state: StateRoot, runs: list[dict[str, Any]], lessons: list[dict[str, Any]]) -> dict[str, Any]:
    from labloop.knowledge import KnowledgeStore
    from labloop.skills import SkillStore, standing

    cards = []
    for card_path in sorted((state.knowledge / "tools").glob("*/versions/*.json")) if state.knowledge.exists() else []:
        c = json.loads(card_path.read_text())
        cards.append({"tool": c["tool"], "title": c.get("title"), "version": c.get("version"),
                      "ingested_at": c.get("ingested_at"), "numbers": len(c.get("reported_numbers", [])),
                      "guidance": len(c.get("guidance", [])), "papers": len(c.get("papers", []))})
    skills = [{"name": s["name"], "version": s["version"], "standing": standing(s), "evidence": len(s["evidence"]),
               "created_at": s.get("created_at"), "updated_at": s.get("updated_at")}
              for s in SkillStore(state.skills).list()]
    by_hour: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    import time as _time
    for l in lessons:
        hour = _time.strftime("%Y-%m-%dT%H:00Z", _time.gmtime(l.get("at", 0)))
        by_hour[hour][l.get("lesson_type") or "observation"] += 1
    return {"knowledge": cards, "skills": skills,
            "lessons_by_hour": [{"hour": h, **v} for h, v in sorted(by_hour.items())],
            "lessons_total": len(lessons), "corrections_total": sum(1 for l in lessons if l.get("lesson_type") == "correction"),
            "runs_by_hour": _runs_by_hour(runs)}


def _runs_by_hour(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in runs:
        if r["started"]:
            by[r["started"][:13] + ":00Z"][r["status"].get("verdict") or r["status"].get("phase") or "queued"] += 1
    return [{"hour": h, **v} for h, v in sorted(by.items())]


def learning(state: StateRoot, routing: dict[str, str]) -> dict[str, Any]:
    runs = _runs(state)
    lessons = _jsonl(state.memory / "lessons.jsonl")
    calls = [c for r in runs for c in r["calls"]]
    for job in sorted(state.jobs.glob("j-*")) if state.jobs.exists() else []:
        calls += _jsonl(job / "CALLS.jsonl")
    return {"corrections": corrections(runs), "fixups": fixups(runs, lessons),
            "roles": roles(calls, runs, routing), "refresh": refresh(state, runs, lessons),
            "totals": {"runs": len(runs), "passed": sum(1 for r in runs if r["status"].get("verdict") == "PASS"),
                       "calls": len(calls), "calls_recorded_by_mubit": sum(1 for c in calls if c.get("recorded_by_mubit")),
                       "runs_without_ledger": sum(1 for r in runs if not r["calls"])}}
