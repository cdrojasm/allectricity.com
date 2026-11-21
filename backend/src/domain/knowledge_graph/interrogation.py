"""Resumen de interrogación posterior a la ingesta (PR-23)."""

from collections import defaultdict

from src.domain.knowledge_graph.claims import LIVE_STATUSES, effective_value, same_value


# Entradas que Allectricity necesita para poder proponer el primer cálculo desde documentos.
REQUIRED_INPUTS = (
    ("fault_current", "fault.current_a"),
    ("shock_duration", "fault.clearing_time_s"),
    ("surface_layer_resistivity", "fault.surface_resistivity_ohm_m"),
    ("surface_layer_thickness", "fault.surface_thickness_m"),
    ("grid_length", "geometry.length_m"),
    ("grid_width", "geometry.width_m"),
    ("burial_depth", "geometry.burial_depth_m"),
    ("conductor_spacing", "geometry.conductor_spacing_m"),
)


def build_interrogation(claims: list[dict], questions: list[dict] = ()) -> dict:
    """Resume encontrados, conflictos y faltantes con IDs listos para confirmación batch."""
    by_attribute = defaultdict(list)
    for claim in claims:
        if claim.get("kind") == "attribute" and claim.get("status") in LIVE_STATUSES:
            by_attribute[claim.get("attribute")].append(claim)

    found, conflicts, missing, confirmable = [], [], [], []
    conflict_ids = {claim_id for question in questions
                    if question.get("kind") == "conflict"
                    for claim_id in question.get("claim_ids", [])}
    for attribute, route in REQUIRED_INPUTS:
        candidates = by_attribute.get(attribute, [])
        values = []
        for claim in candidates:
            if not any(same_value(effective_value(claim), effective_value(other)) for other in values):
                values.append(claim)
        if not candidates:
            missing.append({"attribute": attribute, "route": route})
        elif len(values) > 1 or any(claim.get("claim_id") in conflict_ids for claim in candidates):
            conflicts.append({"attribute": attribute, "route": route,
                              "claim_ids": [claim.get("claim_id") for claim in candidates]})
        else:
            claim = candidates[0]
            item = {"attribute": attribute, "route": route, "claim_id": claim.get("claim_id"),
                    "value": effective_value(claim).get("value_literal"),
                    "unit": claim.get("unit_literal"), "source": claim.get("filename")}
            found.append(item)
            if claim.get("status") != "accepted":
                confirmable.append(claim.get("claim_id"))

    return {
        "kind": "knowledge.interrogation", "found": found, "conflicts": conflicts,
        "missing": missing, "confirmable_claim_ids": [claim_id for claim_id in confirmable if claim_id],
        "found_count": len(found), "total_count": len(REQUIRED_INPUTS),
        "conflict_count": len(conflicts), "missing_count": len(missing),
        "questions": list(questions),
    }


def interrogation_text(summary: dict, filename: str = "") -> str:
    prefix = f"Analicé «{filename}». " if filename else "Analicé el documento. "
    text = f"{prefix}Encontré {summary['found_count']} de {summary['total_count']} datos de diseño."
    if summary["conflict_count"]:
        text += f" Hay {summary['conflict_count']} conflicto(s) por resolver."
    if summary["missing_count"]:
        text += f" Faltan {summary['missing_count']} dato(s)."
    return text


__all__ = ["REQUIRED_INPUTS", "build_interrogation", "interrogation_text"]
