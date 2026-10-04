"""Reference-case validation and discretisation convergence for the C++ potential engine.

Cases live in services/potential_engine/validation/reference_cases.json with geometry, inputs,
published or closed-form references, tolerances and source provenance.
"""

from __future__ import annotations

import json
from math import ceil, dist
from pathlib import Path
from typing import Any

from src.infrastructure.calculations.potential_engine_client import (
    ElectrodeSegment,
    HomogeneousSoil,
    PotentialEngineClient,
    PotentialPoint,
    SoilModel,
    TwoLayerSoil,
    point_batch_size,
)

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[4] / "services" / "potential_engine" / "validation" / "reference_cases.json"


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def case_soil(case: dict[str, Any]) -> SoilModel:
    """Soil model of a case: `soil` (two-layer) or the homogeneous `soil_resistivity_ohm_m`."""
    soil = case.get("soil")
    if soil:
        return TwoLayerSoil(soil["upper_resistivity_ohm_m"], soil["lower_resistivity_ohm_m"], soil["upper_thickness_m"])
    return HomogeneousSoil(case["soil_resistivity_ohm_m"])


def _split(prefix: str, group: str, kind: str, start, end, radius: float, max_length_m: float,
           interface_z: float | None = None) -> list[ElectrodeSegment]:
    """Discretise one straight conductor; with `interface_z`, cut it there first."""
    if interface_z is not None and min(start[2], end[2]) < interface_z < max(start[2], end[2]):
        t = (interface_z - start[2]) / (end[2] - start[2])
        cut = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t, interface_z)
        if min(dist(start, cut), dist(cut, end)) < 5.0 * radius:
            raise ValueError(f"conductor {prefix} crosses the soil interface within 5 radii of its end")
        return (_split(f"{prefix}a", group, kind, start, cut, radius, max_length_m)
                + _split(f"{prefix}b", group, kind, cut, end, radius, max_length_m))
    pieces = max(1, ceil(dist(start, end) / max_length_m - 1e-9))
    return [
        ElectrodeSegment(
            f"{prefix}_{k}", group, kind,
            tuple(start[i] + (end[i] - start[i]) * k / pieces for i in range(3)),
            tuple(start[i] + (end[i] - start[i]) * (k + 1) / pieces for i in range(3)),
            radius,
        )
        for k in range(pieces)
    ]


def case_segments(case: dict[str, Any], discretization_m: float | None = None) -> list[ElectrodeSegment]:
    """Discretise a case's conductors; grid conductors are cut at every crossing and, in two-layer
    soil, every conductor is cut at the interface so no segment straddles it."""
    step = float(discretization_m or case["discretization_m"])
    soil = case_soil(case)
    interface_z = -soil.upper_thickness_m if isinstance(soil, TwoLayerSoil) else None
    segments: list[ElectrodeSegment] = []
    for index, conductor in enumerate(case.get("conductors", [])):
        segments += _split(f"c{index}", conductor["group"], conductor["kind"], conductor["start_m"],
                           conductor["end_m"], conductor["radius_m"], step, interface_z)
    grid = case.get("grid")
    if grid:
        xs, ys, z, r, group = grid["x_lines_m"], grid["y_lines_m"], -grid["depth_m"], grid["radius_m"], grid["group"]
        for ix, x in enumerate(xs):
            for k in range(len(ys) - 1):
                segments += _split(f"gx{ix}_{k}", group, "grid", (x, ys[k], z), (x, ys[k + 1], z), r, step)
        for iy, y in enumerate(ys):
            for k in range(len(xs) - 1):
                segments += _split(f"gy{iy}_{k}", group, "grid", (xs[k], y, z), (xs[k + 1], y, z), r, step)
        rods = grid.get("perimeter_rods")
        if rods:
            corners = [(x, y) for x in xs for y in ys if x in (xs[0], xs[-1]) or y in (ys[0], ys[-1])]
            for index, (x, y) in enumerate(corners):
                segments += _split(f"rod{index}", group, "rod", (x, y, z), (x, y, z - rods["length_m"]),
                                   rods["radius_m"], step, interface_z)
    return segments


def _raster(area: list[float], spacing: float) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = area
    nx, ny = round((x1 - x0) / spacing), round((y1 - y0) / spacing)
    return [(x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny) for j in range(ny + 1) for i in range(nx + 1)]


