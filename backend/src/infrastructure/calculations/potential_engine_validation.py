"""Reference-case validation and discretisation convergence for the C++ potential engine.

Cases live in services/potential_engine/validation/reference_cases.json with geometry, inputs,
published or closed-form references, tolerances and source provenance.
"""

from __future__ import annotations

import json
from math import ceil, cos, dist, pi, sin
from pathlib import Path
from typing import Any

from src.infrastructure.calculations.potential_engine_client import (
    ElectrodeSegment,
    HomogeneousSoil,
    PotentialEngineClient,
    PotentialPoint,
    Segmentation,
    SoilModel,
    TwoLayerSoil,
    discretize,
    point_batch_size,
)

STEP_DISTANCE_M = 1.0
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


def case_outline(case: dict[str, Any]) -> list[tuple[float, float]] | None:
    """Plan outline of a case: `outline_m`, else the grid's rectangle or L shape (counter-clockwise)."""
    if case.get("outline_m"):
        return [tuple(point) for point in case["outline_m"]]
    grid = case.get("grid")
    if not grid:
        return None
    x0, x1, y0, y1 = min(grid["x_lines_m"]), max(grid["x_lines_m"]), min(grid["y_lines_m"]), max(grid["y_lines_m"])
    if grid.get("notch_m"):
        nx, ny = grid["notch_m"]
        return [(x0, y0), (x1, y0), (x1, ny), (nx, ny), (nx, y1), (x0, y1)]
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def offset_polygon(polygon: list[tuple[float, float]], distance_m: float) -> list[tuple[float, float]]:
    """Offset a simple polygon outward (inward for a negative distance) with mitred corners."""
    n = len(polygon)
    area = sum(polygon[i][0] * polygon[(i + 1) % n][1] - polygon[(i + 1) % n][0] * polygon[i][1] for i in range(n))
    sign = 1.0 if area > 0 else -1.0

    def normal(a, b):
        length = dist(a, b)
        return sign * (b[1] - a[1]) / length, -sign * (b[0] - a[0]) / length

    result = []
    for i in range(n):
        n1, n2 = normal(polygon[i - 1], polygon[i]), normal(polygon[i], polygon[(i + 1) % n])
        scale = distance_m / (1.0 + n1[0] * n2[0] + n1[1] * n2[1])
        result.append((polygon[i][0] + (n1[0] + n2[0]) * scale, polygon[i][1] + (n1[1] + n2[1]) * scale))
    return result


