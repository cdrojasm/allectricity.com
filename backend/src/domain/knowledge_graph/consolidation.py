"""Consolidación determinista de candidatos contra el grafo del proyecto (EG-06, EG-10).

Detecta duplicados, valores contradictorios y posibles alias. No fusiona entidades ni
reemplaza valores: anota la afirmación, la envía a revisión y formula una pregunta con
los IDs implicados. El grafo existente es evidencia, no verdad aceptada.
"""

import re

from src.domain.knowledge_graph.claims import (
    ACCEPTED, LIVE_STATUSES, NEEDS_REVIEW, REJECTED, effective_value, same_value, stable_key,
)


def _describe(claim: dict) -> str:
    value = effective_value(claim)
    literal = f"{value['value_literal']} {claim.get('unit_literal') or ''}".strip()
    origin = f" ({claim['filename']})" if claim.get("filename") else ""
    return f"{literal}{origin}"


def compact_tag(name: str) -> str:
    """Forma compacta de una etiqueta: T-01, T 1 y t1 comparten «T1»."""
    parts = re.findall(r"[A-Za-z]+|\d+", name)
    return "".join(part.lstrip("0") or "0" if part.isdigit() else part.upper() for part in parts)


def consolidate(project_id: str, candidates: list, existing: list) -> dict:
    """Marca duplicados/conflictos en los candidatos y devuelve preguntas de revisión.

    `candidates` deben tener `claim_id` y `content_key`; `existing` son afirmaciones previas
    del proyecto (ya excluidas las abiertas del mismo documento que serán reemplazadas).
    """
    questions = {}
    live_existing = [claim for claim in existing if claim.get("status") in LIVE_STATUSES]

    def ask(kind, claims, text):
        ids = sorted({claim["claim_id"] for claim in claims})
        key = stable_key(project_id, "question", kind, *sorted({c["content_key"] for c in claims}))
        question = questions.setdefault(key, {"key": key, "kind": kind, "question": text,
                                               "claim_ids": []})
        question["claim_ids"] = sorted(set(question["claim_ids"]) | set(ids))

    for claim in candidates:
        claim.setdefault("duplicate_of", [])
        claim.setdefault("contradicts", [])
        for other in existing:
            if other["content_key"] != claim["content_key"] or other["claim_id"] == claim["claim_id"]:
                continue
            if other.get("status") == REJECTED:
                claim["review_reasons"].append(
                    "Una revisión anterior rechazó esta misma afirmación")
                claim["status"] = NEEDS_REVIEW
            if other.get("status") in LIVE_STATUSES | {REJECTED}:
                claim["duplicate_of"].append(other["claim_id"])

    attributes = [c for c in candidates if c["kind"] == "attribute"]
    pool = attributes + [c for c in live_existing if c["kind"] == "attribute"]
    for claim in attributes:
        for other in pool:
            if (other is claim or other["claim_id"] == claim["claim_id"]
                    or other["entity_key"] != claim["entity_key"]
                    or other["attribute"] != claim["attribute"]
                    or (other.get("qualifier") or "") != (claim.get("qualifier") or "")
                    or same_value(effective_value(claim), effective_value(other))):
                continue
            claim["contradicts"].append(other["claim_id"])
            claim["status"] = NEEDS_REVIEW
            state = "aceptado" if other.get("status") == ACCEPTED else "propuesto"
            claim["review_reasons"].append(
                f"Contradice el valor {state} {_describe(other)} (afirmación {other['claim_id'][:12]})")
            subject = claim.get("subject_name") or claim["entity_key"][:12]
            ask("conflict", [claim, other],
                f"{subject}: {claim['attribute']} tiene valores distintos "
                f"({_describe(claim)} frente a {_describe(other)}). ¿Cuál es el correcto?")

    entities = [c for c in candidates if c["kind"] == "entity"]
    entity_pool = entities + [c for c in live_existing if c["kind"] == "entity"]
    for claim in entities:
        names = {claim["name"], *claim.get("aliases", [])}
        tags = {compact_tag(name) for name in names} - {""}
        for other in entity_pool:
            if (other is claim or other["entity_key"] == claim["entity_key"]
                    or other["entity_type"] != claim["entity_type"]):
                continue
            other_tags = {compact_tag(n) for n in (other["name"], *other.get("aliases", []))}
            if tags & other_tags:
                claim["review_reasons"].append(
                    f"Posible alias de «{other['name']}»; no se fusionó automáticamente")
                claim["status"] = NEEDS_REVIEW
                ask("alias", [claim, other],
                    f"¿«{claim['name']}» y «{other['name']}» ({claim['entity_type']}) "
                    "son el mismo elemento?")

    for claim in candidates:
        claim["review_reasons"] = list(dict.fromkeys(claim["review_reasons"]))
        claim["duplicate_of"] = sorted(set(claim["duplicate_of"]))
        claim["contradicts"] = sorted(set(claim["contradicts"]))
    return {"questions": list(questions.values())}
