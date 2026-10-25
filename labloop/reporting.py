"""A one-page report for a finished (or unfinished) run.

`build_report` turns the bundle that `GET /runs/{id}` returns into a small set
of files: `report.html`, `report.json` and PNG figures under `figures/`. The
HTML references the figures by relative path only, so the directory can be
served as it is from a Volume or a storage bucket. Every sentence is composed
from the bundle by fixed templates; nothing here calls a model, and the same
bundle and artifacts always give the same files.

Each section is built from its own part of the bundle and is left out when
that part is missing. A section that fails to build is recorded in
`report.json` under `section_errors` and left out of the page, so one odd
field never costs the whole report.
"""

from __future__ import annotations

import html
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPORT_VERSION = 1

INK = "#2a2622"
MUTED = "#8a847a"
BG = "#f1ebe1"
OLIVE = "#a3a07a"
CLAY = "#c9937a"
SLATE = "#8da2b8"
FAIL = "#b4654f"
LINE = "#e7e2da"
STATUS_COLORS = {"PASS": OLIVE, "FAIL": FAIL, "UNVERIFIABLE": SLATE}
# Chain identity. Validated as a categorical set on white (lightness band, CVD
# separation and normal-vision separation pass); the fourth slot is a neutral
# that also takes every chain past the fourth, and every chain is labelled.
CHAIN_COLORS = ["#c0612f", "#9a4fa8", "#7d8a1a", "#6b6158"]
# Per-residue confidence: one hue (slate), light for low confidence and dark for high.
CONFIDENCE_RAMP = ["#dde5ee", "#a9bacb", "#6f8aa6", "#3d5f82", "#1d3550"]
DPI = 110

PREDICTORS = {"esmfold", "boltz2", "boltz", "chai1", "chai", "alphafold", "alphafold2", "alphafold3",
              "colabfold", "openfold", "protenix", "rosettafold"}
OPS = {">=": "≥", "<=": "≤", "==": "=", "!=": "≠", ">": ">", "<": "<"}
METRIC_NAMES = {
    "mean_plddt": "mean pLDDT", "plddt": "pLDDT", "ptm": "pTM", "iptm": "ipTM", "protein_iptm": "protein ipTM",
    "complex_plddt": "complex pLDDT", "complex_iplddt": "interface pLDDT", "complex_pde": "complex PDE",
    "complex_ipde": "interface PDE", "confidence_score": "confidence score", "n_chains": "chain count",
    "n_atoms": "atom count", "length": "sequence length", "ipsae": "ipSAE", "dockq": "DockQ", "rmsd": "RMSD",
    "pae": "PAE", "lddt": "lDDT", "tm_score": "TM-score",
}
CONFIDENCE_WORDS = ("plddt", "ptm", "iptm", "pae", "pde", "dockq", "rmsd", "ipsae", "lddt", "tm_score",
                    "confidence")
STEP_REF = re.compile(r"^\$steps\.([a-z][a-z0-9_]*)\.")
SOURCE_PART = re.compile(r"^\s*(\S+?)\s+chunks?\s+([\d,\s]+)\s*$", re.I)


# ----------------------------------------------------------------- formatting
def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value: Any) -> str:
    """A number in a short, fixed form: 90.477 is 90.5, 0.8289 is 0.829, 660 is 660."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return str(value)
    if value.is_integer() and abs(value) < 1e6:
        return str(int(value))
    size = abs(value)
    if size >= 10:
        return f"{value:.1f}"
    if size >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _count(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _cap(text: str) -> str:
    if not text or text[1:2].isupper():
        return text
    return text[:1].upper() + text[1:]


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        minutes, rest = divmod(seconds, 60)
        return f"{minutes} min {rest} s" if rest else f"{minutes} min"
    hours, rest = divmod(seconds, 3600)
    return f"{hours} h {rest // 60} min"


def _date(moment: datetime | None) -> str:
    return f"{moment.day} {moment:%B %Y}, {moment:%H:%M} UTC" if moment else ""


def _metric_parts(metric: str) -> tuple[str, str]:
    text = metric[len("$steps."):] if metric.startswith("$steps.") else metric
    parts = text.split(".")
    return parts[0], parts[-1]


def _metric_name(metric: str) -> str:
    _, field = _metric_parts(metric)
    return METRIC_NAMES.get(field.lower(), field.replace("_", " "))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# ------------------------------------------------------------------- the run
def _checks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Graded checks merged with their planned definitions (rationale, source)."""
    planned = {c.get("id"): c for c in _list(_dict(bundle.get("plan")).get("checks")) if isinstance(c, dict)}
    graded = [c for c in _list(_dict(bundle.get("results")).get("checks")) if isinstance(c, dict)]
    if graded:
        return [{**planned.get(c.get("id"), {}), **c} for c in graded]
    return [{**c, "status": "NOT GRADED", "observed": None} for c in planned.values()]


def _criterion(check: dict[str, Any]) -> str:
    if "reference" in check and check.get("reference") is not None:
        return f"{_num(check['reference'])} ± {_num(check.get('tolerance'))}"
    if check.get("op") in OPS:
        return f"{OPS[check['op']]} {_num(check.get('value'))}"
    return ""


def _check_phrase(check: dict[str, Any]) -> str:
    name = _metric_name(check.get("metric", ""))
    obs, status = check.get("observed"), check.get("status")
    if status == "UNVERIFIABLE" or not isinstance(obs, (int, float)) or isinstance(obs, bool):
        reason = check.get("reason") or "no value was recorded"
        return f"{name} could not be read because {reason}"
    o = _num(obs)
    if check.get("reference") is not None:
        ref, tol = _num(check["reference"]), _num(check.get("tolerance"))
        source = f" from {check['source']}" if check.get("source") else ""
        if status == "PASS":
            return f"{name} was {o}, within {tol} of the published {ref}{source}"
        return f"{name} was {o}, outside the tolerance of {tol} around the published {ref}{source}"
    op, v = check.get("op"), _num(check.get("value"))
    passed = status == "PASS"
    if op in (">=", ">"):
        return f"{name} was {o}, {'above' if passed else 'below'} the floor of {v}"
    if op in ("<=", "<"):
        return f"{name} was {o}, {'below' if passed else 'above'} the ceiling of {v}"
    if op == "==":
        return f"{name} was {o} as required" if passed else f"{name} was {o} where {v} was required"
    if op == "!=":
        return f"{name} was {o}, which differs from the excluded {v}" if passed else f"{name} was {o}, the excluded value"
    return f"{name} was {o}"


def _origin(bundle: dict[str, Any]) -> dict[str, Any]:
    plan, status, match = _dict(bundle.get("plan")), _dict(bundle.get("status")), _dict(bundle.get("match"))
    origin = _dict(plan.get("origin")) or _dict(status.get("origin"))
    if not origin and match.get("decision") == "reuse":
        origin = {"kind": "skill", "skill": match.get("skill"), "version": match.get("version")}
    if not origin and match.get("decision") == "plan":
        origin = {"kind": "planned"}
    return origin


def _origin_text(origin: dict[str, Any]) -> str:
    if origin.get("kind") == "skill":
        version = f" v{origin['version']}" if origin.get("version") is not None else ""
        return f"Skill {origin.get('skill')}{version}"
    if origin.get("kind") == "planned":
        return "New pipeline"
    return "Not decided yet"


def _timing(bundle: dict[str, Any]) -> tuple[datetime | None, datetime | None, bool]:
    """Start, end and whether the run has finished."""
    status = _dict(bundle.get("status"))
    history = [h for h in _list(status.get("history")) if isinstance(h, dict) and _time(h.get("at"))]
    events = [e for e in _list(bundle.get("events")) if isinstance(e, dict) and _time(e.get("at"))]
    moments = [_time(h["at"]) for h in history] + [_time(e["at"]) for e in events]
    if not moments:
        return None, None, False
    start = _time(history[0]["at"]) if history else min(moments)
    finished = status.get("phase") in ("done", "error")
    return min(start, min(moments)), max(moments), finished


