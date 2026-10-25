import copy
import io
import json
import math
import struct
import urllib.request

import pytest

from labloop import storage
from labloop.reporting import build_report

pytest.importorskip("matplotlib")
pytest.importorskip("gemmi")

RUN = "r-20261024-235731-d6d4f4"
PAIR = "r-20261024-193439-b06cd9"
SECTIONS = ["Outcome", "How the pipeline was chosen", "Metrics", "Structure", "Study distillation", "Timeline",
            "Lessons recorded"]


def _atom(serial, chain, resseq, x, y, z, b):
    return (f"ATOM  {serial:5d}  CA  ALA {chain}{resseq:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{b:6.2f}"
            f"           C  ")


def _helix(chain, n, shift=0.0, b=lambda i: 50 + i):
    lines = []
    for i in range(n):
        angle = math.radians(100 * i)
        lines.append(_atom(i + 1, chain, i + 1, 2.3 * math.cos(angle) + shift, 2.3 * math.sin(angle), 1.5 * i, b(i)))
    return lines


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines + ["END", ""]))


def _png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _bundle():
    return {
        "run_id": RUN,
        "status": {
            "phase": "done", "verdict": "PASS",
            "history": [{"at": "2026-10-24T23:57:31Z", "phase": "match"}, {"at": "2026-10-24T23:57:37Z", "phase": "research"},
                        {"at": "2026-10-24T23:57:55Z", "phase": "plan"}, {"at": "2026-10-24T23:58:31Z", "phase": "freeze"},
                        {"at": "2026-10-24T23:58:31Z", "phase": "run"}, {"at": "2026-10-24T23:58:55Z", "phase": "grade"},
                        {"at": "2026-10-24T23:58:57Z", "phase": "learn"}, {"at": "2026-10-24T23:59:11Z", "phase": "done"}],
            "lesson_texts": ["Feed esmfold from data.first_chain_sequence."],
            "summary": "The fetch and fold pipeline passed all checks.",
            "origin": {"kind": "planned"},
            "skill": {"action": "created", "skill": "pdb_first_chain_esmfold_confidence", "standing": "draft", "version": 1},
        },
        "task": {"description": "Fetch this PDB entry and fold its first chain with ESMFold.", "inputs": {"pdb_id": "1UBQ"}},
        "match": {"decision": "plan", "skill": None, "candidates": ["single_chain_fold_confidence_esmfold"],
                  "reason": "The task supplies a PDB id, not a sequence."},
        "plan": {
            "origin": {"kind": "planned"}, "input_schema": {"pdb_id": {"type": "string"}},
            "steps": [{"id": "fetch_entry", "tool": "fetch_pdb", "args": {"pdb_id": "$inputs.pdb_id"}},
                      {"id": "fold", "tool": "esmfold", "args": {"sequence": "$steps.fetch_entry.data.first_chain_sequence"}}],
            "checks": [{"id": "has_chain", "metric": "fetch_entry.scores.n_chains", "op": ">=", "value": 1},
                       {"id": "plddt", "metric": "fold.scores.mean_plddt", "op": ">=", "value": 70},
                       {"id": "ptm_ref", "metric": "fold.scores.ptm", "reference": 0.8, "tolerance": 0.1,
                        "source": "10.1126/science.ade2574"}],
            "decisions": [{"topic": "Tool choice", "choice": "ESMFold", "reason": "named", "source_silent": True}],
            "skill": {"name": "pdb_first_chain_esmfold_confidence", "applies_when": ["a PDB id is given"]},
        },
        "experiments": [
            {"step_id": "fetch_entry", "tool": "fetch_pdb", "status": "ok",
             "result": {"scores": {"n_chains": 1}, "artifacts": {"structure": f"{RUN}/fetch_entry/1ABC.pdb"}, "runtime_s": 0.5}},
            {"step_id": "fold", "tool": "esmfold", "status": "ok",
             "result": {"scores": {"mean_plddt": 79.5, "ptm": 0.83}, "artifacts": {"structure": f"{RUN}/fold/model.pdb"},
                        "runtime_s": 13.4}},
        ],
        "results": {"verdict": "PASS", "counts": {"PASS": 3, "FAIL": 0, "UNVERIFIABLE": 0},
                    "checks": [{"id": "has_chain", "metric": "fetch_entry.scores.n_chains", "observed": 1, "op": ">=",
                                "value": 1, "status": "PASS"},
                               {"id": "plddt", "metric": "fold.scores.mean_plddt", "observed": 79.5, "op": ">=",
                                "value": 70, "status": "PASS"},
                               {"id": "ptm_ref", "metric": "fold.scores.ptm", "observed": 0.83, "reference": 0.8,
                                "tolerance": 0.1, "status": "PASS", "source": "10.1126/science.ade2574"}],
                    "domain_graders": [{"grader": "ppi-assure", "status": "SKIPPED", "blocking": False,
                                        "reason": "the task does not match this grader"}]},
        "research": {
            "queries": ["ESMFold pLDDT"],
            "papers": [{"title": "Evolutionary-scale prediction of atomic-level protein structure", "doi": "10.1126/science.ade2574",
                        "year": "2023", "citations": 5540, "text_source": "biorxiv", "full_text": True, "pmcid": "PMC1"}],
            "paperqa": {"answers": [{"question": "Which thresholds are used?", "answer": "pLDDT above 70 is confident.",
                                     "contexts": [{"doc": "PMC1", "citation": "ESM (2023). doi:10.1126/science.ade2574", "score": 8}]}]},
            "extraction": {"summary": "ESMFold confidence is read from pLDDT.",
                           "reported_numbers": [{"quantity": "pLDDT threshold", "value": 70, "unit": "dimensionless",
                                                 "context": "confident fold", "source": "PMC1 chunk 3"}],
                           "guidance": [{"topic": "t", "statement": "Use pLDDT 70 as the confident band.", "source": "PMC1 chunk 3"}],
                           "limitations": [{"statement": "No ESMFold-specific pTM cutoff.", "source": "PMC1 chunk 4"}]},
        },
        "events": [{"seq": 1, "at": "2026-10-24T23:57:31Z", "kind": "info", "message": "accepted"},
                   {"seq": 2, "at": "2026-10-24T23:57:32Z", "kind": "start", "message": "m", "phase": "match", "key": "match"},
                   {"seq": 3, "at": "2026-10-24T23:57:36Z", "kind": "done", "message": "m", "phase": "match", "key": "match"},
                   {"seq": 4, "at": "2026-10-24T23:58:32Z", "kind": "start", "message": "f", "phase": "run", "key": "step:fold"},
                   {"seq": 5, "at": "2026-10-24T23:58:54Z", "kind": "done", "message": "f", "phase": "run", "key": "step:fold"}],
    }


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "artifacts"
    _write(root / RUN / "fetch_entry" / "1ABC.pdb", _helix("A", 30, b=lambda i: 20.0))
    _write(root / RUN / "fold" / "model.pdb", _helix("A", 30, b=lambda i: 0.4 + 0.02 * i))  # ESMFold 0 to 1 scale
    _write(root / PAIR / "cofold" / "model_0.pdb", _helix("A", 22) + _helix("B", 22, shift=12.0, b=lambda i: 85.0))
    return root


