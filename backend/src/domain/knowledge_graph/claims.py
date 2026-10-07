"""Afirmaciones con procedencia y su ciclo de revisión (EG-02, EG-05, EG-08).

Una afirmación (`Claim`) es lo que un documento dice sobre una entidad, un atributo o una
relación. Nunca se sobrescribe: se acepta, se rechaza, se corrige (conservando el valor
propuesto) o queda reemplazada. Solo una decisión humana produce `accepted`.
"""

import hashlib
import json

from src.domain.knowledge_graph.source import normalized_text
from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, parse_quantity

PROPOSED, NEEDS_REVIEW, ACCEPTED, REJECTED, SUPERSEDED = (
    "proposed", "needs_review", "accepted", "rejected", "superseded")
STATUSES = (PROPOSED, NEEDS_REVIEW, ACCEPTED, REJECTED, SUPERSEDED)
OPEN_STATUSES = frozenset({PROPOSED, NEEDS_REVIEW})
LIVE_STATUSES = frozenset({PROPOSED, NEEDS_REVIEW, ACCEPTED})

ACCEPT, REJECT, CORRECT = "accept", "reject", "correct"
REVIEWED_FIELDS = ("reviewed_value_literal", "reviewed_unit_literal", "reviewed_value_si",
                   "reviewed_unit")
DECISIONS = (ACCEPT, REJECT, CORRECT)


class ReviewError(Exception):
    """Decisión de revisión inválida; `code` permite traducirla a HTTP en la API."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def stable_key(*parts) -> str:
    value = "\x1f".join(str(part).strip().casefold() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def entity_key(project_id: str, entity_type: str, name: str) -> str:
    """Identidad conservadora: mismo tipo y mismo nombre normalizado (sin fusión difusa)."""
    return stable_key(project_id, "entity", entity_type, normalized_text(name))


def content_key(claim: dict) -> str:
    """Huella del contenido afirmado, independiente de la ejecución y de la evidencia."""
    kind = claim["kind"]
    if kind == "entity":
        content = [claim["entity_key"]]
    elif kind == "attribute":
        value = (repr(round(claim["value_si"], 12)) if claim.get("value_si") is not None
                 else normalized_text(claim.get("value_literal", "")))
        content = [claim["entity_key"], claim["attribute"], value, claim.get("unit") or "",
                   normalized_text(claim.get("qualifier") or "")]
    else:
        source, target = claim["source_key"], claim["target_key"]
        if claim.get("symmetric") and target < source:
            source, target = target, source
        content = [source, claim["relation_type"], target]
    return stable_key(kind, *content)


def claim_id(run_id: str, claim: dict) -> str:
    return stable_key(run_id, content_key(claim))


def initial_status(claim: dict) -> str:
    """Estado inicial: nunca `accepted`; el LLM y los datos de cálculo siempre a revisión."""
    if ("llm" in claim.get("methods", ())
            or claim.get("feeds_calculation")
            or claim.get("review_reasons")
            or claim.get("ocr_needs_review")):
        return NEEDS_REVIEW
    return PROPOSED


def same_value(left: dict, right: dict, tolerance: float = 1e-6) -> bool:
    if left.get("value_si") is not None and right.get("value_si") is not None:
        scale = max(abs(left["value_si"]), abs(right["value_si"]), 1e-12)
        return (left.get("unit") == right.get("unit")
                and abs(left["value_si"] - right["value_si"]) <= tolerance * scale)
    return (normalized_text(str(left.get("value_literal", "")))
            == normalized_text(str(right.get("value_literal", ""))))


def review_decision(claim: dict, decision: str, reason: str,
                    corrected_value: str | None = None,
                    corrected_unit: str | None = None) -> dict:
    """Valida una decisión humana y devuelve los cambios a aplicar a la afirmación."""
    if decision not in DECISIONS:
        raise ReviewError("invalid", f"Decisión desconocida «{decision}»")
    if not reason or not reason.strip():
        raise ReviewError("invalid", "La decisión requiere un motivo")
    if claim["status"] == SUPERSEDED:
        raise ReviewError("conflict", "La afirmación fue reemplazada y ya no admite decisiones")
    changes = {"status": REJECTED if decision == REJECT else ACCEPTED}
    if decision != CORRECT:
        if corrected_value is not None or corrected_unit is not None:
            raise ReviewError("invalid", "Solo una corrección admite valor revisado")
        return changes
    if claim["kind"] != "attribute":
        raise ReviewError("invalid", "Solo los atributos admiten corrección de valor; "
                                     "rechace la entidad o relación y registre la correcta")
    if corrected_value is None or not str(corrected_value).strip():
        raise ReviewError("invalid", "La corrección requiere el valor revisado")
    spec = ATTRIBUTES[claim["attribute"]]
    changes["reviewed_value_literal"] = str(corrected_value).strip()
    if spec.is_quantity:
        unit = corrected_unit if corrected_unit is not None else claim.get("unit_literal", "")
        try:
            quantity = parse_quantity(changes["reviewed_value_literal"], unit)
        except ValueError as exc:
            raise ReviewError("invalid", str(exc)) from exc
        if quantity.dimension not in spec.dimensions:
            raise ReviewError("invalid", f"La unidad «{unit}» no corresponde a {spec.name}")
        if spec.si_range and not spec.si_range[0] <= quantity.value_si <= spec.si_range[1]:
            raise ReviewError("invalid", f"{spec.name} fuera del rango físico admitido")
        changes.update(reviewed_unit_literal=unit, reviewed_value_si=quantity.value_si,
                       reviewed_unit=quantity.unit)
    elif spec.choices and changes["reviewed_value_literal"].casefold() not in spec.choices:
        raise ReviewError("invalid", f"Valor no admitido para {spec.name}")
    return changes


def effective_value(claim: dict) -> dict:
    """Valor vigente de un atributo: el revisado si existe, si no el propuesto."""
    if claim.get("reviewed_value_literal") is not None:
        return {"value_literal": claim["reviewed_value_literal"],
                "value_si": claim.get("reviewed_value_si"),
                "unit": claim.get("reviewed_unit", claim.get("unit"))}
    return {"value_literal": claim.get("value_literal"), "value_si": claim.get("value_si"),
            "unit": claim.get("unit")}


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
