"""Discretisation convergence study for the reference cases.

Usage (repository root, after `make potential-engine`):
    python services/potential_engine/validation/convergence.py [--json report.json]
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient  # noqa: E402
from src.infrastructure.calculations.potential_engine_validation import convergence, load_cases  # noqa: E402

# Segment lengths refine from one conductor-spacing fraction to the finest that fits the
# segment limit; surface rasters refine the worst-touch search.
SWEEPS = {
    "single_rod": {"discretizations_m": [3.0, 1.5, 0.75, 0.375, 0.1875]},
    "horizontal_wire": {"discretizations_m": [5.0, 2.5, 1.25, 0.625, 0.3125]},
    "two_rods_coupled_groups": {"discretizations_m": [3.0, 1.5, 0.75, 0.375]},
    "floating_rod": {"discretizations_m": [3.0, 1.5, 0.75, 0.375]},
    # Grids 1-3 use graded segments (see the case files); d halves from 4 m to 0.5 m.
    "ieee80_annex_h_grid1": {"discretizations_m": [4.0, 2.0, 1.0, 0.5], "raster_spacings_m": [1.0, 0.5, 0.25]},
    "ieee80_annex_h_grid2": {"discretizations_m": [4.0, 2.0, 1.0, 0.5], "raster_spacings_m": [1.0, 0.5, 0.25]},
    "ieee80_annex_b_example1": {"discretizations_m": [7.0, 3.5, 1.75], "raster_spacings_m": [1.0, 0.5, 0.25]},
    "ieee80_annex_h_grid3": {"discretizations_m": [4.0, 2.0, 1.0, 0.5], "raster_spacings_m": [1.0, 0.5, 0.25]},
    "ieee80_annex_h_grid4": {"discretizations_m": [7.0, 3.5, 1.75, 1.0]},
    "ieee80_annex_h_grid5": {"discretizations_m": [7.0, 3.5, 1.75]},
    "ieee80_annex_h_grid6": {"discretizations_m": [7.0, 3.5, 1.75, 1.0, 0.7]},
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the full report to this file")
    args = parser.parse_args()
    client = PotentialEngineClient()
    cases = {case["id"]: case for case in load_cases()["cases"]}
    reports = [convergence(client, cases[case_id], **sweep) for case_id, sweep in SWEEPS.items()]
    for report in reports:
        print(f"\n{report['case']}")
        for sweep, key in (("segment_sweep", "discretization_m"), ("raster_sweep", "raster_spacing_m")):
            for row in report.get(sweep, []):
                changes = row["change_rel"] or [None] * len(row["values"])
                cells = "  ".join(
                    f"{q[:22]}={v:.5g}" + ("" if c is None else f" ({100 * c:.2f} %)")
                    for q, v, c in zip(report["quantities"], row["values"], changes)
                )
                print(f"  {key}={row[key]:<7} n={row['segment_count']:<4} pts={row['point_count']:<6} {cells}")
    if args.json:
        args.json.write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
