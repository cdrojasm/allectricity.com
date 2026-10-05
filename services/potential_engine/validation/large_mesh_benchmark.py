"""Benchmark the IEEE 80 Annex H Grid 5 above the direct-solver segment limit.

Run after building the API engine:
    python services/potential_engine/validation/large_mesh_benchmark.py \
      --engine services/potential_engine/build/spat-potential-engine

For a same-matrix comparison with LU, build a benchmark-only executable with
    g++ -std=c++17 -O3 -DSPAT_DIRECT_SOLVER_MAX_SEGMENTS=4000 \
      services/potential_engine/src/main.cpp -o /tmp/spat-potential-lu
and pass it as --direct-engine.
"""

import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
from src.infrastructure.calculations.potential_engine_validation import case_segments, case_soil, load_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--direct-engine", help="optional build that uses LU at all benchmark sizes, for comparison")
    parser.add_argument("--steps", default="1.75,1.0,0.7",
                        help="graded discretization lengths in metres")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    case = next(item for item in load_cases()["cases"] if item["id"] == "ieee80_annex_h_grid5")
    soil = case_soil(case)
    client = PotentialEngineClient(args.engine)
    direct_client = PotentialEngineClient(args.direct_engine) if args.direct_engine else None
    rows = []
    print(f"{'step m':>8} {'segments':>9} {'solver iters':>12} {'seconds':>9} {'R ohm':>10} {'GPR V':>10} {'residual':>11} {'peak MiB':>10}")
    for step in map(float, args.steps.split(",")):
        segments = case_segments(case, discretization_m=step, segmentation="graded")
        before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        started = time.perf_counter()
        result = client.calculate(soil=soil, segments=segments, injections_a=case["injections_a"], points=[])
        elapsed = time.perf_counter() - started
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        scale = 1 if sys.platform == "darwin" else 1024
        group = result["groups"]["grid"]
        row = {
            "discretization_m": step,
            "segments": len(segments),
            "solver_iterations": int(result["diagnostics"]["solver_iterations"]),
            "seconds": round(elapsed, 3),
            "peak_child_rss_mib": round(peak * scale / 2**20, 1),
            "resistance_ohm": group["resistance_to_remote_earth_ohm"],
            "gpr_v": group["potential_v"],
            "backward_error": result["diagnostics"]["backward_error"],
            "relative_current_balance_error": result["diagnostics"]["max_relative_balance_error"],
            "condition_1norm_estimate": result["diagnostics"]["condition_1norm_estimate"],
            "method": result["trace"]["method"],
            "warnings": result["warnings"],
            "client_timeout_s": client.timeout_s,
            "memory_limit_mb": client.memory_limit_mb,
            "maxrss_before_mib": round(before * scale / 2**20, 1),
        }
        if direct_client:
            direct_started = time.perf_counter()
            direct = direct_client.calculate(soil=soil, segments=segments,
                                             injections_a=case["injections_a"], points=[])
            direct_group = direct["groups"]["grid"]
            row["direct_comparison"] = {
                "seconds": round(time.perf_counter() - direct_started, 3),
                "resistance_ohm": direct_group["resistance_to_remote_earth_ohm"],
                "gpr_v": direct_group["potential_v"],
                "relative_resistance_delta": group["resistance_to_remote_earth_ohm"] / direct_group["resistance_to_remote_earth_ohm"] - 1.0,
                "relative_gpr_delta": group["potential_v"] / direct_group["potential_v"] - 1.0,
                "backward_error": direct["diagnostics"]["backward_error"],
                "condition_1norm_estimate": direct["diagnostics"]["condition_1norm_estimate"],
            }
        rows.append(row)
        print(f"{step:8.2f} {len(segments):9d} {row['solver_iterations']:12d} {elapsed:9.2f} "
              f"{group['resistance_to_remote_earth_ohm']:10.5f} {group['potential_v']:10.2f} "
              f"{row['backward_error']:11.2e} {row['peak_child_rss_mib']:10.1f}")
    report = {"case": case["id"], "hardware": {"system": platform.platform(), "machine": platform.machine(),
                                                    "processor": platform.processor(), "cpu_count": os.cpu_count()},
              "soil": soil.__dict__, "rows": rows}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
