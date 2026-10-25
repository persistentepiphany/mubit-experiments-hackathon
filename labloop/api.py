"""The JSON API.

The API never writes state. It reloads the state Volume before each read and
hands work to the orchestrator through `submit`, which on Modal spawns the
orchestrator function and records the call in a Modal Dict outside the state
Volume. A run that has been submitted but not yet started is reported as
queued.
"""

from __future__ import annotations

from typing import Any, Callable

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from labloop.events import in_flight, read as read_events
from labloop.skills import SkillStore, card
from labloop.state import RUN_ID, RunDir, StateRoot, new_run_id

WEB = Path(__file__).parent / "web"
Submit = Callable[[dict[str, Any], str, str | None], None]


class TaskIn(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    research_queries: list[str] | None = None


class SkillRunIn(BaseModel):
    inputs: dict[str, Any]
    description: str | None = None


def create_app(state: StateRoot, submit: Submit, call_state: Callable[[str], str | None],
               refresh_knowledge: Callable[[list[str] | None], str] | None = None) -> FastAPI:
    """`call_state(run_id)` is None for an unknown run, "queued" for a submitted run that has not
    written state yet, and an error message for a submitted run whose orchestrator call failed."""
    app = FastAPI(title="labloop", version="0.1.0")
    skills = SkillStore(state.skills)

    @app.post("/tasks", status_code=202)
    def post_task(task: TaskIn) -> dict[str, Any]:
        run_id = new_run_id()
        submit(task.model_dump(exclude_none=True), run_id, None)
        return {"run_id": run_id, "phase": "queued"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/runs")
    def list_runs(limit: int = 50) -> dict[str, Any]:
        state.reload()
        runs = []
        paths = sorted(state.runs.glob("r-*"), reverse=True)[: max(1, min(limit, 200))] if state.runs.exists() else []
        for path in paths:
            run = RunDir(path)
            status = run.read_json("run.json", {}) or {}
            task = run.read_json("task.json", {}) or {}
            events = read_events(path / "EVENTS.jsonl") if status.get("phase") not in ("done", "error") else []
            runs.append({"activity": events[-1] if events else None,
                         "in_flight": in_flight(events),
                         "run_id": path.name, "description": task.get("description"), "phase": status.get("phase"),
                         "verdict": status.get("verdict"), "origin": status.get("origin"),
                         "skill": status.get("skill"),
                         "started_at": (status.get("history") or [{}])[0].get("at")})
        return {"runs": runs}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        if not RUN_ID.match(run_id):
            raise HTTPException(404, "unknown run")
        state.reload()
        path = state.run_dir(run_id)
        if not path.exists():
            call = call_state(run_id)
            if call is None:
                raise HTTPException(404, "unknown run")
            if call == "queued":
                return {"run_id": run_id, "phase": "queued"}
            return {"run_id": run_id, "phase": "error", "status": {"phase": "error", "error": call}}
        run = RunDir(path)
        return {
            "run_id": run_id,
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

    @app.get("/knowledge")
    def knowledge() -> dict[str, Any]:
        state.reload()
        from labloop.knowledge import KnowledgeStore

        cards = KnowledgeStore(state.knowledge).all()
        return {"tools": [{"tool": c["tool"], "title": c.get("title"), "deployed": c.get("deployed"),
                           "summary": c.get("summary"), "version": c.get("version"),
                           "ingested_at": c.get("ingested_at"), "papers": c.get("papers", []),
                           "papers_missing": c.get("papers_missing", []), "guidance": c.get("guidance", []),
                           "reported_numbers": c.get("reported_numbers", []),
                           "limitations": c.get("limitations", [])} for c in cards]}

    @app.post("/knowledge/refresh", status_code=202)
    def refresh(tools: list[str] | None = None) -> dict[str, Any]:
        if refresh_knowledge is None:
            raise HTTPException(501, "knowledge refresh is not configured here")
        return {"job_id": refresh_knowledge(tools), "phase": "queued"}

    @app.get("/jobs")
    def list_jobs() -> dict[str, Any]:
        state.reload()
        jobs = []
        for path in sorted(state.jobs.glob("j-*"), reverse=True)[:20] if state.jobs.exists() else []:
            job = RunDir(path).read_json("job.json", {}) or {}
            events = read_events(path / "EVENTS.jsonl")
            jobs.append({**job, "job_id": path.name, "activity": events[-1] if events else None,
                         "in_flight": in_flight(events) if job.get("phase") == "running" else []})
        return {"jobs": jobs}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        state.reload()
        path = state.jobs / job_id
        if not job_id.startswith("j-") or "/" in job_id or not path.exists():
            raise HTTPException(404, "unknown job")
        return {**(RunDir(path).read_json("job.json", {}) or {}), "job_id": job_id,
                "events": read_events(path / "EVENTS.jsonl")}

    @app.get("/skills")
    def list_skills(include_retired: bool = False) -> dict[str, Any]:
        state.reload()
        return {"skills": [card(s) for s in skills.list(include_retired=include_retired)]}

    @app.get("/skills/{name}")
    def get_skill(name: str) -> dict[str, Any]:
        state.reload()
        skill = skills.get(name)
        if skill is None:
            raise HTTPException(404, "unknown skill")
        return {"card": card(skill), "skill": skill}

    @app.post("/skills/{name}/run", status_code=202)
    def run_skill(name: str, body: SkillRunIn) -> dict[str, Any]:
        state.reload()
        skill = skills.get(name)
        if skill is None:
            raise HTTPException(404, "unknown skill")
        if skill.get("retired"):
            raise HTTPException(409, "the skill is retired")
        missing = sorted(set(skill.get("input_schema", {})) - set(body.inputs))
        if missing:
            raise HTTPException(422, f"missing inputs: {missing}")
        run_id = new_run_id()
        task = {"description": body.description or f"Run skill {name}: {skill['description']}",
                "inputs": body.inputs}
        submit(task, run_id, name)
        return {"run_id": run_id, "phase": "queued", "skill": name}

    return app
