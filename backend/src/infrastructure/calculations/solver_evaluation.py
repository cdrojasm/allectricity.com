"""Stable, stateless evaluation interface for optimization callers.

This module deliberately sits below artifact persistence and above the potential-engine
client. One call describes one grounding geometry, one soil model and one current injection.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from src.infrastructure.calculations import artifact_potential
from src.infrastructure.calculations.potential_engine_client import (
    ElectrodeSegment,
    MIN_LENGTH_TO_RADIUS,
    PotentialEngineClient,
    PotentialPoint,
    PROTOCOL,
    SoilModel,
    as_soil,
    soil_record,
    split_at_interface,
)

EVALUATION_SCHEMA = "spat.solver-evaluation/1.0"

DEFAULT_SETTINGS = {
    "conductor_radius_m": 0.00525,
    "discretization_m": 1.0,
    "surface_spacing_m": 0.5,
    "segmentation": artifact_potential.DEFAULT_SEGMENTATION,
    "touch_reach_m": 0.0,
    "l1_surface_spacing_m": 2.0,
    "adaptive_budget_points": 4000,
    "adaptive_tolerance": 1e-4,
    "adaptive_min_step_m": 0.01,
}
# Settings that only matter at some levels: kept out of the fingerprint elsewhere, so a level's
# fingerprint does not change when another level gains a setting.
LEVEL_SETTINGS = {
    "L1": {"l1_surface_spacing_m"},
    "L2+": {"l1_surface_spacing_m"},
    "L3": {"l1_surface_spacing_m", "adaptive_budget_points", "adaptive_tolerance", "adaptive_min_step_m"},
}


def _element_at(geometry: dict[str, Any], segment: ElectrodeSegment) -> tuple[str | None, int | None]:
    """Drawn conductor or rod that contains a discretised segment's midpoint, when the plan is drawn."""
    half_x, half_y = float(geometry["length_m"]) / 2, float(geometry["width_m"]) / 2
    x = 0.5 * (segment.start_m[0] + segment.end_m[0]) + half_x
    y = 0.5 * (segment.start_m[1] + segment.end_m[1]) + half_y
    if segment.kind == "rod":
        for index, rod in enumerate(geometry.get("rods") or []):
            if abs(rod["x"] - x) <= 1e-3 and abs(rod["y"] - y) <= 1e-3:
                return "rod", index
        return None, None
    for index, conductor in enumerate(geometry.get("conductors") or []):
        (ax, ay), (bx, by) = (conductor["start"]["x"], conductor["start"]["y"]), (conductor["end"]["x"], conductor["end"]["y"])
        length = math.hypot(bx - ax, by - ay)
        if length and abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) / length <= 1e-3 \
                and min(ax, bx) - 1e-3 <= x <= max(ax, bx) + 1e-3 and min(ay, by) - 1e-3 <= y <= max(ay, by) + 1e-3:
            return "conductor", index
    return None, None


