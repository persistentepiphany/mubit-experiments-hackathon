"""labloop-backend: the JSON API and the orchestrator, on Modal.

The API is served with `@modal.asgi_app()` and only reads the `labloop-state`
Volume. Each task runs in a spawned `orchestrate` call, the only writer of
state, limited to one container so that two runs never write the skill store
at once. Keys come from the Modal Secret `labloop-keys`.

    modal secret create labloop-keys MUBIT_API_KEY=... ZAI_API_KEY=... [MOONSHOT_API_KEY=...] [MUBIT_PROJECT_ID=...]
    modal deploy modal_apps/backend_app.py
    modal run modal_apps/backend_app.py::retire --name <skill> --by "<person>" --reason "<why>"
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

app = modal.App("labloop-backend")

STATE = Path("/state")
ARTIFACTS = Path("/artifacts")
state_volume = modal.Volume.from_name("labloop-state", create_if_missing=True)
artifacts_volume = modal.Volume.from_name("labloop-artifacts", create_if_missing=True)
calls = modal.Dict.from_name("labloop-calls", create_if_missing=True)
keys = modal.Secret.from_name("labloop-keys")
# Per-role model overrides (LABLOOP_MODEL_<ROLE>, LABLOOP_PAPERQA_LLM, ...). Edit this secret to reroute
# every role without a code change.
routing = modal.Secret.from_name("labloop-routing")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("anthropic==2.3.0", "mubit-sdk==0.13.2", "fastapi[standard]==0.162.0", "pydantic>=2.9",
                    "jsonschema>=4.20", "PyYAML>=6.0")
)
_ppi = os.environ.get("PPI_HARNESS_PATH")
if _ppi and Path(_ppi).is_dir():
    # ppi-assure is optional; when a checkout is given at deploy time it is shipped for the domain grader.
    image = image.env({"PPI_HARNESS_PATH": "/opt/ppi-harness"}).add_local_dir(
        _ppi, "/opt/ppi-harness", ignore=[".git", "fixtures", "tests", "benchmarks"])
image = image.add_local_python_source("labloop", ignore=["**/__pycache__/**", "**/*.pyc"])


@app.function(image=image, volumes={STATE: state_volume, ARTIFACTS: artifacts_volume}, secrets=[keys, routing],
              timeout=3 * 60 * 60, max_containers=1)
def orchestrate(task: dict, run_id: str, force_skill: str | None = None) -> dict:
    from labloop import memory
    from labloop.dispatch import ModalDispatcher
    from labloop.graders import default_graders
    from labloop.models import AnthropicModels
    from labloop.orchestrator import Loop
    from labloop.state import StateRoot

    state_volume.reload()
    state = StateRoot(STATE, commit=state_volume.commit, reload=state_volume.reload)
    loop = Loop(state, models=AnthropicModels(), dispatcher=ModalDispatcher(),
                memory=memory.from_env(state.memory), graders=default_graders(),
                artifacts_root=ARTIFACTS, artifacts_reload=artifacts_volume.reload)
    return loop.run_task(task, run_id=run_id, force_skill=force_skill)


@app.function(image=image, volumes={STATE: state_volume}, secrets=[keys, routing], timeout=2 * 60 * 60,
              max_containers=1)
def ingest_knowledge(tools: list[str] | None = None, job_id: str | None = None) -> list[dict]:
    """Read every catalogued model's method papers on Modal and store a knowledge card per tool."""
    import secrets
    import time

    from labloop import catalog, memory
    from labloop.dispatch import ModalDispatcher
    from labloop.events import Events
    from labloop.knowledge import KnowledgeStore, ingest
    from labloop.models import AnthropicModels
    from labloop.state import RunDir, StateRoot

    state_volume.reload()
    state = StateRoot(STATE, commit=state_volume.commit, reload=state_volume.reload)
    job_id = job_id or time.strftime("j-%Y%m%d-%H%M%S-", time.gmtime()) + secrets.token_hex(3)
    job = RunDir(state.jobs / job_id)
    job.path.mkdir(parents=True, exist_ok=True)
    tools = tools or sorted(catalog.with_papers())
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    job.write_json("job.json", {"kind": "knowledge", "phase": "running", "tools": tools, "started_at": started})
    emit = Events(job.path / "EVENTS.jsonl", state_volume.commit).emit
    emit("info", f"Knowledge refresh started for {len(tools)} tools: {', '.join(tools)}")
    mem = memory.from_env(state.memory)
    try:
        reports = ingest(tools, store=KnowledgeStore(state.knowledge), dispatcher=ModalDispatcher(),
                         models=AnthropicModels(), memory=mem, run_id=job_id, emit=emit)
        errors = list(getattr(mem, "errors", []))
        if errors:
            emit("info", f"Mubit memory and skill writes were refused ({len(errors)} times); cards and lessons are "
                         f"kept on the state Volume. Last error: {errors[-1][:160]}")
        job.write_json("job.json", {"kind": "knowledge", "phase": "done", "tools": tools, "started_at": started,
                                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "reports": reports, "mubit_errors": errors[-3:]})
        emit("info", f"Knowledge refresh finished: {sum(1 for r in reports if 'version' in r)} of {len(tools)} cards saved")
    except Exception as error:
        job.write_json("job.json", {"kind": "knowledge", "phase": "error", "tools": tools, "started_at": started,
                                    "error": f"{type(error).__name__}: {error}"})
        emit("error", f"Knowledge refresh stopped: {type(error).__name__}: {str(error)[:300]}")
        raise
    state_volume.commit()
    return reports


@app.local_entrypoint()
def ingest(tools: str = "") -> None:
    import json

    print(json.dumps(ingest_knowledge.remote([t for t in tools.split(",") if t] or None), indent=1))


@app.function(image=image, volumes={STATE: state_volume}, max_containers=1)
def retire_skill(name: str, by: str, reason: str) -> dict:
    """The human path to retiring a skill. No model call reaches this function."""
    from labloop.skills import SkillStore, card
    from labloop.state import StateRoot

    state_volume.reload()
    state = StateRoot(STATE)
    skill = SkillStore(state.skills).retire(name, by=by, reason=reason)
    state_volume.commit()
    return card(skill)


@app.local_entrypoint()
def retire(name: str, by: str, reason: str) -> None:
    print(retire_skill.remote(name, by, reason))


@app.function(image=image, volumes={STATE: state_volume}, scaledown_window=300)
@modal.asgi_app()
def api():
    from labloop.api import create_app
    from labloop.state import StateRoot

    state = StateRoot(STATE, reload=state_volume.reload, create=False)

    def submit(task: dict, run_id: str, force_skill: str | None) -> None:
        call = orchestrate.spawn(task, run_id, force_skill)
        calls[run_id] = call.object_id

    def call_state(run_id: str) -> str | None:
        if not calls.contains(run_id):
            return None
        try:
            modal.FunctionCall.from_id(calls[run_id]).get(timeout=0)
        except TimeoutError:
            return "queued"
        except Exception as error:
            return f"the orchestrator call failed before writing state: {type(error).__name__}: {error}"
        return "the orchestrator call finished without writing state"

    def refresh_knowledge(tools: list[str] | None) -> str:
        import secrets
        import time

        job_id = time.strftime("j-%Y%m%d-%H%M%S-", time.gmtime()) + secrets.token_hex(3)
        ingest_knowledge.spawn(tools, job_id)
        return job_id

    return create_app(state, submit, call_state, refresh_knowledge)
