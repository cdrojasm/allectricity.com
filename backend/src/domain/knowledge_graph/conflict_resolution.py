"""Resolución explícita de candidatas contradictorias del grafo (PR-21).

La resolución es una recomendación, no una decisión humana del grafo: nunca cambia el
estado de una afirmación. Una afirmación aceptada por una persona tiene prioridad. Para
las demás, la prioridad es tipo de documento (si el caso la configura) y fecha de fuente;
si el desempate no es único se devuelve una pregunta.
"""

from collections import defaultdict
from datetime import date, datetime

from src.domain.knowledge_graph.claims import ACCEPTED, LIVE_STATUSES, effective_value, same_value


DEFAULT_DOCUMENT_PREFERENCE = (
    "as_built", "as-built", "calculation", "study", "specification", "design", "report",
)


def _group_key(claim: dict) -> tuple:
    return (claim.get("entity_key") or (claim.get("entity_type"), claim.get("subject_name")),
            claim.get("attribute"), claim.get("qualifier") or "")


def _date_value(claim: dict):
    value = (claim.get("document_date") or claim.get("source_date")
             or claim.get("created_at") or claim.get("upload_created_at"))
    if value is None:
        return (0, "")
    if isinstance(value, (int, float)):
        return (1, float(value))
    text = str(value).strip()
    try:
        return (1, datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        try:
            return (1, date.fromisoformat(text).toordinal())
        except ValueError:
            return (0, text)


def _document_rank(claim: dict, preference: tuple[str, ...]) -> int:
    document_type = str(claim.get("document_type") or claim.get("doc_type") or "").casefold()
    for index, preferred in enumerate(preference):
        if document_type == preferred.casefold():
            return len(preference) - index
    return 0


def _distinct_values(claims: list[dict]) -> list[dict]:
    values = []
    for claim in claims:
        if not any(same_value(effective_value(claim), effective_value(other)) for other in values):
            values.append(claim)
    return values


def _question(group: tuple, candidates: list[dict]) -> dict:
    subject, attribute, qualifier = group
    names = ", ".join(str(c.get("value_literal") or c.get("value_si")) for c in candidates)
    subject_name = next((c.get("subject_name") for c in candidates if c.get("subject_name")), subject)
    return {
        "kind": "conflict",
        "subject": subject_name,
        "attribute": attribute,
        "qualifier": qualifier or None,
        "claim_ids": [c.get("claim_id") for c in candidates],
        "question": f"{subject_name}: {attribute} tiene valores contradictorios ({names}). ¿Cuál es el correcto?",
    }


def resolve_conflicts(claims: list[dict], *, document_preference=DEFAULT_DOCUMENT_PREFERENCE) -> dict:
    """Resuelve conflictos de atributos sin mutar afirmaciones.

    Devuelve ``entries`` con ``state`` igual a ``encontrado`` o ``conflicto``. Una entrada
    en conflicto incluye ``selected=None`` y una pregunta si no hay un único ganador.
    ``document_preference`` recibe tipos normalizados por el integrador del documento,
    de más a menos preferido.
    """
    groups = defaultdict(list)
    for claim in claims:
        if claim.get("kind") == "attribute" and claim.get("status") in LIVE_STATUSES:
            groups[_group_key(claim)].append(claim)

    entries = []
    questions = []
    for group, candidates in groups.items():
        different = _distinct_values(candidates)
        if len(different) <= 1:
            entries.append({"key": group, "state": "encontrado", "selected": candidates[0],
                            "candidates": candidates, "question": None})
            continue

        accepted = [claim for claim in different if claim.get("status") == ACCEPTED]
        pool = accepted if accepted else different
        ranked = sorted(pool, key=lambda claim: (
            _document_rank(claim, tuple(document_preference)), _date_value(claim),
            str(claim.get("claim_id") or "")), reverse=True)
        winner = ranked[0]
        tied = [claim for claim in ranked if (
            _document_rank(claim, tuple(document_preference)), _date_value(claim)) == (
                _document_rank(winner, tuple(document_preference)), _date_value(winner))]
        selected = winner if len(tied) == 1 else None
        question = None if selected else _question(group, different)
        if question:
            questions.append(question)
        entries.append({"key": group, "state": "encontrado" if selected else "conflicto",
                        "selected": selected, "candidates": candidates, "question": question})

    return {"entries": entries, "questions": questions}


__all__ = ["DEFAULT_DOCUMENT_PREFERENCE", "resolve_conflicts"]
