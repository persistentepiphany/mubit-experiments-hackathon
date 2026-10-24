"""The ppi-assure grader for protein-protein co-folding outputs.

It applies only to Boltz-2 and Chai-1 steps with two or more chains, and only
when ppi-assure is importable, either installed or found through the
`PPI_HARNESS_PATH` environment variable. A finding counts against the verdict
only when ppi-assure reports it as a FAIL of BLOCKING severity. Everything else
it reports is recorded as advisory, because most of its checks need declarations
and measurement backends that a small run does not have, and an unmet
precondition there is unverifiable rather than negative.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

COFOLD_TOOLS = {"boltz2", "chai1"}


def _import_audit():
    extra = os.environ.get("PPI_HARNESS_PATH")
    if extra and extra not in sys.path:
        sys.path.insert(0, extra)
    try:
        from ppi_assure.core.run import audit
    except Exception:
        return None
    return audit


class PPIAssureGrader:
    name = "ppi-assure"

    def _cofold_steps(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [s for s in plan["steps"] if s["tool"] in COFOLD_TOOLS]

    def applies(self, plan: dict[str, Any], results: dict[str, dict[str, Any]]) -> bool:
        for step in self._cofold_steps(plan):
            scores = (results.get(step["id"]) or {}).get("scores", {})
            if (scores.get("n_chains") or 0) >= 2:
                return True
        return False

    def grade(self, plan: dict[str, Any], results: dict[str, dict[str, Any]],
              artifacts_root: Path | None) -> dict[str, Any]:
        audit = _import_audit()
        if audit is None:
            return {"status": "UNVERIFIABLE", "blocking": False,
                    "reason": "ppi-assure is not importable; set PPI_HARNESS_PATH to a checkout"}
        if artifacts_root is None:
            return {"status": "UNVERIFIABLE", "blocking": False,
                    "reason": "the artifacts volume is not mounted where grading runs"}
        reports, blocking_fails = [], []
        for step in self._cofold_steps(plan):
            result = results.get(step["id"]) or {}
            output_dir = (result.get("artifacts") or {}).get("output_dir")
            if not output_dir:
                continue
            run = audit(artifacts_root / output_dir, measurements=False)
            document = run.as_document()
            fails = [f for f in document["findings"]
                     if f.get("status") == "FAIL" and f.get("severity") == "BLOCKING"]
            blocking_fails += [f"{step['id']}:{f['check_id']}" for f in fails]
            reports.append({"step": step["id"], "adapter": document["adapter"],
                            "counts": document["counts"],
                            "safe_to_interpret": document["safe_to_interpret"]})
        if not reports:
            return {"status": "UNVERIFIABLE", "blocking": False, "reason": "no co-folding output directory"}
        return {"status": "FAIL" if blocking_fails else "PASS", "blocking": bool(blocking_fails),
                "blocking_findings": blocking_fails, "reports": reports}