def _verdict(bundle: dict[str, Any]) -> str:
    results, status = _dict(bundle.get("results")), _dict(bundle.get("status"))
    if results.get("verdict"):
        return str(results["verdict"])
    if status.get("verdict"):
        return str(status["verdict"])
    phase = status.get("phase") or bundle.get("phase")
    return "ERROR" if phase == "error" else "IN PROGRESS"


def _steps(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in _list(_dict(bundle.get("plan")).get("steps")) if isinstance(s, dict) and s.get("id")]


def _experiments(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["step_id"]: e for e in _list(bundle.get("experiments")) if isinstance(e, dict) and e.get("step_id")}


def _refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [r for v in value.values() for r in _refs(v)]
    if isinstance(value, list):
        return [r for v in value for r in _refs(v)]
    return []


def _dependencies(step: dict[str, Any]) -> tuple[set[str], bool]:
    deps, uses_inputs = set(), False
    for ref in _refs(step.get("args", {})):
        found = STEP_REF.match(ref)
        if found:
            deps.add(found.group(1))
        elif ref.startswith("$inputs."):
            uses_inputs = True
    return deps, uses_inputs


# ------------------------------------------------------------------ figures
def _mpl():
    import matplotlib
    from matplotlib.figure import Figure

    return matplotlib, Figure


def _style() -> dict[str, Any]:
    return {"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": INK,
            "axes.edgecolor": LINE, "xtick.color": MUTED, "ytick.color": MUTED, "axes.linewidth": 0.8,
            "savefig.facecolor": "white", "figure.facecolor": "white"}


def _png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, facecolor="white", metadata={"Software": None})
    return buffer.getvalue()


def pipeline_figure(bundle: dict[str, Any]) -> bytes | None:
    """Boxes for the steps in dependency order, an inputs box and a checks box, joined by arrows."""
    steps = _steps(bundle)
    if not steps:
        return None
    matplotlib, Figure = _mpl()
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    ids = {s["id"] for s in steps}
    deps = {s["id"]: _dependencies(s) for s in steps}
    level: dict[str, int] = {}
    for _ in range(len(steps) + 1):
        for s in steps:
            before = [level.get(d, 0) for d in deps[s["id"]][0] if d in ids]
            level[s["id"]] = 1 + max(before, default=0)
    columns: dict[int, list[str]] = {}
    for s in steps:
        columns.setdefault(level[s["id"]], []).append(s["id"])
    plan = _dict(bundle.get("plan"))
    inputs = list(_dict(plan.get("input_schema")) or _dict(_dict(bundle.get("task")).get("inputs")))
    n_checks = len(_list(plan.get("checks")))
    last = max(columns)
    tallest = max(len(c) for c in columns.values())
    width_units = last + 2
    box_w, box_h, gap_y = 1.45, 0.78, 0.32
    height_units = tallest * box_h + (tallest - 1) * gap_y
    fig_w = min(9.5, max(5.2, 1.85 * width_units))
    fig_h = max(1.6, 0.95 * height_units + 0.7)
    experiments = _experiments(bundle)
    tools = {s["id"]: s.get("tool", "") for s in steps}

    with matplotlib.rc_context(_style()):
        fig = Figure(figsize=(fig_w, fig_h))
        ax = fig.add_axes([0.01, 0.02, 0.98, 0.96])
        ax.set_xlim(-0.15, width_units * 1.9 - 0.25)
        ax.set_ylim(-height_units / 2 - 0.35, height_units / 2 + 0.35)
        ax.axis("off")
        centers: dict[str, tuple[float, float]] = {}

        def place(col: int, names: list[str]) -> None:
            total = len(names) * box_h + (len(names) - 1) * gap_y
            for i, name in enumerate(names):
                centers[name] = (col * 1.9 + box_w / 2, total / 2 - box_h / 2 - i * (box_h + gap_y))

        place(0, ["$inputs"])
        for col, names in sorted(columns.items()):
            place(col, names)
        place(last + 1, ["$checks"])

        def box(name: str, title: str, subtitle: str, edge: str, face: str) -> None:
            x, y = centers[name]
            ax.add_patch(FancyBboxPatch((x - box_w / 2, y - box_h / 2), box_w, box_h,
                                        boxstyle="round,pad=0,rounding_size=0.12", linewidth=1.4,
                                        edgecolor=edge, facecolor=face))
            ax.text(x, y + 0.12, title, ha="center", va="center", fontsize=9.5, fontweight="bold", color=INK)
            ax.text(x, y - 0.17, subtitle, ha="center", va="center", fontsize=7.5, color=MUTED)

        shown = ", ".join(inputs[:2]) + (f" +{len(inputs) - 2}" if len(inputs) > 2 else "")
        box("$inputs", "inputs", shown or "none", LINE, "#faf7f2")
        for s in steps:
            exp = experiments.get(s["id"], {})
            state = exp.get("status")
            edge = {"ok": OLIVE, "error": FAIL, "skipped": MUTED}.get(state, SLATE)
            runtime = _dict(exp.get("result")).get("runtime_s")
            sub = s["id"] if len(s["id"]) <= 20 else s["id"][:19] + "…"
            if isinstance(runtime, (int, float)):
                sub += f" · {_num(float(runtime))} s"
            elif state in ("error", "skipped"):
                sub += f" · {state}"
            box(s["id"], tools[s["id"]], sub, edge, "white")
        box("$checks", _count(n_checks, "check"), "frozen", LINE, "#faf7f2")

        def arrow(a: str, b: str) -> None:
            (x1, y1), (x2, y2) = centers[a], centers[b]
            ax.add_patch(FancyArrowPatch((x1 + box_w / 2, y1), (x2 - box_w / 2, y2), arrowstyle="-|>",
                                         mutation_scale=11, linewidth=1.1, color=MUTED,
                                         shrinkA=2, shrinkB=2, connectionstyle="arc3,rad=0"))

        has_dependents = {d for s in steps for d in deps[s["id"]][0]}
        for s in steps:
            step_deps, uses_inputs = deps[s["id"]]
            known = [d for d in step_deps if d in ids]
            if uses_inputs or not known:
                arrow("$inputs", s["id"])
            for d in known:
                arrow(d, s["id"])
            if s["id"] not in has_dependents:
                arrow(s["id"], "$checks")
        return _png(fig)


def _axis_range(values: list[float], metric: str) -> tuple[float, float]:
    lo, hi = min(0.0, *values), max(values)
    field = _metric_parts(metric)[1].lower()
    if lo >= 0 and hi <= 1 and field not in ("n_chains", "length", "n_atoms"):
        return 0.0, 1.0
    if lo >= 0 and hi <= 100 and "plddt" in field and hi > 1:
        return 0.0, 100.0
    if hi <= lo:
        hi = lo + 1
    return lo, hi + (hi - lo) * 0.18


