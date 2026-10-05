"""Potential-engine calculation for one version of a grounding design artifact."""

from __future__ import annotations

from math import cos, log2, pi, sin
from time import monotonic, time
from typing import Any

from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.fault_current import ReturnPath, grid_current
from src.infrastructure.calculations.potential_engine_client import (
    MAX_LAYERS,
    MAX_SEGMENTS,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    SoilModel,
    TwoLayerSoil,
    interface_depths,
    point_batch_size,
    rectangular_grid_segments,
    soil_record,
)

GROUP = "grid"
INJECTION_ORIGIN = "artifact:fault.current_a"
STEP_DISTANCE_M = 1.0
SURFACE_MARGIN_M = 3.0
STEP_CANDIDATES = 20
STEP_DIRECTIONS = 16
# Graded segments reach the converged corner step of IEEE 80 Annex H Grids 1-3 with 40-55 % fewer
# segments than uniform 1 m pieces, and closer to it (validation/segmentation_study.py).
DEFAULT_SEGMENTATION = "graded"
GCI_SAFETY_FACTOR = 1.25
# A calculation left "running" longer than this is assumed lost (worker crash) and may run again.
STALE_RUNNING_S = 900
MODEL_WARNINGS = [
    "La corriente de falla del artefacto se inyecta completa en la malla, sin factor de división (P1 del backlog).",
    "El contacto máximo se busca solo dentro del perímetro de la malla; cercas y estructuras externas no se modelan.",
    "La capa superficial solo modifica las tensiones tolerables (factor Cs); el campo eléctrico del motor no la modela.",
]


class UnsupportedModelError(ValueError):
    """The artifact needs a model the engine does not solve; the calculation is rejected."""


def soil_model(soil_layers: list[dict[str, Any]]) -> SoilModel:
    """Engine soil model from the artifact's layers (top to bottom, `depth_m` = layer thickness).

    Every layer but the last needs a positive thickness; the last is a half-space (`depth_m` null).
    Adjacent layers with exactly the same resistivity are one physical layer and are merged, adding
    their thicknesses (layers with different resistivity are never merged, however close). One
    resulting layer is homogeneous soil; two are a two-layer soil (image series of the engine, as
    before); 3 to 8 are an n-layer stack solved with the engine's n-layer kernel.
    """
    if not 1 <= len(soil_layers) <= MAX_LAYERS:
        raise UnsupportedModelError(f"El suelo debe tener entre 1 y {MAX_LAYERS} capas; el artefacto tiene {len(soil_layers)}.")
    merged: list[list[Any]] = []
    for index, layer in enumerate(soil_layers):
        rho, thickness = float(layer["resistivity_ohm_m"]), layer.get("depth_m")
        last = index == len(soil_layers) - 1
        if last and thickness is not None:
            raise UnsupportedModelError("La última capa del suelo es un semiespacio: su espesor (depth_m) debe ser nulo.")
        if not last and thickness is None:
            if len(soil_layers) == 2:
                raise UnsupportedModelError("La capa superior del suelo de dos capas necesita su espesor (depth_m).")
            raise UnsupportedModelError(f"La capa {index + 1} del suelo necesita su espesor (depth_m).")
        if merged and merged[-1][0] == rho:
            merged[-1][1] = None if thickness is None else merged[-1][1] + float(thickness)
        else:
            merged.append([rho, None if thickness is None else float(thickness)])
    try:
        if len(merged) == 1:
            return HomogeneousSoil(merged[0][0])
        if len(merged) == 2:
            return TwoLayerSoil(merged[0][0], merged[1][0], merged[0][1])
        return LayerStackSoil(tuple((rho, thickness) for rho, thickness in merged))
    except ValueError as exc:
        raise UnsupportedModelError(f"Modelo de suelo fuera del rango del motor: {exc}.") from exc


def top_resistivity(soil: SoilModel) -> float:
    """Resistivity of the soil directly beneath the surface layer."""
    if isinstance(soil, HomogeneousSoil):
        return soil.resistivity_ohm_m
    if isinstance(soil, TwoLayerSoil):
        return soil.upper_resistivity_ohm_m
    return float(soil.layers[0][0])