def evaluate_case(
    client: PotentialEngineClient,
    case: dict[str, Any],
    discretization_m: float | None = None,
    raster_spacing_m: float | None = None,
) -> dict[str, Any]:
    """Run one case and return each check's computed value plus the engine diagnostics."""
    segments = case_segments(case, discretization_m)
    points: dict[str, tuple[float, float, float]] = {}
    rasters: dict[int, list[str]] = {}
    for index, check in enumerate(case["checks"]):
        if check["quantity"] == "touch_v":
            points[f"k{index}"] = (*check["point_m"], 0.0)
        elif check["quantity"] == "step_v":
            points[f"k{index}a"] = (*check["points_m"][0], 0.0)
            points[f"k{index}b"] = (*check["points_m"][1], 0.0)
        elif check["quantity"] == "max_touch_v":
            raster = _raster(check["area_m"], raster_spacing_m or check["spacing_m"])
            rasters[index] = [f"k{index}r{n}" for n in range(len(raster))]
            points.update({pid: (x, y, 0.0) for pid, (x, y) in zip(rasters[index], raster)})
    queries = [PotentialPoint(pid, xyz) for pid, xyz in points.items()]
    batch = point_batch_size(case_soil(case), segments, queries)
    v: dict[str, float] = {}
    for start in range(0, max(len(queries), 1), batch):
        result = client.calculate(
            soil=case_soil(case),
            segments=segments,
            injections_a=case["injections_a"],
            points=queries[start:start + batch],
            injection_origins={group: "validation-case" for group in case["injections_a"]},
        )
        v.update(result["potentials_v"])
    values: list[float] = []
    for index, check in enumerate(case["checks"]):
        quantity = check["quantity"]
        if quantity == "resistance_ohm":
            values.append(result["groups"][check["group"]]["resistance_to_remote_earth_ohm"])
        elif quantity == "group_potential_v":
            values.append(result["groups"][check["group"]]["potential_v"])
        elif quantity == "touch_v":
            values.append(result["groups"][check["group"]]["potential_v"] - v[f"k{index}"])
        elif quantity == "step_v":
            values.append(abs(v[f"k{index}a"] - v[f"k{index}b"]))
        elif quantity == "max_touch_v":
            gpr = result["groups"][check["group"]]["potential_v"]
            values.append(max(gpr - v[pid] for pid in rasters[index]))
        else:
            raise ValueError(f"unknown check quantity: {quantity}")
    return {"values": values, "segment_count": len(segments), "point_count": len(points),
            "diagnostics": result["diagnostics"], "warnings": result["warnings"], "trace": result["trace"]}


def deviation(value: float, reference: dict[str, float]) -> float:
    """Relative distance from the reference value or, for a range, from its nearest bound (0 inside)."""
    low = reference.get("min", reference.get("value"))
    high = reference.get("max", reference.get("value"))
    if value < low:
        return value / low - 1.0
    if value > high:
        return value / high - 1.0
    return 0.0


def validate(client: PotentialEngineClient, cases: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare every check of every case against its reference; one row per check."""
    rows = []
    for case in cases["cases"]:
        run = evaluate_case(client, case)
        for check, value in zip(case["checks"], run["values"]):
            error = deviation(value, check["reference"])
            source = cases["sources"][check["source"]]
            rows.append({
                "case": case["id"], "quantity": check["quantity"], "label": check.get("label", f"{check['quantity']} ({check.get('group', '')})"),
                "value": value, "reference": check["reference"], "deviation_rel": error,
                "tolerance_rel": check["tolerance_rel"], "passed": abs(error) <= check["tolerance_rel"],
                "source": check["source"], "source_citation": source["citation"], "source_version": source["version"],
                "segment_count": run["segment_count"], "diagnostics": run["diagnostics"],
                "engine_version": run["trace"]["solver_version"],
            })
    return rows


def convergence(
    client: PotentialEngineClient,
    case: dict[str, Any],
    discretizations_m: list[float],
    raster_spacings_m: list[float] | None = None,
) -> dict[str, Any]:
    """Re-run a case with refined segments, then refined surface rasters, reporting relative changes.

    Each row's `change_rel` is the relative difference to the previous (coarser) run, and
    `error_vs_finest_rel` the difference to the finest run of the same sweep.
    """
    def sweep(runs: list[tuple[float, dict[str, Any]]], parameter: str) -> list[dict[str, Any]]:
        finest = runs[-1][1]["values"]
        rows, previous = [], None
        for setting, run in runs:
            rows.append({
                parameter: setting, "segment_count": run["segment_count"], "point_count": run["point_count"],
                "values": run["values"],
                "change_rel": None if previous is None else [abs(v / p - 1.0) for v, p in zip(run["values"], previous)],
                "error_vs_finest_rel": [abs(v / f - 1.0) for v, f in zip(run["values"], finest)],
            })
            previous = run["values"]
        return rows

    labels = [check.get("label", check["quantity"]) for check in case["checks"]]
    segment_runs = [(step, evaluate_case(client, case, discretization_m=step)) for step in discretizations_m]
    report = {"case": case["id"], "quantities": labels, "segment_sweep": sweep(segment_runs, "discretization_m")}
    if raster_spacings_m:
        finest_step = discretizations_m[-1]
        raster_runs = [(spacing, evaluate_case(client, case, finest_step, spacing)) for spacing in raster_spacings_m]
        report["raster_sweep"] = sweep(raster_runs, "raster_spacing_m")
    return report
