from fastapi.testclient import TestClient

from labloop.api import create_app
from labloop.memory import LocalMemory
from labloop.models import ScriptedModels
from labloop.orchestrator import Loop
from labloop.state import StateRoot
from labloop.testing import EXTRACTION, REVIEW, FakeDispatcher, esmfold_plan, reuse_answer

CONDITION = "the task asks for the structure of one protein chain given its sequence"


def test_api_round_trip(tmp_path):
    state = StateRoot(tmp_path / "state")
    models = ScriptedModels({
        "extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW, REVIEW, REVIEW],
        "applicability": [reuse_answer("esmfold_monomer_confidence", CONDITION, {"sequence": "sequence"})]})
    loop = Loop(state, models=models, dispatcher=FakeDispatcher(), memory=LocalMemory(state.memory))
    submitted = set()

    def submit(task, run_id, force_skill):
        submitted.add(run_id)
        loop.run_task(task, run_id=run_id, force_skill=force_skill)

    client = TestClient(create_app(StateRoot(state.root, create=False), submit, submitted.__contains__))
    first = client.post("/tasks", json={"description": "Fold a peptide", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    assert first.status_code == 202
    run = client.get(f"/runs/{first.json()['run_id']}").json()
    assert run["status"]["phase"] == "done" and run["results"]["verdict"] == "PASS"
    assert run["plan_sha256"] and run["experiments"][0]["tool"] == "esmfold"

    cards = client.get("/skills").json()["skills"]
    assert cards == [{**cards[0], "name": "esmfold_monomer_confidence", "tools": ["esmfold"], "standing": "draft",
                      "runs": 1, "passes": 1}]
    assert cards[0]["inputs"][0]["name"] == "sequence"

    second = client.post("/tasks", json={"description": "Fold another", "inputs": {"sequence": "MKTAYIAKQRQISF"}})
    assert client.get(f"/runs/{second.json()['run_id']}").json()["match"]["decision"] == "reuse"

    direct = client.post("/skills/esmfold_monomer_confidence/run", json={"inputs": {"sequence": "GSHMKTAYIA"}})
    assert direct.status_code == 202
    detail = client.get("/skills/esmfold_monomer_confidence").json()
    assert detail["card"]["runs"] == 3 and detail["card"]["standing"] == "validated"

    assert client.post("/skills/esmfold_monomer_confidence/run", json={"inputs": {}}).status_code == 422
    assert client.get("/skills/nope").status_code == 404
    assert client.get("/runs/r-20990101-000000-abcdef").status_code == 404