def metrics_figure(checks: list[dict[str, Any]]) -> bytes | None:
    """One row per check: the observed value as a bar from zero, the passing region shaded."""
    if not checks:
        return None
    matplotlib, Figure = _mpl()
    rows = len(checks)
    with matplotlib.rc_context(_style()):
        fig = Figure(figsize=(7.2, 0.3 + 0.78 * rows))
        top, bottom = 0.3 / (0.3 + 0.78 * rows), 0.12 / (0.3 + 0.78 * rows)
        span = (1 - top - bottom) / rows
        for i, check in enumerate(checks):
            ax = fig.add_axes([0.03, 1 - top - (i + 1) * span + span * 0.18, 0.94, span * 0.36])
            obs = check.get("observed")
            numeric = isinstance(obs, (int, float)) and not isinstance(obs, bool) and math.isfinite(obs)
            values = [float(obs)] if numeric else []
            ref = check.get("reference")
            if ref is not None:
                tol = float(check.get("tolerance") or 0)
                values += [float(ref) - tol, float(ref) + tol]
            elif isinstance(check.get("value"), (int, float)):
                values.append(float(check["value"]))
            if not values:
                values = [1.0]
            lo, hi = _axis_range(values, check.get("metric", ""))
            ax.set_xlim(lo, hi)
            ax.set_ylim(0, 1)
            ax.set_yticks([])
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(LINE)
            ax.tick_params(axis="x", labelsize=7, length=2, pad=1.5)
            ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(5))
            ax.axvspan(lo, hi, color="#faf7f2", zorder=0)
            op, value = check.get("op"), check.get("value")
            if ref is not None:
                tol = float(check.get("tolerance") or 0)
                ax.axvspan(float(ref) - tol, float(ref) + tol, color="#e9ead9", zorder=1)
                ax.axvline(float(ref), color=INK, linewidth=1, linestyle=(0, (2, 2)), zorder=3)
            elif isinstance(value, (int, float)):
                if op in (">=", ">"):
                    ax.axvspan(float(value), hi, color="#e9ead9", zorder=1)
                elif op in ("<=", "<"):
                    ax.axvspan(lo, float(value), color="#e9ead9", zorder=1)
                ax.axvline(float(value), color=INK, linewidth=1.2, zorder=3)
            status = check.get("status", "")
            color = STATUS_COLORS.get(status, SLATE)
            if numeric:
                ax.barh(0.5, float(obs) - 0, left=0, height=0.62, color=color, zorder=2)
            else:
                ax.text((lo + hi) / 2, 0.5, "no observed value", ha="center", va="center", fontsize=7.5,
                        color=MUTED, style="italic", zorder=4)
            step, _ = _metric_parts(check.get("metric", ""))
            ax.text(0, 1.28, _cap(_metric_name(check.get("metric", ""))), transform=ax.transAxes, ha="left",
                    va="bottom", fontsize=9, fontweight="bold", color=INK)
            ax.text(0, 1.28, " " * 0, transform=ax.transAxes)
            label = f"{_num(obs) if numeric else 'n/a'}   {_criterion(check)}   {status}"
            ax.text(1, 1.28, label, transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color=INK)
            ax.text(0.0, 1.28, "", transform=ax.transAxes)
            name_w = len(_cap(_metric_name(check.get("metric", ""))))
            ax.text(min(0.62, 0.012 * name_w + 0.03), 1.28, step, transform=ax.transAxes, ha="left",
                    va="bottom", fontsize=7.5, color=MUTED)
        return _png(fig)


# --------------------------------------------------------------- structures
def _rotation(elev: float, azim: float) -> tuple[float, float, float]:
    e, a = math.radians(elev), math.radians(azim)
    return (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))


def read_trace(path: Path) -> dict[str, Any]:
    """C-alpha (or C4' for nucleic acids) coordinates, B-factors and chain ids from a PDB or mmCIF file."""
    import gemmi

    structure = gemmi.read_structure(str(path))
    if len(structure) == 0:
        return {"chains": []}
    chains = []
    for chain in structure[0]:
        residues = []
        for residue in chain:
            if residue.het_flag == "H":
                continue
            atom = residue.find_atom("CA", "*") or residue.find_atom("C4'", "*")
            if atom is None:
                continue
            residues.append({"num": residue.seqid.num, "name": residue.name,
                             "xyz": (atom.pos.x, atom.pos.y, atom.pos.z), "b": float(atom.b_iso)})
        if residues:
            chains.append({"id": chain.name, "residues": residues})
    return {"chains": chains}


def _normalize_confidence(trace: dict[str, Any]) -> None:
    values = [r["b"] for c in trace["chains"] for r in c["residues"]]
    scale = 100.0 if values and max(values) <= 1.0 else 1.0
    for c in trace["chains"]:
        for r in c["residues"]:
            r["conf"] = max(0.0, min(100.0, r["b"] * scale))


def _aligned(trace: dict[str, Any]):
    import numpy as np

    xyz = np.array([r["xyz"] for c in trace["chains"] for r in c["residues"]], dtype=float)
    centered = xyz - xyz.mean(axis=0)
    if len(xyz) >= 3:
        _, vectors = np.linalg.eigh(np.cov(centered.T))
        basis = vectors[:, ::-1]
        if np.linalg.det(basis) < 0:
            basis[:, 2] *= -1
        centered = centered @ basis
    return centered


VIEWS = [("front", 90, -90), ("side", 0, 0), ("top", 0, -90), ("oblique", 28, -55)]


def structure_figures(trace: dict[str, Any], predicted: bool, title: str) -> tuple[bytes, bytes | None]:
    """The trace from four angles, and for predictions the per-residue confidence line plot."""
    import numpy as np

    matplotlib, Figure = _mpl()
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.lines import Line2D
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    if predicted:
        _normalize_confidence(trace)
    coords = _aligned(trace)
    cmap = LinearSegmentedColormap.from_list("labloop_confidence", CONFIDENCE_RAMP)
    norm = Normalize(0, 100)
    complex_ = len(trace["chains"]) > 1
    segments, seg_conf, seg_chain = [], [], []
    index = 0
    for ci, chain in enumerate(trace["chains"]):
        residues = chain["residues"]
        for j in range(len(residues) - 1):
            a, b = coords[index + j], coords[index + j + 1]
            # A gap in the chain (missing residues) stays a gap rather than a bridging line.
            if np.linalg.norm(a - b) <= 4.6:
                segments.append((a, b))
                seg_conf.append((residues[j].get("conf", 0) + residues[j + 1].get("conf", 0)) / 2)
                seg_chain.append(ci)
        index += len(residues)
    radius = float(np.abs(coords).max()) * 1.04 or 1.0
    chain_color = [CHAIN_COLORS[min(i, len(CHAIN_COLORS) - 1)] for i in range(len(trace["chains"]))]
    thin = min(1.0, max(0.45, math.sqrt(150 / max(1, len(coords)))))

    with matplotlib.rc_context(_style()):
        fig = Figure(figsize=(7.2, 7.7))
        for k, (name, elev, azim) in enumerate(VIEWS):
            ax = fig.add_subplot(2, 2, k + 1, projection="3d", proj_type="ortho")
            ax.view_init(elev=elev, azim=azim)
            ax.set_xlim(-radius, radius)
            ax.set_ylim(-radius, radius)
            ax.set_zlim(-radius, radius)
            ax.set_box_aspect((1, 1, 1), zoom=1.32)
            ax.set_axis_off()
            ax.set_title(name, fontsize=9.5, color=MUTED, pad=-4)
            eye = np.array(_rotation(elev, azim))
            depth = [float((a + b) @ eye / 2) for a, b in segments]
            order = np.argsort(depth)
            span = (max(depth) - min(depth)) or 1.0 if depth else 1.0
            lines, colors, widths = [], [], []
            for o in order:
                near = (depth[o] - min(depth)) / span
                if complex_:
                    lines.append(segments[o])
                    colors.append(chain_color[seg_chain[o]])
                    widths.append((4.2 + 1.4 * near) * thin)
                lines.append(segments[o])
                if predicted:
                    colors.append(cmap(norm(seg_conf[o])))
                else:
                    colors.append(chain_color[seg_chain[o]] if complex_ else INK)
                widths.append(((1.4 + 1.2 * near) if complex_ else (1.6 + 1.6 * near)) * thin)
            if lines:
                ax.add_collection3d(Line3DCollection(lines, colors=colors, linewidths=widths,
                                                     capstyle="round", joinstyle="round"))
            if complex_:
                start = 0
                for ci, chain in enumerate(trace["chains"]):
                    p = coords[start]
                    ax.text(p[0], p[1], p[2], f" {chain['id']}", fontsize=8.5, fontweight="bold",
                            color=chain_color[ci])
                    start += len(chain["residues"])
        bottom = 0.02 + (0.1 if predicted else 0) + (0.035 * math.ceil(len(trace["chains"]) / 4) if complex_ else 0)
        fig.subplots_adjust(left=0.0, right=1.0, top=0.96, bottom=bottom,
                            wspace=0.0, hspace=0.06)
        if predicted:
            cax = fig.add_axes([0.2, bottom - 0.045, 0.6, 0.016])
            bar = fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax,
                               orientation="horizontal", ticks=[0, 50, 70, 90, 100])
            bar.outline.set_visible(False)
            bar.ax.tick_params(labelsize=7.5, length=2, colors=MUTED)
            bar.set_label("per-residue confidence (pLDDT, 0 to 100)", fontsize=8, color=INK)
        if complex_:
            handles = [Line2D([], [], color=chain_color[i], linewidth=4,
                              label=f"chain {c['id']} ({len(c['residues'])} res.)")
                       for i, c in enumerate(trace["chains"])]
            fig.legend(handles=handles, loc="lower center", ncol=min(4, len(handles)), frameon=False,
                       fontsize=8, bbox_to_anchor=(0.5, 0.0))
        views = _png(fig)

    if not predicted:
        return views, None
    with matplotlib.rc_context(_style()):
        fig = Figure(figsize=(7.2, 2.5))
        ax = fig.add_axes([0.075, 0.2, 0.86, 0.68])
        ax.axhspan(90, 100, color="#e6ecf2", zorder=0)
        ax.axhspan(70, 90, color="#f2f5f8", zorder=0)
        for level in (70, 90):
            ax.axhline(level, color=SLATE, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
        offset, ticks, labels = 0, [], []
        for ci, chain in enumerate(trace["chains"]):
            nums = [r["num"] for r in chain["residues"]]
            x, y = [], []
            for j, r in enumerate(chain["residues"]):
                if j and r["num"] - nums[j - 1] > 1:
                    x.append(float("nan"))
                    y.append(float("nan"))
                x.append(offset + r["num"] - nums[0])
                y.append(r["conf"])
            color = chain_color[ci] if complex_ else "#3d5f82"
            ax.plot(x, y, color=color, linewidth=1.6, zorder=3, label=f"chain {chain['id']}")
            if complex_:
                ax.text(offset + (nums[-1] - nums[0]) / 2, 102, f"chain {chain['id']}", ha="center",
                        va="bottom", fontsize=8, color=chain_color[ci], fontweight="bold")
                if ci:
                    ax.axvline(offset - 2.5, color=LINE, linewidth=1, zorder=1)
            ticks += [offset, offset + nums[-1] - nums[0]]
            labels += [str(nums[0]), str(nums[-1])]
            offset += nums[-1] - nums[0] + 5
        ax.set_xlim(-1, offset - 4)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 50, 70, 90, 100])
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_xlabel("residue number", fontsize=8, color=MUTED)
        ax.set_ylabel("pLDDT", fontsize=8, color=MUTED)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=7.5, length=2)
        ax.text(1.005, 95, "very high", transform=ax.get_yaxis_transform(), fontsize=7, color=MUTED, va="center")
        ax.text(1.005, 80, "confident", transform=ax.get_yaxis_transform(), fontsize=7, color=MUTED, va="center")
        return views, _png(fig)


