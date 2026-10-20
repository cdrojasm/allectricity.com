"""Profile solver phases against mesh size and layer count.

Usage: make potential-engine-profile [PROFILE_OUT=/tmp/solver-profile.json]
                                     [ARGS='--meshes 10:5,20:5 --points 100']
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import (  # noqa: E402
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialPoint,
    TwoLayerSoil,
    interface_depths,
)
from n_layer_benchmark import grid  # noqa: E402

SOILS = {
    "homogeneous": HomogeneousSoil(100.0),
    "two-layer": TwoLayerSoil(300.0, 100.0, 2.0),
    "4-layer": LayerStackSoil(((500.0, 0.6), (80.0, 1.2), (1500.0, 2.5), (40.0, None))),
    "8-layer": LayerStackSoil(((200.0, 0.4), (500.0, 0.6), (50.0, 0.5), (800.0, 0.5),
                                (120.0, 1.0), (2000.0, 1.0), (60.0, 4.0), (400.0, None))),
}
PROFILE_KEYS = (
    "profile_kernel_setup_ms", "profile_matrix_assembly_ms", "profile_factorization_ms",
    "profile_solve_ms", "profile_condition_estimation_ms", "profile_point_evaluation_ms",
    "profile_request_total_ms", "profile_peak_rss_mib",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--meshes", default="10:5,20:5,40:5", help="side_m:spacing_m pairs")
    parser.add_argument("--points", type=int, default=100, help="surface query points per solve")
    parser.add_argument("--soils", default=",".join(SOILS), help=f"comma-separated: {','.join(SOILS)}")
    parser.add_argument("--json", type=Path, required=True, help="write complete measurements and traces here")
    args = parser.parse_args()
    if args.points < 0:
        parser.error("--points must be non-negative")

    client = PotentialEngineClient(args.engine, timeout_s=600.0, memory_limit_mb=0)
    rows = []
    print(f"{'soil':>12} {'side':>6} {'segments':>8} {'points':>6} {'total_ms':>10} {'kernel':>9} "
          f"{'assembly':>10} {'factor':>9} {'solve':>9} {'points_ms':>10} {'peak_MiB':>9}")
    for soil_name in args.soils.split(","):
        if soil_name not in SOILS:
            parser.error(f"unknown soil {soil_name!r}; choose from {','.join(SOILS)}")
        soil = SOILS[soil_name]
        for mesh_spec in args.meshes.split(","):
            side, spacing = map(float, mesh_spec.split(":"))
            segments = grid(side, spacing, soil)
            side_points = max(int(args.points ** 0.5), 1)
            points = [PotentialPoint(
                f"p{i}_{j}",
                (-side / 2 - 3 + (side + 6) * i / max(side_points - 1, 1),
                 -side / 2 - 3 + (side + 6) * j / max(side_points - 1, 1), 0.0),
            ) for i in range(side_points) for j in range(side_points)][:args.points]
            started = time.perf_counter()
            result = client.calculate(soil=soil, segments=segments, injections_a={"grid": 1000.0}, points=points)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            diagnostics = result["diagnostics"]
            row = {
                "soil": soil_name,
                "mesh_side_m": side,
                "spacing_m": spacing,
                "segments": len(segments),
                "points": len(points),
                "client_wall_ms": round(elapsed_ms, 3),
                "diagnostics": diagnostics,
                "trace": result["trace"],
                "resistance_ohm": result["groups"]["grid"]["resistance_to_remote_earth_ohm"],
            }
            rows.append(row)
            fields = [diagnostics.get(key, 0.0) for key in PROFILE_KEYS]
            print(f"{soil_name:>12} {side:>6.1f} {len(segments):>8} {len(points):>6} {fields[6]:>10.2f} "
                  f"{fields[0]:>9.2f} {fields[1]:>10.2f} {fields[2]:>9.2f} {fields[3]:>9.2f} "
                  f"{fields[5]:>10.2f} {fields[7]:>9.1f}", flush=True)

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hardware": {"system": platform.platform(), "machine": platform.machine(),
                     "processor": platform.processor()},
        "engine": client.executable,
        "cases": rows,
    }, indent=2) + "\n")
    print(f"Wrote phase traces to {args.json}")


if __name__ == "__main__":
    main()
