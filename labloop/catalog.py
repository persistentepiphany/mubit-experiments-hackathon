"""The tool catalog.

Every tool here is one function of the Modal app `labloop-tools`. Planning
chooses only from the entries marked available, and never writes
infrastructure. Each function takes one dict of arguments and returns a dict
with `scores`, `artifacts` (paths relative to the `labloop-artifacts` Volume)
and `data` (small structured outputs such as a fetched sequence).
"""

from __future__ import annotations

from typing import Any

APP_NAME = "labloop-tools"

CHAIN_LIST = {
    "type": "array",
    "description": "chains as [{\"id\": \"A\", \"sequence\": \"...\"}]; protein only",
}

CATALOG: dict[str, dict[str, Any]] = {
    "esmfold": {
        "kind": "model",
        "purpose": "Fast single-chain protein structure prediction from sequence, without MSAs.",
        "inputs": {
            "sequence": {"type": "string", "required": True, "description": "one protein chain, single-letter codes"},
            "name": {"type": "string", "required": False, "description": "label for output files"},
        },
        "scores": ["mean_plddt", "ptm", "length"],
        "artifacts": ["structure"],
        "data": [],
        "gpu": "A10G",
        "typical_runtime_s": 60,
        "available": True,
        "notes": "mean_plddt is on a 0 to 100 scale. Monomers only.",
    },
    "boltz2": {
        "kind": "model",
        "purpose": "Biomolecular complex structure prediction (Boltz-2), including protein-protein co-folding.",
        "inputs": {
            "chains": {**CHAIN_LIST, "required": True},
            "seed": {"type": "integer", "required": False, "description": "random seed, default 0"},
            "recycling_steps": {"type": "integer", "required": False, "description": "default 3"},
            "sampling_steps": {"type": "integer", "required": False, "description": "default 200"},
            "diffusion_samples": {"type": "integer", "required": False, "description": "default 1"},
            "use_msa_server": {"type": "boolean", "required": False, "description": "default true, public ColabFold MSA server"},
            "name": {"type": "string", "required": False, "description": "label for output files"},
        },
        "scores": ["confidence_score", "ptm", "iptm", "complex_plddt", "complex_iplddt", "complex_pde", "n_chains"],
        "artifacts": ["structure", "confidence", "output_dir"],
        "data": [],
        "gpu": "H100",
        "typical_runtime_s": 300,
        "available": True,
        "notes": "complex_plddt is on a 0 to 1 scale. iptm is only meaningful with two or more chains.",
    },
    "chai1": {
        "kind": "model",
        "purpose": "Biomolecular complex structure prediction (Chai-1), an independent second opinion to Boltz-2.",
        "inputs": {
            "chains": {**CHAIN_LIST, "required": True},
            "seed": {"type": "integer", "required": False, "description": "random seed, default 0"},
            "num_trunk_recycles": {"type": "integer", "required": False, "description": "default 3"},
            "num_diffn_timesteps": {"type": "integer", "required": False, "description": "default 200"},
            "use_msa_server": {"type": "boolean", "required": False, "description": "default false"},
            "name": {"type": "string", "required": False, "description": "label for output files"},
        },
        "scores": ["aggregate_score", "ptm", "iptm", "n_chains"],
        "artifacts": ["structure", "scores", "output_dir"],
        "data": [],
        "gpu": "H100",
        "typical_runtime_s": 300,
        "available": True,
        "notes": "Scores are those of the top-ranked of five diffusion samples.",
    },
    "fetch_uniprot": {
        "kind": "data",
        "purpose": "Fetch a protein sequence from UniProtKB by accession.",
        "inputs": {"accession": {"type": "string", "required": True, "description": "e.g. P69905"}},
        "scores": ["length"],
        "artifacts": [],
        "data": ["sequence", "header"],
        "gpu": None,
        "typical_runtime_s": 3,
        "available": True,
        "notes": "data.sequence can feed a model step through $steps.<id>.data.sequence.",
    },
    "fetch_pdb": {
        "kind": "data",
        "purpose": "Fetch an experimental structure from the RCSB PDB by four-character id.",
        "inputs": {"pdb_id": {"type": "string", "required": True, "description": "e.g. 1CRN"}},
        "scores": ["n_atoms", "n_chains"],
        "artifacts": ["structure"],
        "data": ["chains", "first_chain_id", "first_chain_sequence"],
        "gpu": None,
        "typical_runtime_s": 3,
        "available": True,
        "notes": "data.chains maps chain id to one-letter sequence read from ATOM records; chain ids are not known "
                 "before the fetch, so feed a single-chain step from data.first_chain_sequence (a plain string).",
    },
    "literature_search": {
        "kind": "data",
        "purpose": "Search Europe PMC and return titles, abstracts and open-access full-text excerpts.",
        "inputs": {
            "query": {"type": "string", "required": True, "description": "Europe PMC query syntax"},
            "page_size": {"type": "integer", "required": False, "description": "default 5"},
            "fulltext_chars": {"type": "integer", "required": False, "description": "characters of full text per paper, default 0"},
        },
        "scores": ["n_results"],
        "artifacts": [],
        "data": ["results"],
        "gpu": None,
        "typical_runtime_s": 5,
        "available": True,
        "notes": "Used by the research step; rarely useful inside a pipeline.",
    },
    "colabfold": {
        "kind": "model",
        "purpose": "AlphaFold2 and AlphaFold-Multimer prediction with MMseqs2 MSAs (ColabFold).",
        "inputs": {"chains": {**CHAIN_LIST, "required": True}, "seed": {"type": "integer", "required": False, "description": "default 0"}},
        "scores": ["mean_plddt", "ptm", "iptm"],
        "artifacts": ["structure"],
        "data": [],
        "gpu": "A100",
        "typical_runtime_s": 600,
        "available": False,
        "notes": "Not deployed; the image has not been built and verified.",
    },
    "proteinmpnn": {
        "kind": "model",
        "purpose": "Design sequences for a given protein backbone (ProteinMPNN).",
        "inputs": {
            "structure": {"type": "string", "required": True, "description": "artifact path of a PDB backbone"},
            "num_sequences": {"type": "integer", "required": False, "description": "default 4"},
            "sampling_temp": {"type": "number", "required": False, "description": "default 0.1"},
            "seed": {"type": "integer", "required": False, "description": "default 0"},
        },
        "scores": ["best_score", "mean_recovery"],
        "artifacts": ["fasta"],
        "data": ["sequences"],
        "gpu": "A10G",
        "typical_runtime_s": 60,
        "available": False,
        "notes": "Not deployed until the first three model tools are verified.",
    },
    "rfdiffusion": {"kind": "model", "purpose": "Backbone generation (RFdiffusion).", "inputs": {}, "scores": [], "artifacts": [], "data": [], "gpu": "A100", "typical_runtime_s": 600, "available": False, "notes": "Optional; not deployed."},
    "diffdock": {"kind": "model", "purpose": "Protein-ligand docking (DiffDock).", "inputs": {}, "scores": [], "artifacts": [], "data": [], "gpu": "A10G", "typical_runtime_s": 300, "available": False, "notes": "Optional; not deployed."},
    "protenix": {"kind": "model", "purpose": "AF3-class complex prediction (Protenix).", "inputs": {}, "scores": [], "artifacts": [], "data": [], "gpu": "H100", "typical_runtime_s": 600, "available": False, "notes": "Optional; not deployed."},
    "alphafold3": {"kind": "model", "purpose": "AlphaFold 3 complex prediction.", "inputs": {}, "scores": [], "artifacts": [], "data": [], "gpu": "H100", "typical_runtime_s": 900, "available": False, "notes": "Stub; weights are available only on request from Google DeepMind."},
}


def available() -> dict[str, dict[str, Any]]:
    return {name: entry for name, entry in CATALOG.items() if entry["available"]}


def output_fields(tool: str) -> set[str]:
    """Dotted fields a later step or a check may reference on this tool's result."""
    entry = CATALOG[tool]
    fields = {f"scores.{s}" for s in entry["scores"]}
    fields |= {f"artifacts.{a}" for a in entry["artifacts"]}
    fields |= {f"data.{d}" for d in entry["data"]}
    return fields


def for_prompt() -> list[dict[str, Any]]:
    """The available catalog in the shape the planner reads."""
    return [
        {
            "tool": name,
            "purpose": e["purpose"],
            "inputs": e["inputs"],
            "outputs": sorted(output_fields(name)),
            "gpu": e["gpu"],
            "typical_runtime_s": e["typical_runtime_s"],
            "notes": e["notes"],
        }
        for name, e in available().items()
    ]
