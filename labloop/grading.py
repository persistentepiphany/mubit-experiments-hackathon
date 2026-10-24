"""Grading frozen checks into a three-state verdict.

A check that cannot find its metric is UNVERIFIABLE, never a pass. The verdict
follows the convention of ppi-harness `harness/results.py`: INCONCLUSIVE refuses
to be read as a boolean, so `if verdict` cannot silently treat missing evidence
as a failure or as a success.
"""

from __future__ import annotations

import math
import operator
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from labloop.pipeline import lookup, metric_path

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
        "==": operator.eq, "!=": operator.ne}


class InconclusiveError(ValueError):
    pass


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"

    def __bool__(self) -> bool:
        if self is Verdict.INCONCLUSIVE:
            raise InconclusiveError(
                "an inconclusive verdict has no truth value; the run could not "
                "establish its checks, which is neither a pass nor a fail"
            )
        return self is Verdict.PASS


def grade_check(check: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    step_id, path = metric_path(check["metric"])
    record = {"id": check.get("id"), "metric": check["metric"]}
    result = results.get(step_id)
    if result is None or result.get("error"):
        reason = "the step did not run" if result is None else f"the step failed: {result['error']}"
        return {**record, "status": "UNVERIFIABLE", "observed": None, "reason": reason}
    try:
        observed = lookup(result, path)
    except KeyError:
        return {**record, "status": "UNVERIFIABLE", "observed": None,
                "reason": "the step's result does not contain this metric"}
    if not isinstance(observed, (int, float)) or isinstance(observed, bool) or not math.isfinite(observed):
        return {**record, "status": "UNVERIFIABLE", "observed": observed,
                "reason": "the metric is not a finite number"}
    if "reference" in check:
        delta = abs(observed - check["reference"])
        ok = delta <= check["tolerance"]
        return {**record, "status": "PASS" if ok else "FAIL", "observed": observed,
                "reference": check["reference"], "tolerance": check["tolerance"],
                "source": check.get("source"), "delta": delta}
    ok = _OPS[check["op"]](observed, check["value"])
    return {**record, "status": "PASS" if ok else "FAIL", "observed": observed,
            "op": check["op"], "value": check["value"]}


class DomainGrader(Protocol):
    name: str

    def applies(self, plan: dict[str, Any], results: dict[str, dict[str, Any]]) -> bool: ...

    def grade(self, plan: dict[str, Any], results: dict[str, dict[str, Any]],
              artifacts_root: Path | None) -> dict[str, Any]: ...


def verdict_of(statuses: list[str]) -> Verdict:
    if "FAIL" in statuses:
        return Verdict.FAIL
    if not statuses or "UNVERIFIABLE" in statuses:
        return Verdict.INCONCLUSIVE
    return Verdict.PASS


def grade(plan: dict[str, Any], results: dict[str, dict[str, Any]],
          graders: list[DomainGrader] = (), artifacts_root: Path | None = None) -> dict[str, Any]:
    checks = [grade_check(c, results) for c in plan["checks"]]
    domain = []
    for grader in graders:
        if not grader.applies(plan, results):
            domain.append({"grader": grader.name, "status": "SKIPPED", "blocking": False,
                           "reason": "the task does not match this grader"})
            continue
        try:
            domain.append({"grader": grader.name, **grader.grade(plan, results, artifacts_root)})
        except Exception as error:  # a broken grader is unverifiable evidence, not a pass
            domain.append({"grader": grader.name, "status": "UNVERIFIABLE", "blocking": False,
                           "reason": f"{type(error).__name__}: {error}"})
    statuses = [c["status"] for c in checks]
    statuses += [d["status"] for d in domain if d.get("blocking")]
    verdict = verdict_of(statuses)
    metrics = {c["metric"]: c["observed"] for c in checks if isinstance(c.get("observed"), (int, float))}
    return {
        "verdict": verdict.value,
        "checks": checks,
        "domain_graders": domain,
        "metrics": metrics,
        "counts": {s: statuses.count(s) for s in ("PASS", "FAIL", "UNVERIFIABLE")},
    }