def _is_prediction(experiment: dict[str, Any]) -> bool:
    tool = str(experiment.get("tool") or _dict(experiment.get("result")).get("tool") or "")
    try:
        from labloop import catalog

        entry = catalog.CATALOG.get(tool)
        if entry is not None:
            return entry.get("kind") == "model"
    except Exception:
        pass
    scores = _dict(_dict(experiment.get("result")).get("scores"))
    return tool in PREDICTORS or any("plddt" in k.lower() for k in scores)


# ---------------------------------------------------------------- timeline
def _phase_spans(bundle: dict[str, Any], end: datetime | None) -> list[tuple[str, datetime, datetime]]:
    history = [(h.get("phase"), _time(h.get("at"))) for h in _list(_dict(bundle.get("status")).get("history"))
               if isinstance(h, dict)]
    history = [(p, t) for p, t in history if p and t]
    merged: list[tuple[str, datetime]] = []
    for phase, moment in history:
        if not merged or merged[-1][0] != phase:
            merged.append((phase, moment))
    spans = []
    for i, (phase, moment) in enumerate(merged):
        if phase in ("done", "error"):
            break
        stop = merged[i + 1][1] if i + 1 < len(merged) else end
        if stop is not None:
            spans.append((phase, moment, stop))
    return spans


def _event_spans(bundle: dict[str, Any], end: datetime | None) -> list[dict[str, Any]]:
    spans: dict[str, dict[str, Any]] = {}
    for event in _list(bundle.get("events")):
        if not isinstance(event, dict) or not event.get("key") or not _time(event.get("at")):
            continue
        key, moment = event["key"], _time(event["at"])
        if event.get("kind") == "start":
            spans[key] = {"key": key, "start": moment, "end": None, "state": "open",
                          "phase": event.get("phase")}
        elif event.get("kind") in ("done", "error") and key in spans:
            spans[key].update(end=moment, state=event["kind"])
    for span in spans.values():
        if span["end"] is None:
            span["end"] = end or span["start"]
    return sorted(spans.values(), key=lambda s: s["start"])


def timeline_figure(bundle: dict[str, Any]) -> bytes | None:
    start, end, finished = _timing(bundle)
    phases = _phase_spans(bundle, end)
    events = _event_spans(bundle, end)
    if start is None or (not events and len(phases) < 2):
        return None
    matplotlib, Figure = _mpl()
    from matplotlib.patches import Patch

    total = max(1.0, (end - start).total_seconds())
    rows = ["phases"] + [e["key"] for e in events]
    with matplotlib.rc_context(_style()):
        fig = Figure(figsize=(7.2, 0.95 + 0.3 * len(rows)))
        ax = fig.add_axes([0.16, 0.6 / (0.95 + 0.3 * len(rows)), 0.8, 1 - 0.85 / (0.95 + 0.3 * len(rows))])
        minimum = total * 0.006
        tints = ["#e6ecf2", "#e9ead9"]
        for i, (phase, a, b) in enumerate(phases):
            x0, w = (a - start).total_seconds(), max(minimum, (b - a).total_seconds())
            ax.barh(0, w, left=x0, height=0.7, color=tints[i % 2], edgecolor="white", linewidth=1.5)
            if w > total * 0.07:
                ax.text(x0 + w / 2, 0, phase, ha="center", va="center", fontsize=7.5, color=INK)
        colors = {"done": SLATE, "error": FAIL, "open": CLAY}
        for row, span in enumerate(events, start=1):
            x0 = (span["start"] - start).total_seconds()
            w = max(minimum, (span["end"] - span["start"]).total_seconds())
            ax.barh(row, w, left=x0, height=0.55, color=colors[span["state"]],
                    hatch="////" if span["state"] == "open" else None, edgecolor="white", linewidth=0.8)
            ax.text(x0 + w + total * 0.008, row, _duration((span["end"] - span["start"]).total_seconds()),
                    va="center", fontsize=7, color=MUTED)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r.removeprefix("step:") for r in rows], fontsize=8, color=INK)
        ax.invert_yaxis()
        ax.set_xlim(0, total * 1.08)
        ticks = ax.get_xticks()
        ax.set_xticks([t for t in ticks if 0 <= t <= total * 1.08])
        ax.set_xticklabels([_duration(t) for t in ax.get_xticks()], fontsize=7.5)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color=LINE, linewidth=0.6)
        ax.set_axisbelow(True)
        present = sorted({s["state"] for s in events}, key=["done", "error", "open"].index)
        if present:
            names = {"done": "finished", "error": "failed", "open": "still running"}
            fig.legend(handles=[Patch(facecolor=colors[s], hatch="////" if s == "open" else None,
                                      edgecolor="white", label=names[s]) for s in present],
                       loc="lower right", ncol=len(present), frameon=False, fontsize=7.5)
        return _png(fig)


