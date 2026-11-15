"""Potential-engine calculation for one version of a grounding design artifact."""

from __future__ import annotations

import hashlib
import json
from math import atan2, cos, hypot, isfinite, log2, pi, sin
from time import monotonic, time
from typing import Any

from src.domain.spat import grid_geometry
from src.domain.spat.artifact_contract import validate_document
from src.domain.spat.input_coherence import coherence_warnings, resistance_plausibility
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.conductor_thermal import equivalent_radius_m
from src.infrastructure.calculations.conductor_thermal_profiles import calculate_conductor_thermal
from src.infrastructure.calculations.fault_current import ReturnPath, grid_current
from src.infrastructure.calculations.potential_engine_client import (
    MAX_POINTS,
    MAX_SCENARIO_RESULT_ROWS,
    MAX_LAYERS,
    MAX_SEGMENTS,
    MAX_COORDINATE_M,
    ElectricalConnection,
    ElectrodeSegment,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    PROTOCOL,
    SoilModel,
    TwoLayerSoil,
    interface_depths,
    network_segments,
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
TOUCH_REFINE_CANDIDATES = 5
STEP_REFINE_CANDIDATES = 5
LOCAL_REFINE_DIVISIONS = 4
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
    spacing_x, spacing_y = grid_geometry.spacings(geometry)
    if grid_geometry.is_explicit(geometry) or spacing_x != spacing_y:
        # Drawn conductors, explicit rods or a different spacing per axis: general network,
        # centred on the outline like the regular mesh.
        half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
        rods = grid_geometry.rod_points(geometry)
        pieces = grid_geometry.split_lines(grid_geometry.conductor_lines(geometry), [(x, y) for x, y, _ in rods])
        return network_segments(
            lines=[((a[0] - half_x, a[1] - half_y), (b[0] - half_x, b[1] - half_y)) for a, b in pieces],
            rods=[(x - half_x, y - half_y, length) for x, y, length in rods],
            burial_depth_m=geometry["burial_depth_m"], conductor_radius_m=parameters["conductor_radius_m"],
            group=GROUP, discretization_m=step, interface_depths_m=interface_depths(soil),
            segmentation=parameters.get("segmentation", DEFAULT_SEGMENTATION),
        )
    return rectangular_grid_segments(
        length_m=geometry["length_m"], width_m=geometry["width_m"],
        conductor_spacing_m=spacing_x, burial_depth_m=geometry["burial_depth_m"],
        conductor_radius_m=parameters["conductor_radius_m"], group=GROUP,
        rods_count=geometry.get("rods_count", 0), rod_length_m=geometry.get("rod_length_m", 2.4),
        discretization_m=step,
        interface_depths_m=interface_depths(soil),
        segmentation=parameters.get("segmentation", DEFAULT_SEGMENTATION),
    )


def calculate(snapshot: dict[str, Any], parameters: dict[str, Any], client: PotentialEngineClient) -> dict[str, Any]:
    """Return `{"result": ..., "trace": ...}` for an artifact snapshot and calculation parameters."""
    if snapshot.get("schema_version") == "2.0":
        return _calculate_v2(snapshot, parameters, client)
    if parameters.get("scenarios"):
        raise UnsupportedModelError("Los escenarios de inyección requieren un artefacto 2.0 con redes y electrodos identificados.")
    missing = grid_geometry.missing_for_calculation(snapshot)
    if missing:
        raise UnsupportedModelError("El artefacto está incompleto para calcular; faltan: " + ", ".join(missing))
    geometry, fault = snapshot["geometry"], snapshot["fault"]
    conductor = snapshot.get("conductor")
    effective_parameters = parameters
    if conductor:
        # One section controls both the thermal check and the equivalent radius used by the field solver.
        effective_parameters = {**parameters, "conductor_radius_m": equivalent_radius_m(float(conductor["cross_section_mm2"]))}
    soil = soil_model(snapshot["soil_layers"])
    segments = _segments(geometry, effective_parameters, soil)
    if len(segments) > MAX_SEGMENTS:
        raise UnsupportedModelError(
            f"La malla necesita {len(segments)} segmentos con discretización de "
            f"{float(effective_parameters['discretization_m']):g} m y el límite es {MAX_SEGMENTS}. Una discretización "
            "mayor reduce la precisión de las tensiones de paso."
        )
    current, origin, fault_breakdown = _fault_current(fault, effective_parameters, client, soil, segments)
    field = _field(client, geometry, soil, segments, current, origin, float(effective_parameters["surface_spacing_m"]),
                   float(effective_parameters.get("touch_reach_m") or 0.0))
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
        "surface_potential": field["surface_potential"],
        "diagnostics": first["diagnostics"],
        "engine_warnings": first["warnings"],
        "model_warnings": MODEL_WARNINGS if fault_breakdown is None else MODEL_WARNINGS[1:],
        "fault_current": fault_breakdown,
    }
    thermal_input = conductor or {
        "material_id": "copper_hard_drawn",
        "cross_section_mm2": pi * (float(parameters["conductor_radius_m"]) * 1000.0) ** 2,
        "joint_type": "unspecified-legacy",
        "maximum_temperature_c": 250.0,
        "thermal_duration_s": float(fault["clearing_time_s"]),
        "ambient_temperature_c": 40.0,
    }
    result["conductor_thermal"] = calculate_conductor_thermal(thermal_input, current)
    # Advisories about the conductor standard travel with the other model warnings: the study page, the agent
    # summary and the chat panel already show them.
    # BL-15 / EG-21: unusual inputs and an implausible resistance are reported, never repaired.
    plausibility = resistance_plausibility(geometry, snapshot["soil_layers"], result["grid_resistance_ohm"])
    result["model_warnings"] = [*result["model_warnings"],
                                *(f"Conductor ({result['conductor_thermal']['profile']}): {warning}"
                                  for warning in result["conductor_thermal"]["warnings"]),
                                *(f"Entrada ({d['path']}): {d['message']}" for d in coherence_warnings(snapshot)),
                                *([f"Verosimilitud: {plausibility['message']}"] if plausibility else [])]
    hashes = field["hashes"]
    if parameters.get("estimate_uncertainty"):
        result["numerical_uncertainty"], extra = _uncertainty(client, geometry, effective_parameters, soil, current, origin, field)
        hashes = hashes + extra
    # IEEE 80 Cs uses the resistivity of the soil directly beneath the surface layer.
    result["safety"] = _safety(result, fault, top_resistivity(soil), effective_parameters)
    trace = {**first["trace"], "schema_version": "1.0", "parameters": effective_parameters,
             "request_sha256_batches": hashes,
             "fault_current": fault_breakdown, "numerical_uncertainty": result.get("numerical_uncertainty")}
    trace["conductor_thermal"] = result["conductor_thermal"]
    result["schema_version"] = "1.0"
    validate_document("calculation_result", result)
    validate_document("calculation_trace", trace)
    return {"result": result, "trace": trace}


