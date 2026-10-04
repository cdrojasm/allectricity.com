"""Wall time and peak memory of the engine versus segment count, point count and soil model.

Builds an Annex H-style 70 m square grid at increasing refinement and queries surface rasters, in
homogeneous soil and in two-layer soils (the image series makes every kernel evaluation costlier,
more so as |K| approaches 1). Run after building a benchmark binary without the segment cap:
    g++ -std=c++17 -O3 -DSPAT_MAX_SEGMENTS=4000 services/potential_engine/src/main.cpp -o /tmp/spat-bench
    python services/potential_engine/validation/benchmark.py --engine /tmp/spat-bench
"""

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations import potential_engine_client as engine  # noqa: E402
from src.infrastructure.calculations.potential_engine_validation import case_segments  # noqa: E402

SOILS = {
    "homogeneous 140": engine.HomogeneousSoil(140),
    "two-layer 300/100 h 6.1 (K -0.5)": engine.TwoLayerSoil(300, 100, 6.096),
    "two-layer 100/1000 h 2 (K 0.82)": engine.TwoLayerSoil(100, 1000, 2.0),
}


def grid(step: float) -> list:
    lines = [0, 14, 28, 42, 56, 70]
    return case_segments({"discretization_m": step, "soil_resistivity_ohm_m": 140, "grid": {
        "group": "grid", "x_lines_m": lines, "y_lines_m": lines, "depth_m": 0.5, "radius_m": 0.00525}})


def run(executable: str, soil, segments: list, points: int) -> tuple[float, float, float]:
    side = max(int(points ** 0.5), 1) if points else 0
    rows = [engine.PROTOCOL, engine._soil_line(soil, len(segments))]
    rows += [f"{s.id} {s.group} {s.kind} {engine._floats(s.start_m)} {engine._floats(s.end_m)} {s.radius_m}" for s in segments]
    rows += ["1", "grid 744.8 benchmark", str(side * side)]
    rows += [f"p{i}_{j} {70 * i / side} {70 * j / side} 0" for i in range(side) for j in range(side)]
    rows.append("END")
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    started = time.perf_counter()
    done = subprocess.run([executable], input="\n".join(rows) + "\n", capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    if done.returncode:
        raise RuntimeError(done.stdout)
    terms = next((float(r.split("\t")[2]) for r in done.stdout.splitlines() if r.startswith("DIAG\timage_terms")), 0.0)
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss is bytes on macOS, KiB on Linux
    return elapsed, max(peak, before) * scale / 2**20, terms


def hardware() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            names = [line.split(":", 1)[1].strip() for line in handle if line.lower().startswith(("model name", "cpu model"))]
        cpu = names[0] if names else cpu
    except OSError:
        pass
    return {"system": platform.system(), "machine": platform.machine(), "cpu": cpu,
            "cpu_count": os.cpu_count(), "python": platform.python_version()}


def worst_allowed_case(executable: str, soil) -> dict:
    """Largest request inside the limits, through the client with its timeout and memory cap."""
    segments = grid(0.7)

    def raster(side: int) -> list:
        return [engine.PotentialPoint(f"p{i}_{j}", (70 * i / side, 70 * j / side, 0.0)) for i in range(side) for j in range(side)]

    side = int((engine.MAX_POINT_SEGMENT_WORK / len(segments)) ** 0.5)
    side = min(side, int(engine.point_batch_size(soil, segments, raster(side)) ** 0.5))
    points = raster(side)
    client = engine.PotentialEngineClient(executable)
    started = time.perf_counter()
    result = client.calculate(soil=soil, segments=segments, injections_a={"grid": 744.8}, points=points)
    return {"segments": len(segments), "points": len(points), "seconds": round(time.perf_counter() - started, 3),
            "timeout_s": client.timeout_s, "memory_limit_mib": client.memory_limit_mb,
            "memory_limit_enforced": sys.platform.startswith("linux"),
            "image_terms": result["diagnostics"]["image_terms"],
            "backward_error": result["diagnostics"]["backward_error"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="benchmark binary built without the segment cap")
    parser.add_argument("--client-engine", help="production binary for the worst allowed case through the client")
    parser.add_argument("--json", type=Path, help="write the measurements to this file")
    args = parser.parse_args()
    rows = []
    print(f"{'soil':<34} {'segments':>8} {'points':>8} {'terms':>5} {'seconds':>8} {'peak MiB*':>9}")
    for name, soil in SOILS.items():
        for step in (7.0, 3.5, 1.75, 1.0, 0.7, 0.5):
            segments = grid(step)
            for points in (0, 10_000, 40_000):
                side = max(int(points ** 0.5), 1) if points else 0
                probe = [engine.PotentialPoint(f"p{i}", (70.0 * (i % 2), 70.0 * (i % 2), 0.0)) for i in range(side * side)]
                matrix_work, point_work = engine.image_work(soil, segments, probe)
                if (len(segments) * points > engine.MAX_POINT_SEGMENT_WORK or point_work > engine.MAX_POINT_IMAGE_WORK
                        or matrix_work > engine.MAX_MATRIX_IMAGE_WORK):
                    continue
                seconds, mib, terms = run(args.engine, soil, segments, points)
                rows.append({"soil": name, "segments": len(segments), "points": points, "image_terms": terms,
                             "seconds": round(seconds, 3), "peak_mib": round(mib, 1)})
                print(f"{name:<34} {len(segments):>8} {points:>8} {terms:>5.0f} {seconds:>8.2f} {mib:>9.1f}")
    print("* peak RSS of the largest child so far (monotone across rows)")
    report = {"hardware": hardware(), "rows": rows}
    if args.client_engine:
        report["worst_allowed_case"] = {name: worst_allowed_case(args.client_engine, soil) for name, soil in SOILS.items()}
        for name, case in report["worst_allowed_case"].items():
            print(f"worst allowed case through the client, {name}: {case}")
    print("hardware:", report["hardware"])
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
