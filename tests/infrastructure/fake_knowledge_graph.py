"""Grafo en memoria con la semántica del adaptador Neo4j, para tests de pipeline y API."""

import copy
from collections import Counter

from src.application.ports.knowledge_graph import KnowledgeGraphRepository
from src.domain.knowledge_graph.claims import (
    ACCEPTED, LIVE_STATUSES, OPEN_STATUSES, REJECTED, REVIEWED_FIELDS, SUPERSEDED,
)


class InMemoryKnowledgeGraph(KnowledgeGraphRepository):
    def __init__(self):
        self.runs, self.claims, self.questions, self.decisions = {}, {}, {}, []
        self.edges = set()  # relaciones materializadas (source, tipo, target, claim_id)
        self.saves = 0

    def run_exists(self, run_id):
        return run_id in self.runs

    def load_project_claims(self, project_id, exclude_open_upload_id=None, limit=5000):
        return [copy.deepcopy(c) for c in self.claims.values()
                if c["project_id"] == project_id
                and c["status"] in LIVE_STATUSES | {REJECTED}
                and not (c["upload_id"] == exclude_open_upload_id
                         and c["status"] in OPEN_STATUSES)][:limit]

    def save_run(self, run):
        if run["run_id"] in self.runs:
            return False
        self.saves += 1
        for old in self.runs.values():
            if old["upload_id"] == run["upload_id"] and not old.get("superseded_by"):
                old["superseded_by"] = run["run_id"]
                for claim in self.claims.values():
                    if claim["run_id"] == old["run_id"] and claim["status"] in OPEN_STATUSES:
                        claim["status"] = SUPERSEDED
        self.runs[run["run_id"]] = {k: v for k, v in run.items() if k not in {"claims",
                                                                             "questions"}}
        for claim in run["claims"]:
            self.claims.setdefault(claim["claim_id"], dict(
                copy.deepcopy(claim), project_id=run["project_id"], upload_id=run["upload_id"],
                run_id=run["run_id"], filename=run["filename"]))
        for question in run["questions"]:
            stored = self.questions.setdefault(question["key"], dict(
                question, project_id=run["project_id"], status="pending", claim_ids=[]))
            stored["claim_ids"] = sorted(set(stored["claim_ids"]) | set(question["claim_ids"]))
        return True

    def list_claims(self, project_id, *, status=None, upload_id=None, kind=None,
                    entity_type=None, attribute=None, limit=50, skip=0):
        items = [c for c in self.claims.values() if c["project_id"] == project_id
                 and all(value is None or c.get(name) == value for name, value in (
                     ("status", status), ("upload_id", upload_id), ("kind", kind),
                     ("entity_type", entity_type), ("attribute", attribute)))]
        return {"items": items[skip:skip + limit], "total": len(items), "limit": limit,
                "skip": skip}

    def get_claim(self, project_id, claim_id):
        claim = self.claims.get(claim_id)
        if not claim or claim["project_id"] != project_id:
            return None
        return dict(copy.deepcopy(claim),
                    decisions=[d for d in self.decisions if d["claim_id"] == claim_id])

    def accepted_attribute_claims(self, project_id, entity_key, attribute, qualifier):
        return [copy.deepcopy(c) for c in self.claims.values()
                if c["project_id"] == project_id and c.get("entity_key") == entity_key
                and c.get("attribute") == attribute and c["status"] == ACCEPTED
                and (c.get("qualifier") or "") == (qualifier or "")]

    def apply_decision(self, project_id, claim_id, *, expected_status, changes, decision,
                       supersede_ids=()):
        claim = self.claims.get(claim_id)
        if not claim or claim["status"] != expected_status:
            return False
        claim.update({field: None for field in REVIEWED_FIELDS}, **changes)
        self.decisions.append(decision)
        for other in supersede_ids:
            self.claims[other]["status"] = SUPERSEDED
        if claim["kind"] == "relation":
            edge = (claim["source_key"], claim["relation_type"], claim["target_key"], claim_id)
            (self.edges.add if claim["status"] == ACCEPTED else self.edges.discard)(edge)
        return True

    def list_questions(self, project_id, status="pending", limit=50, skip=0):
        items = [q for q in self.questions.values() if q["project_id"] == project_id
                 and (status is None or q["status"] == status)]
        return {"items": items[skip:skip + limit], "total": len(items), "limit": limit,
                "skip": skip}

    def resolve_question(self, project_id, key, *, actor_id, status, resolution):
        question = self.questions.get(key)
        if not question or question["project_id"] != project_id:
            return None
        question.update(status=status, resolution=resolution, resolved_by=actor_id)
        return question

    def entity_map(self, project_id, limit=300):
        return {"nodes": [], "edges": sorted(self.edges), "truncated": False}

    def list_runs(self, project_id, upload_id=None, limit=50):
        return [r for r in self.runs.values() if r["project_id"] == project_id
                and (upload_id is None or r["upload_id"] == upload_id)][:limit]

    def summary(self, project_id):
        claims = [c for c in self.claims.values() if c["project_id"] == project_id]
        live = {c["claim_id"] for c in claims if c["status"] in LIVE_STATUSES}
        conflicts = {tuple(sorted((c["claim_id"], other))) for c in claims
                     if c["claim_id"] in live for other in c.get("contradicts", [])
                     if other in live}
        runs = {r["upload_id"]: r for r in self.runs.values() if r["project_id"] == project_id
                and not r.get("superseded_by")}
        entities = {c.get(field) for c in claims
                    for field in ("entity_key", "source_key", "target_key") if c.get(field)}
        return {"claims": {"total": len(claims),
                           "by_status": dict(Counter(c["status"] for c in claims)),
                           "by_kind": dict(Counter(c["kind"] for c in claims))},
                "questions": dict(Counter(q["status"] for q in self.questions.values()
                                          if q["project_id"] == project_id)),
                "open_conflicts": len(conflicts), "entities": len(entities),
                "documents": [{"upload_id": r["upload_id"], "filename": r["filename"],
                               "mime_type": r.get("mime_type"), "run_id": r["run_id"],
                               "run_status": r["status"], "started_at": r["started_at"],
                               "metrics": r.get("metrics")}
                              for r in sorted(runs.values(), key=lambda r: r["filename"])]}