def _fault_current(fault, parameters, client, soil, segments) -> tuple[float, str, dict[str, Any] | None]:
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
        unit = client.calculate(soil=soil, segments=segments, injections_a={GROUP: 1.0},
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


def _solve(client, soil, segments, current, points, origin=INJECTION_ORIGIN):
    """Solve once per batch of surface points; every batch shares the same electrode solution."""
    batch = point_batch_size(soil, segments, points)
    potentials: dict[str, float] = {}
    first, hashes = None, []
    for start in range(0, max(len(points), 1), batch):
        result = client.calculate(
            soil=soil, segments=segments, injections_a={GROUP: current},
            points=points[start:start + batch], injection_origins={GROUP: origin},
        )
        potentials.update(result["potentials_v"])
        hashes.append(result["trace"]["request_sha256"])
        first = first or result
    return first, potentials, hashes


def _segments(geometry: dict[str, Any], parameters: dict[str, Any], soil: SoilModel, scale: float = 1.0):
    step = float(parameters["discretization_m"]) * scale
    return rectangular_grid_segments(
        length_m=geometry["length_m"], width_m=geometry["width_m"],
        conductor_spacing_m=geometry["conductor_spacing_m"], burial_depth_m=geometry["burial_depth_m"],
        conductor_radius_m=parameters["conductor_radius_m"], group=GROUP,
        rods_count=geometry.get("rods_count", 0), rod_length_m=geometry.get("rod_length_m", 2.4),
        discretization_m=step,
        interface_depths_m=interface_depths(soil),
        segmentation=parameters.get("segmentation", DEFAULT_SEGMENTATION),
    )


def calculate(snapshot: dict[str, Any], parameters: dict[str, Any], client: PotentialEngineClient) -> dict[str, Any]:
    """Return `{"result": ..., "trace": ...}` for an artifact snapshot and calculation parameters."""
    geometry, fault = snapshot["geometry"], snapshot["fault"]
    soil = soil_model(snapshot["soil_layers"])
    segments = _segments(geometry, parameters, soil)
    if len(segments) > MAX_SEGMENTS:
        raise UnsupportedModelError(
            f"La malla necesita {len(segments)} segmentos con discretización de "
            f"{float(parameters['discretization_m']):g} m y el límite es {MAX_SEGMENTS}. Una discretización "
            "mayor reduce la precisión de las tensiones de paso."
        )
    current, origin, fault_breakdown = _fault_current(fault, parameters, client, soil, segments)
    field = _field(client, geometry, soil, segments, current, origin, float(parameters["surface_spacing_m"]))
    first, group = field["first"], field["first"]["groups"][GROUP]
    result = {
        "soil": soil_record(soil),
        "injected_current_a": current,
        "grid_resistance_ohm": group["resistance_to_remote_earth_ohm"],
        "gpr_v": field["gpr_v"],
        "max_touch_v": field["max_touch_v"],
        "max_step_v": field["max_step_v"],
        "segment_count": len(segments),
        "segmentation": parameters.get("segmentation", DEFAULT_SEGMENTATION),
        "surface_point_count": field["point_count"],
        "diagnostics": first["diagnostics"],
        "engine_warnings": first["warnings"],
        "model_warnings": MODEL_WARNINGS if fault_breakdown is None else MODEL_WARNINGS[1:],
        "fault_current": fault_breakdown,
    }
    hashes = field["hashes"]
    if parameters.get("estimate_uncertainty"):
        result["numerical_uncertainty"], extra = _uncertainty(client, geometry, parameters, soil, current, origin, field)
        hashes = hashes + extra
    # IEEE 80 Cs uses the resistivity of the soil directly beneath the surface layer.
    result["safety"] = _safety(result, fault, top_resistivity(soil), parameters)
    trace = {**first["trace"], "parameters": parameters, "request_sha256_batches": hashes,
             "fault_current": fault_breakdown, "numerical_uncertainty": result.get("numerical_uncertainty")}
    return {"result": result, "trace": trace}


def _uncertainty(client, geometry, parameters, soil, current, origin, finest):
    """Discretisation error of R, GPR, worst touch and worst step from the requested run and two coarser ones.

    Levels use 4d, 2d and d (the reported run), so the estimate never needs more segments or image
    evaluations than the requested calculation. With differences e1 = f(2d) - f(4d) and
    e2 = f(d) - f(2d) of the same sign and shrinking, the observed order is p = log2(e1/e2) and,
    for 0.5 <= p <= 4, the error estimate of f(d) is the grid convergence index
    1.25·|e2| / (2^p - 1) (Richardson extrapolation with Roache's safety factor for three grids,
    P. J. Roache, J. Fluids Eng. 116, 1994); otherwise the conservative bound |e2| is reported.
    The same injected current is used at every level.
    """
    started = monotonic()
    levels, hashes = [], []
    try:
        for scale in (4.0, 2.0):
            segments = _segments(geometry, parameters, soil, scale)
            run = _field(client, geometry, soil, segments, current, origin, float(parameters["surface_spacing_m"]))
            levels.append((scale, len(segments), run))
            hashes += run["hashes"]
    except (ValueError, PotentialEngineError) as exc:
        return {"status": "no estimable", "reason": str(exc)}, hashes
    levels.append((1.0, None, finest))

    def value(run: dict[str, Any], quantity: str) -> float:
        if quantity == "grid_resistance_ohm":
            return run["first"]["groups"][GROUP]["resistance_to_remote_earth_ohm"]
        if quantity == "gpr_v":
            return run["gpr_v"]
        return run[quantity]["value"]

    quantities = {}
    for quantity in ("grid_resistance_ohm", "gpr_v", "max_touch_v", "max_step_v"):
        coarse, middle, fine = (value(run, quantity) for _, _, run in levels)
        e1, e2 = middle - coarse, fine - middle
        estimate, method, order = abs(e2), "diferencia-entre-refinamientos", None
        if e2 == 0.0:
            estimate, method = 0.0, "sin-cambio-entre-refinamientos"
        elif e1 * e2 > 0 and abs(e2) < abs(e1):
            observed = log2(e1 / e2)
            if 0.5 <= observed <= 4.0:
                estimate, method, order = GCI_SAFETY_FACTOR * abs(e2) / (2 ** observed - 1), "richardson-gci", observed
        quantities[quantity] = {
            "value": fine, "error_estimate": estimate,
            "relative_error_estimate": estimate / abs(fine) if fine else None,
            "method": method, "observed_order": order, "levels": [coarse, middle, fine],
        }
    return {
        "status": "estimado",
        "discretizations_m": [float(parameters["discretization_m"]) * scale for scale, _, _ in levels],
        "segment_counts": [count for _, count, _ in levels[:2]] + [None],
        "extra_seconds": round(monotonic() - started, 3),
        "quantities": quantities,
    }, hashes


def _field(client, geometry, soil, segments, current, origin, spacing) -> dict[str, Any]:
    """Surface search for GPR, the worst touch inside the grid and the worst 1 m step."""
    half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
    nx = round(2 * (half_x + SURFACE_MARGIN_M) / spacing)
    ny = round(2 * (half_y + SURFACE_MARGIN_M) / spacing)
    raster = {
        f"s{i}_{j}": (-half_x - SURFACE_MARGIN_M + i * spacing, -half_y - SURFACE_MARGIN_M + j * spacing, 0.0)
        for i in range(nx + 1) for j in range(ny + 1)
    }
    first, v, hashes = _solve(client, soil, segments, current,
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
    _, probe_v, probe_hashes = _solve(client, soil, segments, current,
                                      [PotentialPoint(pid, xyz) for pid, xyz in probes.items()], origin)
    step_value, step_from, step_to = 0.0, None, None
    for c, pid in enumerate(candidates):
        for d in range(STEP_DIRECTIONS):
            difference = abs(v[pid] - probe_v[f"p{c}_{d}"])
            if difference > step_value:
                step_value, step_from, step_to = difference, raster[pid][:2], probes[f"p{c}_{d}"][:2]
    return {
        "first": first,
        "gpr_v": gpr,
        "max_touch_v": {"value": gpr - v[touch_id], "x_m": raster[touch_id][0], "y_m": raster[touch_id][1]},
        "max_step_v": {"value": step_value, "from_m": step_from, "to_m": step_to},
        "point_count": len(raster) + len(probes),
        "hashes": hashes + probe_hashes,
    }


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
