#!/usr/bin/env python3
"""Fetch a literature corpus from keyless sources, then freeze and hash it.

Four sources, none of which needs an API key:

  Europe PMC    https://www.ebi.ac.uk/europepmc/webservices/rest/search
                https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML
  OpenAlex      https://api.openalex.org
  Unpaywall     https://api.unpaywall.org/v2/{doi}?email=...   (email, not a key)
  bioRxiv       https://api.biorxiv.org/details/biorxiv/{doi}

The corpus is the evidence base for the planning stage, so it is frozen rather
than live: every document is written once, `manifest.json` records the sha256 of
each file and of the query that produced it, and `freeze` refuses to overwrite a
manifest that already exists. A question answered against a corpus nobody can
re-hash is a question answered against nothing.

PaperQA2 reads the frozen directory afterwards; it is not called from here, so
this script needs no model credential and makes no model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org"
UNPAYWALL = "https://api.unpaywall.org/v2"
BIORXIV = "https://api.biorxiv.org/details/biorxiv"

# A contact address is Unpaywall's condition of use and OpenAlex's polite-pool
# request. It is not a secret and is not a key; it is read from the environment
# or passed in, so it is not committed here.
USER_AGENT = "ppi-planning-corpus/0.1 (mailto:{email})"


def _get(url: str, email: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT.format(email=email)}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def europepmc_search(query: str, email: str, page_size: int = 25) -> list[dict]:
    """Search Europe PMC. Returns the result list as the API gave it."""
    params = urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": page_size}
    )
    payload = json.loads(_get(f"{EUROPEPMC}/search?{params}", email))
    return payload.get("resultList", {}).get("result", [])


def europepmc_fulltext(pmcid: str, email: str) -> bytes | None:
    """Open-access full text as XML, or None when there is none to fetch.

    Availability is the rule rather than the exception's exception: most records
    are abstract-only, and a 404 here is an ordinary outcome, not a failure.
    """
    try:
        return _get(f"{EUROPEPMC}/{pmcid}/fullTextXML", email)
    except urllib.error.HTTPError as error:
        if error.code in (400, 404):
            return None
        raise


def openalex_work(doi: str, email: str) -> dict:
    """Metadata, citation counts and concepts for a DOI."""
    return json.loads(_get(f"{OPENALEX}/works/doi:{doi}?mailto={email}", email))


def unpaywall(doi: str, email: str) -> dict:
    """Open-access status and the best free location for a DOI."""
    return json.loads(_get(f"{UNPAYWALL}/{doi}?email={urllib.parse.quote(email)}", email))


def biorxiv(doi: str, email: str) -> dict:
    """Preprint detail, including the version history a citation should pin."""
    return json.loads(_get(f"{BIORXIV}/{doi}", email))


def fetch(queries: list[str], out: Path, email: str, page_size: int) -> dict:
    """Fetch every query into `out`, returning the manifest that describes it."""
    out.mkdir(parents=True, exist_ok=True)
    documents: list[dict] = []
    for query in queries:
        results = europepmc_search(query, email, page_size)
        for result in results:
            record = {
                "source": "europepmc",
                "query": query,
                "query_sha256": _sha256(query.encode()),
                "id": result.get("id"),
                "pmcid": result.get("pmcid"),
                "doi": result.get("doi"),
                "title": result.get("title"),
                "year": result.get("pubYear"),
                "is_open_access": result.get("isOpenAccess"),
            }
            stem = result.get("pmcid") or result.get("id") or _sha256(
                json.dumps(result, sort_keys=True).encode()
            )[:12]
            meta_path = out / f"{stem}.meta.json"
            body = json.dumps(result, indent=1, sort_keys=True).encode()
            meta_path.write_bytes(body)
            record["files"] = {meta_path.name: _sha256(body)}

            if result.get("pmcid"):
                text = europepmc_fulltext(result["pmcid"], email)
                if text is not None:
                    text_path = out / f"{stem}.fulltext.xml"
                    text_path.write_bytes(text)
                    record["files"][text_path.name] = _sha256(text)
                    record["full_text"] = True
                else:
                    record["full_text"] = False
            documents.append(record)
            time.sleep(0.2)  # the published courtesy rate for the keyless tier
    return {
        "format": "ppi-planning.corpus.manifest/v1",
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contact_email": email,
        "queries": queries,
        "documents": documents,
    }


def freeze(out: Path, manifest: dict, force: bool = False) -> Path:
    """Write the manifest, refusing to overwrite a freeze that already exists."""
    path = out / "manifest.json"
    if path.exists() and not force:
        raise SystemExit(
            f"{path} exists: the corpus is already frozen. Fetch into a new "
            "directory rather than editing a frozen one, or pass --force to "
            "state plainly that you are replacing it."
        )
    body = json.dumps(manifest, indent=1, sort_keys=True).encode()
    path.write_bytes(body)
    (out / "manifest.sha256").write_text(f"{_sha256(body)}  manifest.json\n")
    return path


def verify(out: Path) -> int:
    """Re-hash every file the manifest names. Exit non-zero on any mismatch."""
    manifest = json.loads((out / "manifest.json").read_bytes())
    problems: list[str] = []
    for document in manifest["documents"]:
        for name, digest in document["files"].items():
            path = out / name
            if not path.exists():
                problems.append(f"missing: {name}")
            elif _sha256(path.read_bytes()) != digest:
                problems.append(f"changed since the freeze: {name}")
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(manifest['documents'])} documents, {len(problems)} problems")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--email",
        required=True,
        help="contact address: Unpaywall requires it, OpenAlex asks for it",
    )
    parser.add_argument("--query", action="append", default=[], help="repeatable")
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="re-hash an existing freeze and report, fetching nothing",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        return verify(args.out)
    if not args.query:
        parser.error("--query is required unless --verify-only")
    # Checked before the first fetch rather than at the freeze: a run that is
    # going to be refused must not write documents into a frozen directory on
    # its way to being refused. Found by running it twice.
    if (args.out / "manifest.json").exists() and not args.force:
        freeze(args.out, {}, force=False)
    manifest = fetch(args.query, args.out, args.email, args.page_size)
    path = freeze(args.out, manifest, args.force)
    print(f"froze {len(manifest['documents'])} documents in {path.parent} ({path.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
