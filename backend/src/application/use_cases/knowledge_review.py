"""Revisión humana de afirmaciones del grafo (EG-08).

Cada decisión registra usuario, fecha, motivo y estados anterior/nuevo. Una corrección
guarda el valor revisado sin borrar el propuesto ni su evidencia. Aceptar un valor que
contradice otro ya aceptado exige reemplazarlo de forma explícita.
"""

import time
from uuid import uuid4

from src.application.ports.knowledge_graph import KnowledgeGraphRepository
from src.domain.knowledge_graph.claims import (
    ACCEPTED, REVIEWED_FIELDS, ReviewError, effective_value, review_decision, same_value,
)

QUESTION_STATUSES = ("resolved", "dismissed")


class KnowledgeReview:
    def __init__(self, graph: KnowledgeGraphRepository):
        self.graph = graph

    def decide(self, project_id: str, claim_id: str, actor_id: str, decision: str, reason: str,
               corrected_value: str | None = None, corrected_unit: str | None = None,
               supersede_claim_ids=()) -> dict:
        claim = self.graph.get_claim(project_id, claim_id)
        if claim is None:
            raise ReviewError("not_found", "Claim not found")
        changes = review_decision(claim, decision, reason, corrected_value, corrected_unit)
        supersede = sorted(set(supersede_claim_ids))
        if changes["status"] == ACCEPTED and claim["kind"] == "attribute":
            proposed = {**claim, **changes}
            competing = [
                other for other in self.graph.accepted_attribute_claims(
                    project_id, claim["entity_key"], claim["attribute"], claim.get("qualifier"))
                if other["claim_id"] != claim_id
            ]
            conflicting = [other for other in competing
                           if not same_value(effective_value(proposed), effective_value(other))]
            unresolved = [other["claim_id"] for other in conflicting
                          if other["claim_id"] not in supersede]
            if unresolved:
                raise ReviewError(
                    "conflict", "Otro valor aceptado contradice esta afirmación; indique en "
                                "supersede_claim_ids cuál reemplaza", {"claim_ids": unresolved})
            allowed = {other["claim_id"] for other in competing}
            if set(supersede) - allowed:
                raise ReviewError("invalid", "Solo se pueden reemplazar valores aceptados del "
                                             "mismo atributo y entidad")
        elif supersede:
            raise ReviewError("invalid", "Solo la aceptación de un atributo reemplaza valores")
        record = {"decision_id": str(uuid4()), "claim_id": claim_id, "decision": decision,
                  "reason": reason.strip()[:2000], "actor_id": actor_id,
                  "decided_at": int(time.time()), "previous_status": claim["status"],
                  "new_status": changes["status"], "supersedes": supersede,
                  **{field: changes.get(field) for field in REVIEWED_FIELDS}}
        applied = self.graph.apply_decision(project_id, claim_id,
                                            expected_status=claim["status"], changes=changes,
                                            decision=record, supersede_ids=supersede)
        if not applied:
            raise ReviewError("conflict", "La afirmación cambió mientras se revisaba; recárguela")
        return self.graph.get_claim(project_id, claim_id)

    def resolve_question(self, project_id: str, key: str, actor_id: str, status: str,
                         resolution: str) -> dict:
        if status not in QUESTION_STATUSES:
            raise ReviewError("invalid", "Estado de pregunta no admitido")
        if not resolution or not resolution.strip():
            raise ReviewError("invalid", "La resolución requiere un texto")
        question = self.graph.resolve_question(project_id, key, actor_id=actor_id,
                                               status=status, resolution=resolution.strip()[:2000])
        if question is None:
            raise ReviewError("not_found", "Question not found")
        return question
