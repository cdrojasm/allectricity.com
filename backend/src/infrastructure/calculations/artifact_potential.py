"""Potential-engine calculation for one version of a grounding design artifact."""

from __future__ import annotations

from math import cos, pi, sin
from time import time
from typing import Any

from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.fault_current import ReturnPath, grid_current
from src.infrastructure.calculations.potential_engine_client import (
    MAX_POINT_SEGMENT_WORK,
    MAX_POINTS,
    MAX_SEGMENTS,
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    rectangular_grid_segments,
)

GROUP = "grid"
INJECTION_ORIGIN = "artifact:fault.current_a"
STEP_DISTANCE_M = 1.0
SURFACE_MARGIN_M = 3.0
STEP_CANDIDATES = 20
STEP_DIRECTIONS = 16
# A calculation left "running" longer than this is assumed lost (worker crash) and may run again.
STALE_RUNNING_S = 900
MODEL_WARNINGS = [
    "La corriente de falla del artefacto se inyecta completa en la malla, sin factor de división (P1 del backlog).",
    "El contacto máximo se busca solo dentro del perímetro de la malla; cercas y estructuras externas no se modelan.",
    "La capa superficial solo modifica las tensiones tolerables (factor Cs); el campo eléctrico del motor no la modela.",
]


class UnsupportedModelError(ValueError):
    """The artifact needs a model the engine does not solve; the calculation is rejected."""


def homogeneous_resistivity(soil_layers: list[dict[str, Any]]) -> float:
    values = {float(layer["resistivity_ohm_m"]) for layer in soil_layers}
    if len(values) != 1:
        raise UnsupportedModelError(
            "El motor solo resuelve suelo homogéneo y el artefacto tiene capas con resistividades distintas; "
            "el suelo estratificado es un P1 del backlog."
        )
    return values.pop()


def _fault_current(fault, parameters, client, rho, segments) -> tuple[float, str, dict[str, Any] | None]:
    """Grid current I_G = D_f · S_f · 3I0, its injection origin token and breakdown (None without data).

    R_g does not depend on the injected current, so return paths need one points-free solve at
    1 A first; a user split factor or X/R alone need no extra solve.
    """
    split = parameters.get("fault_split") or {}
    x_over_r = parameters.get("x_over_r")
    if not split and x_over_r is None:
        return float(fault["current_a"]), INJECTION_ORIGIN, None
    paths = [ReturnPath(p["name"], p["kind"], complex(p["resistance_ohm"], p.get("reactance_ohm", 0.0)))
             for p in split.get("return_paths") or []]
    grid_resistance = None
    if paths:
        unit = client.calculate(soil_resistivity_ohm_m=rho, segments=segments, injections_a={GROUP: 1.0},
                                points=[], injection_origins={GROUP: "unit-current-for-split"})
        grid_resistance = unit["groups"][GROUP]["resistance_to_remote_earth_ohm"]
    breakdown = grid_current(
        float(fault["current_a"]), float(fault["clearing_time_s"]), grid_resistance_ohm=grid_resistance,
        x_over_r=x_over_r, frequency_hz=parameters.get("system_frequency_hz", 60.0),
        split_factor=split.get("split_factor"), split_factor_origin=split.get("split_factor_origin"),
        return_paths=paths,
    )
    origin = INJECTION_ORIGIN + (":df" if x_over_r is not None else "") + (
        ":sf-paths" if paths else ":sf-user" if split.get("split_factor") is not None else "")
    return breakdown["grid_current_a"], origin, breakdown


