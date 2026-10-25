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
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from labloop.bundle import run_bundle
from labloop.events import in_flight, read as read_events
from labloop.skills import SkillStore, card
from labloop.state import RUN_ID, RunDir, StateRoot, new_run_id

WEB = Path(__file__).parent / "web"
Submit = Callable[[dict[str, Any], str, str | None], None]


ARTIFACT_TYPES = {".pdb": "chemical/x-pdb", ".cif": "chemical/x-cif", ".json": "application/json",
                  ".png": "image/png", ".txt": "text/plain; charset=utf-8", ".pdf": "application/pdf"}


class TaskIn(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    project: str | None = Field(default=None, max_length=80)
    replan: bool | None = None
    corrects: str | None = Field(default=None, max_length=40)
    inputs: dict[str, Any] = Field(default_factory=dict)
    research_queries: list[str] | None = None


class CorrectionIn(BaseModel):
    text: str = Field(min_length=5, max_length=2000)
    by: str | None = Field(default=None, max_length=80)


class SkillRunIn(BaseModel):
    inputs: dict[str, Any]
    project: str | None = Field(default=None, max_length=80)
    description: str | None = None


def create_app(state: StateRoot, submit: Submit, call_state: Callable[[str], str | None],
               refresh_knowledge: Callable[[list[str] | None], str] | None = None,
               artifacts_root: Path | None = None, artifacts_reload: Callable[[], None] | None = None,
               record_correction: Callable[[str, str, str], str] | None = None) -> FastAPI:
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
            runs.append({"project": task.get("project") or "General",
                         "activity": events[-1] if events else None,
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
        return run_bundle(path)

    @app.post("/runs/{run_id}/corrections", status_code=202)
    def correct(run_id: str, body: CorrectionIn) -> dict[str, Any]:
        state.reload()
        if not RUN_ID.match(run_id) or not state.run_dir(run_id).exists():
            raise HTTPException(404, "unknown run")
        if record_correction is None:
            raise HTTPException(501, "corrections are not configured here")
        return {"call": record_correction(run_id, body.text, body.by or "a person"), "phase": "queued"}

    @app.get("/learning")
    def get_learning() -> dict[str, Any]:
        state.reload()
        from labloop.learning import learning
        from labloop.models import ROLE_DEFAULTS, ModelError, role_target

        routing = {}
        for role in ROLE_DEFAULTS:
            try:
                provider, model, effort = role_target(role)
                routing[role] = f"{provider}:{model}" + (f"@{effort}" if effort else "")
            except ModelError as error:
                routing[role] = str(error)
        return learning(state, routing)

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def get_report(run_id: str):
        state.reload()
        path = state.root / "reports" / run_id / "report.html"
        if not RUN_ID.match(run_id) or not path.exists():
            raise HTTPException(404, "no report for this run")
        html = path.read_text("utf-8").replace('src="figures/', f'src="/runs/{run_id}/report/figures/')
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/runs/{run_id}/report/figures/{name}")
    def get_figure(run_id: str, name: str):
        path = state.root / "reports" / run_id / "figures" / name
        if not RUN_ID.match(run_id) or "/" in name or not name.endswith(".png") or not path.exists():
            raise HTTPException(404, "no such figure")
        return FileResponse(path, media_type="image/png")

    @app.get("/artifacts/{rel:path}")
    def get_artifact(rel: str):
        if artifacts_root is None:
            raise HTTPException(501, "artifacts are not mounted here")
        path = (artifacts_root / rel).resolve()
        if artifacts_root.resolve() not in path.parents or path.suffix not in ARTIFACT_TYPES:
            raise HTTPException(404, "no such artifact")
        if not path.exists() and artifacts_reload:
            artifacts_reload()
        if not path.exists():
            raise HTTPException(404, "no such artifact")
        return FileResponse(path, media_type=ARTIFACT_TYPES[path.suffix],
                            headers={"Content-Disposition": f'inline; filename="{path.name}"'})

    @app.get("/projects")
    def projects() -> dict[str, Any]:
        state.reload()
        grouped: dict[str, dict[str, Any]] = {}
        for path in sorted(state.runs.glob("r-*")) if state.runs.exists() else []:
            run = RunDir(path)
            task = run.read_json("task.json", {}) or {}
            status = run.read_json("run.json", {}) or {}
            name = task.get("project") or "General"
            g = grouped.setdefault(name, {"name": name, "runs": 0, "PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0,
                                          "errors": 0, "running": 0, "skills_created": [], "skills_used": [],
                                          "latest": None, "recent": []})
            g["runs"] += 1
            verdict, phase = status.get("verdict"), status.get("phase")
            if phase == "done" and verdict in ("PASS", "FAIL", "INCONCLUSIVE"):
                g[verdict] += 1
            elif phase == "error":
                g["errors"] += 1
            else:
                g["running"] += 1
            sk = status.get("skill") or {}
            if sk.get("action") == "created":
                g["skills_created"].append(sk["skill"])
            elif sk.get("skill") and sk["skill"] not in g["skills_used"]:
                g["skills_used"].append(sk["skill"])
            started = (status.get("history") or [{}])[0].get("at")
            g["latest"] = max(filter(None, [g["latest"], started]), default=None)
            g["recent"] = ([{"run_id": path.name, "description": task.get("description"), "phase": phase,
                             "verdict": verdict}] + g["recent"])[:6]
        return {"projects": sorted(grouped.values(), key=lambda g: g["latest"] or "", reverse=True)}

    @app.get("/library")
    def library() -> dict[str, Any]:
        """Every report with its figures, and every paper a run or a knowledge card read."""
        state.reload()
        reports, papers = [], {}
        for path in sorted(state.runs.glob("r-*"), reverse=True) if state.runs.exists() else []:
            run = RunDir(path)
            task = run.read_json("task.json", {}) or {}
            status = run.read_json("run.json", {}) or {}
            folder = state.root / "reports" / path.name
            if (folder / "report.html").exists():
                reports.append({"run_id": path.name, "description": task.get("description"),
                                "project": task.get("project"), "verdict": status.get("verdict"),
                                "at": (status.get("history") or [{}])[0].get("at"),
                                "figures": sorted(f.name for f in (folder / "figures").glob("*.png"))})
            research = run.read_json("research/extractions.json", {}) or {}
            corpus = (research.get("corpus") or {}).get("path")
            for doc in research.get("papers") or []:
                key = doc.get("doi") or doc.get("title")
                if not key:
                    continue
                entry = papers.setdefault(key, {**{k: doc.get(k) for k in ("title", "year", "doi", "pmcid", "journal",
                                                                           "citations", "text_source")},
                                                "file": f"{corpus}/{doc['file']}" if corpus and doc.get("file") else None,
                                                "runs": []})
                entry["runs"].append(path.name)
        from labloop.knowledge import KnowledgeStore

        for c in KnowledgeStore(state.knowledge).all():
            for doc in c.get("papers", []):
                key = doc.get("doi") or doc.get("title")
                if not key:
                    continue
                entry = papers.setdefault(key, {**{k: doc.get(k) for k in ("title", "year", "doi", "pmcid", "journal",
                                                                           "citations", "text_source")},
                                                "file": (f"{c['corpus']}/{doc['file']}" if c.get("corpus")
                                                         and doc.get("file") else None), "runs": []})
                entry.setdefault("tools", []).append(c["tool"])
        return {"reports": reports, "papers": sorted(papers.values(), key=lambda p: -len(p["runs"]))}

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
                           "limitations": c.get("limitations", []), "corpus": c.get("corpus")} for c in cards]}

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
        return {"card": card(skill), "skill": skill, "consultations": skills.consultations(name)}

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
                "inputs": body.inputs, **({"project": body.project} if body.project else {})}
        submit(task, run_id, name)
        return {"run_id": run_id, "phase": "queued", "skill": name}

    return app