def discretization_violations(
    geometry: dict[str, Any], soil: SoilModel | float, settings: dict[str, Any] | None = None, level: str = "L2",
) -> list[dict[str, Any]]:
    """Reasons the solver would refuse this geometry once discretised, found without calling it.

    Applies the engine's thin-wire rule (every segment at least 5 radii long, which a junction or
    crossing close to a node can break), the same rule for the parts a soil interface cuts, the
    segment limit, and a touch search area wholly inside structures (no accessible point at the
    raster spacing of `level`). Returns violations shaped like the OP-05 geometry check, each naming the drawn
    conductor or rod that holds the offending segment when there is one.
    """
    effective = {**DEFAULT_SETTINGS, **(settings or {})}
    model = as_soil(soil)
    radius = float(effective["conductor_radius_m"])
    minimum = MIN_LENGTH_TO_RADIUS * radius
    try:
        segments = artifact_potential._segments(geometry, effective, model)
    except ValueError as exc:
        return [{"kind": "discretization", "element": "geometry", "index": None, "message": str(exc)}]
    violations: list[dict[str, Any]] = []
    if len(segments) > artifact_potential.MAX_SEGMENTS:
        violations.append({"kind": "segment_limit", "element": "geometry", "index": None,
                           "message": f"the geometry needs {len(segments)} segments; the limit is {artifact_potential.MAX_SEGMENTS}"})
    for segment in segments:
        length = math.dist(segment.start_m, segment.end_m)
        if length < minimum:
            element, index = _element_at(geometry, segment)
            where = f" on {element} [{index}]" if element else ""
            violations.append({
                "kind": "thin_wire", "element": element or "segment", "index": index, "segment": segment.id,
                "length_m": length, "minimum_m": minimum,
                "message": f"segment {segment.id}{where} is {length:.4f} m long; the thin-wire model needs at least "
                           f"{minimum:.4f} m (5 radii). Move the nearby junction or crossing, or merge the nodes",
            })
    spacing = float(effective["l1_surface_spacing_m"] if level == "L1" else effective["surface_spacing_m"])
    if not artifact_potential.touch_area_is_accessible(geometry, spacing, float(effective["touch_reach_m"])):
        violations.append({"kind": "no_touch_area", "element": "geometry", "index": None,
                           "message": "every point of the touch search area (the grid's bounding box) lies inside a structure; "
                                      "no accessible touch point exists"})
    if not violations:
        try:
            split_at_interface(segments, model)
        except ValueError as exc:   # a part left by a soil interface is too short
            violations.append({"kind": "thin_wire", "element": "segment", "index": None, "message": str(exc)})
    return violations


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate(
    *,
    geometry: dict[str, Any],
    soil: SoilModel | float,
    injection_a: float,
    points: list[PotentialPoint],
    client: PotentialEngineClient,
    settings: dict[str, Any] | None = None,
    level: str = "L2",
) -> dict[str, Any]:
    """Evaluate a single network without reading or mutating artifact/application state.

    `geometry` follows the current canonical grid geometry contract. `settings` accepts
    `conductor_radius_m`, `discretization_m`, `surface_spacing_m`, `segmentation`, and
    `touch_reach_m`; defaults match artifact calculations. The returned input hash is
    independent of point ordering, timestamps, execution duration and engine location.

    `level` is the fidelity: "L2" (default) searches the full raster with local refinements;
    "L3" adds an adaptive pattern search around the strongest touch and step candidates, with
    convergence tolerance and a point budget (`adaptive_*` settings); `refinement` reports how it
    stopped. "L2+" is the union of the L1 and L2 searches: the full search plus the critical touch points
    and the step origins the coarse raster ranks first, each point evaluated once, so it is never
    below either level. "L1" uses a coarser raster (`l1_surface_spacing_m`, 2 m by default), nine known critical
    points and no refinements. Every value is attained at a real surface point, so L1 `Vs` and
    `Vt` are lower bounds of the true maxima: an L1 violation is conclusive, an L1 pass is not.
    They are not lower bounds of the L2 values, because L2 is also a sampled search: L1 finds a
    higher `Vt` when the maximum sits on a critical point L2 does not sample, and L2 finds a
    higher `Vs` when the worst step starts off the coarse raster. L0 does not call the solver
    (see `optimizer_evaluation.evaluate_design`).

    The extrema are approximate because their global search is finite, even though SV-08
    locally refines candidates. `points` are returned separately as requested point values.
    """
    if not isinstance(injection_a, (int, float)) or not math.isfinite(injection_a) or injection_a <= 0:
        raise ValueError("injection_a must be positive")
    if level not in ("L1", "L2", "L2+", "L3"):
        raise ValueError("solver evaluation level must be 'L1', 'L2', 'L2+' or 'L3'; 'L0' never reaches the solver")
    model = as_soil(soil)
    effective = {**DEFAULT_SETTINGS, **(settings or {})}
    allowed_settings = {"conductor_radius_m", "discretization_m", "surface_spacing_m", "segmentation", "touch_reach_m",
                        "l1_surface_spacing_m", "adaptive_budget_points", "adaptive_tolerance", "adaptive_min_step_m"}
    unknown_settings = set(effective) - allowed_settings
    if unknown_settings:
        raise ValueError(f"unsupported evaluation settings: {', '.join(sorted(unknown_settings))}")
    point_records = sorted(
        ({"id": point.id, "xyz_m": list(point.xyz_m)} for point in points),
        key=lambda item: item["id"],
    )
    if len({item["id"] for item in point_records}) != len(point_records):
        raise ValueError("point ids must be unique")
    fingerprint_data = {
        "schema": EVALUATION_SCHEMA,
        "geometry": geometry,
        "soil": soil_record(model),
        "injection_a": float(injection_a),
        "points": point_records,
        "settings": {k: v for k, v in effective.items()
                     if k not in set().union(*LEVEL_SETTINGS.values()) or k in LEVEL_SETTINGS.get(level, set())},
        "quadrature_tolerance": client.quadrature_tolerance,
    }
    coarse = level == "L1"
    if level != "L2":  # L2 fingerprints stay as they were before fidelity levels existed
        fingerprint_data["level"] = level
    input_sha256 = _canonical_hash(fingerprint_data)

    segments = artifact_potential._segments(geometry, effective, model)
    if len(segments) > artifact_potential.MAX_SEGMENTS:
        raise artifact_potential.UnsupportedModelError(
            f"La geometría necesita {len(segments)} segmentos; el límite es {artifact_potential.MAX_SEGMENTS}."
        )
    field = artifact_potential._field(
        client, geometry, model, segments, float(injection_a), "evaluation:injection_a",
        max(float(effective["surface_spacing_m"]), float(effective["l1_surface_spacing_m"])) if coarse
        else float(effective["surface_spacing_m"]),
        float(effective["touch_reach_m"]), coarse,
        **({"critical": True, "coarse_spacing": float(effective["l1_surface_spacing_m"])} if level in ("L2+", "L3") else {}),
        **({"adaptive": {"budget_points": int(effective["adaptive_budget_points"]),
                         "tolerance": float(effective["adaptive_tolerance"]),
                         "min_step_m": float(effective["adaptive_min_step_m"])}} if level == "L3" else {}),
    )
    first = field["first"]
    requested = {}
    if points:
        _, requested, _ = artifact_potential._solve(
            client, model, segments, float(injection_a), points, "evaluation:injection_a"
        )
    group = first["groups"][artifact_potential.GROUP]
    return {
        "schema_version": EVALUATION_SCHEMA,
        "protocol_version": PROTOCOL,
        "solver_version": first["trace"].get("solver_version"),
        "input_sha256": input_sha256,
        "status": "approximate",
        "fidelity": {"level": level, "values_are": "lower_bounds" if coarse else "refined_estimates"},
        "refinement": field.get("adaptive"),
        "quantities": {
            "Rg_ohm": group["resistance_to_remote_earth_ohm"],
            "GPR_v": field["gpr_v"],
            "Vs_v": field["max_step_v"]["value"],
            "Vt_v": field["max_touch_v"]["value"],
        },
        "locations": {
            "Vs": {"from_m": field["max_step_v"]["from_m"], "to_m": field["max_step_v"]["to_m"]},
            "Vt": {"x_m": field["max_touch_v"]["x_m"], "y_m": field["max_touch_v"]["y_m"]},
        },
        "point_potentials_v": dict(sorted(requested.items())),
        "diagnostics": first["diagnostics"],
        "warnings": first["warnings"],
    }
