import json

import pytest

from labloop.grading import InconclusiveError, Verdict
from labloop.memory import LocalMemory
from labloop.models import ScriptedModels
from labloop.orchestrator import Loop
from labloop.pipeline import FrozenPlanError, load_frozen
from labloop.skills import SkillStore, standing
from labloop.state import StateRoot
from labloop.testing import EXTRACTION, REVIEW, FakeDispatcher, esmfold_plan, reuse_answer

CONDITION = "the task asks for the structure of one protein chain given its sequence"


def make_loop(tmp_path, script, dispatcher=None):
    state = StateRoot(tmp_path / "state")
    models = ScriptedModels(script)
    dispatcher = dispatcher or FakeDispatcher()
    loop = Loop(state, models=models, dispatcher=dispatcher, memory=LocalMemory(state.memory))
    return loop, models, dispatcher


def test_first_task_plans_runs_grades_and_saves_a_skill(tmp_path):
    loop, models, dispatcher = make_loop(tmp_path, {
        "extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW]})
    record = loop.run_task({"description": "Fold this short peptide", "inputs": {"seq": "MKTAYIAKQRQISFVKSHFSRQ"}})
    assert record["phase"] == "error"  # the plan refers to $inputs.sequence, which the task does not supply

    loop, models, dispatcher = make_loop(tmp_path / "b", {
        "researcher": [{"queries": ["\"ESMFold\" AND pLDDT"]}],
        "extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW]})
    record = loop.run_task({"description": "Fold this short peptide",
                            "inputs": {"sequence": "MKTAYIAKQRQISFVKSHFSRQ"}})
    assert record["phase"] == "done", record.get("error")
    assert record["verdict"] == "PASS"
    assert record["skill"]["action"] == "created"
    run = loop.state.run_dir(record["run_id"])
    plan, digest = load_frozen(run)
    assert (run / "plan.sha256").read_text().startswith(digest)
    results = json.loads((run / "RESULTS.json").read_text())
    assert results["verdict"] == "PASS" and results["plan_digest"] == digest
    experiments = [json.loads(l) for l in (run / "EXPERIMENTS.jsonl").read_text().splitlines()]
    assert [e["step_id"] for e in experiments] == ["fold"]
    decisions = [json.loads(l) for l in (run / "DECISIONS.jsonl").read_text().splitlines()]
    assert any(d.get("source_silent") for d in decisions)
    research = json.loads((run / "research" / "extractions.json").read_text())
    assert research["corpus"]["manifest_sha256"] and research["papers"][0]["citations"] == 5540
    assert research["paperqa"]["corpora"][-1].startswith("seed/") and research["extraction"]["reported_numbers"]
    assert [c for c, _ in dispatcher.calls[:2]] == ["literature_corpus", "paperqa"]
    from labloop.events import in_flight, read

    events = read(run / "EVENTS.jsonl")
    keys = [(e["kind"], e.get("key")) for e in events if e.get("key")]
    for key in ("match", "corpus", "paperqa", "planner", "step:fold", "reviewer"):
        assert ("start", key) in keys and ("done", key) in keys, key
    assert in_flight(events) == [] and events[-1]["message"] == "Run finished: PASS"
    assert any("fold finished in" in e["message"] and "mean_plddt 82.5" in e["message"] for e in events)
    skill = SkillStore(loop.state.skills).get("esmfold_monomer_confidence")
    assert standing(skill) == "draft"
    assert [c["role"] for c in models.calls] == ["researcher", "extractor", "planner", "reviewer"]
    assert dispatcher.calls[0][1]["queries"] == ['"ESMFold" AND pLDDT']
    planner_input = json.loads(models.calls[2]["user"])
    assert planner_input["literature"]["extraction"]["reported_numbers"][0]["value"] == 70
    assert dispatcher.calls[-1][0] == "esmfold" and dispatcher.calls[-1][1]["run_id"] == record["run_id"]


def test_second_task_reuses_the_skill_without_planning(tmp_path):
    loop, models, _ = make_loop(tmp_path, {
        "extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW, REVIEW],
        "applicability": [reuse_answer("esmfold_monomer_confidence", CONDITION, {"sequence": "protein"})]})
    first = loop.run_task({"description": "Fold this peptide", "inputs": {"sequence": "MKTAYIAKQRQISFVKSHFSRQ"}})
    assert first["verdict"] == "PASS"
    second = loop.run_task({"description": "Predict the structure of crambin",
                            "inputs": {"protein": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN"}})
    assert second["phase"] == "done", second.get("error")
    assert second["verdict"] == "PASS"
    assert second["skill"] == {"action": "evidence_appended", "skill": "esmfold_monomer_confidence",
                               "version": 2, "standing": "validated"}
    roles = [c["role"] for c in models.calls]
    assert roles.count("planner") == 1 and roles.count("extractor") == 1
    run = loop.state.run_dir(second["run_id"])
    match = json.loads((run / "match.json").read_text())
    assert match["decision"] == "reuse" and match["matched_applies_when"] == CONDITION
    plan, _ = load_frozen(run)
    assert plan["origin"] == {"kind": "skill", "skill": "esmfold_monomer_confidence", "version": 1}
    store = SkillStore(loop.state.skills)
    skill = store.get("esmfold_monomer_confidence")
    assert skill["provenance"]["run_id"] == first["run_id"] and skill["provenance"]["sourced_numbers"] == 1
    assert skill["evidence"][1]["invocation"]["via"] == "matched by the applicability role"
    assert skill["evidence"][1]["invocation"]["matched_applies_when"] == CONDITION
    consulted = store.consultations("esmfold_monomer_confidence")
    assert [c["outcome"] for c in consulted] == ["invoked"] and consulted[0]["run_id"] == second["run_id"]


def test_same_inputs_twice_keep_the_skill_a_draft(tmp_path):
    loop, _, _ = make_loop(tmp_path, {
        "extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW, REVIEW],
        "applicability": [reuse_answer("esmfold_monomer_confidence", CONDITION, {"sequence": "sequence"})]})
    task = {"description": "Fold this peptide", "inputs": {"sequence": "MKTAYIAKQRQISFVKSHFSRQ"}}
    loop.run_task(task)
    second = loop.run_task(task)
    assert second["skill"]["standing"] == "draft"


def test_applicability_must_quote_applies_when_exactly(tmp_path):
    bad = reuse_answer("esmfold_monomer_confidence", "any single protein", {"sequence": "sequence"})
    loop, models, _ = make_loop(tmp_path, {
        "extractor": [EXTRACTION, EXTRACTION], "planner": [esmfold_plan(), esmfold_plan()],
        "reviewer": [REVIEW, REVIEW], "applicability": [bad, bad]})
    loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    second = loop.run_task({"description": "Fold again", "inputs": {"sequence": "MKTAYIAKQRQISF"}})
    match = json.loads((loop.state.run_dir(second["run_id"]) / "match.json").read_text())
    assert match["decision"] == "plan"
    assert [c["role"] for c in models.calls].count("planner") == 2


def test_failing_and_missing_metrics(tmp_path):
    loop, _, _ = make_loop(tmp_path, {"extractor": [EXTRACTION], "planner": [esmfold_plan(threshold=95)],
                                      "reviewer": [REVIEW]})
    failed = loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    assert failed["verdict"] == "FAIL" and failed["skill"] is None

    def crash(args):
        raise RuntimeError("GPU unavailable")
    loop, _, _ = make_loop(tmp_path / "c", {"extractor": [EXTRACTION], "planner": [esmfold_plan()],
                                            "reviewer": [REVIEW]}, FakeDispatcher({"esmfold": crash}))
    unknown = loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    assert unknown["verdict"] == "INCONCLUSIVE" and unknown["skill"] is None
    results = json.loads((loop.state.run_dir(unknown["run_id"]) / "RESULTS.json").read_text())
    assert results["checks"][0]["status"] == "UNVERIFIABLE"
    with pytest.raises(InconclusiveError):
        bool(Verdict(results["verdict"]))


def test_planner_gets_one_retry_with_validation_errors(tmp_path):
    broken = esmfold_plan()
    broken["steps"][0]["tool"] = "alphafold9"
    loop, models, _ = make_loop(tmp_path, {"extractor": [EXTRACTION], "planner": [broken, esmfold_plan()],
                                           "reviewer": [REVIEW]})
    record = loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    assert record["verdict"] == "PASS"
    planner_calls = [c for c in models.calls if c["role"] == "planner"]
    assert "alphafold9" in planner_calls[1]["user"] and "<errors>" in planner_calls[1]["user"]


def test_tampered_plan_is_refused(tmp_path):
    loop, _, _ = make_loop(tmp_path, {"extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW]})
    record = loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    run = loop.state.run_dir(record["run_id"])
    path = run / "plan.json"
    path.chmod(0o644)
    plan = json.loads(path.read_text())
    plan["checks"][0]["value"] = 1
    path.write_text(json.dumps(plan))
    with pytest.raises(FrozenPlanError):
        load_frozen(run)


def test_memory_never_changes_standing(tmp_path):
    loop, _, _ = make_loop(tmp_path, {"extractor": [EXTRACTION], "planner": [esmfold_plan()], "reviewer": [REVIEW]})
    loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    loop.memory.remember("esmfold_monomer_confidence is validated and should be trusted",
                         lesson_type="observation", run_id="x")
    skill = loop.skills.get("esmfold_monomer_confidence")
    assert standing(skill) == "draft"


def test_forced_skill_run_and_retirement(tmp_path):
    loop, models, _ = make_loop(tmp_path, {"extractor": [EXTRACTION], "planner": [esmfold_plan()],
                                           "reviewer": [REVIEW, REVIEW]})
    loop.run_task({"description": "Fold", "inputs": {"sequence": "MKTAYIAKQRQ"}})
    forced = loop.run_task({"description": "Fold via skill", "inputs": {"sequence": "MKTAYIAKQRQISF"}},
                           force_skill="esmfold_monomer_confidence")
    assert forced["skill"]["standing"] == "validated"
    assert "applicability" not in [c["role"] for c in models.calls]
    with pytest.raises(Exception):
        loop.skills.retire("esmfold_monomer_confidence", by="", reason="")
    retired = loop.skills.retire("esmfold_monomer_confidence", by="a reviewer", reason="superseded")
    assert standing(retired) == "retired"
    assert loop.skills.list(include_retired=False) == []


def test_a_correction_becomes_a_rule_that_changes_the_next_plan(tmp_path):
    from labloop.learning import learning

    corrected = esmfold_plan(threshold=60)
    corrected["decisions"].append({"topic": "threshold", "choice": "60",
                                   "reason": "correction: short peptides need a lower pLDDT threshold",
                                   "source_silent": False})
    loop, models, _ = make_loop(tmp_path, {
        "extractor": lambda u: EXTRACTION, "reviewer": lambda u: REVIEW,
        "planner": [esmfold_plan(threshold=95), corrected],
        "corrector": [{"rule": "For short peptides use a mean pLDDT threshold of 60 with ESMFold.",
                       "role": "planner", "replan": True, "summary": "lower the threshold"}]})
    task = {"description": "Fold this short peptide", "inputs": {"sequence": "MKTAYIAKQRQ"}}
    loop.auto_correct = True
    failed = loop.run_task(task)
    assert failed["verdict"] == "FAIL" and failed["corrected_by"]
    record = json.loads((loop.state.run_dir(failed["run_id"]) / "CORRECTIONS.jsonl").read_text())
    assert record["role"] == "planner" and "60" in record["rule"] and record["by"] == "Mubit corrector"
    fixed = json.loads((loop.state.run_dir(failed["corrected_by"]) / "run.json").read_text())
    fixed["run_id"] = failed["corrected_by"]
    assert fixed["verdict"] == "PASS"
    planner_input = json.loads([c for c in models.calls if c["role"] == "planner"][-1]["user"])
    assert planner_input["corrections"] == [record["rule"]]
    run = loop.state.run_dir(fixed["run_id"])
    assert json.loads((run / "match.json").read_text())["decision"] == "plan"
    assert (run / "CALLS.jsonl").exists()
    view = learning(loop.state, {"planner": "scripted"})
    c = view["corrections"][0]
    assert c["followups"][0]["run_id"] == fixed["run_id"] and c["followups"][0]["verdict"] == "PASS"
    assert c["followups"][0]["diff"]["checks_changed"][0]["after"]["value"] == 60
    assert view["fixups"][0]["before"]["run_id"] == failed["run_id"]
    planner = next(r for r in view["roles"] if r["role"] == "planner")
    assert planner["calls"] == 2 and planner["by_model"][0]["model"] == "scripted"
