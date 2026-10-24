"""The short research step.

It searches Europe PMC through the `literature_search` tool, freezes what it
found with the vendored corpus fetcher's manifest format, and asks the
extractor role to report each paper's procedure. It is capped by a fixed number
of queries, a fixed number of papers and a token budget, and stops early rather
than exceed the budget.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from labloop.canonical import digest_bytes
from labloop.dispatch import Dispatcher
from labloop.lit import fetch_corpus
from labloop.models import ModelError, Models, ask_json
from labloop.state import RunDir, now


def limits() -> dict[str, int]:
    return {
        "max_queries": int(os.environ.get("LABLOOP_RESEARCH_MAX_QUERIES", "2")),
        "page_size": int(os.environ.get("LABLOOP_RESEARCH_PAGE_SIZE", "5")),
        "max_papers": int(os.environ.get("LABLOOP_RESEARCH_MAX_PAPERS", "2")),
        "fulltext_chars": int(os.environ.get("LABLOOP_RESEARCH_FULLTEXT_CHARS", "6000")),
        "token_budget": int(os.environ.get("LABLOOP_RESEARCH_TOKEN_BUDGET", "40000")),
    }


def _freeze_corpus(out: Path, queries: list[str], papers: list[dict[str, Any]]) -> str:
    out.mkdir(parents=True, exist_ok=True)
    documents = []
    for paper in papers:
        stem = paper.get("pmcid") or paper.get("id") or digest_bytes(json.dumps(paper, sort_keys=True).encode())[:12]
        body = json.dumps(paper, indent=1, sort_keys=True).encode()
        (out / f"{stem}.meta.json").write_bytes(body)
        documents.append({"source": "europepmc", "query": paper.get("_query"),
                          "query_sha256": digest_bytes((paper.get("_query") or "").encode()),
                          "id": paper.get("id"), "pmcid": paper.get("pmcid"), "doi": paper.get("doi"),
                          "title": paper.get("title"), "year": paper.get("year"),
                          "full_text": bool(paper.get("fulltext_excerpt")),
                          "files": {f"{stem}.meta.json": digest_bytes(body)}})
    manifest = {"format": "ppi-planning.corpus.manifest/v1", "frozen_at": now(),
                "contact_email": "labloop@example.org", "queries": queries, "documents": documents}
    path = fetch_corpus.freeze(out, manifest)
    return (path.parent / "manifest.sha256").read_text().split()[0]


def research(task: dict[str, Any], *, run: RunDir, run_id: str, dispatcher: Dispatcher,
             models: Models) -> dict[str, Any]:
    cap = limits()
    queries = [q for q in (task.get("research_queries") or [task["description"][:300]]) if q][: cap["max_queries"]]
    calls = [("literature_search", {"query": q, "page_size": cap["page_size"],
                                    "fulltext_chars": cap["fulltext_chars"], "run_id": run_id,
                                    "step_id": f"research_{i}"}) for i, q in enumerate(queries)]
    outcomes = dispatcher.run_wave(calls)
    papers: dict[str, dict[str, Any]] = {}
    search_errors = []
    for query, outcome in zip(queries, outcomes):
        if isinstance(outcome, BaseException):
            search_errors.append(f"{query[:60]}: {type(outcome).__name__}: {outcome}")
            continue
        for record in outcome.get("data", {}).get("results", []):
            key = record.get("id") or record.get("doi") or record.get("title")
            if key and key not in papers and (record.get("abstract") or record.get("fulltext_excerpt")):
                papers[key] = {**record, "_query": query}
    chosen = list(papers.values())[: cap["max_papers"]]
    manifest_digest = _freeze_corpus(run.path / "research" / "corpus", queries, chosen) if chosen else None

    spent, extractions, stopped = 0, [], None
    for paper in chosen:
        if spent >= cap["token_budget"]:
            stopped = f"token budget of {cap['token_budget']} reached after {len(extractions)} papers"
            break
        user = json.dumps({
            "task": task["description"],
            "paper": {"id": paper.get("id"), "doi": paper.get("doi"), "title": paper.get("title"),
                      "year": paper.get("year"), "abstract": paper.get("abstract"),
                      "fulltext_excerpt": paper.get("fulltext_excerpt")},
        }, indent=1)
        try:
            extraction, replies = ask_json(models, "extractor", user, run_id=run_id, max_tokens=2048,
                                           check=lambda o: [] if isinstance(o, dict) else ["not an object"])
        except ModelError as error:
            extractions.append({"paper": paper.get("id"), "error": str(error)})
            continue
        spent += sum(r.input_tokens + r.output_tokens for r in replies)
        extractions.append({"paper": paper.get("id"), "doi": paper.get("doi"), "title": paper.get("title"),
                            "year": paper.get("year"), **extraction})
    summary = {
        "queries": queries,
        "search_errors": search_errors,
        "papers": [{"id": p.get("id"), "doi": p.get("doi"), "title": p.get("title"), "year": p.get("year")}
                   for p in chosen],
        "corpus_manifest_sha256": manifest_digest,
        "extractions": extractions,
        "tokens_spent": spent,
        "limits": cap,
        "stopped_early": stopped,
    }
    (run.path / "research").mkdir(exist_ok=True)
    run.write_json("research/extractions.json", summary)
    return summary
