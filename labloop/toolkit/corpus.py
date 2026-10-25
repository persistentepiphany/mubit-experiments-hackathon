"""Build and freeze a literature corpus with the harness-experiments fetcher.

This follows `lit/fetch_corpus.py` from harness-experiments end to end. Europe
PMC is searched with each query, OpenAlex supplies citation counts for ranking,
and full text comes from Europe PMC (JATS XML), from bioRxiv's own JATS for
preprints, or from an open-access PDF that Unpaywall locates. Every file is
written once and the corpus is frozen with the fetcher's manifest format, so
PaperQA2 reads an immutable directory.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from labloop.lit import fetch_corpus

CONTACT = os.environ.get("LABLOOP_CONTACT_EMAIL", "labloop@example.org")
_SECTION = re.compile(rb"<title[^>]*>(.*?)</title>", re.S)


def jats_to_text(xml: bytes) -> str:
    """Plain text from JATS XML: the title, the abstract and the body, with section titles as headings.

    Journal front matter (identifiers, affiliations, licences) and back matter (references) are left
    out, so readers and PaperQA2 see the paper rather than its metadata.
    """
    parts = []
    title = re.search(rb"<article-title[^>]*>(.*?)</article-title>", xml, re.S)
    if title:
        parts.append(b"# " + re.sub(rb"<[^>]+>", b"", title.group(1)).strip())
    for block, heading in ((rb"<abstract[^>]*>(.*?)</abstract>", b"## Abstract"), (rb"<body[^>]*>(.*)</body>", None)):
        found = re.search(block, xml, re.S)
        if found:
            parts.append((heading + b"\n" if heading else b"") + found.group(1))
    if len(parts) > 1:
        xml = b"\n".join(parts)
    xml = _SECTION.sub(lambda m: b"\n\n## " + m.group(1) + b"\n", xml)
    xml = re.sub(rb"</(p|sec|abstract|caption|title-group)>", b"\n", xml)
    text = re.sub(rb"<[^>]+>", b" ", xml).decode("utf-8", "replace")
    import html

    text = html.unescape(text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())


def _plain(text: str | None) -> str:
    import html

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


def _search(query: str, page_size: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query": query, "format": "json", "pageSize": page_size,
                                     "resultType": "core"})
    payload = json.loads(fetch_corpus._get(f"{fetch_corpus.EUROPEPMC}/search?{params}", CONTACT))
    return payload.get("resultList", {}).get("result", [])


def _citations(doi: str | None) -> int | None:
    if not doi:
        return None
    try:
        return int(fetch_corpus.openalex_work(doi, CONTACT).get("cited_by_count") or 0)
    except Exception:
        return None


def _full_text(record: dict[str, Any], out: Path, stem: str) -> tuple[str | None, str | None]:
    """Write the best available full text. Returns (file name, source) or (None, None)."""
    pmcid, doi = record.get("pmcid"), record.get("doi")
    if pmcid and record.get("isOpenAccess") == "Y":
        try:
            xml = fetch_corpus.europepmc_fulltext(pmcid, CONTACT)
        except Exception:
            xml = None
        if xml:
            (out / f"{stem}.txt").write_text(jats_to_text(xml))
            return f"{stem}.txt", "europepmc"
    if doi and doi.startswith("10.1101/"):
        try:
            detail = fetch_corpus.biorxiv(doi, CONTACT)
            versions = detail.get("collection") or []
            jats_url = versions[-1].get("jatsxml") if versions else None
            if jats_url:
                xml = fetch_corpus._get(jats_url, CONTACT, timeout=60)
                if xml.strip():
                    (out / f"{stem}.txt").write_text(jats_to_text(xml))
                    return f"{stem}.txt", "biorxiv"
        except Exception:
            pass
    if doi:
        try:
            location = (fetch_corpus.unpaywall(doi, CONTACT).get("best_oa_location") or {})
            pdf_url = location.get("url_for_pdf")
            if pdf_url:
                pdf = fetch_corpus._get(pdf_url, CONTACT, timeout=60)
                if pdf[:4] == b"%PDF":
                    (out / f"{stem}.pdf").write_bytes(pdf)
                    return f"{stem}.pdf", "unpaywall"
        except Exception:
            pass
    return None, None


def build(queries: list[str], out: Path, *, page_size: int = 25, max_docs: int = 8) -> dict[str, Any]:
    """Search, rank, fetch and freeze. Returns the manifest plus the chosen documents."""
    out.mkdir(parents=True, exist_ok=True)
    pool: dict[str, dict[str, Any]] = {}
    errors = []
    for query in queries:
        try:
            results = _search(query, page_size)
        except Exception as error:
            errors.append(f"{query[:80]}: {type(error).__name__}: {error}")
            continue
        for rank, record in enumerate(results):
            key = record.get("doi") or record.get("pmcid") or record.get("id")
            if not key:
                continue
            entry = pool.setdefault(key, {"record": record, "best_rank": rank, "hits": 0, "query": query})
            entry["hits"] += 1
            entry["best_rank"] = min(entry["best_rank"], rank)
    # Rank by search position, how many queries found it, and citations, preferring papers with open full text.
    candidates = sorted(pool.values(), key=lambda e: e["best_rank"] - 2 * e["hits"])[: max_docs * 4]
    for entry in candidates:
        entry["citations"] = _citations(entry["record"].get("doi"))
        time.sleep(0.1)

    def score(entry: dict[str, Any]) -> float:
        record = entry["record"]
        open_text = record.get("isOpenAccess") == "Y" or (record.get("doi") or "").startswith("10.1101/")
        return (math.log1p(entry.get("citations") or 0) + 2 * entry["hits"] - 0.15 * entry["best_rank"]
                + (3 if open_text else 0))

    documents = []
    for entry in sorted(candidates, key=score, reverse=True):
        if len(documents) >= max_docs:
            break
        record = entry["record"]
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", record.get("pmcid") or record.get("id") or record.get("doi"))[:60]
        meta = {"id": record.get("id"), "pmid": record.get("pmid"), "pmcid": record.get("pmcid"),
                "doi": record.get("doi"), "title": _plain(record.get("title")), "year": record.get("pubYear"),
                "journal": (record.get("journalInfo") or {}).get("journal", {}).get("title"),
                "abstract": _plain(record.get("abstractText")), "citations": entry.get("citations"),
                "query": entry["query"]}
        name, source = _full_text(record, out, stem)
        if name is None:
            if not meta["abstract"]:
                continue
            (out / f"{stem}.txt").write_text(f"{meta['title']}\n\n{meta['abstract']}\n")
            name, source = f"{stem}.txt", "abstract"
        meta_body = json.dumps(meta, indent=1, sort_keys=True).encode()
        (out / f"{stem}.meta.json").write_bytes(meta_body)
        file_body = (out / name).read_bytes()
        documents.append({**meta, "file": name, "full_text": source != "abstract", "text_source": source,
                          "files": {name: fetch_corpus._sha256(file_body),
                                    f"{stem}.meta.json": fetch_corpus._sha256(meta_body)}})
        time.sleep(0.2)  # the published courtesy rate for the keyless tier
    manifest = {"format": "ppi-planning.corpus.manifest/v1",
                "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "contact_email": CONTACT, "queries": queries, "documents": documents}
    path = fetch_corpus.freeze(out, manifest)
    return {"manifest_sha256": (path.parent / "manifest.sha256").read_text().split()[0],
            "documents": [{k: v for k, v in d.items() if k not in ("abstract", "files")} for d in documents],
            "searched": len(pool), "errors": errors}
