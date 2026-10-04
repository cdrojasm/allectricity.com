"""Wall time and peak memory of the engine versus segment and point counts.

Builds an Annex H-style 70 m square grid at increasing refinement and queries surface rasters.
Run after building a benchmark binary without the segment cap, for example:
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


def grid(step: float) -> list:
    lines = [0, 14, 28, 42, 56, 70]
    return case_segments({"discretization_m": step, "grid": {
        "group": "grid", "x_lines_m": lines, "y_lines_m": lines, "depth_m": 0.5, "radius_m": 0.00525}})


def run(executable: str, segments: list, points: int) -> tuple[float, float]:
    side = max(int(points ** 0.5), 1) if points else 0
    rows = [engine.PROTOCOL, f"140 {len(segments)}"]
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
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss is bytes on macOS, KiB on Linux
    return elapsed, max(peak, before) * scale / 2**20


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


def worst_allowed_case(executable: str) -> dict:
    """Largest request inside the limits, through the client with its timeout and memory cap."""
    segments = grid(0.7)
    side = int((engine.MAX_POINT_SEGMENT_WORK / len(segments)) ** 0.5)
    points = [engine.PotentialPoint(f"p{i}_{j}", (70 * i / side, 70 * j / side, 0.0)) for i in range(side) for j in range(side)]
    client = engine.PotentialEngineClient(executable)
    started = time.perf_counter()
    result = client.calculate(soil_resistivity_ohm_m=140, segments=segments, injections_a={"grid": 744.8}, points=points)
    return {"segments": len(segments), "points": len(points), "seconds": round(time.perf_counter() - started, 3),
            "timeout_s": client.timeout_s, "memory_limit_mib": client.memory_limit_mb,
            "memory_limit_enforced": sys.platform.startswith("linux"),
            "backward_error": result["diagnostics"]["backward_error"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="benchmark binary built without the segment cap")
    parser.add_argument("--client-engine", help="production binary for the worst allowed case through the client")
    parser.add_argument("--json", type=Path, help="write the measurements to this file")
    args = parser.parse_args()
    rows = []
    print(f"{'segments':>8} {'points':>8} {'seconds':>8} {'peak MiB*':>9}")
    for step in (7.0, 3.5, 2.5, 1.75, 1.0, 0.7, 0.5):
        segments = grid(step)
        for points in (0, 10_000, 40_000):
            if len(segments) * points > engine.MAX_POINT_SEGMENT_WORK:
                continue
            seconds, mib = run(args.engine, segments, points)
            rows.append({"segments": len(segments), "points": points, "seconds": round(seconds, 3), "peak_mib": round(mib, 1)})
            print(f"{len(segments):>8} {points:>8} {seconds:>8.2f} {mib:>9.1f}")
    print("* peak RSS of the largest child so far (monotone across rows)")
    report = {"hardware": hardware(), "rows": rows}
    if args.client_engine:
        report["worst_allowed_case"] = worst_allowed_case(args.client_engine)
        print("worst allowed case through the client:", report["worst_allowed_case"])
    print("hardware:", report["hardware"])
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
