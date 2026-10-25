"""Tool knowledge read from each model's own method papers.

For every catalogued model with papers, `literature_corpus` fetches and freezes
those papers on Modal by DOI, `paperqa` answers fixed questions about the model
over them and the seed corpus, and the extractor turns the cited answers into a
knowledge card: purpose and limits, how to read its confidence scores, reported
numbers and recommended settings, each with its source.

A card is saved versioned under `knowledge/tools/` on the state Volume, which
the planner reads. Each sourced statement is also stored as a memory lesson,
and the card is mirrored as a tool skill, so both reach Mubit when the key
allows its memory API. Cards are context for planning; nothing in them changes
a frozen plan, a grade or a skill's standing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from labloop import catalog
from labloop.dispatch import Dispatcher
from labloop.events import Emit, silent
from labloop.memory import Memory
from labloop.models import ModelError, Models
from labloop.research import SEED_CORPORA, limits, structure

QUESTIONS = [
    "What is {title} designed to predict or do, what inputs does it accept, and what limitations do its authors state?",
    "How should the confidence scores of {title} ({scores}) be interpreted, and what threshold or typical values are "
    "reported for them?",
    "What settings (for example seeds, recycling or sampling steps, number of samples, MSA use) are recommended for "
    "{title}, and what benchmark accuracy is reported for it?",
]


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root) / "tools"

    def get(self, tool: str) -> dict[str, Any] | None:
        path = self.root / tool / "card.json"
        return json.loads(path.read_text()) if path.exists() else None

    def all(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        return [json.loads(p.read_text()) for p in sorted(self.root.glob("*/card.json"))]

    def save(self, card: dict[str, Any]) -> dict[str, Any]:
        directory = self.root / card["tool"]
        (directory / "versions").mkdir(parents=True, exist_ok=True)
        previous = self.get(card["tool"])
        card["version"] = (previous or {}).get("version", 0) + 1
        body = json.dumps(card, indent=2, sort_keys=True) + "\n"
        snapshot = directory / "versions" / f"v{card['version']:04d}.json"
        snapshot.write_text(body)
        snapshot.chmod(0o444)
        tmp = directory / "card.json.tmp"
        tmp.write_text(body)
        tmp.replace(directory / "card.json")
        return card


def for_planner(store: KnowledgeStore) -> list[dict[str, Any]]:
    """Cards of the tools a pipeline may use, trimmed to what planning needs."""
    usable = set(catalog.available())
    return [{"tool": c["tool"], "summary": c.get("summary"), "guidance": c.get("guidance", [])[:10],
             "reported_numbers": c.get("reported_numbers", [])[:12], "limitations": c.get("limitations", [])[:6],
             "sources": [p.get("title") for p in c.get("papers", [])]}
            for c in store.all() if c["tool"] in usable]


def ingest(tools: list[str], *, store: KnowledgeStore, dispatcher: Dispatcher, models: Models, memory: Memory,
           run_id: str, emit: Emit = silent) -> list[dict[str, Any]]:
    """Ingest the method papers of each named tool. Returns one report per tool."""
    cap = limits()
    entries = {t: catalog.CATALOG[t] for t in tools if catalog.CATALOG.get(t, {}).get("papers")}
    calls = [("literature_corpus", {"queries": [" OR ".join(f'DOI:"{d}"' for d in e["papers"])],
                                    "page_size": 25, "max_docs": len(e["papers"]) + 2,
                                    "run_id": run_id, "step_id": f"knowledge_{t}"}) for t, e in entries.items()]
    for tool, entry in entries.items():
        emit("start", f"{entry['title']}: fetching {len(entry['papers'])} method papers on Modal", key=f"corpus:{tool}")
    built = dict(zip(entries, dispatcher.run_wave(calls)))
    for tool, outcome in built.items():
        if isinstance(outcome, BaseException):
            emit("error", f"{entries[tool]['title']}: corpus failed: {str(outcome)[:200]}", key=f"corpus:{tool}")
        else:
            sc = outcome["scores"]
            emit("done", f"{entries[tool]['title']}: {sc['n_documents']} papers frozen ({sc['n_full_text']} full text)",
                 key=f"corpus:{tool}")
    read_calls, order = [], []
    for tool, outcome in built.items():
        corpora = list(SEED_CORPORA)
        if not isinstance(outcome, BaseException):
            corpora.insert(0, outcome["artifacts"]["corpus"])
        entry = entries[tool]
        scores = ", ".join(entry.get("scores", [])) or "its scores"
        read_calls.append(("paperqa", {"corpora": corpora,
                                       "questions": [q.format(title=entry["title"], scores=scores) for q in QUESTIONS],
                                       "llm": cap["paperqa_llm"], "summary_llm": cap["paperqa_summary_llm"],
                                       "evidence_k": cap["evidence_k"], "run_id": run_id,
                                       "step_id": f"knowledge_{tool}_paperqa"}))
        order.append(tool)
    for tool in order:
        emit("start", f"{entries[tool]['title']}: PaperQA2 answering {len(QUESTIONS)} questions on Modal",
             key=f"paperqa:{tool}")
    reads = dict(zip(order, dispatcher.run_wave(read_calls)))
    for tool, outcome in reads.items():
        if isinstance(outcome, BaseException):
            emit("error", f"{entries[tool]['title']}: PaperQA2 failed: {str(outcome)[:200]}", key=f"paperqa:{tool}")
        else:
            emit("done", f"{entries[tool]['title']}: PaperQA2 read {len(outcome['data']['added'])} papers",
                 key=f"paperqa:{tool}")

    reports = []
    for tool in order:
        entry, corpus, read = entries[tool], built[tool], reads[tool]
        report: dict[str, Any] = {"tool": tool}
        if isinstance(read, BaseException):
            report["error"] = f"paperqa: {type(read).__name__}: {read}"
            reports.append(report)
            continue
        papers = [] if isinstance(corpus, BaseException) else corpus["data"]["documents"]
        found = {(p.get("doi") or "").lower() for p in papers}
        evidence = [{"question": a["question"], "answer": a["answer"],
                     "sources": sorted({c["citation"] for c in a["contexts"]})} for a in read["data"]["answers"]]
        try:
            card = structure(models, run_id, f"Tool: {entry['title']} ({entry['purpose']})", evidence)
        except ModelError as error:
            report["error"] = f"extraction: {error}"
            reports.append(report)
            continue
        card = {"tool": tool, "title": entry["title"], "deployed": entry["available"],
                "summary": card.get("summary"), "guidance": card.get("guidance", []),
                "reported_numbers": card.get("reported_numbers", []), "limitations": card.get("limitations", []),
                "procedure": card.get("procedure", {}),
                "papers": [{k: p.get(k) for k in ("title", "doi", "year", "citations", "text_source", "file", "pmcid")}
                           for p in papers],
                "papers_missing": [d for d in entry["papers"] if d.lower() not in found],
                "corpus": None if isinstance(corpus, BaseException) else corpus["artifacts"]["corpus"],
                "manifest_sha256": None if isinstance(corpus, BaseException) else corpus["data"].get("manifest_sha256"),
                "paperqa_answers": evidence, "ingested_by": run_id,
                "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        card = store.save(card)
        lessons = 0
        for item in card["guidance"] + card["limitations"]:
            memory.remember(f"{entry['title']}: {item.get('statement')} ({item.get('source')})",
                            lesson_type="tool_knowledge", run_id=run_id, metadata={"tool": tool})
            lessons += 1
        for item in card["reported_numbers"]:
            memory.remember(f"{entry['title']}: {item.get('quantity')} = {item.get('value')} {item.get('unit') or ''}"
                            f" ({item.get('context')}; {item.get('source')})", lesson_type="tool_knowledge",
                            run_id=run_id, metadata={"tool": tool})
            lessons += 1
        memory.mirror_tool(card, entry)
        report.update(version=card["version"], papers=len(papers), full_text=sum(p.get("text_source") != "abstract"
                                                                                  for p in papers),
                      missing=card["papers_missing"], guidance=len(card["guidance"]),
                      numbers=len(card["reported_numbers"]), lessons=lessons)
        emit("info", f"{entry['title']}: knowledge card v{card['version']} saved with {len(card['guidance'])} "
                     f"guidance, {len(card['reported_numbers'])} numbers; {lessons} lessons stored")
        reports.append(report)
    return reports
