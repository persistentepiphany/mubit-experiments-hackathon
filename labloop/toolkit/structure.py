"""Input writers and output readers for the structure predictors.

These run inside the Modal containers and are kept free of heavy imports so
they can be tested locally against recorded outputs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

AMINO = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXUO]+$")
BOLTZ_SCORES = ("confidence_score", "ptm", "iptm", "complex_plddt", "complex_iplddt", "complex_pde",
                "complex_ipde", "protein_iptm")


def clean_sequence(sequence: str) -> str:
    seq = re.sub(r"\s+", "", str(sequence)).upper()
    if not seq or not AMINO.match(seq):
        raise ValueError(f"not a protein sequence: {sequence[:40]!r}")
    return seq


def normalise_chains(chains: Any) -> list[dict[str, str]]:
    """Accept [{"id","sequence"}], {"A": "SEQ"} or ["SEQ", ...] and return the first form."""
    if isinstance(chains, dict):
        chains = [{"id": k, "sequence": v} for k, v in chains.items()]
    if isinstance(chains, str):
        chains = [chains]
    out = []
    for index, chain in enumerate(chains or []):
        if isinstance(chain, str):
            chain = {"sequence": chain}
        cid = str(chain.get("id") or chr(ord("A") + index))
        out.append({"id": cid, "sequence": clean_sequence(chain["sequence"])})
    if not out:
        raise ValueError("no chains given")
    if len({c["id"] for c in out}) != len(out):
        raise ValueError("chain ids must be unique")
    return out


def safe_name(name: str | None, default: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", name or default).strip("_")
    return text[:48] or default


def boltz_yaml(chains: list[dict[str, str]]) -> str:
    lines = ["version: 1", "sequences:"]
    for chain in chains:
        lines += ["  - protein:", f"      id: {chain['id']}", f"      sequence: {chain['sequence']}"]
    return "\n".join(lines) + "\n"


def boltz_outputs(out_dir: Path, name: str) -> dict[str, Path]:
    """Locate the top model's structure and confidence file in a Boltz output tree."""
    predictions = next(out_dir.glob(f"boltz_results_*/predictions/{name}"), None)
    if predictions is None:
        raise FileNotFoundError(f"no Boltz predictions for {name} under {out_dir}")
    structure = next(iter(sorted(predictions.glob(f"{name}_model_0.*"))), None)
    confidence = predictions / f"confidence_{name}_model_0.json"
    if structure is None or not confidence.exists():
        raise FileNotFoundError(f"Boltz output for {name} lacks model_0 structure or confidence")
    return {"structure": structure, "confidence": confidence}


def boltz_scores(confidence: Path) -> dict[str, float]:
    document = json.loads(Path(confidence).read_text())
    return {k: float(document[k]) for k in BOLTZ_SCORES if isinstance(document.get(k), (int, float))}


def chai_fasta(chains: list[dict[str, str]]) -> str:
    return "".join(f">protein|name={c['id']}\n{c['sequence']}\n" for c in chains)


def mean_ca_bfactor(pdb_text: str) -> float | None:
    values = [float(line[60:66]) for line in pdb_text.splitlines()
              if line.startswith("ATOM") and line[12:16].strip() == "CA"]
    return sum(values) / len(values) if values else None