# ----------------------------------------------------------------- research
def _paper_index(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for paper in _list(research.get("papers")):
        if not isinstance(paper, dict):
            continue
        for key in ("pmcid", "id", "pmid", "doi"):
            if paper.get(key):
                index[str(paper[key])] = {"title": paper.get("title"), "year": paper.get("year")}
        if paper.get("file"):
            index[str(paper["file"]).rsplit(".", 1)[0]] = {"title": paper.get("title"), "year": paper.get("year")}
    for answer in _list(_dict(research.get("paperqa")).get("answers")):
        for context in _list(_dict(answer).get("contexts")):
            context = _dict(context)
            if context.get("doc") and context.get("citation") and str(context["doc"]) not in index:
                found = re.match(r"^(.*?)\s*\((\d{4})\)", str(context["citation"]))
                index[str(context["doc"])] = {"title": found.group(1) if found else context["citation"],
                                              "year": found.group(2) if found else None}
    return index


def _short_title(title: str, words: int = 6) -> str:
    title = re.sub(r"<[^>]+>", "", html.unescape(str(title))).strip().rstrip(".")
    parts = title.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _source_html(source: Any, index: dict[str, dict[str, Any]]) -> str:
    """'PMC1 chunk 14; PMC1 chunk 15' as the paper's short title and year, with the raw locator on hover."""
    if not source:
        return ""
    labels: dict[str, list[str]] = {}
    for part in str(source).split(";"):
        found = SOURCE_PART.match(part)
        doc = found.group(1) if found else part.strip()
        if found:
            labels.setdefault(doc, []).extend(c.strip() for c in found.group(2).split(",") if c.strip())
        else:
            labels.setdefault(doc, [])
    out = []
    for doc, chunks in labels.items():
        paper = index.get(doc)
        if paper and paper.get("title"):
            text = _short_title(paper["title"]) + (f" ({paper['year']})" if paper.get("year") else "")
        else:
            text = doc
        out.append(f'<span title="{_esc(source)}">{_esc(text)}</span>')
    return "; ".join(out)


def _distillation(research: dict[str, Any]) -> dict[str, Any] | None:
    """Both research shapes as one: summary, numbers, guidance, limitations, papers and answers."""
    if not research:
        return None
    papers = []
    for p in _list(research.get("papers")):
        if isinstance(p, dict):
            full = p.get("full_text")
            if full is None and p.get("text_source"):
                full = p["text_source"] not in ("abstract", "none", None)
            papers.append({"title": _short_title(p.get("title", ""), 40), "doi": p.get("doi"), "year": p.get("year"),
                           "citations": p.get("citations"), "full_text": full})
    extraction = _dict(research.get("extraction"))
    if extraction:
        out = {"shape": "paperqa", "summary": extraction.get("summary"),
               "numbers": [n for n in _list(extraction.get("reported_numbers")) if isinstance(n, dict)],
               "guidance": [g for g in _list(extraction.get("guidance")) if isinstance(g, dict)],
               "limitations": [l for l in _list(extraction.get("limitations")) if l]}
    elif isinstance(research.get("extractions"), list):
        extractions = [e for e in research["extractions"] if isinstance(e, dict)]
        relevant = [e for e in extractions if e.get("relevant")]
        summary = (f"{_count(len(relevant), 'of ' + str(len(extractions)) + ' screened paper', 'of ' + str(len(extractions)) + ' screened papers')} "
                   f"{'was' if len(relevant) == 1 else 'were'} judged relevant to the task.")
        if relevant:
            summary += " " + " ".join(str(e.get("summary") or "") for e in relevant)
        numbers, guidance = [], []
        for e in extractions:
            source = _short_title(e.get("title", ""))
            for n in _list(e.get("reported_numbers")):
                if isinstance(n, dict):
                    numbers.append({**n, "source": n.get("source") or source})
            if e.get("relevant"):
                for step in _list(_dict(e.get("procedure")).get("steps")):
                    guidance.append({"statement": step, "source": source})
        out = {"shape": "extractions", "summary": summary, "numbers": numbers, "guidance": guidance,
               "limitations": [f"{_short_title(e.get('title', ''))}: {e.get('relevance_reason')}"
                               for e in extractions if not e.get("relevant") and e.get("relevance_reason")]}
        if not papers:
            papers = [{"title": _short_title(e.get("title", ""), 40), "doi": e.get("doi"), "year": e.get("year"),
                       "citations": None, "full_text": None} for e in extractions]
    else:
        out = {"shape": "none", "summary": None, "numbers": [], "guidance": [], "limitations": []}
    out["papers"] = papers
    out["answers"] = [a for a in _list(_dict(research.get("paperqa")).get("answers")) if isinstance(a, dict)]
    out["queries"] = [q for q in _list(research.get("queries")) if isinstance(q, str)]
    out["errors"] = [str(e) for e in _list(research.get("errors")) + _list(research.get("search_errors")) if e]
    if research.get("query_error"):
        out["errors"].append(f"query writing: {research['query_error']}")
    if not (out["summary"] or out["numbers"] or out["guidance"] or papers or out["answers"]):
        return None
    return out


# --------------------------------------------------------------------- html
CSS = """
:root{--bg:#f1ebe1;--ink:#2a2622;--muted:#8a847a;--card:#fff;--soft:#faf7f2;--line:rgba(42,38,34,.08);
--olive:#a3a07a;--clay:#c9937a;--slate:#8da2b8;--slatebg:#e6ecf2;--okbg:#e9ead9;--runbg:#f3e3da;--failbg:#f2dcd6;--fail:#b4654f}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Geist',system-ui,-apple-system,sans-serif;
font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
main{max-width:780px;margin:0 auto;padding:32px 16px 56px;display:flex;flex-direction:column;gap:16px}
h1,h2{font-family:'Instrument Serif',Georgia,serif;font-weight:400;letter-spacing:-.01em;margin:0}
h1{font-size:34px;line-height:1.12;text-wrap:balance}
h2{font-size:24px;margin-bottom:10px}
h3{font-size:13px;font-weight:500;margin:18px 0 6px;color:var(--ink)}
p{margin:0 0 10px}p:last-child{margin-bottom:0}
.card{background:var(--card);border-radius:16px;padding:20px;box-shadow:0 1px 0 rgba(42,38,34,.04),0 8px 30px rgba(42,38,34,.05)}
.eyebrow{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.head{display:flex;flex-direction:column;gap:12px;padding:8px 0}
.pill{display:inline-block;font-size:12px;font-weight:500;letter-spacing:.04em;padding:4px 11px;border-radius:999px;vertical-align:middle}
.pill.PASS{background:var(--okbg);color:#5d5b3c}.pill.FAIL{background:var(--failbg);color:var(--fail)}
.pill.INCONCLUSIVE,.pill.UNVERIFIABLE{background:var(--slatebg);color:#4c6075}
.pill.ERROR{background:var(--failbg);color:var(--fail)}.pill.IN{background:var(--runbg);color:#8a5a43}
.pill.NOT{background:var(--soft);color:var(--muted)}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 18px;margin-top:4px}
.meta div{font-size:13px;overflow-wrap:anywhere}.meta span{display:block;font-size:11px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.lead{font-size:16px}
.quote{border-left:3px solid var(--okbg);padding:2px 0 2px 12px;margin:10px 0;color:var(--ink)}
.muted{color:var(--muted)}.small{font-size:12.5px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:var(--soft);padding:1px 5px;border-radius:5px;overflow-wrap:anywhere}
figure{margin:14px 0 4px}figure img{display:block;width:100%;height:auto;border-radius:10px}
figcaption{font-size:12.5px;color:var(--muted);margin-top:6px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th{font-weight:500;color:var(--muted);font-size:11.5px;text-align:left;letter-spacing:.03em;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:none}
ul.plain{margin:6px 0;padding-left:18px}ul.plain li{margin:4px 0}
details{margin:8px 0;border-top:1px solid var(--line);padding-top:8px}
summary{cursor:pointer;font-size:13px;color:var(--ink)}
details>div{padding:8px 0 2px;font-size:13.5px}
.note{font-size:12.5px;color:var(--muted);margin-top:10px}
footer{font-size:11.5px;color:var(--muted);text-align:center}
@media (max-width:520px){h1{font-size:28px}.card{padding:16px}main{padding-top:20px}}
"""


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{cell}</td>'
                                    for i, cell in enumerate(row)) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _figure(name: str, alt: str, caption: str = "") -> str:
    cap = f"<figcaption>{caption}</figcaption>" if caption else ""
    return f'<figure><img src="figures/{_esc(name)}" alt="{_esc(alt)}" loading="lazy">{cap}</figure>'


def _pill(verdict: str) -> str:
    return f'<span class="pill {_esc(verdict.split()[0])}">{_esc(verdict)}</span>'