def _on_segment(point, a, b, tolerance=1e-9) -> bool:
    ab = (b[0] - a[0], b[1] - a[1])
    t = ((point[0] - a[0]) * ab[0] + (point[1] - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2)
    t = min(max(t, 0.0), 1.0)
    return dist(point, (a[0] + ab[0] * t, a[1] + ab[1] * t)) <= tolerance


def inside_polygon(point, polygon) -> bool:
    """Point in polygon, boundary included."""
    n, inside = len(polygon), False
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if _on_segment(point, a, b):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


def _perimeter_position(point, polygon) -> float:
    travelled = 0.0
    for i in range(len(polygon)):
        a, b = polygon[i], polygon[(i + 1) % len(polygon)]
        if _on_segment(point, a, b):
            return travelled + dist(a, point)
        travelled += dist(a, b)
    raise ValueError(f"{point} is not on the outline")


def _walk(polygon, spacing_m: float) -> list[tuple[float, float]]:
    """Points every `spacing_m` around a closed polygon, starting at each vertex."""
    points = []
    for i in range(len(polygon)):
        a, b = polygon[i], polygon[(i + 1) % len(polygon)]
        n = max(1, round(dist(a, b) / spacing_m))
        points += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return points


def case_segments(case: dict[str, Any], discretization_m: float | None = None,
                  segmentation: str | None = None) -> list[ElectrodeSegment]:
    """Discretise a case's conductors with `segmentation` (default: the case's, else `uniform`).

    `graded` first cuts the geometry into node-to-node pieces and then grades each piece with
    `Segmentation.for_discretization("graded", discretization_m)`.
    """
    step = float(discretization_m or case["discretization_m"])
    if (segmentation or case.get("segmentation", "uniform")) == "graded":
        soil = case_soil(case)
        interface_z = -soil.upper_thickness_m if isinstance(soil, TwoLayerSoil) else None
        return discretize(_case_pieces(case, float("inf")), Segmentation.for_discretization("graded", step), interface_z)
    return _case_pieces(case, step)


def _case_pieces(case: dict[str, Any], step: float) -> list[ElectrodeSegment]:
    """Uniformly discretise a case's conductors; `step` = inf gives one piece per node-to-node conductor.

    Supported geometry: explicit `conductors`; a `grid` of x/y lines (optionally L-shaped with
    `notch_m`, with `diagonals_m` and `perimeter_rods` at every or every other perimeter node);
    explicit `rods`; and `fences` of posts (plus an optional buried ring) offset from the outline.
    Grid conductors are cut at every crossing and, in two-layer soil, every conductor is cut at
    the interface so no segment straddles it.
    """
    soil = case_soil(case)
    interface_z = -soil.upper_thickness_m if isinstance(soil, TwoLayerSoil) else None
    segments: list[ElectrodeSegment] = []
    for index, conductor in enumerate(case.get("conductors", [])):
        segments += _split(f"c{index}", conductor["group"], conductor["kind"], conductor["start_m"],
                           conductor["end_m"], conductor["radius_m"], step, interface_z)
    grid = case.get("grid")
    outline = case_outline(case)
    if grid:
        xs, ys, z, r, group = grid["x_lines_m"], grid["y_lines_m"], -grid["depth_m"], grid["radius_m"], grid["group"]
        notch = grid.get("notch_m")
        for ix, x in enumerate(xs):
            top = max(ys) if not notch or x <= notch[0] + 1e-9 else notch[1]
            stops = [y for y in ys if y <= top + 1e-9]
            for k in range(len(stops) - 1):
                segments += _split(f"gx{ix}_{k}", group, "grid", (x, stops[k], z), (x, stops[k + 1], z), r, step)
        for iy, y in enumerate(ys):
            right = max(xs) if not notch or y <= notch[1] + 1e-9 else notch[0]
            stops = [x for x in xs if x <= right + 1e-9]
            for k in range(len(stops) - 1):
                segments += _split(f"gy{iy}_{k}", group, "grid", (stops[k], y, z), (stops[k + 1], y, z), r, step)
        for index, (x1, y1, x2, y2) in enumerate(grid.get("diagonals_m", [])):
            segments += _split(f"gd{index}", group, "diagonal", (x1, y1, z), (x2, y2, z), r, step)
        rods = grid.get("perimeter_rods")
        if rods:
            nodes = [(x, y) for x in xs for y in ys if any(_on_segment((x, y), outline[i], outline[(i + 1) % len(outline)])
                                                           for i in range(len(outline)))]
            if rods.get("rule", "all") == "alternate":
                nodes = sorted(nodes, key=lambda node: _perimeter_position(node, outline))[::2]
            for index, (x, y) in enumerate(nodes):
                segments += _split(f"rod{index}", group, "rod", (x, y, z), (x, y, z - rods["length_m"]),
                                   rods["radius_m"], step, interface_z)
    for index, rod in enumerate(case.get("rods", [])):
        top = -rod["top_depth_m"]
        segments += _split(f"r{index}", rod["group"], rod.get("kind", "rod"), (rod["x_m"], rod["y_m"], top),
                           (rod["x_m"], rod["y_m"], top - rod["length_m"]), rod["radius_m"], step, interface_z)
    for f, fence in enumerate(case.get("fences", [])):
        line = offset_polygon(outline, fence["offset_m"])
        for index, (x, y) in enumerate(_walk(line, fence["post_spacing_m"])):
            segments += _split(f"f{f}p{index}", fence["group"], "post", (x, y, 0.0), (x, y, -fence["post_length_m"]),
                               fence["post_radius_m"], step, interface_z)
        if "conductor_offset_m" in fence:
            ring = offset_polygon(line, fence["conductor_offset_m"])
            depth = -fence["conductor_depth_m"]
            for i in range(len(ring)):
                a, b = ring[i], ring[(i + 1) % len(ring)]
                segments += _split(f"f{f}c{i}", fence["group"], "fence", (a[0], a[1], depth), (b[0], b[1], depth),
                                   fence["conductor_radius_m"], step, interface_z)
    return segments


def _raster(area: list[float], spacing: float) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = area
    nx, ny = round((x1 - x0) / spacing), round((y1 - y0) / spacing)
    return [(x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny) for j in range(ny + 1) for i in range(nx + 1)]


def _area(case: dict[str, Any], check: dict[str, Any]) -> list[tuple[float, float]]:
    """Evaluation polygon: the `area_m` rectangle, or the outline offset by `area_outline_offset_m`."""
    if "area_m" in check:
        x0, y0, x1, y1 = check["area_m"]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return offset_polygon(case_outline(case), check.get("area_outline_offset_m", 0.0))


def _area_raster(case, check, spacing: float) -> list[tuple[float, float]]:
    if "area_m" in check:
        return _raster(check["area_m"], spacing)
    polygon = _area(case, check)
    x0, y0 = min(p[0] for p in polygon), min(p[1] for p in polygon)
    x1, y1 = max(p[0] for p in polygon), max(p[1] for p in polygon)
    nx, ny = int((x1 - x0) / spacing + 1e-9), int((y1 - y0) / spacing + 1e-9)
    grid = ((round(x0 + i * spacing, 9), round(y0 + j * spacing, 9)) for j in range(ny + 1) for i in range(nx + 1))
    return [point for point in grid if inside_polygon(point, polygon)]


def _subraster(center, spacing: float, refine: float, polygon) -> list[tuple[float, float]]:
    n = round(spacing / refine)
    points = [(round(center[0] + i * refine, 9), round(center[1] + j * refine, 9))
              for i in range(-n, n + 1) for j in range(-n, n + 1)]
    return [point for point in points if inside_polygon(point, polygon)]


STEP_DIRECTIONS = [(cos(2 * pi * k / 16), sin(2 * pi * k / 16)) for k in range(16)]
# IEEE 80 models the foot as a 0.08 m radius disc: nobody stands on the axis of an electrode that
# reaches the surface (a fence post), so surface points closer than this to one are not evaluated.
FOOT_RADIUS_M = 0.08
STEP_CANDIDATES = 50
TOUCH_REFINE_CANDIDATES = 12
STEP_REFINE_CANDIDATES = 5


def evaluate_case(
    client: PotentialEngineClient,
    case: dict[str, Any],
    discretization_m: float | None = None,
    raster_spacing_m: float | None = None,
    segmentation: str | None = None,
) -> dict[str, Any]:
    """Run one case and return each check's computed value plus the engine diagnostics.

    Surface potentials are evaluated in up to three passes (each re-solves the same electrode
    system): fixed points and area rasters; refinement around the worst touch points and 16
    step directions around the strongest step candidates; and a refined step search.
    """
    segments = case_segments(case, discretization_m, segmentation)
    soil = case_soil(case)
    exposed = [s.start_m[:2] for s in segments if s.start_m[2] > -FOOT_RADIUS_M] + \
              [s.end_m[:2] for s in segments if s.end_m[2] > -FOOT_RADIUS_M]

    def standable(point) -> bool:
        return all(dist(point, top) >= FOOT_RADIUS_M for top in exposed)

    state: dict[str, Any] = {"result": None, "points": 0}
    v: dict[str, float] = {}

    def solve(points: dict[str, tuple[float, float]]) -> None:
        queries = [PotentialPoint(pid, (x, y, 0.0)) for pid, (x, y) in points.items()]
        batch = point_batch_size(soil, segments, queries)
        for start in range(0, max(len(queries), 1), batch):
            result = client.calculate(
                soil=soil, segments=segments, injections_a=case["injections_a"], points=queries[start:start + batch],
                injection_origins={group: "validation-case" for group in case["injections_a"]},
            )
            v.update(result["potentials_v"])
            state["result"] = state["result"] or result
        state["points"] += len(points)

    def group_v(name: str) -> float:
        return state["result"]["groups"][name]["potential_v"]

    first: dict[str, tuple[float, float]] = {}
    rasters: dict[int, list[str]] = {}
    for index, check in enumerate(case["checks"]):
        quantity = check["quantity"]
        if quantity == "touch_v":
            first[f"k{index}"] = tuple(check["point_m"])
        elif quantity == "step_v":
            first[f"k{index}a"], first[f"k{index}b"] = tuple(check["points_m"][0]), tuple(check["points_m"][1])
        elif quantity in ("max_touch_v", "max_step_v"):
            raster = [p for p in _area_raster(case, check, raster_spacing_m or check["spacing_m"]) if standable(p)]
            rasters[index] = [f"k{index}r{n}" for n in range(len(raster))]
            first.update(zip(rasters[index], raster))
    solve(first)

    # Pass 2: refine the lowest surface potentials (touch) and probe 16 directions (step).
    second: dict[str, tuple[float, float]] = {}
    step_candidates: dict[int, list[str]] = {}
    for index, check in enumerate(case["checks"]):
        spacing = raster_spacing_m or check.get("spacing_m", 0.5)
        if check["quantity"] == "max_touch_v" and check.get("refine_m"):
            polygon = _area(case, check)
            for c, pid in enumerate(sorted(rasters[index], key=v.__getitem__)[:TOUCH_REFINE_CANDIDATES]):
                for n, point in enumerate(_subraster(first[pid], spacing, check["refine_m"], polygon)):
                    if standable(point):
                        second[f"k{index}t{c}_{n}"] = point
        elif check["quantity"] == "max_step_v":
            reach = max(1, round(STEP_DISTANCE_M / spacing))
            index_of = {(round(first[pid][0] / spacing), round(first[pid][1] / spacing)): pid for pid in rasters[index]}

            def screen(pid):
                ix, iy = round(first[pid][0] / spacing), round(first[pid][1] / spacing)
                return max((abs(v[pid] - v[index_of[(ix + dx, iy + dy)]]) for dx, dy in
                            ((reach, 0), (-reach, 0), (0, reach), (0, -reach)) if (ix + dx, iy + dy) in index_of), default=0.0)

            step_candidates[index] = sorted(rasters[index], key=screen, reverse=True)[:STEP_CANDIDATES]
            for pid in step_candidates[index]:
                x, y = first[pid]
                for d, (ux, uy) in enumerate(STEP_DIRECTIONS):
                    foot = (x + STEP_DISTANCE_M * ux, y + STEP_DISTANCE_M * uy)
                    if standable(foot):
                        second[f"{pid}d{d}"] = foot
    if second:
        solve(second)

    def best_step(origins: list[str]) -> list[tuple[float, str]]:
        return sorted(((max((abs(v[pid] - v[f"{pid}d{d}"]) for d in range(16) if f"{pid}d{d}" in v), default=0.0), pid)
                       for pid in origins), reverse=True)

    # Pass 3: refined step search around the strongest candidates.
    third: dict[str, tuple[float, float]] = {}
    refined: dict[int, list[str]] = {}
    for index, check in enumerate(case["checks"]):
        if check["quantity"] == "max_step_v" and check.get("refine_m"):
            spacing = raster_spacing_m or check["spacing_m"]
            polygon = _area(case, check)
            refined[index] = []
            for c, (_, pid) in enumerate(best_step(step_candidates[index])[:STEP_REFINE_CANDIDATES]):
                for n, (x, y) in enumerate(_subraster(first[pid], spacing, check["refine_m"], polygon)):
                    if not standable((x, y)):
                        continue
                    origin = f"k{index}s{c}_{n}"
                    refined[index].append(origin)
                    third[origin] = (x, y)
                    for d, (ux, uy) in enumerate(STEP_DIRECTIONS):
                        foot = (x + STEP_DISTANCE_M * ux, y + STEP_DISTANCE_M * uy)
                        if standable(foot):
                            third[f"{origin}d{d}"] = foot
    if third:
        solve(third)

    values: list[float] = []
    for index, check in enumerate(case["checks"]):
        quantity = check["quantity"]
        if quantity == "resistance_ohm":
            value = state["result"]["groups"][check["group"]]["resistance_to_remote_earth_ohm"]
        elif quantity == "group_potential_v":
            value = group_v(check["group"])
        elif quantity == "group_difference_v":
            value = group_v(check["groups"][0]) - group_v(check["groups"][1])
        elif quantity == "touch_v":
            value = group_v(check["group"]) - v[f"k{index}"]
        elif quantity == "step_v":
            value = abs(v[f"k{index}a"] - v[f"k{index}b"])
        elif quantity == "max_touch_v":
            lowest = min(v[pid] for pid in rasters[index])
            lowest = min([lowest] + [v[pid] for pid in v if pid.startswith(f"k{index}t")])
            value = group_v(check["group"]) - lowest
        elif quantity == "max_step_v":
            origins = step_candidates[index] + refined.get(index, [])
            value = best_step(origins)[0][0]
        else:
            raise ValueError(f"unknown check quantity: {quantity}")
        if check.get("per") == "gpr_percent":
            value *= 100.0 / group_v(check["group"])
        values.append(value)
    result = state["result"]
    return {"values": values, "segment_count": len(segments), "point_count": state["points"],
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
    """Compare every check of every case against its reference; one row per check.

    Checks marked `"status": "known-deviation"` are reported with their explanation but are
    informative: an investigated disagreement with the reference that is not an engine defect.
    """
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
                "known_deviation": check.get("status") == "known-deviation",
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
    segmentation: str | None = None,
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
    segment_runs = [(step, evaluate_case(client, case, step, segmentation=segmentation)) for step in discretizations_m]
    report = {"case": case["id"], "quantities": labels, "segment_sweep": sweep(segment_runs, "discretization_m"),
              "segmentation": segmentation or case.get("segmentation", "uniform")}
    if raster_spacings_m:
        finest_step = discretizations_m[-1]
        raster_runs = [(spacing, evaluate_case(client, case, finest_step, spacing, segmentation))
                       for spacing in raster_spacings_m]
        report["raster_sweep"] = sweep(raster_runs, "raster_spacing_m")
    return report
