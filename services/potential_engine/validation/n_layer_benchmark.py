"""Benchmark the n-layer soil kernel against mesh size, surface points and layer count.

Run after building the engine:
    python services/potential_engine/validation/n_layer_benchmark.py \
      --engine services/potential_engine/build/spat-potential-engine --json out.json

Surface points are split with `point_batch_size` as artifact calculations do; every batch re-solves
the electrode system and is timed. Every soil solves the same square grid with 8 perimeter rods driven through the layers (cut at
every interface by the client). The two-layer image series is included as the baseline route.
Reports time, peak memory, kernel diagnostics and the image work the client mirrors, and the time
per million image evaluations that calibrates the 4e9 work limits. Separate from the large-mesh
benchmark of the GMRES path (large_mesh_benchmark.py), whose results it does not touch.
"""

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import (  # noqa: E402
    LayerStackSoil,
    PotentialEngineClient,
    PotentialPoint,
    TwoLayerSoil,
    image_work,
    interface_depths,
    point_batch_size,
    rectangular_grid_segments,
    split_at_interface,
)

SOILS = {
    "two-layer series": TwoLayerSoil(300.0, 100.0, 2.0),
    "2-layer kernel": LayerStackSoil(((300.0, 2.0), (100.0, None))),
    "3-layer": LayerStackSoil(((300.0, 1.0), (60.0, 2.0), (1000.0, None))),
    "4-layer": LayerStackSoil(((500.0, 0.6), (80.0, 1.2), (1500.0, 2.5), (40.0, None))),
    "8-layer": LayerStackSoil(((200.0, 0.4), (500.0, 0.6), (50.0, 0.5), (800.0, 0.5), (120.0, 1.0),
                               (2000.0, 1.0), (60.0, 4.0), (400.0, None))),
}


def grid(side_m: float, spacing_m: float, soil) -> list:
    segments = rectangular_grid_segments(
        length_m=side_m, width_m=side_m, conductor_spacing_m=spacing_m, burial_depth_m=0.5,
        conductor_radius_m=0.006, rods_count=8, rod_length_m=6.0, discretization_m=1.0, segmentation="graded",
        interface_depths_m=interface_depths(soil))
    return split_at_interface(segments, soil)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--meshes", default="20:5,40:5,60:5,70:3.5", help="side_m:spacing_m pairs")
    parser.add_argument("--points", default="0,2500,10000")
    parser.add_argument("--soils", default=",".join(SOILS))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    client = PotentialEngineClient(args.engine, timeout_s=600.0, memory_limit_mb=0)
    rows = []
    print(f"{'soil':>17} {'mesh':>8} {'segs':>5} {'points':>6} {'s':>7} {'MiB':>6} {'terms':>5} "
          f"{'bound':>8} {'Gwork':>7} {'ns/eval':>7}")
    for name in args.soils.split(","):
        soil = SOILS[name]
        for mesh in args.meshes.split(","):
            side, spacing = map(float, mesh.split(":"))
            segments = grid(side, spacing, soil)
            for count in map(int, args.points.split(",")):
                n = max(int(count ** 0.5), 1)
                points = [PotentialPoint(f"p{i}_{j}", (-side / 2 - 3 + (side + 6) * i / max(n - 1, 1),
                                                       -side / 2 - 3 + (side + 6) * j / max(n - 1, 1), 0.0))
                          for i in range(n) for j in range(n)][:count]
                matrix_work, point_work = image_work(soil, segments, points)
                batch = point_batch_size(soil, segments, points)
                batches = range(0, max(len(points), 1), batch)
                matrix_work *= len(batches)  # each batch re-solves the electrode system
                started = time.perf_counter()
                for start in batches:
                    result = client.calculate(soil=soil, segments=segments, injections_a={"grid": 1000.0},
                                              points=points[start:start + batch])
                elapsed = time.perf_counter() - started
                peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / (1 if sys.platform == "darwin" else 1024) / 2**20
                diagnostics = result["diagnostics"]
                work = matrix_work + point_work
                row = {
                    "soil": name, "soil_record": result["trace"]["soil"], "mesh_side_m": side, "spacing_m": spacing,
                    "segments": len(segments), "points": len(points), "batches": len(batches),
                    "seconds": round(elapsed, 3),
                    "peak_child_rss_mib_cumulative": round(peak, 1),
                    "resistance_ohm": result["groups"]["grid"]["resistance_to_remote_earth_ohm"],
                    "matrix_image_work": matrix_work, "point_image_work": point_work,
                    "ns_per_image_evaluation": round(1e9 * elapsed / work, 3) if work else None,
                    "kernel_terms": diagnostics.get("kernel_terms"), "kernel_error_bound": diagnostics.get("kernel_error_bound"),
                    "image_terms": diagnostics.get("image_terms"), "solver_iterations": diagnostics["solver_iterations"],
                    "backward_error": diagnostics["backward_error"], "method": result["trace"]["method"],
                }
                rows.append(row)
                bound = row["kernel_error_bound"]
                print(f"{name:>17} {mesh:>8} {len(segments):>5} {len(points):>6} {elapsed:>7.2f} {peak:>6.0f} "
                      f"{row['kernel_terms'] or row['image_terms'] or 0:>5.0f} {bound if bound is not None else 0:>8.1e} "
                      f"{work / 1e9:>7.3f} {row['ns_per_image_evaluation'] or 0:>7.2f}", flush=True)
    if args.json:
        args.json.write_text(json.dumps({
            "hardware": {"system": platform.platform(), "machine": platform.machine(), "processor": platform.processor()},
            "engine": args.engine, "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
