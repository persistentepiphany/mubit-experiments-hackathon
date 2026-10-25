"""Builds each mocked run's report with labloop's own report generator.

The bundles come from seed/world.ts (dumped by seed/bundles.mjs) and the
structures from seed/artifacts, so the report shown in the film is exactly
what reporting.build_report writes for those runs.

    node seed/bundles.mjs > bundles.json
    PYTHONPATH=<repo> python seed/make_reports.py bundles.json seed/artifacts seed/reports

Needs labloop's `reports` extra: matplotlib, gemmi and numpy.
"""

import json
import sys
from pathlib import Path

from labloop.reporting import build_report


def main(bundles: Path, artifacts: Path, out: Path) -> None:
    for bundle in json.loads(bundles.read_text()):
        files = build_report(bundle, artifacts)
        for name, data in files.items():
            path = out / bundle["run_id"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        errors = json.loads(files["report.json"]).get("section_errors")
        print(f"  {bundle['run_id']}: {sorted(files)}" + (f" section errors: {errors}" if errors else ""))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