def _calculate_v2(snapshot: dict[str, Any], parameters: dict[str, Any], client: PotentialEngineClient) -> dict[str, Any]:
    """Evaluate each v2 network/electrode independently and group those records by building.

    V2 describes associations, but not yet electrical connections or current division between
    entities. Each record is therefore a single-entity evaluation using the stated injection;
    fault split models that require a combined grounding system are rejected explicitly.
    """
    missing = grid_geometry.missing_for_calculation(snapshot)
    if missing:
        raise UnsupportedModelError("El artefacto 2.0 está incompleto para calcular; faltan: " + ", ".join(missing))
    scenarios = parameters.get("scenarios") or []
    if (parameters.get("transfer_exposures") or parameters.get("transfer_assessment_complete") is True) and not scenarios:
        raise UnsupportedModelError("La evaluación de tensión transferida requiere escenarios 2.0 nombrados.")
    if scenarios:
        if parameters.get("fault_split") or parameters.get("x_over_r") is not None:
            raise UnsupportedModelError(
                "Los escenarios reciben corrientes firmadas ya calculadas; SV-11 no aplica automáticamente "
                "fault_split ni el factor de decremento X/R."
            )
        return _calculate_v2_scenarios(snapshot, parameters, client, scenarios)
    if snapshot.get("connections"):
        raise UnsupportedModelError("El artefacto declara conexiones eléctricas; envíe escenarios con inyecciones para calcularlas.")
    if parameters.get("fault_split") or parameters.get("x_over_r") is not None:
        raise UnsupportedModelError(
            "El cálculo 2.0 requiere escenarios de corriente explícitos para repartir la falla entre entidades; "
            "agregue `scenarios` a los parámetros de cálculo."
        )
    from src.domain.spat.artifact_contract import group_results_by_building
    from src.infrastructure.calculations.solver_evaluation import evaluate

    soil = soil_model(snapshot["soil_layers"])
    fault = snapshot["fault"]
    current = float(fault["current_a"])
    settings = {
        key: parameters[key]
        for key in ("conductor_radius_m", "discretization_m", "surface_spacing_m", "segmentation", "touch_reach_m")
        if key in parameters
    }
    conductor = snapshot.get("conductor")
    if conductor:
        settings["conductor_radius_m"] = equivalent_radius_m(float(conductor["cross_section_mm2"]))
    records: dict[str, dict[str, Any]] = {"networks": {}, "electrodes": {}}
    evaluation_trace = []
    for kind in ("networks", "electrodes"):
        for entity in sorted(snapshot.get(kind, []), key=lambda item: item["id"]):
            outcome = evaluate(
                geometry=entity["geometry"], soil=soil, injection_a=current, points=[],
                client=client, settings=settings,
            )
            record = {"id": entity["id"], "name": entity["name"], "evaluation": outcome}
            records[kind][entity["id"]] = record
            evaluation_trace.append({
                "kind": kind[:-1], "id": entity["id"], "input_sha256": outcome["input_sha256"],
                "solver_version": outcome["solver_version"],
            })
    buildings = group_results_by_building(snapshot, records["networks"], records["electrodes"])
    canonical_inputs = {
        "schema_version": "2.0",
        "buildings": sorted(snapshot.get("buildings", []), key=lambda item: item["id"]),
        "networks": sorted(snapshot.get("networks", []), key=lambda item: item["id"]),
        "electrodes": sorted(snapshot.get("electrodes", []), key=lambda item: item["id"]),
        "soil": soil_record(soil), "fault": fault, "settings": settings,
    }
    input_sha256 = hashlib.sha256(json.dumps(
        canonical_inputs, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    result = {
        "schema_version": "2.0", "soil": soil_record(soil), "injected_current_a": current,
        "networks": records["networks"], "electrodes": records["electrodes"], "buildings": buildings,
        "warnings": [
            "Cada red y electrodo se evalúa como entidad aislada con la corriente indicada; no se modelan conexiones ni reparto entre entidades.",
            "El resultado numérico de cada entidad es aproximado por la búsqueda finita de máximos de SV-08.",
        ],
    }
    trace = {
        "schema_version": "2.0", "input_sha256": input_sha256,
        "solver_protocol": PROTOCOL, "parameters": parameters,
        "evaluations": evaluation_trace,
    }
    validate_document("calculation_result_v2", result)
    validate_document("calculation_trace_v2", trace)
    return {"result": result, "trace": trace}


def _calculate_v2_scenarios(snapshot, parameters, client, scenario_requests):
    """Solve all artifact entities jointly for named signed-current scenarios."""
    from src.domain.spat.artifact_contract import group_results_by_building

    soil = soil_model(snapshot["soil_layers"])
    settings = {
        "conductor_radius_m": 0.00525,
        "discretization_m": 1.0,
        "surface_spacing_m": 0.5,
        "segmentation": DEFAULT_SEGMENTATION,
        "touch_reach_m": 0.0,
        **{key: parameters[key] for key in (
            "conductor_radius_m", "discretization_m", "surface_spacing_m", "segmentation", "touch_reach_m"
        ) if key in parameters},
    }
    if snapshot.get("conductor"):
        settings["conductor_radius_m"] = equivalent_radius_m(float(snapshot["conductor"]["cross_section_mm2"]))
    entities = []
    segments: list[ElectrodeSegment] = []
    entity_group: dict[str, str] = {}
    entity_kind: dict[str, str] = {}
    for collection, prefix in (("networks", "n"), ("electrodes", "e")):
        for index, entity in enumerate(sorted(snapshot.get(collection, []), key=lambda item: item["id"])):
            entity_id = entity["id"]
            if entity_id in entity_group:
                raise UnsupportedModelError(f"Id de entidad duplicado entre redes y electrodos: {entity_id}")
            group = f"{prefix}{index}"
            entity_group[entity_id] = group
            entity_kind[entity_id] = collection
            entities.append(entity)
            generated = _segments(entity["geometry"], settings, soil)
            for part, segment in enumerate(generated):
                segments.append(ElectrodeSegment(
                    f"{group}.s{part}", group, segment.kind,
                    segment.start_m, segment.end_m, segment.radius_m,
                ))
    if not segments:
        raise UnsupportedModelError("El artefacto 2.0 necesita al menos una red o electrodo para resolver escenarios.")
    if len(segments) > MAX_SEGMENTS:
        raise UnsupportedModelError(f"La geometría conjunta necesita {len(segments)} segmentos; el límite es {MAX_SEGMENTS}.")

    connection_ids = set()
    engine_connections = []
    engine_connection_to_id = {}
    for index, connection in enumerate(snapshot.get("connections", [])):
        if connection["id"] in connection_ids:
            raise UnsupportedModelError(f"Id de conexión duplicado: {connection['id']}")
        connection_ids.add(connection["id"])
        group_a = entity_group.get(connection["group_a"])
        group_b = entity_group.get(connection["group_b"])
        if group_a is None or group_b is None:
            raise UnsupportedModelError(f"La conexión {connection['id']} referencia una entidad desconocida.")
        if group_a == group_b:
            raise UnsupportedModelError(f"La conexión {connection['id']} debe enlazar dos entidades distintas.")
        engine_id = f"c{index}"
        engine_connection_to_id[engine_id] = connection["id"]
        engine_connections.append(ElectricalConnection(
            engine_id, connection["kind"], group_a, group_b, connection.get("resistance_ohm"),
        ))

    if not 1 <= len(scenario_requests) <= 100:
        raise UnsupportedModelError("La solicitud debe incluir entre 1 y 100 escenarios nombrados.")
    transfer_pair_count = len(entities) * (len(entities) - 1) // 2
    if transfer_pair_count * len(scenario_requests) > 100_000:
        raise UnsupportedModelError("La tabla de potenciales transferidos supera 100 000 pares; reduzca entidades o escenarios.")
    scenarios = {}
    scenario_origins = {}
    scenario_injected_entities = {}
    for scenario in scenario_requests:
        scenario_id = scenario["id"]
        if scenario_id in scenarios:
            raise UnsupportedModelError(f"Id de escenario duplicado: {scenario_id}")
        injections = scenario.get("injections_a") or {}
        if not injections:
            raise UnsupportedModelError(f"El escenario {scenario_id} necesita al menos una inyección.")
        mapped = {}
        for entity_id, current in injections.items():
            group = entity_group.get(entity_id)
            if group is None:
                raise UnsupportedModelError(f"El escenario {scenario_id} inyecta en una entidad desconocida: {entity_id}.")
            mapped[group] = float(current)
        scenarios[scenario_id] = mapped
        scenario_origins[scenario_id] = {group: f"artifact:scenario.{scenario_id}" for group in mapped}
        scenario_injected_entities[scenario_id] = {
            entity_id for entity_id, current in injections.items() if float(current) != 0.0
        }

    transfer_exposures = parameters.get("transfer_exposures") or []
    if transfer_exposures and not parameters.get("scenarios"):
        raise UnsupportedModelError("Las exposiciones transferidas requieren escenarios 2.0 nombrados.")
    if len({item.get("id") for item in transfer_exposures}) != len(transfer_exposures):
        raise UnsupportedModelError("Los ids de exposiciones transferidas deben ser únicos.")

    # A transfer exposure is evaluated only when the accessible metal entity is
    # explicitly connected to an injected entity in this scenario.
    adjacency = {entity_id: set() for entity_id in entity_group}
    for connection in snapshot.get("connections", []):
        a, b = connection.get("group_a"), connection.get("group_b")
        if a in adjacency and b in adjacency:
            adjacency[a].add(b)
            adjacency[b].add(a)

    transfer_rows_by_scenario: dict[str, list[dict[str, Any]]] = {key: [] for key in scenarios}
    transfer_point_by_id: dict[str, str] = {}
    transfer_points: list[PotentialPoint] = []
    for exposure in transfer_exposures:
        exposure_id = exposure.get("id")
        scenario_id = exposure.get("scenario_id")
        metal_entity_id = exposure.get("metal_entity_id")
        if scenario_id not in scenarios:
            raise UnsupportedModelError(f"La exposición transferida {exposure_id} referencia un escenario desconocido.")
        if metal_entity_id not in entity_group:
            raise UnsupportedModelError(f"La exposición transferida {exposure_id} referencia una entidad desconocida.")
        row = {
            "id": exposure_id,
            "scenario_id": scenario_id,
            "metal_entity_id": metal_entity_id,
            "contact_surface_xyz_m": list(exposure.get("contact_surface_xyz_m") or []),
            "accessibility": exposure.get("accessibility"),
            "evidence": exposure.get("evidence"),
            "exposure_class": exposure.get("exposure_class"),
            "surface_layer_present": exposure.get("surface_layer_present"),
            "surface_resistivity_ohm_m": exposure.get("surface_resistivity_ohm_m"),
            "surface_thickness_m": exposure.get("surface_thickness_m"),
            "clearing_time_s": exposure.get("clearing_time_s"),
            "status": "no_evaluable",
        }
        transfer_rows_by_scenario[scenario_id].append(row)
        if exposure.get("accessibility") == "not_accessible":
            row.update(status="not_applicable", reason="El inventario declara que el elemento no es accesible.")
            continue
        if exposure.get("accessibility") != "confirmed" or not (exposure.get("evidence") or "").strip():
            row["reason"] = "La accesibilidad y su evidencia deben estar confirmadas para evaluar la exposición."
            continue
        xyz = row["contact_surface_xyz_m"]
        if len(xyz) != 3 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) for value in xyz):
            row["reason"] = "El punto de contacto debe tener tres coordenadas finitas."
            continue
        if abs(xyz[0]) > MAX_COORDINATE_M or abs(xyz[1]) > MAX_COORDINATE_M:
            row["reason"] = "El punto de contacto excede el dominio espacial admitido por el solver."
            continue
        reached = set(scenario_injected_entities[scenario_id])
        frontier = list(reached)
        while frontier:
            current_entity = frontier.pop()
            for neighbor in adjacency[current_entity] - reached:
                reached.add(neighbor)
                frontier.append(neighbor)
        if metal_entity_id not in reached:
            row["reason"] = "La entidad metálica no tiene un camino eléctrico explícito desde una entidad inyectada en este escenario."
            continue
        point_id = "transfer_" + hashlib.sha256(str(exposure_id).encode("utf-8")).hexdigest()[:20]
        transfer_point_by_id[exposure_id] = point_id
        transfer_points.append(PotentialPoint(point_id, (float(xyz[0]), float(xyz[1]), 0.0)))
        row["status"] = "pending_solver"

    spacing = float(settings["surface_spacing_m"])
    site_length = max(float(entity["geometry"]["length_m"]) for entity in entities)
    site_width = max(float(entity["geometry"]["width_m"]) for entity in entities)
    margin = SURFACE_MARGIN_M + float(settings["touch_reach_m"])
    half_x, half_y = site_length / 2, site_width / 2
    nx = round(2 * (half_x + margin) / spacing)
    ny = round(2 * (half_y + margin) / spacing)
    if (nx + 1) * (ny + 1) > 1_000_000:
        raise UnsupportedModelError("La rasterización conjunta supera 1 000 000 puntos; aumente surface_spacing_m.")
    raster: dict[tuple[int, int], tuple[str, tuple[float, float, float]]] = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            point_id = f"p{i}_{j}"
            xyz = (-half_x - margin + i * spacing,
                   -half_y - margin + j * spacing, 0.0)
            raster[(i, j)] = (point_id, xyz)
    points = [PotentialPoint(point_id, xyz) for point_id, xyz in raster.values()]
    max_rows_per_scenario = MAX_SCENARIO_RESULT_ROWS // len(scenarios)
    result_overhead = len(segments) + len(entity_group) + len(engine_connections) + 128
    if max_rows_per_scenario <= result_overhead:
        raise UnsupportedModelError("La cantidad de entidades supera el límite de salida de los escenarios.")
    row_batch = max_rows_per_scenario - result_overhead
    batch = min(point_batch_size(soil, segments, points), MAX_POINTS, row_batch)
    batch = max(batch, 1)

    outcome_by_scenario = {scenario_id: {"potentials": {}, "first": None, "hashes": []}
                           for scenario_id in scenarios}
    for start in range(0, max(len(points), 1), batch):
        chunk = points[start:start + batch]
        solved = client.calculate_scenarios(
            soil=soil, segments=segments, points=chunk, scenarios=scenarios,
            injection_origins=scenario_origins, connections=engine_connections,
        )
        for scenario_id, result in solved.items():
            target = outcome_by_scenario[scenario_id]
            target["potentials"].update(result["potentials_v"])
            target["first"] = target["first"] or result
            target["hashes"].append(result["trace"]["request_sha256"])

    obstacles = []
    entity_boxes = {}
    for entity in entities:
        geometry = entity["geometry"]
        entity_half_x, entity_half_y = float(geometry["length_m"]) / 2, float(geometry["width_m"]) / 2
        fx0, fx1, fy0, fy1 = grid_geometry.footprint(geometry)
        reach = float(settings["touch_reach_m"])
        entity_boxes[entity["id"]] = (fx0 - entity_half_x - reach, fx1 - entity_half_x + reach,
                                      fy0 - entity_half_y - reach, fy1 - entity_half_y + reach)
        for _, rect, _ in grid_geometry.obstacles(geometry):
            cx, cy = float(rect["x"]) - entity_half_x, float(rect["y"]) - entity_half_y
            obstacles.append((cx - float(rect["width"]) / 2, cx + float(rect["width"]) / 2,
                              cy - float(rect["height"]) / 2, cy + float(rect["height"]) / 2))

    def accessible(x, y):
        return not any(x0 < x < x1 and y0 < y < y1 for x0, x1, y0, y1 in obstacles)

    # Sample each declared local soil-contact point exactly. The existing surface
    # raster is only for extrema and must not be reused as an approximate transfer endpoint.
    eligible_transfer_points = []
    for rows in transfer_rows_by_scenario.values():
        for row in rows:
            if row.get("status") != "pending_solver":
                continue
            x, y, _ = row["contact_surface_xyz_m"]
            if not accessible(x, y):
                row.update(status="no_evaluable",
                           reason="El punto declarado como contacto del suelo cae dentro de una estructura no accesible.")
                continue
            eligible_transfer_points.append(PotentialPoint(
                transfer_point_by_id[row["id"]], (float(x), float(y), 0.0),
            ))
    if eligible_transfer_points:
        transfer_solutions = client.calculate_scenarios(
            soil=soil,
            segments=segments,
            points=eligible_transfer_points,
            scenarios=scenarios,
            injection_origins=scenario_origins,
            connections=engine_connections,
        )
        for scenario_id, solved_transfer in transfer_solutions.items():
            outcome = outcome_by_scenario[scenario_id]
            outcome["potentials"].update(solved_transfer["potentials_v"])
            outcome["hashes"].append(solved_transfer["trace"]["request_sha256"])

    scenario_results = {}
    evaluation_trace = []
    segment_group = {segment.id: segment.group for segment in segments}
    for scenario_id, scenario in scenarios.items():
        outcome = outcome_by_scenario[scenario_id]
        first = outcome["first"]
        potentials = outcome["potentials"]
        entity_results = {}
        for entity_id, group in entity_group.items():
            solved_group = first["groups"][group]
            leakage = sum(current for segment_id, current in first["segment_currents_a"].items()
                          if segment_group[segment_id] == group)
            entity_results[entity_id] = {
                "injected_current_a": scenario.get(group, 0.0),
                "potential_v": solved_group["potential_v"],
                "potential_spread_v": solved_group["potential_spread_v"],
                "leakage_current_a": leakage,
                "current_balance_error_a": solved_group["current_balance_error_a"],
            }

        transfer_results = []
        for row in transfer_rows_by_scenario[scenario_id]:
            result_row = dict(row)
            if row.get("status") == "pending_solver":
                point_id = transfer_point_by_id[row["id"]]
                if point_id not in potentials:
                    result_row.update(status="no_evaluable",
                                      reason="El solver no devolvió el potencial del punto de contacto local.")
                else:
                    metal = entity_results[row["metal_entity_id"]]
                    result_row.update(
                        status="computed",
                        calculation_status="computed",
                        metal_potential_v=metal["potential_v"],
                        metal_entity_potential_spread_v=metal["potential_spread_v"],
                        local_surface_potential_v=potentials[point_id],
                        actual_touch_v=abs(metal["potential_v"] - potentials[point_id]),
                        solver_point_id=point_id,
                        model_assumption=(
                            "La entidad metálica representa el objeto accesible equipotencial y su ruta eléctrica "
                            "se representa mediante las conexiones explícitas del artefacto; el potencial del nodo "
                            "se usa como potencial del punto tocable."
                        ),
                    )
            transfer_results.append(result_row)

        transfers = []
        ordered_entities = sorted(entity_group)
        for index, entity_a in enumerate(ordered_entities):
            for entity_b in ordered_entities[index + 1:]:
                signed = entity_results[entity_a]["potential_v"] - entity_results[entity_b]["potential_v"]
                transfers.append({"from_entity_id": entity_a, "to_entity_id": entity_b,
                                  "signed_potential_v": signed, "absolute_potential_v": abs(signed)})

        touches = []
        for entity_id, group in entity_group.items():
            x0, x1, y0, y1 = entity_boxes[entity_id]
            candidates = []
            for point_id, (x, y, _) in raster.values():
                if x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9 and accessible(x, y):
                    candidates.append((abs(entity_results[entity_id]["potential_v"] - potentials[point_id]), x, y))
            if not candidates:
                raise UnsupportedModelError(
                    f"La entidad {entity_id} no tiene puntos de toque accesibles en el raster; "
                    "ajuste surface_spacing_m, la geometría o las áreas no intervenibles."
                )
            value, x, y = max(candidates)
            touches.append({"entity_id": entity_id, "value_v": value, "x_m": x, "y_m": y})

        step = {"value_v": 0.0, "from_m": None, "to_m": None}
        k = max(1, round(1.0 / spacing))
        for (i, j), (point_id, xyz) in raster.items():
            if not accessible(xyz[0], xyz[1]):
                continue
            for di, dj in ((k, 0), (0, k)):
                neighbor = raster.get((i + di, j + dj))
                if neighbor is None or not accessible(neighbor[1][0], neighbor[1][1]):
                    continue
                difference = abs(potentials[point_id] - potentials[neighbor[0]])
                if difference > step["value_v"]:
                    step = {"value_v": difference, "from_m": list(xyz[:2]), "to_m": list(neighbor[1][:2])}

        touch = max(touches, key=lambda item: item["value_v"])
        engine_link_currents = first["connection_currents_a"]
        link_currents = {engine_connection_to_id[key]: value for key, value in engine_link_currents.items()}
        values = {
            "potential_reference": "remote-earth",
            "injections_a": {entity_id: scenario.get(group, 0.0) for entity_id, group in entity_group.items()},
            "entities": entity_results,
            "gpr_v": max((abs(item["potential_v"]) for item in entity_results.values()), default=0.0),
            "transferred_potentials_v": transfers,
            "transfer_exposure_results": transfer_results,
            "transfer_assessment": {
                "complete": parameters.get("transfer_assessment_complete") is True,
                "evidence": parameters.get("transfer_assessment_evidence"),
            },
            "connection_currents_a": link_currents,
            "touch_by_entity": touches,
            "max_touch_v": touch,
            "max_step_v": step,
            "surface_potentials_v": {key: potentials[key] for key, _ in raster.values()},
            "surface_grid": {"spacing_m": spacing, "x_min_m": -half_x - margin,
                             "y_min_m": -half_y - margin, "nx": nx + 1, "ny": ny + 1},
            "diagnostics": first["diagnostics"],
            "warnings": first["warnings"] + ["Máximos de toque y paso estimados sobre raster; no hay refinamiento local SV-08 en el cálculo conjunto."],
        }
        values["safety"] = _safety({
            "gpr_v": values["gpr_v"],
            "max_touch_v": {"value": touch["value_v"]},
            "max_step_v": {"value": step["value_v"]},
        }, snapshot["fault"], top_resistivity(soil), parameters)
        _evaluate_transferred_safety(
            values["safety"], transfer_results,
            assessment_complete=parameters.get("transfer_assessment_complete") is True,
            assessment_evidence=parameters.get("transfer_assessment_evidence"),
            fault=snapshot["fault"], rho=top_resistivity(soil),
        )
        scenario_results[scenario_id] = values
        evaluation_trace.append({
            "kind": "scenario", "id": scenario_id,
            "input_sha256": first["trace"]["request_sha256"],
            "solver_version": first["trace"].get("solver_version"),
            "additional_input_sha256s": outcome["hashes"][1:],
        })

    records: dict[str, dict[str, Any]] = {"networks": {}, "electrodes": {}}
    for entity in entities:
        entity_id = entity["id"]
        record = {"id": entity_id, "name": entity["name"], "scenario_results": {
            scenario_id: scenario_results[scenario_id]["entities"][entity_id]
            for scenario_id in scenario_results
        }}
        records[entity_kind[entity_id]][entity_id] = record
    buildings = group_results_by_building(snapshot, records["networks"], records["electrodes"])
    canonical_inputs = {
        "schema_version": "2.0",
        "buildings": sorted(snapshot.get("buildings", []), key=lambda item: item["id"]),
        "networks": sorted(snapshot.get("networks", []), key=lambda item: item["id"]),
        "electrodes": sorted(snapshot.get("electrodes", []), key=lambda item: item["id"]),
        "connections": sorted(snapshot.get("connections", []), key=lambda item: item["id"]),
        "scenarios": scenario_requests,
        "transfer_assessment_complete": parameters.get("transfer_assessment_complete"),
        "transfer_assessment_evidence": parameters.get("transfer_assessment_evidence"),
        "transfer_exposures": parameters.get("transfer_exposures", []),
        "fault": snapshot["fault"], "soil": soil_record(soil), "settings": settings,
    }
    input_sha256 = hashlib.sha256(json.dumps(
        canonical_inputs, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    first_outcome = next(iter(outcome_by_scenario.values()))["first"]
    result = {
        "schema_version": "2.0", "soil": soil_record(soil),
        "injected_current_a": float(snapshot["fault"]["current_a"]),
        "networks": records["networks"], "electrodes": records["electrodes"],
        "buildings": buildings, "scenario_results": scenario_results,
        "connections": snapshot.get("connections", []),
        "warnings": [
            "Las corrientes firmadas se especifican por escenario y entidad; el modelo no las reparte automáticamente desde fault.current_a.",
            "Las máximas tensiones de toque y paso se buscan sobre el raster y no incluyen refinamiento local.",
            "Se supone un origen común centrado en cada plano de geometría; confirme que las coordenadas relativas de todas las entidades están alineadas.",
        ],
    }
    trace = {
        "schema_version": "2.0", "input_sha256": input_sha256,
        "solver_protocol": first_outcome["trace"]["protocol"],
        "parameters": parameters,
        "scenario_ids": list(scenario_results),
        "evaluations": evaluation_trace,
    }
    validate_document("calculation_result_v2", result)
    validate_document("calculation_trace_v2", trace)
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
            run = _field(client, geometry, soil, segments, current, origin, float(parameters["surface_spacing_m"]),
                         float(parameters.get("touch_reach_m") or 0.0))
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


def _field(client, geometry, soil, segments, current, origin, spacing, reach=0.0, coarse=False,
           critical=None, coarse_spacing=None, adaptive=None) -> dict[str, Any]:
    """`_field_search` on one prepared system: assemble, factor and solve once, then query points.

    Clients without `session` (test doubles, older callers) keep the one-solve-per-query path.
    """
    open_session = getattr(client, "session", None)
    if open_session is None:
        return _field_search(client, geometry, soil, segments, current, origin, spacing, reach, coarse, critical, coarse_spacing, adaptive)
    with open_session(soil=soil, segments=segments, injections_a={GROUP: current},
                      injection_origins={GROUP: origin}) as session:
        return _field_search(session, geometry, soil, segments, current, origin, spacing, reach, coarse, critical, coarse_spacing, adaptive)


def _adaptive_refine(lookup, stats, in_structure, touch_box, gpr, touch_seeds, step_seeds, stride, budget, tolerance, min_stride):
    """Pattern search from the strongest touch points and step pairs (fidelity L3).

    Each search moves to its best neighbour (8 around the origin, plus two rotations for a step
    pair) while one improves, halves its stride when none does, and stops on a relative gain below
    `tolerance`, a stride below `min_stride`, or when the next round would exceed `budget` new
    points. Seeds are (voltage, xy) for touch and (voltage, origin xy, end xy) for step; both maximise
    a voltage, and the touch voltage is `gpr` minus the surface potential.
    """
    start = stats["fresh"]
    ring = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    searches = [{"kind": "touch", "x": xy[0], "y": xy[1], "h": stride, "value": value, "initial": value, "stop": None}
                for value, xy in touch_seeds]
    searches += [{"kind": "step", "x": a[0], "y": a[1], "theta": atan2(b[1] - a[1], b[0] - a[0]), "h": stride,
                  "value": value, "initial": value, "stop": None} for value, a, b in step_seeds]
    rounds = 0
    while rounds < 60 and any(s["stop"] is None for s in searches):
        rounds += 1
        plan, moves = {}, []
        for index, s in enumerate(searches):
            if s["stop"] is not None:
                continue
            if s["kind"] == "touch":
                options = [(s["x"] + dx * s["h"], s["y"] + dy * s["h"], None) for dx, dy in ring]
            else:
                turn = s["h"] / STEP_DISTANCE_M
                options = [(s["x"] + dx * s["h"], s["y"] + dy * s["h"], s["theta"]) for dx, dy in ring]
                options += [(s["x"], s["y"], s["theta"] + turn), (s["x"], s["y"], s["theta"] - turn)]
            for k, (px, py, theta) in enumerate(options):
                if s["kind"] == "touch":
                    if not (touch_box[0] - 1e-9 <= px <= touch_box[1] + 1e-9 and touch_box[2] - 1e-9 <= py <= touch_box[3] + 1e-9) \
                            or in_structure(px, py):
                        continue
                    plan[f"a{index}_{k}"] = (px, py, 0.0)
                    moves.append((s, f"a{index}_{k}", None, (px, py, None)))
                else:
                    ex, ey = px + STEP_DISTANCE_M * cos(theta), py + STEP_DISTANCE_M * sin(theta)
                    if in_structure(px, py) or in_structure(ex, ey):
                        continue
                    plan[f"b{index}_{k}a"], plan[f"b{index}_{k}b"] = (px, py, 0.0), (ex, ey, 0.0)
                    moves.append((s, f"b{index}_{k}a", f"b{index}_{k}b", (px, py, theta)))
        if not plan:
            for s in searches:
                s["stop"] = s["stop"] or "blocked"
            break
        values, _ = lookup(plan, limit=budget - (stats["fresh"] - start))
        if values is None:
            for s in searches:
                s["stop"] = s["stop"] or "budget"
            break
        best = {}
        for s, first_id, second_id, params in moves:
            candidate = gpr - values[first_id] if second_id is None else abs(values[first_id] - values[second_id])
            if id(s) not in best or candidate > best[id(s)][0]:
                best[id(s)] = (candidate, params)
        for s in searches:
            if s["stop"] is not None:
                continue
            candidate, params = best.get(id(s), (None, None))
            if candidate is not None and candidate > s["value"] * (1 + 1e-12):
                gain = (candidate - s["value"]) / candidate
                s["value"], s["x"], s["y"] = candidate, params[0], params[1]
                if params[2] is not None:
                    s["theta"] = params[2]
                if gain < tolerance:
                    s["stop"] = "tolerance"
            else:
                s["h"] /= 2
                if s["h"] < min_stride:
                    s["stop"] = "min_stride"
    for s in searches:
        s["stop"] = s["stop"] or "rounds"
    stops = {}
    for s in searches:
        stops[s["stop"]] = stops.get(s["stop"], 0) + 1
    summary = {"searches": len(searches), "rounds": rounds, "points_evaluated": stats["fresh"] - start, "budget_points": budget,
               "stops": stops,
               # Each search stopped improving from its own seed. This says nothing about maxima
               # elsewhere on the surface, so it is never a certificate.
               "locally_converged": all(s["stop"] in ("tolerance", "min_stride") for s in searches),
               "certifies_global_maximum": False,
               "touch_gain_v": max([s["value"] - s["initial"] for s in searches if s["kind"] == "touch"], default=0.0),
               "step_gain_v": max([s["value"] - s["initial"] for s in searches if s["kind"] == "step"], default=0.0)}
    return searches, summary


def _touch_search_area(geometry: dict[str, Any], reach: float):
    """Touch search box (xmin, xmax, ymin, ymax) and an `in_structure(x, y)` test, in the engine's centred frame."""
    half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
    fx0, fx1, fy0, fy1 = grid_geometry.footprint(geometry)
    touch_box = (max(fx0 - reach, -SURFACE_MARGIN_M) - half_x, min(fx1 + reach, 2 * half_x + SURFACE_MARGIN_M) - half_x,
                 max(fy0 - reach, -SURFACE_MARGIN_M) - half_y, min(fy1 + reach, 2 * half_y + SURFACE_MARGIN_M) - half_y)
    obstacles = []
    for _, rect, _ in grid_geometry.obstacles(geometry):
        if "x_min" in rect:
            obstacles.append((float(rect["x_min"]) - half_x, float(rect["x_max"]) - half_x,
                              float(rect["y_min"]) - half_y, float(rect["y_max"]) - half_y))
        else:
            cx, cy = float(rect["x"]) - half_x, float(rect["y"]) - half_y
            obstacles.append((cx - float(rect["width"]) / 2, cx + float(rect["width"]) / 2,
                              cy - float(rect["height"]) / 2, cy + float(rect["height"]) / 2))

    def in_structure(x: float, y: float) -> bool:
        return any(x0 + 1e-9 < x < x1 - 1e-9 and y0 + 1e-9 < y < y1 - 1e-9
                   for x0, x1, y0, y1 in obstacles)
    return touch_box, in_structure


def touch_area_is_accessible(geometry: dict[str, Any], spacing: float, reach: float = 0.0) -> bool:
    """Whether the touch search finds at least one raster point outside every structure.

    The search area is the conductors' bounding box widened by `reach`; a grid drawn wholly inside a
    building has none and the field search refuses it, so callers can reject it before solving.
    """
    half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
    box, in_structure = _touch_search_area(geometry, reach)
    nx = round(2 * (half_x + SURFACE_MARGIN_M) / spacing)
    ny = round(2 * (half_y + SURFACE_MARGIN_M) / spacing)
    for i in range(nx + 1):
        x = -half_x - SURFACE_MARGIN_M + i * spacing
        if not box[0] - 1e-9 <= x <= box[1] + 1e-9:
            continue
        for j in range(ny + 1):
            y = -half_y - SURFACE_MARGIN_M + j * spacing
            if box[2] - 1e-9 <= y <= box[3] + 1e-9 and not in_structure(x, y):
                return True
    return False


def _field_search(client, geometry, soil, segments, current, origin, spacing, reach=0.0, coarse=False,
                  critical=None, coarse_spacing=None, adaptive=None) -> dict[str, Any]:
    """Surface search for GPR, the worst touch over the grid and the worst 1 m step.

    The raster covers the whole site plus a margin. Touch is searched only over the grid's
    footprint (its conductors' bounding box, widened by `reach`), not over the rest of the site;
    step is searched everywhere except inside structures, whose floor is not open ground.

    `coarse` (fidelity L1) skips both local refinements, adds nine known critical points to the
    touch search and ranks step candidates by gradient, since raster neighbours are no longer 1 m
    apart. Every value is still exact at its own points, so `Vt` and `Vs` are lower bounds of the true
    maxima, though not necessarily of the refined search, which samples different points.

    `critical` adds the nine known critical touch points and starts step probes from them (default:
    on for a coarse search, off otherwise). With `coarse_spacing` and a full search (fidelity L2+)
    it also probes the step candidates a raster of that spacing would rank first, so the result is
    the union of the L1 and L2 searches. A point is evaluated once however many sub-searches ask
    for it. `adaptive` ({"budget_points", "tolerance", "min_step_m"}, fidelity L3) then refines the
    strongest touch and step candidates with a pattern search, within a budget of new points.
    """
    half_x, half_y = geometry["length_m"] / 2, geometry["width_m"] / 2
    touch_box, in_structure = _touch_search_area(geometry, reach)

    nx = round(2 * (half_x + SURFACE_MARGIN_M) / spacing)
    ny = round(2 * (half_y + SURFACE_MARGIN_M) / spacing)
    raster = {
        f"s{i}_{j}": (-half_x - SURFACE_MARGIN_M + i * spacing, -half_y - SURFACE_MARGIN_M + j * spacing, 0.0)
        for i in range(nx + 1) for j in range(ny + 1)
    }
    critical_on = coarse if critical is None else critical
    critical = {}
    if critical_on:
        mid_x, mid_y = (touch_box[0] + touch_box[1]) / 2, (touch_box[2] + touch_box[3]) / 2
        for cx in (touch_box[0], mid_x, touch_box[1]):
            for cy in (touch_box[2], mid_y, touch_box[3]):
                if not in_structure(cx, cy):
                    critical[f"c{len(critical)}"] = (cx, cy, 0.0)
    first, v, hashes = _solve(client, soil, segments, current,
                              [PotentialPoint(pid, xyz) for pid, xyz in {**raster, **critical}.items()], origin)
    gpr = first["groups"][GROUP]["potential_v"]
    known = {(round(x, 9), round(y, 9)): v[pid] for pid, (x, y, _) in {**raster, **critical}.items()}

    stats = {"fresh": 0}

    def lookup(points: dict[str, tuple[float, float, float]], limit: int | None = None):
        """Potentials at `points`, asking the engine only for coordinates not evaluated before.

        With `limit`, returns (None, []) instead of evaluating when more new coordinates than that are needed.
        """
        keys = {pid: (round(x, 9), round(y, 9)) for pid, (x, y, _) in points.items()}
        fresh: dict[tuple[float, float], str] = {}
        for pid, key in keys.items():
            if key not in known and key not in fresh:
                fresh[key] = pid
        hashes: list[str] = []
        if limit is not None and len(fresh) > limit:
            return None, []
        if fresh:
            stats["fresh"] += len(fresh)
            _, values, hashes = _solve(client, soil, segments, current,
                                       [PotentialPoint(pid, points[pid]) for pid in fresh.values()], origin)
            for key, pid in fresh.items():
                known[key] = values[pid]
        return {pid: known[key] for pid, key in keys.items()}, hashes

    inside = [pid for pid, (x, y, _) in raster.items()
              if touch_box[0] - 1e-9 <= x <= touch_box[1] + 1e-9 and touch_box[2] - 1e-9 <= y <= touch_box[3] + 1e-9]
    touchable = [pid for pid in inside if not in_structure(*raster[pid][:2])]
    if not touchable:
        raise UnsupportedModelError("No hay puntos de contacto accesibles fuera de los obstáculos en el área de búsqueda.")

    # Refine the surface minimum on a local lattice; keep only points inside the touch search box
    # and on open ground. This lets the reported coordinate move off the coarse raster.
    local_spacing = spacing / LOCAL_REFINE_DIVISIONS
    touch_seeds = [] if coarse else sorted(touchable, key=v.__getitem__)[:TOUCH_REFINE_CANDIDATES]
    touch_refine = {}
    for c, pid in enumerate(touch_seeds):
        x, y, _ = raster[pid]
        for ix in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
            for iy in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
                px, py = x + ix * local_spacing, y + iy * local_spacing
                if (touch_box[0] - 1e-9 <= px <= touch_box[1] + 1e-9
                        and touch_box[2] - 1e-9 <= py <= touch_box[3] + 1e-9
                        and not in_structure(px, py)):
                    touch_refine[f"t{c}_{ix}_{iy}"] = (px, py, 0.0)
    touch_v, touch_hashes = lookup(touch_refine)
    touch_candidates = [(v[pid], raster[pid][:2]) for pid in touchable]
    touch_candidates.extend((value, touch_refine[pid][:2]) for pid, value in touch_v.items())
    touch_candidates.extend((v[pid], xyz[:2]) for pid, xyz in critical.items())
    touch_min, touch_xy = min(touch_candidates, key=lambda item: item[0])

    # Step voltage: rank raster points by their largest 1 m axis difference, then search
    # 16 directions around the strongest candidates (the worst step is usually diagonal at a corner).
    k = max(1, round(STEP_DISTANCE_M / spacing))
    # Neighbours are k * spacing apart; on a coarse raster that is not 1 m, so rank by gradient.
    step_scale = STEP_DISTANCE_M / (k * spacing) if coarse else 1.0
    def axis_step(pid: str) -> float:
        i, j = map(int, pid[1:].split("_"))
        return step_scale * max((abs(v[pid] - v[f"s{i + di}_{j + dj}"]) for di, dj in ((k, 0), (0, k), (-k, 0), (0, -k))
                    if f"s{i + di}_{j + dj}" in v), default=0.0)
    open_ground = [pid for pid, (x, y, _) in raster.items() if not in_structure(x, y)]
    candidates = sorted(open_ground, key=axis_step, reverse=True)[:STEP_CANDIDATES]
    # (id prefix, potential at the origin, origin xy); a coarse search also starts from the critical points.
    probe_origins = [(f"p{c}", v[pid], raster[pid][:2]) for c, pid in enumerate(candidates)]
    if critical_on and not coarse and coarse_spacing and coarse_spacing > spacing:
        # Fidelity L2+: also the origins the coarse (L1) raster ranks first by gradient.
        ratio = max(2, round(coarse_spacing / spacing))
        reach_nodes = max(1, round(STEP_DISTANCE_M / (ratio * spacing))) * ratio
        def coarse_gradient(pid: str) -> float:
            i, j = map(int, pid[1:].split("_"))
            return max((abs(v[pid] - v[f"s{i + di}_{j + dj}"]) for di, dj in
                        ((reach_nodes, 0), (0, reach_nodes), (-reach_nodes, 0), (0, -reach_nodes))
                        if f"s{i + di}_{j + dj}" in v), default=0.0) / (reach_nodes * spacing)
        lattice = [pid for pid in open_ground if all(int(n) % ratio == 0 for n in pid[1:].split("_"))]
        already = set(candidates)
        probe_origins += [(f"g{c}", v[pid], raster[pid][:2]) for c, pid in
                          enumerate(sorted(lattice, key=coarse_gradient, reverse=True)[:STEP_CANDIDATES])
                          if pid not in already]
    probe_origins += [(f"q{c}", v[cid], xyz[:2]) for c, (cid, xyz) in enumerate(critical.items())
                      if not in_structure(*xyz[:2])]
    probes = {}
    for prefix, _, (x, y) in probe_origins:
        for d in range(STEP_DIRECTIONS):
            angle = 2 * pi * d / STEP_DIRECTIONS
            probes[f"{prefix}_{d}"] = (x + STEP_DISTANCE_M * cos(angle), y + STEP_DISTANCE_M * sin(angle), 0.0)
    probe_v, probe_hashes = lookup(probes)
    step_value, step_from, step_to = 0.0, None, None
    step_pairs = []
    for prefix, origin_v, origin_xy in probe_origins:
        for d in range(STEP_DIRECTIONS):
            if in_structure(*probes[f"{prefix}_{d}"][:2]):
                continue
            difference = abs(origin_v - probe_v[f"{prefix}_{d}"])
            step_pairs.append((difference, tuple(origin_xy), tuple(probes[f"{prefix}_{d}"][:2])))
            if difference > step_value:
                step_value, step_from, step_to = difference, list(origin_xy), list(probes[f"{prefix}_{d}"][:2])

    # Search a finer set of step origins around the strongest coarse candidates, keeping both
    # feet on open ground. Directions remain on the existing angular set so each reported pair
    # stays exactly STEP_DISTANCE_M apart.
    step_seeds = [] if coarse else candidates[:STEP_REFINE_CANDIDATES]
    step_refine = {}
    refine_radius = spacing
    for c, pid in enumerate(step_seeds):
        x, y, _ = raster[pid]
        for ix in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
            for iy in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
                sx, sy = x + ix * refine_radius / LOCAL_REFINE_DIVISIONS, y + iy * refine_radius / LOCAL_REFINE_DIVISIONS
                if in_structure(sx, sy):
                    continue
                for d in range(STEP_DIRECTIONS):
                    angle = 2 * pi * d / STEP_DIRECTIONS
                    ex, ey = sx + STEP_DISTANCE_M * cos(angle), sy + STEP_DISTANCE_M * sin(angle)
                    if not in_structure(ex, ey):
                        step_refine[f"r{c}_{ix}_{iy}_{d}a"] = (sx, sy, 0.0)
                        step_refine[f"r{c}_{ix}_{iy}_{d}b"] = (ex, ey, 0.0)
    refined_v, refined_hashes = lookup(step_refine)
    for c, pid in enumerate(step_seeds):
        x, y, _ = raster[pid]
        for ix in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
            for iy in range(-LOCAL_REFINE_DIVISIONS, LOCAL_REFINE_DIVISIONS + 1):
                for d in range(STEP_DIRECTIONS):
                    a, b = f"r{c}_{ix}_{iy}_{d}a", f"r{c}_{ix}_{iy}_{d}b"
                    if a in refined_v:
                        difference = abs(refined_v[a] - refined_v[b])
                        step_pairs.append((difference, tuple(step_refine[a][:2]), tuple(step_refine[b][:2])))
                        if difference > step_value:
                            step_value = difference
                            step_from, step_to = list(step_refine[a][:2]), list(step_refine[b][:2])
    adaptive_summary = None
    if adaptive:
        def distinct(ranked, count):
            chosen = []
            for entry in ranked:
                if all(hypot(entry[1][0] - c[1][0], entry[1][1] - c[1][1]) > 0.5 for c in chosen):
                    chosen.append(entry)
                if len(chosen) == count:
                    break
            return chosen
        touch_seeds = [(gpr - value, xy) for value, xy in distinct(sorted(touch_candidates, key=lambda item: item[0]), 3)]
        step_seeds_a = distinct(sorted(step_pairs, key=lambda item: -item[0]), 3)
        searches, adaptive_summary = _adaptive_refine(
            lookup, stats, in_structure, touch_box, gpr, touch_seeds, step_seeds_a, spacing / LOCAL_REFINE_DIVISIONS / 2,
            int(adaptive["budget_points"]), float(adaptive["tolerance"]), float(adaptive["min_step_m"]))
        for s in searches:
            if s["kind"] == "touch" and gpr - s["value"] < touch_min:
                touch_min, touch_xy = gpr - s["value"], (s["x"], s["y"])
            elif s["kind"] == "step" and s["value"] > step_value:
                step_value = s["value"]
                step_from = [s["x"], s["y"]]
                step_to = [s["x"] + STEP_DISTANCE_M * cos(s["theta"]), s["y"] + STEP_DISTANCE_M * sin(s["theta"])]
    return {
        "first": first,
        "gpr_v": gpr,
        "adaptive": adaptive_summary,
        # This is the raster solved by the engine; step-search probes are not included.
        "surface_potential": {
            "spacing_m": spacing,
            "x_min_m": -half_x - SURFACE_MARGIN_M,
            "y_min_m": -half_y - SURFACE_MARGIN_M,
            # The touch search area, relative to the raster origin.
            "grid_x_m": touch_box[0] + half_x + SURFACE_MARGIN_M,
            "grid_y_m": touch_box[2] + half_y + SURFACE_MARGIN_M,
            "grid_width_m": touch_box[1] - touch_box[0],
            "grid_height_m": touch_box[3] - touch_box[2],
            "nx": nx + 1,
            "ny": ny + 1,
            "values_v": [v[f"s{i}_{j}"] for j in range(ny + 1) for i in range(nx + 1)],
        },
        "max_touch_v": {"value": gpr - touch_min, "x_m": touch_xy[0], "y_m": touch_xy[1]},
        "max_step_v": {"value": step_value, "from_m": step_from, "to_m": step_to},
        "point_count": len(known),
        "points_requested": len(raster) + len(critical) + len(probes) + len(touch_refine) + len(step_refine),
        "hashes": hashes + probe_hashes + touch_hashes + refined_hashes,
    }


def _fault_exposure(fault: dict[str, Any], rho: float) -> safety_criteria.FaultExposure:
    return safety_criteria.FaultExposure(
        clearing_time_s=float(fault["clearing_time_s"]),
        body_weight_kg=float(fault.get("body_weight_kg", 50)),
        surface_resistivity_ohm_m=float(fault.get("surface_resistivity_ohm_m", 3000)),
        surface_thickness_m=float(fault.get("surface_thickness_m", 0.1)),
        soil_resistivity_ohm_m=rho,
        exposure_class=fault.get("exposure_class"),
        surface_layer_present=fault.get("surface_layer_present"),
    )


def _evaluate_transferred_safety(
    safety: list[dict[str, Any]],
    transfer_rows: list[dict[str, Any]],
    *,
    assessment_complete: bool,
    assessment_evidence: str | None,
    fault: dict[str, Any],
    rho: float,
) -> None:
    """Evaluate explicit metal-to-local-soil touch exposures; never use pairwise GPR deltas."""
    for standard_result in safety:
        standard = standard_result["standard"]
        criteria = [item for item in standard_result.get("criteria", [])
                    if item.get("criterion") != "transferred"]
        candidate_rows = [item for item in transfer_rows if item.get("accessibility") != "not_accessible"]
        source = None
        method = (
            "Tensión de contacto transferida = potencial del nodo metálico accesible menos potencial "
            "del suelo en el punto local de contacto, calculado en la coordenada declarada. "
            "La red/conexión y la entidad metálica deben estar representadas explícitamente."
        )
        if not assessment_complete:
            transferred = {
                "criterion": "transferred", "status": "no_evaluable",
                "reason": "El inventario de exposiciones transferidas no fue declarado completo y documentado.",
                "assessment_evidence": assessment_evidence,
            }
        elif not candidate_rows:
            transferred = {
                "criterion": "transferred", "status": "not_applicable",
                "reason": "El inventario completo no identificó puntos accesibles de potencial transferido.",
                "assessment_evidence": assessment_evidence,
                "method": method,
            }
        else:
            missing_rows = [item for item in candidate_rows if item.get("calculation_status", item.get("status")) != "computed"]
            evaluated_rows = []
            unevaluated_ids = [item["id"] for item in missing_rows]
            for row in candidate_rows:
                if row.get("calculation_status", row.get("status")) != "computed":
                    continue
                local_fault = dict(fault)
                for key in ("exposure_class", "surface_layer_present", "surface_resistivity_ohm_m",
                            "surface_thickness_m", "clearing_time_s"):
                    if row.get(key) is not None:
                        local_fault[key] = row[key]
                try:
                    limits = safety_criteria.tolerable_limits(standard, _fault_exposure(local_fault, rho))
                except (safety_criteria.StandardNotLoadedError, ValueError):
                    unevaluated_ids.append(row["id"])
                    reason = "No hay límite tolerable aplicable con los datos de exposición declarados."
                    row.update(status="no_evaluable", reason=reason)
                    row.setdefault("safety_by_standard", {})[standard] = {
                        "status": "no_evaluable", "reason": reason,
                    }
                    continue
                limit = limits["touch_v"]
                source = limits.get("source") or limits.get("touch_source") or {
                    "document": standard, "edition": "seleccionada explícitamente",
                    "clause": "límite tolerable de contacto",
                }
                actual = float(row["actual_touch_v"])
                margin = limit - actual
                standard_evaluation = {
                    "status": "cumple" if margin >= 0 else "no_cumple",
                    "actual_v": actual, "tolerable_v": limit, "margin_v": margin,
                    "safety_source": source, "safety_method": method,
                }
                row.setdefault("safety_by_standard", {})[standard] = standard_evaluation
                # Keep legacy single-standard fields for existing consumers;
                # keyed evaluations are authoritative for multi-standard runs.
                if "safety_standard" not in row:
                    row.update(criterion_status=standard_evaluation["status"],
                               tolerable_touch_v=limit, margin_v=margin, safety_standard=standard,
                               safety_source=source, safety_method=method)
                evaluated_rows.append(row)
            worst_row = min(evaluated_rows, key=lambda item: item["safety_by_standard"][standard]["margin_v"]) if evaluated_rows else None
            if unevaluated_ids:
                transferred = {
                    "criterion": "transferred", "status": "no_evaluable",
                    "reason": "Una o más exposiciones no se pudieron modelar o no tienen datos para seleccionar su límite.",
                    "assessment_evidence": assessment_evidence,
                    "evaluated_exposure_ids": [item["id"] for item in evaluated_rows],
                    "unevaluated_exposure_ids": sorted(set(unevaluated_ids)),
                    "actual_v": worst_row["safety_by_standard"][standard]["actual_v"] if worst_row else None,
                    "tolerable_v": worst_row["safety_by_standard"][standard]["tolerable_v"] if worst_row else None,
                    "source": worst_row["safety_by_standard"][standard]["safety_source"] if worst_row else None,
                    "method": method,
                }
            elif worst_row is None:
                transferred = {"criterion": "transferred", "status": "no_evaluable",
                              "reason": "No se obtuvo un valor de tensión transferida para las exposiciones declaradas.",
                              "assessment_evidence": assessment_evidence}
            else:
                transferred = {
                    "criterion": "transferred", "actual_v": worst_row["safety_by_standard"][standard]["actual_v"],
                    "tolerable_v": worst_row["safety_by_standard"][standard]["tolerable_v"],
                    "margin_v": worst_row["safety_by_standard"][standard]["margin_v"],
                    "status": "cumple" if all(item["safety_by_standard"][standard]["status"] == "cumple" for item in evaluated_rows) else "no_cumple",
                    "evaluated_exposure_ids": [item["id"] for item in evaluated_rows],
                    "assessment_evidence": assessment_evidence,
                    "source": worst_row["safety_by_standard"][standard]["safety_source"],
                    "method": method,
                    "model_assumption": "La entidad metálica se aproxima como equipotencial; su potencial de nodo se usa como potencial tocable.",
                }
        criteria.append(transferred)
        standard_result["criteria"] = criteria
        statuses = [item.get("status") for item in criteria]
        if "no_cumple" in statuses:
            standard_result["status"] = "no_cumple"
        elif "no_evaluable" in statuses or not statuses:
            standard_result["status"] = "no_evaluable"
        else:
            standard_result["status"] = "cumple"
        standard_result.pop("reason", None)
        if standard_result["status"] == "no_evaluable":
            standard_result["reason"] = transferred.get("reason", "Faltan criterios de seguridad por evaluar.")
        standard_result["unassessed_criteria"] = [
            item["criterion"] for item in criteria if item.get("status") == "no_evaluable"
        ]


def _safety(result: dict[str, Any], fault: dict[str, Any], rho: float, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Normative decision, kept apart from the field result it reads."""
    exposure = _fault_exposure(fault, rho)
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
        artifact = db.designs.get_version(calculation["project_id"], calculation["artifact_id"],
                                          calculation["artifact_version"])
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
