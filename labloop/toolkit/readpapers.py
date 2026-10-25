"""PaperQA2 over frozen corpora, as harness-experiments `lit/README.md` runs it.

PaperQA2 routes every model call through LiteLLM. Here LiteLLM speaks the
Anthropic Messages format through the Mubit gateway (`mubit:<model>`), so the
summary and answer calls are recorded by the gateway like every other call. The
OpenAI format through the gateway (`mubit-openai:<model>[@effort]`) and Z.AI
(`zai:<model>`) are used when the routing secret names them.
Embeddings are a local
sentence-transformers model, because the gateway serves embeddings only in the
OpenAI format. The configuration sends no `temperature`, which the Anthropic
API no longer accepts.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

PROVIDERS = {"mubit": ("https://api.mubit.ai/anthropic", ("MUBIT_API_KEY", "MUBIT_API_TOKEN")),
             "zai": ("https://api.z.ai/api/anthropic", ("ZAI_API_KEY",)),
             "mubit-openai": ("https://api.mubit.ai/openai/v1", ("MUBIT_API_KEY", "MUBIT_API_TOKEN"))}
EMBEDDING = "st-multi-qa-MiniLM-L6-cos-v1"


def _llm_config(spec: str) -> tuple[str, dict[str, Any]]:
    provider, _, model = spec.partition(":") if ":" in spec else ("mubit", "", spec)
    model, _, effort = model.partition("@")
    base, key_names = PROVIDERS[provider]
    key = next((os.environ[k] for k in key_names if os.environ.get(k)), None)
    name = f"{'openai' if provider == 'mubit-openai' else 'anthropic'}/{model}"
    params: dict[str, Any] = {"model": name, "api_base": base, "api_key": key}
    if effort:
        params["reasoning_effort"] = effort
    if provider.startswith("mubit"):
        params["extra_headers"] = {"x-middleware-record": os.environ.get("LABLOOP_MUBIT_RECORD", "full")}
    return name, {"name": name, "model_list": [{"model_name": name, "litellm_params": params}]}


def settings(llm: str, summary_llm: str, evidence_k: int, max_sources: int):
    from paperqa import Settings

    llm_name, llm_config = _llm_config(llm)
    summary_name, summary_config = _llm_config(summary_llm)
    s = Settings(llm=llm_name, llm_config=llm_config, summary_llm=summary_name,
                 summary_llm_config=summary_config, embedding=EMBEDDING)
    s.answer.evidence_k = evidence_k
    s.answer.answer_max_sources = max_sources
    s.parsing.use_doc_details = False
    s.parsing.multimodal = False
    return s


def corpus_documents(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Each readable file in a frozen corpus, with its metadata."""
    out = []
    for path in sorted(directory.iterdir()):
        if path.suffix not in (".txt", ".pdf"):
            continue
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        out.append((path, meta))
    return out


def citation_of(meta: dict[str, Any], path: Path) -> str:
    year = meta.get("year") or "n.d."
    title = meta.get("title") or path.stem
    ident = f"doi:{meta['doi']}" if meta.get("doi") else (meta.get("pmcid") or path.stem)
    return f"{title} ({year}). {ident}"


async def _answer(directories: list[Path], questions: list[str], s) -> dict[str, Any]:
    from paperqa import Docs

    docs = Docs()
    added, failed = [], []
    for directory in directories:
        for path, meta in corpus_documents(directory):
            docname = (meta.get("pmcid") or meta.get("id") or path.stem).replace(".", "_")
            try:
                await docs.aadd(path, citation=citation_of(meta, path), docname=docname,
                                title=meta.get("title"), doi=meta.get("doi"), settings=s)
                added.append({"docname": docname, "title": meta.get("title"), "doi": meta.get("doi"),
                              "corpus": directory.name})
            except Exception as error:
                failed.append({"file": path.name, "error": f"{type(error).__name__}: {str(error)[:200]}"})
    answers = []
    for question in questions:
        session = await docs.aquery(question, settings=s)
        answers.append({
            "question": question,
            "answer": session.answer,
            "contexts": [{"doc": c.text.doc.docname, "citation": c.text.doc.citation, "score": c.score,
                          "summary": c.context} for c in session.contexts if c.score > 0][:12],
            "cost_usd": session.cost,
        })
    return {"added": added, "failed": failed, "answers": answers}


def answer(directories: list[Path], questions: list[str], *, llm: str, summary_llm: str,
           evidence_k: int = 10, max_sources: int = 6) -> dict[str, Any]:
    return asyncio.run(_answer(directories, questions, settings(llm, summary_llm, evidence_k, max_sources)))