def _solve(client, rho, segments, current, points, origin=INJECTION_ORIGIN):
    """Solve once per batch of surface points; every batch shares the same electrode solution."""
    batch = max(1, min(MAX_POINTS, int(MAX_POINT_SEGMENT_WORK // len(segments))))
    potentials: dict[str, float] = {}
    first, hashes = None, []
    for start in range(0, max(len(points), 1), batch):
        result = client.calculate(
            soil_resistivity_ohm_m=rho, segments=segments, injections_a={GROUP: current},
            points=points[start:start + batch], injection_origins={GROUP: origin},
        )
        potentials.update(result["potentials_v"])
        hashes.append(result["trace"]["request_sha256"])
        first = first or result
    return first, potentials, hashes


def calculate(snapshot: dict[str, Any], parameters: dict[str, Any], client: PotentialEngineClient) -> dict[str, Any]:
    """Return `{"result": ..., "trace": ...}` for an artifact snapshot and calculation parameters."""
    geometry, fault = snapshot["geometry"], snapshot["fault"]
    rho = homogeneous_resistivity(snapshot["soil_layers"])
    step = float(parameters["discretization_m"])
    segments = rectangular_grid_segments(
        length_m=geometry["length_m"], width_m=geometry["width_m"],
        conductor_spacing_m=geometry["conductor_spacing_m"], burial_depth_m=geometry["burial_depth_m"],
        conductor_radius_m=parameters["conductor_radius_m"], group=GROUP,
        rods_count=geometry.get("rods_count", 0), rod_length_m=geometry.get("rod_length_m", 2.4),
        discretization_m=step,
    )
    if len(segments) > MAX_SEGMENTS:
        raise UnsupportedModelError(
            f"La malla necesita {len(segments)} segmentos con discretización de {step:g} m y el límite es "
            f"{MAX_SEGMENTS}. Una discretización mayor reduce la precisión de las tensiones de paso."
        )
    current, origin, fault_breakdown = _fault_current(fault, parameters, client, rho, segments)
    half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
    spacing = float(parameters["surface_spacing_m"])
    nx = round(2 * (half_x + SURFACE_MARGIN_M) / spacing)
    ny = round(2 * (half_y + SURFACE_MARGIN_M) / spacing)
    raster = {
        f"s{i}_{j}": (-half_x - SURFACE_MARGIN_M + i * spacing, -half_y - SURFACE_MARGIN_M + j * spacing, 0.0)
        for i in range(nx + 1) for j in range(ny + 1)
    }
    first, v, hashes = _solve(client, rho, segments, current,
                              [PotentialPoint(pid, xyz) for pid, xyz in raster.items()], origin)
    gpr = first["groups"][GROUP]["potential_v"]

    inside = [pid for pid, (x, y, _) in raster.items() if abs(x) <= half_x + 1e-9 and abs(y) <= half_y + 1e-9]
    touch_id = min(inside, key=v.__getitem__)

    # Step voltage: rank raster points by their largest 1 m axis difference, then search
    # 16 directions around the strongest candidates (the worst step is usually diagonal at a corner).
    k = max(1, round(STEP_DISTANCE_M / spacing))
    def axis_step(pid: str) -> float:
        i, j = map(int, pid[1:].split("_"))
        return max((abs(v[pid] - v[f"s{i + di}_{j + dj}"]) for di, dj in ((k, 0), (0, k), (-k, 0), (0, -k))
                    if f"s{i + di}_{j + dj}" in v), default=0.0)
    candidates = sorted(raster, key=axis_step, reverse=True)[:STEP_CANDIDATES]
    probes = {}
    for c, pid in enumerate(candidates):
        x, y, _ = raster[pid]
        for d in range(STEP_DIRECTIONS):
            angle = 2 * pi * d / STEP_DIRECTIONS
            probes[f"p{c}_{d}"] = (x + STEP_DISTANCE_M * cos(angle), y + STEP_DISTANCE_M * sin(angle), 0.0)
    _, probe_v, probe_hashes = _solve(client, rho, segments, current,
                                      [PotentialPoint(pid, xyz) for pid, xyz in probes.items()], origin)
    step_value, step_from, step_to = 0.0, None, None
    for c, pid in enumerate(candidates):
        for d in range(STEP_DIRECTIONS):
            difference = abs(v[pid] - probe_v[f"p{c}_{d}"])
            if difference > step_value:
                step_value, step_from, step_to = difference, raster[pid][:2], probes[f"p{c}_{d}"][:2]

    group = first["groups"][GROUP]
    result = {
        "soil_resistivity_ohm_m": rho,
        "injected_current_a": current,
        "grid_resistance_ohm": group["resistance_to_remote_earth_ohm"],
        "gpr_v": gpr,
        "max_touch_v": {"value": gpr - v[touch_id], "x_m": raster[touch_id][0], "y_m": raster[touch_id][1]},
        "max_step_v": {"value": step_value, "from_m": step_from, "to_m": step_to},
        "segment_count": len(segments),
        "surface_point_count": len(raster) + len(probes),
        "diagnostics": first["diagnostics"],
        "engine_warnings": first["warnings"],
        "model_warnings": MODEL_WARNINGS if fault_breakdown is None else MODEL_WARNINGS[1:],
        "fault_current": fault_breakdown,
    }
    result["safety"] = _safety(result, fault, rho, parameters)
    trace = {**first["trace"], "parameters": parameters, "request_sha256_batches": hashes + probe_hashes,
             "fault_current": fault_breakdown}
    return {"result": result, "trace": trace}


def _safety(result: dict[str, Any], fault: dict[str, Any], rho: float, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Normative decision, kept apart from the field result it reads."""
    exposure = safety_criteria.FaultExposure(
        clearing_time_s=float(fault["clearing_time_s"]),
        body_weight_kg=float(fault.get("body_weight_kg", 50)),
        surface_resistivity_ohm_m=float(fault.get("surface_resistivity_ohm_m", 3000)),
        surface_thickness_m=float(fault.get("surface_thickness_m", 0.1)),
        soil_resistivity_ohm_m=rho,
    )
    field = {"touch_v": result["max_touch_v"]["value"], "step_v": result["max_step_v"]["value"], "gpr_v": result["gpr_v"]}
    standards = parameters.get("safety_standards") or [safety_criteria.IEEE80_2013]
    return safety_criteria.evaluate(field, exposure, standards)


def run_potential_calculation(store, calculation_id: str, client: PotentialEngineClient | None = None) -> None:
    """Worker body: idempotent, honours cancellation, and never leaves an unexplained terminal state."""
    now = int(time())
    with store.transaction(write=True) as db:
        calculation = db.one("calculos_potencial_tierras", id=calculation_id)
        if not calculation:
            return
        stale = calculation["status"] == "running" and now - calculation["updated_at"] > STALE_RUNNING_S
        if calculation["status"] != "pending" and not stale:
            return
        artifact = db.one("artefacto_diseno_tierras", project_id=calculation["project_id"],
                          artifact_id=calculation["artifact_id"], version=calculation["artifact_version"])
        db.change("calculos_potencial_tierras", calculation_id, status="running", updated_at=now)

    outcome: dict[str, Any] = {}
    try:
        if not artifact:
            raise UnsupportedModelError("La versión del artefacto ya no existe.")
        computed = calculate(artifact["snapshot"], calculation["parameters"], client or PotentialEngineClient())
        outcome = {"status": "completed", "result": computed["result"], "trace": computed["trace"], "error": None}
    except (UnsupportedModelError, ValueError) as exc:
        outcome = {"status": "rejected", "error": str(exc)}
    except PotentialEngineError as exc:
        outcome = {"status": "failed", "error": f"Error del motor de potencial: {exc}"}
    except Exception:
        outcome = {"status": "failed", "error": "Error inesperado durante el cálculo; revise los registros del worker."}
        raise
    finally:
        with store.transaction(write=True) as db:
            current = db.one("calculos_potencial_tierras", id=calculation_id)
            if current and current["status"] == "running" and outcome:
                db.change("calculos_potencial_tierras", calculation_id, updated_at=int(time()), **outcome)
