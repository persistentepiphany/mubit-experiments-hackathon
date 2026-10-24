import os
from pathlib import Path

import pytest

from labloop.graders.ppi import PPIAssureGrader

CHECKOUT = os.environ.get("PPI_HARNESS_PATH")
PLAN = {"steps": [{"id": "cofold", "tool": "boltz2", "args": {}}], "checks": []}


def test_grader_skips_monomers_and_absent_outputs():
    grader = PPIAssureGrader()
    assert not grader.applies(PLAN, {"cofold": {"scores": {"n_chains": 1}}})
    assert grader.applies(PLAN, {"cofold": {"scores": {"n_chains": 2}}})


@pytest.mark.skipif(not CHECKOUT or not Path(CHECKOUT, "fixtures").is_dir(),
                    reason="PPI_HARNESS_PATH does not point at a ppi-harness checkout with fixtures")
def test_grader_reads_a_recorded_boltz_screen():
    results = {"cofold": {"scores": {"n_chains": 2}, "artifacts": {"output_dir": "clean_boltz"}}}
    report = PPIAssureGrader().grade(PLAN, results, Path(CHECKOUT) / "fixtures" / "synthetic")
    assert report["reports"][0]["adapter"] == "boltz"
    assert report["status"] in ("PASS", "FAIL") and report["blocking"] == bool(report["blocking_findings"])
