"""CPU data functions. Plain Python so they run in a Modal container or locally.

Every function takes one dict of arguments and returns the common result shape
`{"tool", "scores", "artifacts", "data"}`. Artifact paths are relative to the
artifacts root, which is the `labloop-artifacts` Volume on Modal.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from labloop.lit import fetch_corpus

UNIPROT = "https://rest.uniprot.org/uniprotkb/{accession}.fasta"
RCSB = "https://files.rcsb.org/download/{pdb_id}.pdb"
USER_AGENT = "labloop/0.1 (mailto:{email})"
CONTACT = "labloop@example.org"

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G",
    "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P", "SER": "S",
    "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V", "MSE": "M", "SEC": "U", "PYL": "O",
}


def _get(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT.format(email=CONTACT)})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_uniprot(args: dict[str, Any], artifacts_root: Path | None = None) -> dict[str, Any]:
    accession = str(args["accession"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,20}", accession):
        raise ValueError(f"not a UniProt accession: {accession!r}")
    text = _get(UNIPROT.format(accession=accession)).decode()
    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith(">"):
        raise ValueError(f"UniProt returned no FASTA record for {accession}")
    sequence = "".join(lines[1:]).strip()
    return {"tool": "fetch_uniprot", "scores": {"length": len(sequence)}, "artifacts": {},
            "data": {"sequence": sequence, "header": lines[0][1:]}}


def chains_from_pdb(text: str) -> dict[str, str]:
    chains: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        if line.startswith("ENDMDL"):
            break
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            chain, resseq = line[21], line[22:27]
            if (chain, resseq) in seen:
                continue
            seen.add((chain, resseq))
            chains.setdefault(chain, []).append(THREE_TO_ONE.get(line[17:20].strip(), "X"))
    return {c: "".join(s) for c, s in chains.items()}


def fetch_pdb(args: dict[str, Any], artifacts_root: Path | None = None) -> dict[str, Any]:
    pdb_id = str(args["pdb_id"]).strip().upper()
    if not re.fullmatch(r"[0-9][A-Z0-9]{3}", pdb_id):
        raise ValueError(f"not a PDB id: {pdb_id!r}")
    text = _get(RCSB.format(pdb_id=pdb_id)).decode()
    chains = chains_from_pdb(text)
    n_atoms = sum(1 for line in text.splitlines() if line.startswith(("ATOM", "HETATM")))
    artifacts = {}
    if artifacts_root is not None:
        rel = Path(args.get("run_id", "adhoc")) / args.get("step_id", "fetch_pdb") / f"{pdb_id}.pdb"
        (artifacts_root / rel).parent.mkdir(parents=True, exist_ok=True)
        (artifacts_root / rel).write_text(text)
        artifacts["structure"] = str(rel)
    return {"tool": "fetch_pdb", "scores": {"n_atoms": n_atoms, "n_chains": len(chains)},
            "artifacts": artifacts, "data": {"chains": chains}}


def _strip_tags(xml: bytes) -> str:
    text = re.sub(rb"<[^>]+>", b" ", xml).decode("utf-8", "replace")
    return re.sub(r"\s+", " ", text).strip()


def literature_search(args: dict[str, Any], artifacts_root: Path | None = None) -> dict[str, Any]:
    """Europe PMC search with abstracts, using the vendored corpus fetcher's endpoints."""
    query = str(args["query"])
    page_size = max(1, min(int(args.get("page_size", 5)), 25))
    fulltext_chars = max(0, min(int(args.get("fulltext_chars", 0)), 20000))
    params = urllib.parse.urlencode({"query": query, "format": "json", "pageSize": page_size,
                                     "resultType": "core"})
    payload = json.loads(fetch_corpus._get(f"{fetch_corpus.EUROPEPMC}/search?{params}", CONTACT))
    results = []
    for r in payload.get("resultList", {}).get("result", []):
        record = {
            "id": r.get("id"), "source": r.get("source"), "pmid": r.get("pmid"), "pmcid": r.get("pmcid"),
            "doi": r.get("doi"), "title": r.get("title"), "year": r.get("pubYear"),
            "journal": (r.get("journalInfo") or {}).get("journal", {}).get("title"),
            "is_open_access": r.get("isOpenAccess"),
            "abstract": re.sub(r"<[^>]+>", "", r.get("abstractText") or ""),
            "fulltext_excerpt": None,
        }
        if fulltext_chars and r.get("pmcid") and r.get("isOpenAccess") == "Y":
            try:
                xml = fetch_corpus.europepmc_fulltext(r["pmcid"], CONTACT)
            except (urllib.error.URLError, TimeoutError):
                xml = None
            if xml:
                record["fulltext_excerpt"] = _strip_tags(xml)[:fulltext_chars]
        results.append(record)
    return {"tool": "literature_search", "scores": {"n_results": len(results)}, "artifacts": {},
            "data": {"results": results, "query": query}}


DATA_TOOLS = {"fetch_uniprot": fetch_uniprot, "fetch_pdb": fetch_pdb, "literature_search": literature_search}
