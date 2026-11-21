"""Mapeo determinista de afirmaciones del grafo a entradas del artefacto (PR-20).

Este módulo no decide qué afirmación es verdadera ni modifica un artefacto. Devuelve
candidatos y su estado para que la interrogación pueda confirmar o resolver conflictos.
Los valores cuantitativos ya vienen normalizados por la validación del grafo y se
mantienen en unidades SI, salvo los campos del artefacto que explícitamente usan otra
unidad (por ejemplo, la sección del conductor en mm²).
"""

from collections import defaultdict

from src.domain.knowledge_graph.claims import LIVE_STATUSES, effective_value


# attribute, accepted subject types -> artifact route, optional value conversion.
_SCALAR_ROUTES = (
    ("fault_current", frozenset({"FaultScenario", "Busbar", "Substation", "Transformer"}),
     "fault.current_a", None),
    ("shock_duration", frozenset({"FaultScenario", "Busbar", "Substation", "Transformer"}),
     "fault.clearing_time_s", None),
    ("thermal_duration", frozenset({"FaultScenario", "Busbar", "Substation", "Transformer"}),
     "conductor.thermal_duration_s", None),
    ("surface_layer_resistivity",
     frozenset({"GroundingSystem", "Substation", "Site", "Zone"}),
     "fault.surface_resistivity_ohm_m", None),
    ("surface_layer_thickness",
     frozenset({"GroundingSystem", "Substation", "Site", "Zone"}),
     "fault.surface_thickness_m", None),
    ("grid_length", frozenset({"GroundingGrid"}), "geometry.length_m", None),
    ("grid_width", frozenset({"GroundingGrid"}), "geometry.width_m", None),
    ("burial_depth", frozenset({"GroundingGrid", "GridConductor", "RodElectrode"}),
     "geometry.burial_depth_m", None),
    ("conductor_spacing", frozenset({"GroundingGrid"}),
     "geometry.conductor_spacing_m", None),
    ("rod_length", frozenset({"RodElectrode", "GroundingGrid"}),
     "geometry.rod_length_m", None),
    # The taxonomy stores area in m²; the artifact contract stores it in mm².
    ("conductor_cross_section", frozenset({
        "GroundingSystem", "GroundingGrid", "GridConductor", "RodElectrode",
        "DownConductor", "Fence", "BondingConnection",
    }), "conductor.cross_section_mm2", lambda value: value * 1_000_000),
)

_ROUTE_INDEX = {
    (attribute, subject_type): (route, converter)
    for attribute, subject_types, route, converter in _SCALAR_ROUTES
    for subject_type in subject_types
}


def _claim_id(claim: dict) -> str | None:
    return claim.get("claim_id") or claim.get("id")


def _candidate(claim: dict) -> dict:
    """Compacta una afirmación para la respuesta pública del mapeo."""
    value = effective_value(claim)
    return {
        "claim_id": _claim_id(claim),
        "value": value["value_si"] if value.get("value_si") is not None
        else value.get("value_literal"),
        "value_si": value.get("value_si"),
        "value_literal": value.get("value_literal"),
        "unit": value.get("unit"),
        "status": claim.get("status"),
        "subject_type": claim.get("entity_type"),
        "subject_name": claim.get("subject_name"),
        "attribute": claim.get("attribute"),
        "evidence": claim.get("evidence", []),
        "filename": claim.get("filename"),
    }


def _same_value(left: dict, right: dict) -> bool:
    if left.get("value_si") is not None and right.get("value_si") is not None:
        scale = max(abs(left["value_si"]), abs(right["value_si"]), 1e-12)
        return abs(left["value_si"] - right["value_si"]) <= 1e-6 * scale
    return left.get("value_literal", "").strip().casefold() == right.get("value_literal", "").strip().casefold()


def _state(candidates: list[dict]) -> str:
    if not candidates:
        return "falta"
    first = candidates[0]
    return "encontrado" if all(_same_value(first, candidate) for candidate in candidates[1:]) else "conflicto"


def _entry(route: str, candidates: list[dict], converter=None) -> dict:
    state = _state(candidates)
    selected = candidates[0] if state == "encontrado" else None
    value = None if selected is None else selected["value_si"]
    if value is None and selected is not None:
        value = selected["value_literal"]
    if converter is not None and value is not None:
        value = converter(value)
    return {
        "route": route,
        "state": state,
        "value": value,
        "claim": selected,
        "candidates": candidates,
    }


