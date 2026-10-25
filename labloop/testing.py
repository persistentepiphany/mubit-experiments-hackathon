"""Offline stand-ins: a fake dispatcher and canned model answers.

The fake dispatcher returns deterministic results in the shape the real Modal
functions return, so the whole loop runs without a network.
"""

from __future__ import annotations

from typing import Any, Callable

from labloop.dispatch import Call


def _fake_esmfold(args):
    n = len(args["sequence"])
    return {"tool": "esmfold", "scores": {"mean_plddt": 82.5, "ptm": 0.71, "length": n},
            "artifacts": {"structure": f"{args['run_id']}/{args['step_id']}/model.pdb"}, "data": {}}


def _fake_boltz2(args):
    return {"tool": "boltz2", "scores": {"confidence_score": 0.81, "ptm": 0.78, "iptm": 0.66,
                                         "complex_plddt": 0.84, "complex_iplddt": 0.8, "complex_pde": 0.9,
                                         "n_chains": len(args["chains"])},
            "artifacts": {"structure": f"{args['run_id']}/{args['step_id']}/model_0.cif",
                          "confidence": f"{args['run_id']}/{args['step_id']}/confidence.json",
                          "output_dir": f"{args['run_id']}/{args['step_id']}"}, "data": {}}


def _fake_literature(args):
    return {"tool": "literature_search", "scores": {"n_results": 1}, "artifacts": {},
            "data": {"query": args["query"], "results": [{
                "id": "36927031", "pmid": "36927031", "pmcid": None, "doi": "10.1126/science.ade2574",
                "title": "Evolutionary-scale prediction of atomic-level protein structure with a language model",
                "year": "2023", "abstract": "ESMFold predicts structure from a single sequence. Mean pLDDT above 70 indicates a confident fold.",
                "fulltext_excerpt": None, "is_open_access": "N"}]}}


def _fake_uniprot(args):
    return {"tool": "fetch_uniprot", "scores": {"length": 46}, "artifacts": {},
            "data": {"sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN", "header": "sp|P01542|CRAM_CRAAB"}}


def _fake_corpus(args):
    return {"tool": "literature_corpus", "scores": {"n_documents": 1, "n_full_text": 1, "searched": 3},
            "artifacts": {"corpus": f"{args['run_id']}/{args['step_id']}/corpus"},
            "data": {"manifest_sha256": "0" * 64, "errors": [], "documents": [{
                "title": "Evolutionary-scale prediction of atomic-level protein structure with a language model",
                "doi": "10.1126/science.ade2574", "year": "2023", "citations": 5540, "text_source": "biorxiv",
                "full_text": True, "file": "ESM.txt"}]}}


def _fake_paperqa(args):
    return {"tool": "paperqa", "scores": {"n_documents": 11, "n_answers": len(args["questions"]), "cost_usd": 0.01},
            "artifacts": {"answers": f"{args['run_id']}/{args['step_id']}/paperqa.json"},
            "data": {"added": [{"docname": "ESM"}], "failed": [], "answers": [
                {"question": q, "answer": "Predictions with mean pLDDT above 70 are confident (ESM 2023).",
                 "contexts": [{"doc": "ESM", "citation": "ESMFold (2023). doi:10.1126/science.ade2574", "score": 8,
                               "summary": "pLDDT above 70"}], "cost_usd": 0.005} for q in args["questions"]]}}


FAKE_TOOLS: dict[str, Callable[[dict], dict]] = {
    "literature_corpus": _fake_corpus,
    "paperqa": _fake_paperqa,
    "esmfold": _fake_esmfold,
    "boltz2": _fake_boltz2,
    "literature_search": _fake_literature,
    "fetch_uniprot": _fake_uniprot,
}


class FakeDispatcher:
    def __init__(self, overrides: dict[str, Callable[[dict], Any]] | None = None) -> None:
        self.tools = {**FAKE_TOOLS, **(overrides or {})}
        self.calls: list[Call] = []
        self.waves: list[list[Call]] = []

    def run_wave(self, calls):
        self.waves.append(list(calls))
        out = []
        for tool, args in calls:
            self.calls.append((tool, args))
            try:
                out.append(self.tools[tool](args))
            except Exception as error:
                out.append(error)
        return out


def esmfold_plan(threshold: float = 70.0) -> dict[str, Any]:
    return {
        "skill": {"name": "esmfold_monomer_confidence", "title": "Single-chain fold with ESMFold",
                  "description": "Predict a monomer structure with ESMFold and accept it when mean pLDDT is high.",
                  "applies_when": ["the task asks for the structure of one protein chain given its sequence"],
                  "not_for": ["complexes of two or more chains", "sequences longer than 400 residues"]},
        "input_schema": {"sequence": {"type": "string", "description": "protein sequence"}},
        "steps": [{"id": "fold", "tool": "esmfold", "args": {"sequence": "$inputs.sequence", "name": "query"}}],
        "checks": [{"id": "confident_fold", "metric": "fold.scores.mean_plddt", "op": ">=", "value": threshold,
                    "rationale": "pLDDT above 70 marks a confident backbone"}],
        "decisions": [{"topic": "threshold", "choice": str(threshold), "reason": "conventional cut-off",
                       "source_silent": True}],
        "sources": [{"id": "10.1126/science.ade2574", "title": "ESMFold", "used_for": "tool choice"}],
    }


EXTRACTION = {"relevant": True, "relevance_reason": "describes ESMFold",
              "procedure": {"steps": ["fold with ESMFold"], "tools": ["ESMFold"], "parameters": {}},
              "reported_numbers": [{"quantity": "mean pLDDT", "value": 70, "unit": "", "context": "confident fold",
                                    "source": "ESMFold (2023). doi:10.1126/science.ade2574"}],
              "guidance": [{"topic": "confidence", "statement": "mean pLDDT above 70 marks a confident fold",
                            "source": "ESMFold (2023). doi:10.1126/science.ade2574"}],
              "limitations": [], "summary": "ESMFold folds single sequences."}

REVIEW = {"lessons": [{"content": "ESMFold on a short sequence gave mean pLDDT 82.5 against a threshold of 70.",
                       "lesson_type": "success"}], "summary": "passed"}


def reuse_answer(skill_name: str, condition: str, mapping: dict[str, str]) -> dict[str, Any]:
    return {"skill": skill_name, "applies": True, "matched_applies_when": condition, "not_for_conflicts": [],
            "input_mapping": {k: {"from_input": v} for k, v in mapping.items()}, "reason": "single chain"}
