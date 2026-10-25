"""The research step, as harness-experiments does it, on Modal.

The researcher role writes Europe PMC queries. The `literature_corpus` Modal
function runs the harness fetcher (Europe PMC search, OpenAlex citation
ranking, full text from Europe PMC, bioRxiv or Unpaywall) and freezes the
corpus with its manifest on the artifacts Volume. The `paperqa` Modal function
runs PaperQA2 over that corpus together with the frozen seed corpus from the
harness `dsh-lab` branch, answering two fixed questions about procedure and
reported numbers. The extractor role turns the cited answers into structured
procedure, numbers and guidance, each with its source, for the planner.
"""

from __future__ import annotations

import json
import os
from typing import Any

from labloop import catalog
from labloop.dispatch import Dispatcher
from labloop.models import ModelError, Models, ask_json
from labloop.state import RunDir

SEED_CORPORA = [c for c in os.environ.get("LABLOOP_SEED_CORPORA", "seed/dsh-lab-20260927T134914Z").split(",") if c]
QUESTIONS = [
    "Which computational procedure, tools and parameter settings do published studies use to carry out this task: {task}",
    "What numeric values of model confidence or accuracy metrics (for example pLDDT, pTM, ipTM, ipSAE, DockQ) do "
    "published studies report as thresholds or typical results for this task: {task} Give each value with its metric, "
    "its context and its source.",
]


def limits() -> dict[str, Any]:
    return {
        "max_queries": int(os.environ.get("LABLOOP_RESEARCH_MAX_QUERIES", "3")),
        "page_size": int(os.environ.get("LABLOOP_RESEARCH_PAGE_SIZE", "25")),
        "max_docs": int(os.environ.get("LABLOOP_RESEARCH_MAX_DOCS", "8")),
        "evidence_k": int(os.environ.get("LABLOOP_RESEARCH_EVIDENCE_K", "10")),
        "paperqa_llm": os.environ.get("LABLOOP_PAPERQA_LLM", "mubit:claude-sonnet-5-5"),
        "paperqa_summary_llm": os.environ.get("LABLOOP_PAPERQA_SUMMARY_LLM", "mubit:claude-haiku-5-5"),
    }


def _single(dispatcher: Dispatcher, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    outcome = dispatcher.run_wave([(tool, args)])[0]
    if isinstance(outcome, BaseException):
        raise RuntimeError(f"{tool}: {type(outcome).__name__}: {outcome}")
    return outcome


def structure(models: Models, run_id: str, subject: str, evidence: Any) -> dict[str, Any]:
    """The extractor's structured reading of cited evidence."""
    user = json.dumps({"subject": subject, "evidence": evidence}, indent=1, default=str)
    result, _ = ask_json(models, "extractor", user, run_id=run_id, max_tokens=4096,
                         check=lambda o: [] if isinstance(o, dict) else ["not an object"])
    return result


def research(task: dict[str, Any], *, run: RunDir, run_id: str, dispatcher: Dispatcher,
             models: Models) -> dict[str, Any]:
    cap = limits()
    queries = list(task.get("research_queries") or [])
    query_error = None
    if not queries:
        user = json.dumps({"task": task["description"], "max_queries": cap["max_queries"],
                           "tools": sorted(catalog.available())})
        try:
            answer, _ = ask_json(models, "researcher", user, run_id=run_id, max_tokens=1024,
                                 check=lambda o: [] if isinstance(o, dict) and isinstance(o.get("queries"), list)
                                 and all(isinstance(q, str) for q in o["queries"]) else ["queries must be strings"])
            queries = answer["queries"]
        except ModelError as error:
            query_error = str(error)
        queries = queries or [task["description"][:300]]
    queries = [q for q in queries if q.strip()][: cap["max_queries"]]

    summary: dict[str, Any] = {"queries": queries, "query_error": query_error, "limits": cap, "papers": [],
                               "corpus": None, "paperqa": None, "extraction": None, "errors": []}
    corpora = list(SEED_CORPORA)
    try:
        built = _single(dispatcher, "literature_corpus", {"queries": queries, "page_size": cap["page_size"],
                                                          "max_docs": cap["max_docs"], "run_id": run_id,
                                                          "step_id": "research_corpus"})
        summary["corpus"] = {"path": built["artifacts"]["corpus"], "scores": built["scores"],
                             "manifest_sha256": built["data"].get("manifest_sha256"),
                             "errors": built["data"].get("errors", [])}
        summary["papers"] = built["data"]["documents"]
        corpora.insert(0, built["artifacts"]["corpus"])
    except Exception as error:
        summary["errors"].append(f"corpus: {error}")

    if corpora:
        try:
            read = _single(dispatcher, "paperqa", {
                "corpora": corpora, "questions": [q.format(task=task["description"]) for q in QUESTIONS],
                "llm": cap["paperqa_llm"], "summary_llm": cap["paperqa_summary_llm"],
                "evidence_k": cap["evidence_k"], "run_id": run_id, "step_id": "research_paperqa"})
            summary["paperqa"] = {"answers": read["data"]["answers"], "documents": len(read["data"]["added"]),
                                  "failed": read["data"]["failed"], "cost_usd": read["scores"].get("cost_usd"),
                                  "answers_path": read["artifacts"].get("answers"), "corpora": corpora}
        except Exception as error:
            summary["errors"].append(f"paperqa: {error}")

    if summary["paperqa"]:
        evidence = [{"question": a["question"], "answer": a["answer"],
                     "sources": sorted({c["citation"] for c in a["contexts"]})} for a in summary["paperqa"]["answers"]]
        try:
            summary["extraction"] = structure(models, run_id, f"Task: {task['description']}", evidence)
        except ModelError as error:
            summary["errors"].append(f"extraction: {error}")

    (run.path / "research").mkdir(exist_ok=True)
    run.write_json("research/extractions.json", summary)
    return summary
