"""Uniform versus graded segmentation: segment count against error in the corner step voltage S1.

The error is measured against the converged S1 of each grid (the `S1 regression against converged
value` checks in reference_cases.json: Richardson extrapolation of uniform 1, 0.5 and 0.25 m runs).

Usage (repository root, after `make potential-engine`):
    python services/potential_engine/validation/segmentation_study.py [--json report.json]
"""

import argparse
import json
from math import sqrt
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import (  # noqa: E402
    MAX_SEGMENTS,
    PotentialEngineClient,
    PotentialPoint,
)
from src.infrastructure.calculations.potential_engine_validation import case_segments, case_soil, load_cases  # noqa: E402

CASES = ("ieee80_annex_h_grid1", "ieee80_annex_h_grid2", "ieee80_annex_h_grid3")
UNIFORM_M = (3.5, 1.75, 1.0, 0.7)
GRADED_M = (2.0, 1.0, 0.5)


def corner_step(client, case, segments):
    s = sqrt(0.5)
    result = client.calculate(soil=case_soil(case), segments=segments, injections_a=case["injections_a"],
                              points=[PotentialPoint("c", (0, 0, 0)), PotentialPoint("d", (-s, -s, 0))])
    return result["groups"]["grid"]["resistance_to_remote_earth_ohm"], result["potentials_v"]["c"] - result["potentials_v"]["d"]


def study(client: PotentialEngineClient) -> list[dict]:
    rows = []
    cases = {case["id"]: case for case in load_cases()["cases"]}
    for case_id in CASES:
        case = cases[case_id]
        converged = next(c["reference"]["value"] for c in case["checks"] if c.get("label") == "S1 regression against converged value")
        for mode, steps in (("uniform", UNIFORM_M), ("graded", GRADED_M)):
            for d in steps:
                segments = case_segments(case, d, mode)
                if len(segments) > MAX_SEGMENTS:
                    continue
                started = time.perf_counter()
                resistance, step = corner_step(client, case, segments)
                rows.append({"case": case_id, "segmentation": mode, "d_m": d, "segments": len(segments),
                             "resistance_ohm": resistance, "s1_v": step, "s1_converged_v": converged,
                             "s1_error_rel": step / converged - 1, "seconds": round(time.perf_counter() - started, 3)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the rows to this file")
    args = parser.parse_args()
    rows = study(PotentialEngineClient())
    print(f"{'case':<22} {'mode':<8} {'d (m)':>6} {'segments':>8} {'S1 (V)':>8} {'error':>8}")
    for row in rows:
        print(f"{row['case']:<22} {row['segmentation']:<8} {row['d_m']:>6} {row['segments']:>8} "
              f"{row['s1_v']:>8.2f} {100 * row['s1_error_rel']:>+7.2f}%")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
