import json

from labloop import pipeline
from labloop.grading import grade, grade_check
from labloop.memory import LocalMemory
from labloop.models import parse_json
from labloop.toolkit import structure
from labloop.toolkit.data import chains_from_pdb

TWO_STEP = {
    "steps": [
        {"id": "seq", "tool": "fetch_uniprot", "args": {"accession": "$inputs.acc"}},
        {"id": "fold", "tool": "esmfold", "args": {"sequence": "$steps.seq.data.sequence"}},
    ],
    "checks": [{"id": "c", "metric": "fold.mean_plddt", "op": ">", "value": 50}],
}


def test_validation_catches_bad_references_and_missing_checks():
    assert pipeline.validate(TWO_STEP, {"acc"}) == []
    bad = json.loads(json.dumps(TWO_STEP))
    bad["steps"][1]["args"]["sequence"] = "$steps.seq.data.nothing"
    bad["steps"][0]["args"]["accession"] = "$inputs.missing"
    bad["checks"] = []
    errors = pipeline.validate(bad, {"acc"})
    assert any("does not produce" in e for e in errors)
    assert any("undeclared input" in e for e in errors)
    assert any("no acceptance checks" in e for e in errors)
    undeployed = {"steps": [{"id": "x", "tool": "colabfold", "args": {"chains": []}}],
                  "checks": [{"id": "c", "metric": "x.ptm", "op": ">", "value": 0}]}
    assert any("not deployed" in e for e in pipeline.validate(undeployed, set()))


def test_reference_check_needs_a_source():
    plan = {**TWO_STEP, "checks": [{"id": "r", "metric": "fold.mean_plddt", "reference": 80, "tolerance": 5}]}
    assert any("names no source" in e for e in pipeline.validate(plan, {"acc"}))


def test_waves_and_resolution():
    waves = pipeline.waves(TWO_STEP["steps"] + [{"id": "other", "tool": "fetch_pdb", "args": {"pdb_id": "1CRN"}}])
    assert [[s["id"] for s in w] for w in waves] == [["seq", "other"], ["fold"]]
    results = {"seq": {"data": {"sequence": "MKV"}}}
    assert pipeline.resolve(TWO_STEP["steps"][1]["args"], {}, "r", results) == {"sequence": "MKV"}
    assert pipeline.resolve({"x": "$run_id", "y": ["$inputs.a"]}, {"a": 1}, "rid", {}) == {"x": "rid", "y": [1]}


def test_grading_states():
    results = {"fold": {"scores": {"mean_plddt": 80.0}}}
    assert grade_check({"metric": "fold.mean_plddt", "op": ">", "value": 70}, results)["status"] == "PASS"
    assert grade_check({"metric": "fold.mean_plddt", "reference": 90, "tolerance": 5, "source": "x"},
                       results)["status"] == "FAIL"
    assert grade_check({"metric": "fold.ptm", "op": ">", "value": 0.5}, results)["status"] == "UNVERIFIABLE"
    assert grade_check({"metric": "fold.mean_plddt", "op": ">", "value": 0}, {"fold": {"error": "x"}})["status"] == "UNVERIFIABLE"
    mixed = {"checks": [{"id": "a", "metric": "fold.mean_plddt", "op": ">", "value": 70},
                        {"id": "b", "metric": "fold.ptm", "op": ">", "value": 0.5}]}
    assert grade(mixed, results)["verdict"] == "INCONCLUSIVE"


def test_parse_json_handles_fences_and_prose():
    assert parse_json('Here it is:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure. {"a": {"b": [1, 2]}} done') == {"a": {"b": [1, 2]}}


def test_boltz_reader_on_recorded_output(tmp_path):
    pred = tmp_path / "boltz_results_job" / "predictions" / "job"
    pred.mkdir(parents=True)
    (pred / "job_model_0.cif").write_text("data_job\n")
    (pred / "confidence_job_model_0.json").write_text(json.dumps(
        {"confidence_score": 0.62, "ptm": 0.7, "iptm": 0.56, "complex_plddt": 0.86, "chains_ptm": {"0": 0.7}}))
    found = structure.boltz_outputs(tmp_path, "job")
    assert structure.boltz_scores(found["confidence"]) == {"confidence_score": 0.62, "ptm": 0.7, "iptm": 0.56,
                                                           "complex_plddt": 0.86}
    assert "id: B" in structure.boltz_yaml(structure.normalise_chains(["MKV", "PQR"]))
    assert structure.chai_fasta([{"id": "A", "sequence": "MKV"}]) == ">protein|name=A\nMKV\n"


def test_pdb_chain_reader_and_bfactor():
    line = "ATOM      2  CA  MET A   1      11.104   6.134  -6.504  1.00 87.50           C"
    line2 = "ATOM      9  CA  LYS A   2      11.104   6.134  -6.504  1.00 72.50           C"
    text = line + "\n" + line2 + "\n"
    assert chains_from_pdb(text) == {"A": "MK"}
    assert structure.mean_ca_bfactor(text) == 80.0


def test_local_memory_recall(tmp_path):
    memory = LocalMemory(tmp_path)
    memory.remember("Boltz-2 iptm below 0.5 on short chains is common", lesson_type="observation", run_id="r")
    memory.remember("unrelated note about ligands", lesson_type="observation", run_id="r")
    found = memory.context("boltz iptm short chains", run_id="r")
    assert found[0]["content"].startswith("Boltz-2")


def test_every_available_tool_has_a_modal_function():
    import re
    from pathlib import Path

    from labloop import catalog

    source = (Path(__file__).parents[1] / "modal_apps" / "tools_app.py").read_text()
    defined = set(re.findall(r"@app\.function\([^)]*\)\s*\ndef (\w+)\(", source, re.S))
    assert set(catalog.available()) <= defined