class _Report:
    def __init__(self, bundle: dict[str, Any], artifacts_root: Path | None) -> None:
        self.bundle = bundle
        self.root = Path(artifacts_root) if artifacts_root is not None else None
        self.figures: dict[str, bytes] = {}
        self.summary: dict[str, Any] = {}
        self.errors: list[dict[str, str]] = []
        self.sections: list[str] = []
        self.checks = _checks(bundle)
        self.verdict = _verdict(bundle)
        self.status = _dict(bundle.get("status"))
        self.run_id = str(bundle.get("run_id") or self.status.get("run_id") or "unknown")

    def figure(self, name: str, build: Callable[[], bytes | None]) -> bool:
        try:
            data = build()
        except ImportError as error:
            self.errors.append({"section": f"figure {name}", "error": f"{error}; the figure is omitted"})
            return False
        if data:
            self.figures[name] = data
            return True
        return False

    # ---------------------------------------------------------------- header
    def header(self) -> str:
        task = _dict(self.bundle.get("task"))
        start, end, finished = _timing(self.bundle)
        seconds = (end - start).total_seconds() if start and end else None
        origin = _origin(self.bundle)
        phase = self.status.get("phase") or self.bundle.get("phase")
        duration = _duration(seconds) + ("" if finished or seconds is None else " so far")
        self.summary.update({"task": task.get("description"), "inputs": task.get("inputs"), "verdict": self.verdict,
                             "phase": phase, "origin": origin, "origin_text": _origin_text(origin),
                             "started_at": start.strftime("%Y-%m-%dT%H:%M:%SZ") if start else None,
                             "duration_s": round(seconds, 1) if seconds is not None else None,
                             "finished": finished})
        meta = [("Origin", _origin_text(origin)), ("Run", f"<code>{_esc(self.run_id)}</code>"),
                ("Duration", _esc(duration or "not recorded")), ("Started", _esc(_date(start) or "not recorded"))]
        cells = "".join(f"<div><span>{label}</span>{value if label == 'Run' else _esc(value) if label == 'Origin' else value}</div>"
                        for label, value in meta)
        title = task.get("description") or f"Run {self.run_id}"
        return (f'<header class="head"><div class="eyebrow">labloop run report</div>'
                f"<h1>{_esc(title)}</h1><div>{_pill(self.verdict)}</div>"
                f'<div class="meta">{cells}</div></header>')

    # --------------------------------------------------------------- outcome
    def outcome(self) -> str:
        checks, verdict = self.checks, self.verdict
        graded = [c for c in checks if c.get("status") in ("PASS", "FAIL", "UNVERIFIABLE")]
        n = len(graded)
        phase = self.status.get("phase") or self.bundle.get("phase")
        sentences = []
        if verdict == "PASS":
            sentences.append("The run passed its only check." if n == 1 else f"The run passed all {n} checks.")
            decisive = self._decisive(graded)
        elif verdict == "FAIL":
            failed = [c for c in graded if c["status"] == "FAIL"]
            sentences.append(f"The run failed {len(failed)} of {_count(n, 'check')}.")
            decisive = failed[:3]
        elif verdict == "INCONCLUSIVE":
            missing = [c for c in graded if c["status"] == "UNVERIFIABLE"]
            sentences.append(f"The run is inconclusive because {len(missing)} of {_count(n, 'check')} "
                             f"could not be verified." if graded else
                             "The run is inconclusive because it had no checks to grade.")
            decisive = missing[:3]
        elif verdict == "ERROR":
            stopped = [h.get("phase") for h in _list(self.status.get("history")) if isinstance(h, dict)]
            last = next((p for p in reversed(stopped) if p not in ("error", None)), None)
            sentences.append(f"The run stopped with an error during the {last} phase, so it has no verdict."
                             if last else "The run stopped with an error before any phase began, so it has no verdict.")
            decisive = []
        else:
            sentences.append(f"The run is in its {phase or 'first'} phase, so no checks have been graded yet.")
            decisive = []
        if decisive:
            phrases = [_check_phrase(c) for c in decisive]
            sentences.append(_cap(_join(phrases[:1] + [p for p in phrases[1:]])) + ".")
        body = f'<p class="lead">{_esc(" ".join(sentences))}</p>'
        if self.status.get("error"):
            body += f'<p class="small muted">{_esc(str(self.status["error"])[:400])}</p>'
        summary = self.status.get("summary")
        if summary:
            body += f'<div class="eyebrow" style="margin-top:14px">Reviewer summary</div><p class="quote">{_esc(summary)}</p>'
        elif self.status.get("review_error"):
            body += ('<p class="note">The reviewer\'s answer could not be parsed, so the run has no written '
                     "summary.</p>")
        self.summary["decisive"] = [c.get("id") for c in decisive]
        self.summary["reviewer_summary"] = summary
        return f'<section class="card"><h2>Outcome</h2>{body}</section>'

    def _decisive(self, graded: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not graded:
            return []
        order = [s["id"] for s in _steps(self.bundle)]
        by_step: dict[str, list[dict[str, Any]]] = {}
        for c in graded:
            by_step.setdefault(_metric_parts(c.get("metric", ""))[0], []).append(c)
        last = max(by_step, key=lambda s: order.index(s) if s in order else -1)
        pool = by_step[last]
        confident = [c for c in pool if any(w in c.get("metric", "").lower() for w in CONFIDENCE_WORDS)]
        return (confident or pool)[:3]

    # ---------------------------------------------------------------- choice
    def choice(self) -> str:
        match, plan, status = _dict(self.bundle.get("match")), _dict(self.bundle.get("plan")), self.status
        origin = _origin(self.bundle)
        if not match and not plan:
            return ""
        parts = []
        if origin.get("kind") == "skill" or match.get("decision") == "reuse":
            name = origin.get("skill") or match.get("skill")
            version = origin.get("version") or match.get("version")
            parts.append(f"<p>The task matched the saved skill <code>{_esc(name)}</code>"
                         f"{' (version ' + _esc(version) + ')' if version is not None else ''}, so its frozen "
                         "pipeline ran again and the research and planning phases were skipped.</p>")
            condition = match.get("matched_applies_when")
            if condition:
                parts.append(f'<div class="eyebrow">Condition matched</div><p class="quote">{_esc(condition)}</p>')
            elif match.get("reason"):
                parts.append(f"<p class=\"small muted\">{_esc(_cap(str(match['reason'])))}.</p>")
            mapping = _dict(match.get("input_mapping"))
            if mapping:
                rows = []
                for key, entry in mapping.items():
                    entry = _dict(entry)
                    if "from_input" in entry:
                        source = f"task input <code>{_esc(entry['from_input'])}</code>"
                    else:
                        source = f"fixed value <code>{_esc(json.dumps(entry.get('value'))[:80])}</code>"
                    rows.append([f"<code>{_esc(key)}</code>", source])
                parts.append(_table(["Skill input", "Taken from"], rows))
            self.summary["skill_invoked"] = {"name": name, "version": version,
                                             "matched_applies_when": condition, "input_mapping": mapping}
        elif match:
            candidates = [c for c in _list(match.get("candidates")) if isinstance(c, str)]
            if candidates:
                parts.append(f"<p>No saved skill fitted the task, so a new pipeline was planned from the "
                             f"literature and the tool catalog. The matcher considered "
                             f"{_count(len(candidates), 'saved skill')} ("
                             + ", ".join(f"<code>{_esc(c)}</code>" for c in candidates) + ").</p>")
            else:
                parts.append("<p>No saved skill existed yet, so a new pipeline was planned from the literature "
                             "and the tool catalog.</p>")
            if match.get("reason"):
                parts.append(f"<details><summary>Why no skill was reused</summary><div>{_esc(match['reason'])}"
                             "</div></details>")
        else:
            parts.append("<p>The pipeline was planned for this task.</p>")
        decisions = [d for d in _list(plan.get("decisions")) if isinstance(d, dict)]
        if decisions:
            rows = [[_esc(d.get("topic", "")), _esc(d.get("choice", "")),
                     "no" if d.get("source_silent") else "yes"] for d in decisions]
            parts.append(f"<details><summary>Planning decisions ({len(decisions)})</summary><div>"
                         + _table(["Topic", "Choice", "Sourced"], rows) + "</div></details>")
        steps = _steps(self.bundle)
        if steps and self.figure("pipeline.png", lambda: pipeline_figure(self.bundle)):
            tools = " then ".join(s.get("tool", "") for s in steps)
            parts.append(_figure("pipeline.png", f"Pipeline diagram: {tools}",
                                 f"The frozen pipeline, {_count(len(steps), 'step')} in dependency order. "
                                 "Box outlines show each step's outcome (olive finished, rust failed, grey skipped)."))
        skill = _dict(status.get("skill"))
        if skill.get("action") == "created":
            parts.append(f'<p class="note">The passing run was saved as skill <code>{_esc(skill.get("skill"))}</code> '
                         f"(version {_esc(skill.get('version'))}, standing {_esc(skill.get('standing'))}).</p>")
        elif skill.get("action") == "evidence_appended":
            parts.append(f'<p class="note">The run was added as evidence to skill <code>{_esc(skill.get("skill"))}</code>, '
                         f"now at version {_esc(skill.get('version'))} with standing {_esc(skill.get('standing'))}.</p>")
        self.summary["skill_result"] = skill or None
        self.summary["steps"] = [{"id": s["id"], "tool": s.get("tool")} for s in steps]
        return f'<section class="card"><h2>How the pipeline was chosen</h2>{"".join(parts)}</section>'

    # --------------------------------------------------------------- metrics
    def metrics(self) -> str:
        checks = self.checks
        if not checks:
            return ""
        parts = []
        if self.figure("metrics.png", lambda: metrics_figure(checks)):
            parts.append(_figure("metrics.png", "Observed value of each check against its threshold",
                                 "Each bar is the observed value measured from zero; the shaded region passes and "
                                 "the vertical line is the threshold. A dashed line marks a published reference "
                                 "with its tolerance band. Olive passed, rust failed, slate could not be verified."))
        rows = []
        for c in checks:
            observed = _num(c.get("observed")) if c.get("observed") is not None else "not observed"
            criterion = _esc(_criterion(c))
            if c.get("source"):
                criterion += f'<div class="small muted">{_esc(c["source"])}</div>'
            rows.append([f"{_esc(c.get('id', ''))}<div class=\"small muted\">{_esc(c.get('metric', ''))}</div>",
                         _esc(observed), criterion, _pill(str(c.get("status", ""))) ])
        parts.append(_table(["Check", "Observed", "Criterion", "Status"], rows, numeric={1}))
        notes = []
        for g in _list(_dict(self.bundle.get("results")).get("domain_graders")):
            g = _dict(g)
            name = g.get("grader", "domain grader")
            if g.get("status") == "SKIPPED":
                notes.append(f"The {name} grader did not run because {g.get('reason') or 'it did not apply'}.")
                continue
            reports = [_dict(r) for r in _list(g.get("reports"))]
            counts = []
            for r in reports:
                found = _dict(_dict(r.get("counts")).get("status"))
                if found:
                    counts.append(", ".join(f"{v} {k.lower().replace('_', ' ')}" for k, v in found.items() if v))
            blocking = "blocking" if g.get("blocking") else "advisory"
            text = f"The {name} grader returned {g.get('status')} ({blocking})"
            if counts:
                text += f", with findings of {'; '.join(counts)}"
            if any(r.get("safe_to_interpret") is False for r in reports):
                text += ". It marked the output as not safe to interpret, so the structural claims rest on the checks above alone"
            notes.append(text + ".")
        for note in notes:
            parts.append(f'<p class="note">{_esc(note)}</p>')
        self.summary["checks"] = [{"id": c.get("id"), "metric": c.get("metric"), "observed": c.get("observed"),
                                   "criterion": _criterion(c), "status": c.get("status")} for c in checks]
        self.summary["counts"] = _dict(self.bundle.get("results")).get("counts")
        return f'<section class="card"><h2>Metrics</h2>{"".join(parts)}</section>'

    # ------------------------------------------------------------- structure
    def structure(self) -> str:
        experiments = [e for e in _list(self.bundle.get("experiments")) if isinstance(e, dict)]
        candidates = [(e, _dict(_dict(e.get("result")).get("artifacts")).get("structure")) for e in experiments]
        candidates = [(e, p) for e, p in candidates if isinstance(p, str) and p]
        if not candidates:
            return ""
        parts, records, notes = [], [], []
        for experiment, relative in candidates:
            step = str(experiment.get("step_id"))
            tool = str(experiment.get("tool") or "")
            path = (self.root / relative) if self.root is not None else None
            if path is None or not path.is_file():
                where = "no artifacts root was given" if path is None else "the file is not under the artifacts root"
                notes.append(f"The structure from step {step} ({tool}) is not shown because {where}.")
                continue
            try:
                trace = read_trace(path)
            except ImportError:
                notes.append(f"The structure from step {step} is not shown because gemmi is not installed.")
                continue
            except Exception as error:
                notes.append(f"The structure from step {step} could not be parsed ({type(error).__name__}), "
                             "so it is not shown.")
                continue
            if not trace["chains"]:
                notes.append(f"The structure from step {step} has no polymer residues, so it is not shown.")
                continue
            predicted = _is_prediction(experiment)
            safe = re.sub(r"[^a-z0-9_]+", "_", step.lower())
            try:
                views, profile = structure_figures(trace, predicted, step)
            except ImportError as error:
                notes.append(f"The structure from step {step} is not shown because {error}.")
                continue
            self.figures[f"structure_{safe}.png"] = views
            n_res = sum(len(c["residues"]) for c in trace["chains"])
            chain_text = _join([f"chain {c['id']} ({len(c['residues'])} residues)" for c in trace["chains"]])
            record = {"step_id": step, "tool": tool, "path": relative, "n_residues": n_res,
                      "chains": [{"id": c["id"], "n_residues": len(c["residues"])} for c in trace["chains"]],
                      "confidence": "plddt" if predicted else "crystallographic_b_factor"}
            parts.append(f"<h3>{_esc(step)} <span class=\"muted\">({_esc(tool)}, {_esc(path.name)})</span></h3>")
            if predicted:
                confs = [r["conf"] for c in trace["chains"] for r in c["residues"]]
                mean = sum(confs) / len(confs)
                confident = sum(1 for v in confs if v >= 70) / len(confs) * 100
                very_high = sum(1 for v in confs if v >= 90) / len(confs) * 100
                record.update(mean_confidence=round(mean, 2), fraction_ge_70=round(confident / 100, 4),
                              fraction_ge_90=round(very_high / 100, 4))
                parts.append(f"<p>The model has {_count(n_res, 'residue')} in {chain_text}. Mean per-residue "
                             f"confidence is {_num(mean)}; {_num(confident)}% of residues reach 70 and "
                             f"{_num(very_high)}% reach 90.</p>")
                caption = ("C-alpha trace from four orthographic angles after alignment to the principal axes, "
                           "colored by per-residue pLDDT read from the B-factor column")
                caption += "; each chain carries a colored outline." if len(trace["chains"]) > 1 else "."
                parts.append(_figure(f"structure_{safe}.png", f"C-alpha trace of {step} from four angles", caption))
                if profile:
                    self.figures[f"confidence_{safe}.png"] = profile
                    parts.append(_figure(f"confidence_{safe}.png", f"Per-residue pLDDT for {step}",
                                         "Per-residue pLDDT with the confident (70 to 90) and very high (90 and "
                                         "above) bands shaded. Gaps in residue numbering are left as gaps."))
            else:
                parts.append(f"<p>The entry has {_count(n_res, 'residue')} in {chain_text}.</p>")
                parts.append(_figure(f"structure_{safe}.png", f"C-alpha trace of {step} from four angles",
                                     "C-alpha trace from four orthographic angles. The B-factors of an experimental "
                                     "entry are crystallographic temperature factors rather than prediction "
                                     "confidence, so the trace is drawn without a confidence scale."))
            records.append(record)
        parts += [f'<p class="note">{_esc(n)}</p>' for n in notes]
        self.summary["structures"] = records
        if not parts:
            return ""
        return f'<section class="card"><h2>Structure</h2>{"".join(parts)}</section>'

    # ---------------------------------------------------------- distillation
    def study(self) -> str:
        research = _dict(self.bundle.get("research"))
        found = _distillation(research)
        if not found:
            return ""
        index = _paper_index(research)
        parts = []
        if found["summary"]:
            parts.append(f"<p>{_esc(found['summary'])}</p>")
        numbers = found["numbers"]
        if numbers:
            def row(n: dict[str, Any]) -> list[str]:
                unit = str(n.get("unit") or "")
                unit = "" if unit.startswith("dimensionless") else unit
                value = _num(n.get("value")) + (f" {unit}" if unit else "")
                return [_esc(n.get("quantity", "")), _esc(value), _esc(n.get("context", "")),
                        _source_html(n.get("source"), index)]
            headers = ["Quantity", "Value", "Context", "Source"]
            parts.append(f"<h3>Sourced numbers ({len(numbers)})</h3>"
                         + _table(headers, [row(n) for n in numbers[:6]], numeric={1}))
            if len(numbers) > 6:
                parts.append(f"<details><summary>{len(numbers) - 6} more numbers</summary><div>"
                             + _table(headers, [row(n) for n in numbers[6:]], numeric={1}) + "</div></details>")
        guidance = found["guidance"][:5]
        if guidance:
            items = "".join(f"<li>{_esc(g.get('statement', ''))}"
                            + (f' <span class="small muted">({_source_html(g.get("source"), index)})</span>'
                               if g.get("source") else "") + "</li>" for g in guidance)
            parts.append(f'<h3>Guidance</h3><ul class="plain">{items}</ul>')
        limitations = found["limitations"][:3]
        if limitations:
            items = "".join("<li>" + (_esc(l.get("statement", "")) + (f' <span class="small muted">({_source_html(l.get("source"), index)})</span>' if l.get("source") else "")
                                      if isinstance(l, dict) else _esc(l)) + "</li>" for l in limitations)
            parts.append(f'<h3>What the literature does not settle</h3><ul class="plain">{items}</ul>')
        papers = found["papers"]
        if papers:
            def full(value: Any) -> str:
                return "yes" if value is True else "abstract only" if value is False else '<span class="muted">not recorded</span>'

            rows = [[_esc(p["title"]) + (f'<div class="small muted">{_esc(p["doi"])}</div>' if p.get("doi") else ""),
                     _esc(p.get("year") or ""),
                     _esc(p["citations"]) if p.get("citations") is not None else '<span class="muted">not recorded</span>',
                     full(p.get("full_text"))] for p in papers]
            parts.append(f"<h3>Papers ({len(papers)})</h3>" + _table(["Title", "Year", "Citations", "Full text read"],
                                                                     rows, numeric={1, 2}))
        for answer in found["answers"]:
            contexts = [_dict(c) for c in _list(answer.get("contexts"))]
            cited = sorted({str(c.get("citation")) for c in contexts if c.get("citation")})
            paragraphs = "".join(f"<p>{_esc(p.strip())}</p>" for p in str(answer.get("answer", "")).split("\n\n") if p.strip())
            sources = ""
            if cited:
                sources = (f'<p class="small muted">Drawn from {_count(len(contexts), "excerpt")} of '
                           f"{_count(len(cited), 'paper')}.</p>")
            parts.append(f"<details><summary>PaperQA answer to: {_esc(_short_title(answer.get('question', ''), 14))}"
                         f"</summary><div><p class=\"small muted\">{_esc(answer.get('question', ''))}</p>"
                         f"{paragraphs}{sources}</div></details>")
        if found["errors"]:
            parts.append(f'<p class="note">Part of the research step failed ({_esc("; ".join(found["errors"])[:300])}), '
                         "so the planner worked from less evidence than the limits allowed.</p>")
        self.summary["research"] = {"shape": found["shape"], "n_papers": len(papers), "n_numbers": len(numbers),
                                    "n_guidance": len(found["guidance"]), "n_answers": len(found["answers"]),
                                    "errors": found["errors"]}
        return f'<section class="card"><h2>Study distillation</h2>{"".join(parts)}</section>'

    # --------------------------------------------------------------- timeline
    def timeline(self) -> str:
        if not self.figure("timeline.png", lambda: timeline_figure(self.bundle)):
            return ""
        start, end, _ = _timing(self.bundle)
        phases = _phase_spans(self.bundle, end)
        events = _event_spans(self.bundle, end)
        longest = max(phases, key=lambda p: (p[2] - p[1]).total_seconds(), default=None)
        text = ""
        if longest:
            text = (f"<p>The longest phase was {_esc(longest[0])} at "
                    f"{_esc(_duration((longest[2] - longest[1]).total_seconds()))}.</p>")
        caption = ("Phase spans from the run's status history" +
                   (", and below them each tracked activity from its start event to its end event."
                    if events else ". This run predates the activity log, so only phases are shown."))
        self.summary["timeline"] = {"phases": [{"phase": p, "seconds": (b - a).total_seconds()} for p, a, b in phases],
                                    "activities": [{"key": e["key"], "state": e["state"],
                                                    "seconds": (e["end"] - e["start"]).total_seconds()} for e in events]}
        return (f'<section class="card"><h2>Timeline</h2>{text}'
                + _figure("timeline.png", "Gantt chart of run phases and activities", caption) + "</section>")

    # ---------------------------------------------------------------- lessons
    def lessons(self) -> str:
        lessons = [str(l) for l in _list(self.status.get("lesson_texts")) if l]
        self.summary["lessons"] = lessons
        if lessons:
            items = "".join(f"<li>{_esc(l)}</li>" for l in lessons)
            return f'<section class="card"><h2>Lessons recorded</h2><ul class="plain">{items}</ul></section>'
        if self.status.get("review_error"):
            return ('<section class="card"><h2>Lessons recorded</h2><p>The reviewer\'s answer could not be parsed, '
                    "so this run recorded no lessons.</p></section>")
        return ""

    # ------------------------------------------------------------------ build
    def build(self) -> dict[str, bytes]:
        builders = [("header", self.header), ("outcome", self.outcome), ("choice", self.choice),
                    ("metrics", self.metrics), ("structure", self.structure), ("study", self.study),
                    ("timeline", self.timeline), ("lessons", self.lessons)]
        blocks = []
        for name, builder in builders:
            try:
                block = builder()
            except Exception as error:  # one malformed field must not cost the whole report
                self.errors.append({"section": name, "error": f"{type(error).__name__}: {error}"})
                continue
            if block:
                blocks.append(block)
                self.sections.append(name)
        title = f"Run report {self.run_id}"
        page = (
            "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_esc(title)}</title>"
            "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
            "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
            "<link href=\"https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&amp;family=Geist:wght@300;400;500&amp;display=swap\" rel=\"stylesheet\">"
            f"<style>{CSS}</style></head><body><main>"
            + "".join(blocks)
            + f"<footer>Generated by labloop from run {_esc(self.run_id)}.</footer></main></body></html>\n"
        )
        files = {"report.html": page.encode("utf-8")}
        for name, data in sorted(self.figures.items()):
            files[f"figures/{name}"] = data
        machine = {"report_version": REPORT_VERSION, "run_id": self.run_id, **self.summary,
                   "sections": self.sections, "section_errors": self.errors,
                   "figures": sorted(f"figures/{n}" for n in self.figures)}
        files["report.json"] = (json.dumps(machine, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
        return files


def build_report(bundle: dict, artifacts_root: Path | None) -> dict[str, bytes]:
    """The report files for one run bundle, keyed by relative path.

    `bundle` is the document `GET /runs/{id}` returns. `artifacts_root` is the
    directory that artifact paths in the bundle are relative to (the mounted
    artifacts Volume); structures are drawn only for files found under it.
    """
    return _Report(bundle if isinstance(bundle, dict) else {}, artifacts_root).build()
