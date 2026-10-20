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
    PotentialEngineClient,
    PotentialPoint,
    PROTOCOL,
    SoilModel,
    as_soil,
    soil_record,
)

EVALUATION_SCHEMA = "spat.solver-evaluation/1.0"


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
) -> dict[str, Any]:
    """Evaluate a single network without reading or mutating artifact/application state.

    `geometry` follows the current canonical grid geometry contract. `settings` accepts
    `conductor_radius_m`, `discretization_m`, `surface_spacing_m`, `segmentation`, and
    `touch_reach_m`; defaults match artifact calculations. The returned input hash is
    independent of point ordering, timestamps, execution duration and engine location.

    The extrema are approximate because their global search is finite, even though SV-08
    locally refines candidates. `points` are returned separately as requested point values.
    """
    if not isinstance(injection_a, (int, float)) or not math.isfinite(injection_a) or injection_a <= 0:
        raise ValueError("injection_a must be positive")
    model = as_soil(soil)
    effective = {
        "conductor_radius_m": 0.00525,
        "discretization_m": 1.0,
        "surface_spacing_m": 0.5,
        "segmentation": artifact_potential.DEFAULT_SEGMENTATION,
        "touch_reach_m": 0.0,
        **(settings or {}),
    }
    allowed_settings = {"conductor_radius_m", "discretization_m", "surface_spacing_m", "segmentation", "touch_reach_m"}
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
        "settings": effective,
        "quadrature_tolerance": client.quadrature_tolerance,
    }
    input_sha256 = _canonical_hash(fingerprint_data)

    segments = artifact_potential._segments(geometry, effective, model)
    if len(segments) > artifact_potential.MAX_SEGMENTS:
        raise artifact_potential.UnsupportedModelError(
            f"La geometría necesita {len(segments)} segmentos; el límite es {artifact_potential.MAX_SEGMENTS}."
        )
    field = artifact_potential._field(
        client, geometry, model, segments, float(injection_a), "evaluation:injection_a",
        float(effective["surface_spacing_m"]), float(effective["touch_reach_m"]),
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
