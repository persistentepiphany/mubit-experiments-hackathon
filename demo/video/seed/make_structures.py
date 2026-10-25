"""Writes the two mocked ESMFold structures the demo shows.

Neither is a real prediction. The 30-residue chain is an ideal model built
from its sequence: a short coil for the GSHM tag and an alpha helix for the
rest. The Trp-cage model is the first NMR model of PDB 1L2Y. Each has a
per-residue confidence written into the B-factor column, where ESMFold puts
pLDDT, scaled so its mean matches the run's mocked mean pLDDT.

    python seed/make_structures.py <1L2Y.pdb> <out dir>

Needs PeptideBuilder and biopython.
"""

import sys
from pathlib import Path

import PeptideBuilder
from Bio.PDB import PDBIO, PDBParser
from PeptideBuilder import Geometry

PEPTIDE = "GSHMKTAYIAKQRQISFVKSHFSRQLEERL"
RUN_A, RUN_B, RUN_C = "r-20261021-150212-5d8e3a", "r-20261021-152940-8b1f07", "r-20261021-160518-c07b91"


def confidences(raw: list[float], mean: float) -> list[float]:
    shift = mean - sum(raw) / len(raw)
    return [max(30.0, min(98.5, round(v + shift, 2))) for v in raw]


def write(structure, scores: list[float], path: Path) -> None:
    for residue, score in zip(structure.get_residues(), scores):
        for atom in residue:
            atom.set_bfactor(score)
    path.parent.mkdir(parents=True, exist_ok=True)
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(path))


def peptide():
    tag, tail = 4, 2
    geos = []
    for i, aa in enumerate(PEPTIDE):
        geo = Geometry.geometry(aa)
        helix = tag <= i < len(PEPTIDE) - tail
        geo.phi, geo.psi_im1 = (-57.0, -47.0) if helix else (-70.0, 140.0)
        geos.append(geo)
    structure = PeptideBuilder.initialize_res(geos[0])
    for geo in geos[1:]:
        PeptideBuilder.add_residue(structure, geo)
    raw = [62, 66, 71, 78] + [90 + (3 if 8 < i < 24 else 0) for i in range(4, 28)] + [80, 72]
    return structure, confidences(raw, 89.7)


def trp_cage(source: Path):
    full = PDBParser(QUIET=True).get_structure("1L2Y", str(source))
    model = full[0]
    for other in list(full)[1:]:
        full.detach_child(other.id)
    raw = [64, 80, 88, 90, 91, 90, 88, 84, 78, 70, 74, 78, 76, 74, 72, 70, 72, 74, 70, 60]
    return model, confidences(raw, 78.4)


def main(source: Path, out: Path) -> None:
    structure, scores = peptide()
    for run in (RUN_A, RUN_B):
        write(structure, scores, out / run / "fold" / "model.pdb")
    model, scores = trp_cage(source)
    write(model, scores, out / RUN_C / "fold" / "model.pdb")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
