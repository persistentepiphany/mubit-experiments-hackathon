"""Pipelines: validation, reference resolution, scheduling and the freeze.

A pipeline is an ordered list of steps (`id`, `tool`, `args`) and a list of
acceptance checks. An argument whose whole value is a reference string is
replaced at run time. `$inputs.<name>` reads a task input, `$run_id` the run
identifier, and `$steps.<id>.<field>` a field of an earlier step's result,
where the field is `scores.<x>`, `artifacts.<x>` or `data.<x>` with optional
deeper keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from labloop import catalog
from labloop.canonical import digest_document

STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REF = re.compile(r"^\$(inputs|steps|run_id)(?:\.(.+))?$")
OPS = {">", ">=", "<", "<=", "==", "!="}
SECTIONS = {"scores", "artifacts", "data"}


class FrozenPlanError(RuntimeError):
    pass


def _refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if REF.match(value) else []
    if isinstance(value, dict):
        return [r for v in value.values() for r in _refs(v)]
    if isinstance(value, list):
        return [r for v in value for r in _refs(v)]
    return []


def step_dependencies(step: dict[str, Any]) -> set[str]:
    deps = set()
    for ref in _refs(step.get("args", {})):
        kind, rest = REF.match(ref).groups()
        if kind == "steps" and rest:
            deps.add(rest.split(".", 1)[0])
    return deps


def metric_path(metric: str) -> tuple[str, list[str]]:
    """Split a check's metric into a step id and a field path.

    `fold.mean_plddt` is shorthand for `fold.scores.mean_plddt`, and the
    `$steps.` prefix is accepted.
    """
    text = metric[len("$steps."):] if metric.startswith("$steps.") else metric
    parts = text.split(".")
    if len(parts) == 2:
        parts = [parts[0], "scores", parts[1]]
    return parts[0], parts[1:]


def _field_known(tool: str, path: list[str]) -> bool:
    if not path or path[0] not in SECTIONS or len(path) < 2:
        return False
    return f"{path[0]}.{path[1]}" in catalog.output_fields(tool)


def validate(plan: dict[str, Any], input_names: set[str]) -> list[str]:
    """Every reason this plan may not be frozen. An empty list means it may."""
    errors: list[str] = []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["the pipeline has no steps"]
    tools_by_step: dict[str, str] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"step {index} is not an object")
            continue
        sid, tool, args = step.get("id"), step.get("tool"), step.get("args", {})
        if not isinstance(sid, str) or not STEP_ID.match(sid):
            errors.append(f"step {index} has an invalid id {sid!r}")
            continue
        if sid in tools_by_step:
            errors.append(f"step id {sid!r} is used twice")
        entry = catalog.CATALOG.get(tool)
        if entry is None:
            errors.append(f"step {sid!r} names unknown tool {tool!r}")
            continue
        if entry["kind"] == "research":
            errors.append(f"step {sid!r} names {tool!r}, which only the research step uses")
            continue
        if not entry["available"]:
            errors.append(f"step {sid!r} names tool {tool!r}, which is not deployed")
            continue
        if not isinstance(args, dict):
            errors.append(f"step {sid!r} args must be an object")
            continue
        for name in args:
            if name not in entry["inputs"]:
                errors.append(f"step {sid!r} passes unknown argument {name!r} to {tool}")
        for name, spec in entry["inputs"].items():
            if spec.get("required") and name not in args:
                errors.append(f"step {sid!r} omits required argument {name!r} of {tool}")
        for ref in _refs(args):
            kind, rest = REF.match(ref).groups()
            if kind == "inputs" and (not rest or rest.split(".")[0] not in input_names):
                errors.append(f"step {sid!r} refers to undeclared input {ref!r}")
            elif kind == "steps":
                parts = (rest or "").split(".")
                if parts[0] not in tools_by_step:
                    errors.append(f"step {sid!r} refers to {ref!r}, which is not an earlier step")
                elif not _field_known(tools_by_step[parts[0]], parts[1:]):
                    errors.append(f"step {sid!r} refers to {ref!r}, which {tools_by_step[parts[0]]} does not produce")
            elif kind == "run_id" and rest:
                errors.append(f"step {sid!r} uses malformed reference {ref!r}")
        tools_by_step[sid] = tool

    checks = plan.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("the pipeline declares no acceptance checks")
        return errors
    seen: set[str] = set()
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"check {index} is not an object")
            continue
        cid = check.get("id") or f"check_{index}"
        if cid in seen:
            errors.append(f"check id {cid!r} is used twice")
        seen.add(cid)
        metric = check.get("metric")
        if not isinstance(metric, str):
            errors.append(f"check {cid!r} has no metric")
            continue
        step_id, path = metric_path(metric)
        if step_id not in tools_by_step:
            errors.append(f"check {cid!r} reads {metric!r} from a step that does not exist")
        elif not _field_known(tools_by_step[step_id], path):
            errors.append(f"check {cid!r} reads {metric!r}, which {tools_by_step[step_id]} does not produce")
        has_threshold = "op" in check or "value" in check
        has_reference = "reference" in check
        if has_threshold == has_reference:
            errors.append(f"check {cid!r} must have either op and value, or reference and tolerance")
        elif has_threshold:
            if check.get("op") not in OPS:
                errors.append(f"check {cid!r} has unknown op {check.get('op')!r}")
            if not isinstance(check.get("value"), (int, float)) or isinstance(check.get("value"), bool):
                errors.append(f"check {cid!r} value must be a number")
        else:
            if not isinstance(check.get("reference"), (int, float)):
                errors.append(f"check {cid!r} reference must be a number")
            if not isinstance(check.get("tolerance"), (int, float)) or check.get("tolerance") < 0:
                errors.append(f"check {cid!r} needs a non-negative tolerance")
            if not check.get("source"):
                errors.append(f"check {cid!r} matches a published reference but names no source")
    return errors


def lookup(result: dict[str, Any], path: list[str]) -> Any:
    value: Any = result
    for key in path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise KeyError(".".join(path))
    return value


def resolve(value: Any, inputs: dict[str, Any], run_id: str, results: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        match = REF.match(value)
        if not match:
            return value
        kind, rest = match.groups()
        if kind == "run_id":
            return run_id
        parts = rest.split(".")
        if kind == "inputs":
            return lookup(inputs, parts)
        return lookup(results[parts[0]], parts[1:])
    if isinstance(value, dict):
        return {k: resolve(v, inputs, run_id, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, inputs, run_id, results) for v in value]
    return value


def waves(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group steps so that each group depends only on earlier groups."""
    depth: dict[str, int] = {}
    for step in steps:
        deps = step_dependencies(step)
        depth[step["id"]] = 1 + max((depth[d] for d in deps), default=-1)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for step in steps:
        grouped.setdefault(depth[step["id"]], []).append(step)
    return [grouped[k] for k in sorted(grouped)]


def freeze(run_dir: Path, plan: dict[str, Any]) -> str:
    """Write the plan and its digest once, before anything executes."""
    path = run_dir / "plan.json"
    if path.exists():
        raise FrozenPlanError(f"{path} exists; a frozen plan is never rewritten")
    digest = digest_document(plan)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", "utf-8")
    (run_dir / "plan.sha256").write_text(f"{digest}  plan.json\n", "utf-8")
    path.chmod(0o444)
    return digest


def load_frozen(run_dir: Path) -> tuple[dict[str, Any], str]:
    """Read the frozen plan, refusing it if it no longer matches its digest."""
    plan = json.loads((run_dir / "plan.json").read_text("utf-8"))
    recorded = (run_dir / "plan.sha256").read_text("utf-8").split()[0]
    if digest_document(plan) != recorded:
        raise FrozenPlanError(f"the plan in {run_dir} has changed since it was frozen")
    return plan, recorded