def test_full_report(artifacts):
    files = build_report(_bundle(), artifacts)
    page = files["report.html"].decode()
    for heading in SECTIONS:
        assert f"<h2>{heading}</h2>" in page
    for name in ("pipeline", "metrics", "structure_fetch_entry", "structure_fold", "confidence_fold", "timeline"):
        assert f"figures/{name}.png" in files
        assert f'src="figures/{name}.png"' in page
    assert "confidence_fetch_entry.png" not in str(list(files))  # experimental B-factors are not confidence
    for name, data in files.items():
        if name.endswith(".png"):
            width, height = _png_size(data)
            assert 200 < width <= 1200 and 100 < height <= 1200
            assert len(data) < 250_000, name
    summary = json.loads(files["report.json"])
    assert summary["verdict"] == "PASS" and summary["section_errors"] == []
    fold = next(s for s in summary["structures"] if s["step_id"] == "fold")
    assert fold["confidence"] == "plddt" and 40 <= fold["mean_confidence"] <= 100  # 0-1 B-factors rescaled
    assert "Evolutionary-scale prediction of atomic-level" in page  # source locator resolved to the paper
    assert "<details>" in page and "Which thresholds are used?" in page
    for dash in ("—", "–"):
        assert dash not in page


def test_two_chain_complex(artifacts):
    bundle = _bundle()
    bundle["run_id"] = PAIR
    bundle["plan"]["steps"] = [{"id": "cofold", "tool": "boltz2", "args": {"chains": [{"id": "A", "sequence": "$inputs.a"}]}}]
    bundle["experiments"] = [{"step_id": "cofold", "tool": "boltz2", "status": "ok",
                              "result": {"scores": {"iptm": 0.88}, "artifacts": {"structure": f"{PAIR}/cofold/model_0.pdb"}}}]
    summary = json.loads(build_report(bundle, artifacts)["report.json"])
    (record,) = summary["structures"]
    assert [c["id"] for c in record["chains"]] == ["A", "B"] and record["n_residues"] == 44