def map_claims_to_artifact(claims: list[dict], *, include_rejected: bool = False) -> dict:
    """Traduce afirmaciones vivas del grafo a entradas del artefacto.

    El resultado siempre contiene las rutas conocidas, incluso cuando faltan, para que
    la UI pueda renderizar una lista estable de datos encontrados, conflictos y faltantes.
    Afirmaciones rechazadas/superseded se excluyen por defecto; duplicados con el mismo
    valor quedan como un único valor encontrado con todos sus candidatos como evidencia.
    """
    allowed = LIVE_STATUSES if not include_rejected else LIVE_STATUSES | {"rejected", "superseded"}
    buckets = defaultdict(list)
    for claim in claims:
        if claim.get("kind") != "attribute" or claim.get("status") not in allowed:
            continue
        mapping = _ROUTE_INDEX.get((claim.get("attribute"), claim.get("entity_type")))
        if mapping is None:
            continue
        route, converter = mapping
        buckets[(route, converter)].append(_candidate(claim))

    result = {}
    for attribute, subject_types, route, converter in _SCALAR_ROUTES:
        candidates = buckets.get((route, converter), [])
        result[route] = _entry(route, candidates, converter)
    return result


def map_graph_to_artifact(claims: list[dict], **kwargs) -> dict:
    """Nombre orientado al caso de uso; alias explícito para consumidores del dominio."""
    return map_claims_to_artifact(claims, **kwargs)


def _locator_text(claim: dict) -> str | None:
    evidence = claim.get("evidence") or []
    locator = next((item.get("locator") for item in evidence if item.get("locator") is not None), None)
    if locator is None:
        return None
    if isinstance(locator, str):
        return locator[:180]
    return "; ".join(f"{key}={value}" for key, value in locator.items())[:180]


def map_soil_measurements(claims: list[dict], *, include_rejected: bool = False) -> dict:
    """Agrupa afirmaciones ``ResistivityReading`` en el contrato de mediciones.

    Una lectura solo entra al artefacto cuando tiene espaciamiento y resistividad. Las
    incompletas se devuelven como pendientes, nunca se rellenan con un valor supuesto.
    """
    allowed = LIVE_STATUSES if not include_rejected else LIVE_STATUSES | {"rejected", "superseded"}
    groups = defaultdict(dict)
    array_claims = []
    for claim in claims:
        if claim.get("kind") != "attribute" or claim.get("status") not in allowed:
            continue
        attribute = claim.get("attribute")
        if attribute == "array_type" and claim.get("entity_type") in {"SoilSurvey", "ResistivityReading"}:
            array_claims.append(claim)
            continue
        if claim.get("entity_type") != "ResistivityReading" or attribute not in {
                "probe_spacing", "apparent_resistivity"}:
            continue
        key = claim.get("entity_key") or claim.get("subject_name")
        groups[key][attribute] = claim

    readings, pending = [], []
    for subject, values in groups.items():
        missing = sorted({"probe_spacing", "apparent_resistivity"} - values.keys())
        if missing:
            pending.append({"subject": subject, "missing": missing,
                            "claim_ids": [_claim_id(claim) for claim in values.values()]})
            continue
        spacing = effective_value(values["probe_spacing"])
        resistivity = effective_value(values["apparent_resistivity"])
        readings.append({
            "spacing_m": spacing["value_si"],
            "apparent_resistivity_ohm_m": resistivity["value_si"],
            "locator": _locator_text(values["apparent_resistivity"])
                       or _locator_text(values["probe_spacing"]),
            "claim_ids": [_claim_id(values["probe_spacing"]),
                          _claim_id(values["apparent_resistivity"])],
        })

    arrays = []
    for claim in array_claims:
        value = effective_value(claim).get("value_literal")
        if value and value.casefold() not in arrays:
            arrays.append(value.casefold())
    state = "encontrado" if len(arrays) == 1 else "conflicto" if len(arrays) > 1 else "falta"
    array = arrays[0] if state == "encontrado" else None
    return {"state": state if not pending and readings else "incompleto",
            "array": array, "array_candidates": arrays, "measurements": readings,
            "pending": pending, "count": len(readings),
            "valid": len(readings) >= 4 and state == "encontrado" and not pending}


__all__ = ["map_claims_to_artifact", "map_graph_to_artifact", "map_soil_measurements"]