def test_missing_data_still_reports(tmp_path):
    bundle = _bundle()
    for key in ("research", "events", "experiments"):
        bundle.pop(key)
    bundle["status"].pop("history")
    files = build_report(bundle, None)
    page = files["report.html"].decode()
    assert "<h2>Outcome</h2>" in page and "<h2>Metrics</h2>" in page
    for heading in ("Structure", "Study distillation", "Timeline"):
        assert f"<h2>{heading}</h2>" not in page
    assert json.loads(files["report.json"])["section_errors"] == []
    # A skill reuse with an old research shape, a failed check and no artifacts root.
    reuse = copy.deepcopy(_bundle())
    reuse["match"] = {"decision": "reuse", "skill": "s", "version": 2, "matched_applies_when": "one chain is given",
                      "input_mapping": {"sequence": {"from_input": "protein"}}}
    reuse["plan"]["origin"] = {"kind": "skill", "skill": "s", "version": 2}
    reuse["results"]["verdict"] = "FAIL"
    reuse["results"]["checks"][1].update(observed=43.7, status="FAIL")
    reuse["research"] = {"extractions": [{"title": "A paper", "relevant": True, "summary": "It folds.",
                                          "procedure": {"steps": ["Run ESMFold."]}}],
                         "papers": [{"title": "A paper", "year": "2026"}]}
    page = build_report(reuse, tmp_path / "nowhere")["report.html"].decode()
    assert "one chain is given" in page and "below the floor of 70" in page and "Run ESMFold." in page
    # An empty bundle and an in-flight one.
    assert b"<h2>Outcome</h2>" in build_report({}, None)["report.html"]
    assert b"no checks have been graded" in build_report({"run_id": RUN, "status": {"phase": "plan"}}, None)["report.html"]


def test_volume_store(tmp_path):
    files = {"report.html": b"<html></html>", "figures/a.png": b"png", "report.json": b"{}"}
    out = storage.VolumeReportStore(tmp_path).put(RUN, files)
    assert (tmp_path / RUN / "figures" / "a.png").read_bytes() == b"png"
    assert out["urls"]["figures/a.png"] == f"{RUN}/figures/a.png"
    with pytest.raises(storage.ReportStoreError):
        storage.VolumeReportStore(tmp_path).put(RUN, {"../x": b""})


def test_supabase_store(monkeypatch):
    sent = []

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        sent.append(request)
        return Response(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    store = storage.SupabaseReportStore("https://x.supabase.co/", "secret-key", bucket="reports")
    assert "secret-key" not in repr(store)
    out = store.put(RUN, {"report.html": b"<html>", "figures/m.png": b"\x89PNG"})
    assert out["location"].startswith("supabase")
    assert out["urls"]["figures/m.png"] == f"https://x.supabase.co/storage/v1/object/public/reports/{RUN}/figures/m.png"
    html_req, png_req = sent
    assert html_req.full_url == f"https://x.supabase.co/storage/v1/object/reports/{RUN}/report.html"
    assert html_req.get_method() == "POST" and html_req.data == b"<html>"
    headers = {k.lower(): v for k, v in html_req.header_items()}
    assert headers["authorization"] == "Bearer secret-key" and headers["apikey"] == "secret-key"
    assert headers["x-upsert"] == "true" and headers["content-type"].startswith("text/html")
    assert dict((k.lower(), v) for k, v in png_req.header_items())["content-type"] == "image/png"

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"bad key secret-key"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(storage.ReportStoreError) as error:
        store.put(RUN, {"report.html": b"x"})
    assert "403" in str(error.value) and "secret-key" not in str(error.value)


def test_from_env(monkeypatch, tmp_path):
    for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_REPORTS_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    assert [type(s).__name__ for s in storage.from_env(tmp_path)] == ["VolumeReportStore"]
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    assert len(storage.from_env(tmp_path)) == 1
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    stores = storage.from_env(tmp_path)
    assert stores[1].bucket == "labloop-reports"
    monkeypatch.setenv("SUPABASE_REPORTS_BUCKET", "other")
    assert storage.from_env(tmp_path)[1].bucket == "other"
