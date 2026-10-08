"""Neo4j adapter for the provenance-first grounding knowledge graph (EG-02, EG-07, EG-23).

Modelo:
  (Project)-[:HAS_DOCUMENT]->(Document)-[:HAS_RUN]->(ExtractionRun)-[:PRODUCED]->(Claim)
  (Claim)-[:SUPPORTED_BY]->(Evidence)-[:FROM_DOCUMENT]->(Document)
  (Claim)-[:ABOUT]->(Entity)            afirmaciones de entidad y atributo
  (Claim)-[:SOURCE|TARGET]->(Entity)    afirmaciones de relación
  (Claim)-[:CONTRADICTS|DUPLICATE_OF|SUPERSEDES]->(Claim)
  (Claim)-[:REVIEWED_BY]->(ReviewDecision)
  (Document)-[:RAISES_QUESTION]->(ReviewQuestion)-[:ABOUT_CLAIM]->(Claim)
  (Entity)-[:<RELACIÓN> {claim_id}]->(Entity)   solo para relaciones aceptadas por una persona

Los nodos heredados `ElectricalAsset`/`ElectricalParameter` se conservan en solo lectura;
el pipeline nuevo ya no los escribe.
"""

import json
import os
import time

from src.application.ports.knowledge_graph import KnowledgeGraphRepository
from src.domain.knowledge_graph.claims import (
    ACCEPTED, LIVE_STATUSES, OPEN_STATUSES, REJECTED, REVIEWED_FIELDS, SUPERSEDED, stable_key,
)
from src.domain.knowledge_graph.taxonomy import ENTITY_TYPES, RELATION_RULES

MIGRATIONS = (
    (1, (
        "CREATE CONSTRAINT project_id_unique IF NOT EXISTS "
        "FOR (n:Project) REQUIRE n.project_id IS UNIQUE",
        "CREATE CONSTRAINT document_upload_unique IF NOT EXISTS "
        "FOR (n:Document) REQUIRE n.upload_id IS UNIQUE",
        "CREATE CONSTRAINT extraction_run_unique IF NOT EXISTS "
        "FOR (n:ExtractionRun) REQUIRE n.run_id IS UNIQUE",
        "CREATE CONSTRAINT claim_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE",
        "CREATE CONSTRAINT evidence_unique IF NOT EXISTS "
        "FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE",
        "CREATE CONSTRAINT entity_unique IF NOT EXISTS "
        "FOR (n:Entity) REQUIRE n.entity_key IS UNIQUE",
        "CREATE CONSTRAINT review_question_unique IF NOT EXISTS "
        "FOR (n:ReviewQuestion) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT review_decision_unique IF NOT EXISTS "
        "FOR (n:ReviewDecision) REQUIRE n.decision_id IS UNIQUE",
        "CREATE INDEX claim_project_status IF NOT EXISTS FOR (n:Claim) ON (n.project_id, n.status)",
        "CREATE INDEX claim_project_upload IF NOT EXISTS "
        "FOR (n:Claim) ON (n.project_id, n.upload_id)",
        "CREATE INDEX claim_entity_attribute IF NOT EXISTS "
        "FOR (n:Claim) ON (n.entity_key, n.attribute)",
        "CREATE INDEX entity_project IF NOT EXISTS FOR (n:Entity) ON (n.project_id)",
        "CREATE INDEX question_project_status IF NOT EXISTS "
        "FOR (n:ReviewQuestion) ON (n.project_id, n.status)",
        "CREATE INDEX run_project IF NOT EXISTS FOR (n:ExtractionRun) ON (n.project_id)",
    )),
)
SCHEMA_VERSION = MIGRATIONS[-1][0]

_JSON_FIELDS = ("confidence", "coverage", "ocr", "errors", "rejected", "notes", "metrics",
                "interrogation", "locator")
_CLAIM_FIELDS = (
    "claim_id", "kind", "content_key", "status", "methods", "finding_ids", "review_reasons",
    "ocr_quality", "ocr_needs_review", "feeds_calculation", "entity_key", "entity_type", "name",
    "aliases", "subject_name", "attribute", "value_literal", "unit_literal", "value", "value_si",
    "unit", "dimension", "qualifier", "relation_type", "symmetric", "source_key", "target_key",
    "source_type", "target_type", "source_name", "target_name",
)


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(record: dict) -> dict:
    """Propiedades Neo4j → dict, decodificando los campos JSON."""
    result = {}
    for key, value in record.items():
        if key.endswith("_json"):
            result[key[:-5]] = json.loads(value) if value else None
        else:
            result[key] = value
    return result


def _claim_props(claim: dict, run: dict, now: int) -> dict:
    props = {field: claim.get(field) for field in _CLAIM_FIELDS}
    confidence = claim.get("confidence") or {}
    props.update(project_id=run["project_id"], upload_id=run["upload_id"], run_id=run["run_id"],
                 created_at=now, updated_at=now, model=run.get("model"),
                 extractor_prompt_version=run.get("extractor_prompt_version"),
                 confidence_level=confidence.get("level"),
                 confidence_reason=confidence.get("reason"))
    return props


class Neo4jKnowledgeGraph(KnowledgeGraphRepository):
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self._schema_ready = False

    @classmethod
    def from_env(cls):
        uri = os.getenv("NEO4J_URI")
        if not uri:
            return None
        return cls(uri, os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""),
                   os.getenv("NEO4J_DATABASE", "neo4j"))

    def close(self):
        self.driver.close()

    def _session(self):
        return self.driver.session(database=self.database)

    # --- esquema -------------------------------------------------------------------------
    def ensure_schema(self) -> int:
        """Aplica migraciones pendientes; es repetible y registra cada versión aplicada."""
        if self._schema_ready:
            return SCHEMA_VERSION
        with self._session() as session:
            applied = {record["version"] for record in
                       session.run("MATCH (m:SchemaMigration) RETURN m.version AS version")}
            for version, statements in MIGRATIONS:
                if version in applied:
                    continue
                for statement in statements:
                    session.run(statement).consume()
                session.run("MERGE (m:SchemaMigration {version: $version}) "
                            "ON CREATE SET m.applied_at = $now",
                            version=version, now=int(time.time())).consume()
        self._schema_ready = True
        return SCHEMA_VERSION

    # --- ingesta -------------------------------------------------------------------------
    def run_exists(self, run_id: str) -> bool:
        self.ensure_schema()
        with self._session() as session:
            return session.run("MATCH (r:ExtractionRun {run_id: $run_id}) RETURN count(r) > 0 "
                               "AS found", run_id=run_id).single()["found"]

    def load_project_claims(self, project_id: str, exclude_open_upload_id: str | None = None,
                            limit: int = 5000) -> list:
        self.ensure_schema()
        with self._session() as session:
            result = session.run(
                "MATCH (c:Claim {project_id: $project_id}) "
                "WHERE c.status IN $statuses "
                "AND NOT (c.upload_id = $upload_id AND c.status IN $open) "
                "OPTIONAL MATCH (d:Document {upload_id: c.upload_id}) "
                "RETURN c {.*, filename: d.filename} AS claim "
                "ORDER BY c.created_at LIMIT $limit",
                project_id=project_id, upload_id=exclude_open_upload_id,
                statuses=sorted(LIVE_STATUSES | {REJECTED}), open=sorted(OPEN_STATUSES),
                limit=limit)
            return [_load(record["claim"]) for record in result]

    def save_run(self, run: dict) -> bool:
        """Persiste la ejecución completa en una única transacción; repetirla no duplica nada."""
        self.ensure_schema()
        with self._session() as session:
            return session.execute_write(self._write_run, run)

    @staticmethod
    def _write_run(tx, run: dict) -> bool:
        if tx.run("MATCH (r:ExtractionRun {run_id: $run_id}) RETURN r LIMIT 1",
                  run_id=run["run_id"]).single():
            return False
        now = int(time.time())
        tx.run(
            "MERGE (p:Project {project_id: $project_id}) "
            "MERGE (d:Document {upload_id: $upload_id}) "
            "SET d.project_id = $project_id, d.owner_id = $owner_id, d.filename = $filename, "
            "d.object_key = $object_key, d.mime_type = $mime_type, "
            "d.content_sha256 = $content_sha256, d.latest_run_id = $run_id, d.updated_at = $now "
            "MERGE (p)-[:HAS_DOCUMENT]->(d)",
            now=now, **{key: run.get(key) for key in (
                "project_id", "upload_id", "owner_id", "filename", "object_key", "mime_type",
                "content_sha256", "run_id")})
        run_props = {key: value for key, value in run.items()
                     if key not in {"claims", "questions", *_JSON_FIELDS}}
        run_props.update({f"{key}_json": _dump(run.get(key)) for key in _JSON_FIELDS
                          if key in run})
        tx.run(
            "MATCH (d:Document {upload_id: $upload_id}) "
            "CREATE (r:ExtractionRun) SET r = $props "
            "MERGE (d)-[:HAS_RUN]->(r) "
            "WITH d, r "
            "OPTIONAL MATCH (d)-[:HAS_RUN]->(old:ExtractionRun) "
            "WHERE old.run_id <> r.run_id AND old.superseded_by IS NULL "
            "FOREACH (_ IN CASE WHEN old IS NULL THEN [] ELSE [1] END | "
            "  SET old.superseded_by = r.run_id MERGE (r)-[:SUPERSEDES]->(old))",
            upload_id=run["upload_id"], props=run_props)
        # Una nueva versión reemplaza solo propuestas abiertas; las decisiones humanas quedan.
        tx.run(
            "MATCH (r:ExtractionRun {run_id: $run_id})-[:SUPERSEDES]->(:ExtractionRun)"
            "-[:PRODUCED]->(c:Claim) WHERE c.status IN $open "
            "SET c.status = $superseded, c.superseded_by_run = $run_id, c.updated_at = $now",
            run_id=run["run_id"], open=sorted(OPEN_STATUSES), superseded=SUPERSEDED, now=now)
        tx.run(
            "MATCH (d:Document {upload_id: $upload_id})-[:RAISES_QUESTION]->(q:ReviewQuestion "
            "{status: 'pending'}) "
            "WHERE NOT EXISTS { MATCH (q)-[:ABOUT_CLAIM]->(c:Claim) WHERE c.status IN $live } "
            "SET q.status = 'obsolete', q.updated_at = $now",
            upload_id=run["upload_id"], live=sorted(LIVE_STATUSES), now=now)

        entities = {}
        for claim in run["claims"]:
            if claim["kind"] == "entity":
                entities[claim["entity_key"]] = (claim["entity_type"], claim["name"])
            elif claim["kind"] == "attribute":
                entities.setdefault(claim["entity_key"],
                                    (claim["entity_type"], claim["subject_name"]))
            else:
                entities.setdefault(claim["source_key"], (claim["source_type"],
                                                          claim["source_name"]))
                entities.setdefault(claim["target_key"], (claim["target_type"],
                                                          claim["target_name"]))
        by_type = {}
        for key, (entity_type, name) in entities.items():
            by_type.setdefault(entity_type, []).append({"entity_key": key, "name": name})
        for entity_type, rows in by_type.items():
            if entity_type not in ENTITY_TYPES:  # la etiqueta solo sale de la taxonomía
                raise ValueError(f"Unknown entity type {entity_type}")
            tx.run(
                "MATCH (p:Project {project_id: $project_id}) "
                "UNWIND $rows AS row "
                f"MERGE (e:Entity {{entity_key: row.entity_key}}) "
                f"ON CREATE SET e:{entity_type}, e.project_id = $project_id, "
                "e.entity_type = $entity_type, e.name = row.name, e.created_at = $now "
                "MERGE (p)-[:HAS_ENTITY]->(e)",
                project_id=run["project_id"], entity_type=entity_type, rows=rows, now=now)

        claim_rows = [_claim_props(claim, run, now) for claim in run["claims"]]
        tx.run(
            "MATCH (r:ExtractionRun {run_id: $run_id}) "
            "UNWIND $rows AS row "
            "MERGE (c:Claim {claim_id: row.claim_id}) ON CREATE SET c = row "
            "MERGE (r)-[:PRODUCED]->(c) "
            "WITH c, row "
            "OPTIONAL MATCH (about:Entity {entity_key: row.entity_key}) "
            "OPTIONAL MATCH (source:Entity {entity_key: row.source_key}) "
            "OPTIONAL MATCH (target:Entity {entity_key: row.target_key}) "
            "FOREACH (_ IN CASE WHEN about IS NULL THEN [] ELSE [1] END | "
            "  MERGE (c)-[:ABOUT]->(about)) "
            "FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END | "
            "  MERGE (c)-[:SOURCE]->(source)) "
            "FOREACH (_ IN CASE WHEN target IS NULL THEN [] ELSE [1] END | "
            "  MERGE (c)-[:TARGET]->(target))",
            run_id=run["run_id"], rows=claim_rows)

        evidence_rows = []
        for claim in run["claims"]:
            for record in claim["evidence"]:
                locator = record["locator"]
                evidence_rows.append({
                    "claim_id": claim["claim_id"],
                    "evidence_id": stable_key(run["upload_id"], run["text_sha256"],
                                              record["start"], record["end"]),
                    "props": {"upload_id": run["upload_id"], "quote": record["quote"],
                              "start": record["start"], "end": record["end"],
                              "locator_json": _dump(locator), "page": locator.get("page"),
                              "sheet": locator.get("sheet"), "row": locator.get("row"),
                              "paragraph": locator.get("paragraph"),
                              "segment": locator.get("segment"),
                              "ocr_quality": record.get("ocr_quality"),
                              "ocr_needs_review": record.get("ocr_needs_review", False),
                              "text_sha256": run["text_sha256"]},
                })
        tx.run(
            "MATCH (d:Document {upload_id: $upload_id}) "
            "UNWIND $rows AS row "
            "MATCH (c:Claim {claim_id: row.claim_id}) "
            "MERGE (ev:Evidence {evidence_id: row.evidence_id}) ON CREATE SET ev += row.props "
            "MERGE (ev)-[:FROM_DOCUMENT]->(d) "
            "MERGE (c)-[:SUPPORTED_BY]->(ev)",
            upload_id=run["upload_id"], rows=evidence_rows)

        for relation, field in (("CONTRADICTS", "contradicts"), ("DUPLICATE_OF", "duplicate_of")):
            pairs = [{"a": claim["claim_id"], "b": other} for claim in run["claims"]
                     for other in claim.get(field, [])]
            tx.run(
                "UNWIND $pairs AS pair "
                "MATCH (a:Claim {claim_id: pair.a}), (b:Claim {claim_id: pair.b}) "
                f"MERGE (a)-[:{relation}]->(b)", pairs=pairs)

        for question in run["questions"]:
            tx.run(
                "MATCH (d:Document {upload_id: $upload_id}) "
                "MERGE (q:ReviewQuestion {key: $key}) "
                "ON CREATE SET q.project_id = $project_id, q.kind = $kind, "
                "q.question = $question, q.status = 'pending', q.created_at = $now "
                "ON MATCH SET q.status = CASE WHEN q.status IN ['resolved', 'obsolete', "
                "'dismissed'] THEN 'pending' ELSE q.status END, q.updated_at = $now "
                "MERGE (d)-[:RAISES_QUESTION]->(q) "
                "WITH q UNWIND $claim_ids AS claim_id "
                "MATCH (c:Claim {claim_id: claim_id}) MERGE (q)-[:ABOUT_CLAIM]->(c)",
                upload_id=run["upload_id"], project_id=run["project_id"], now=now,
                key=question["key"], kind=question.get("kind", "conflict"),
                question=question["question"], claim_ids=question["claim_ids"])
        return True

    # --- lectura (EG-11) -----------------------------------------------------------------
    def list_claims(self, project_id: str, *, status=None, upload_id=None, kind=None,
                    entity_type=None, attribute=None, limit=50, skip=0) -> dict:
        self.ensure_schema()
        filters = {"status": status, "upload_id": upload_id, "kind": kind,
                   "entity_type": entity_type, "attribute": attribute}
        where = " AND ".join(f"c.{name} = ${name}" for name, value in filters.items()
                             if value is not None)
        query = ("MATCH (c:Claim {project_id: $project_id}) "
                 + (f"WHERE {where} " if where else ""))
        with self._session() as session:
            total = session.run(query + "RETURN count(c) AS total", project_id=project_id,
                                **filters).single()["total"]
            result = session.run(
                query + "WITH c ORDER BY c.created_at DESC, c.claim_id SKIP $skip LIMIT $limit "
                "OPTIONAL MATCH (d:Document {upload_id: c.upload_id}) "
                "OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(ev:Evidence) "
                "WITH c, d, collect(ev {.quote, .locator_json, .page, .sheet, .row}) AS evidence "
                "RETURN c {.*, filename: d.filename} AS claim, evidence, "
                "COUNT { (c)-[:CONTRADICTS]-(other:Claim) WHERE other.status IN $live } "
                "AS conflicts ORDER BY claim.created_at DESC, claim.claim_id",
                project_id=project_id, live=sorted(LIVE_STATUSES), skip=skip, limit=limit,
                **filters)
            items = []
            for record in result:
                claim = _load(record["claim"])
                claim["evidence"] = [_load(item) for item in record["evidence"]]
                claim["conflict_count"] = record["conflicts"]
                items.append(claim)
        return {"items": items, "total": total, "limit": limit, "skip": skip}

    def get_claim(self, project_id: str, claim_id: str) -> dict | None:
        self.ensure_schema()
        with self._session() as session:
            record = session.run(
                "MATCH (c:Claim {project_id: $project_id, claim_id: $claim_id}) "
                "OPTIONAL MATCH (r:ExtractionRun {run_id: c.run_id}) "
                "OPTIONAL MATCH (d:Document {upload_id: c.upload_id}) "
                "CALL { WITH c OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(ev:Evidence)"
                "-[:FROM_DOCUMENT]->(src:Document) "
                "  RETURN collect(ev {.*, filename: src.filename, mime_type: src.mime_type}) "
                "AS evidence } "
                "CALL { WITH c OPTIONAL MATCH (c)-[:CONTRADICTS]-(o:Claim) "
                "  OPTIONAL MATCH (od:Document {upload_id: o.upload_id}) "
                "  RETURN collect(DISTINCT o {.*, filename: od.filename}) AS conflicts } "
                "CALL { WITH c OPTIONAL MATCH (c)-[:DUPLICATE_OF]-(o:Claim) "
                "  RETURN collect(DISTINCT o {.claim_id, .status, .upload_id}) AS duplicates } "
                "CALL { WITH c OPTIONAL MATCH (c)-[:SUPERSEDES]-(o:Claim) "
                "  RETURN collect(DISTINCT o {.claim_id, .status}) AS superseded } "
                "CALL { WITH c OPTIONAL MATCH (c)-[:REVIEWED_BY]->(rd:ReviewDecision) "
                "  WITH rd ORDER BY rd.decided_at RETURN collect(rd {.*}) AS decisions } "
                "CALL { WITH c OPTIONAL MATCH (q:ReviewQuestion)-[:ABOUT_CLAIM]->(c) "
                "  RETURN collect(q {.*}) AS questions } "
                "RETURN c {.*, filename: d.filename} AS claim, "
                "r {.run_id, .method, .model, .parser_version, .taxonomy_version, .schema_version, "
                "   .extractor_prompt_name, .extractor_prompt_version, "
                "   .consolidator_prompt_name, .consolidator_prompt_version, .started_at, "
                "   .status} AS run, evidence, conflicts, duplicates, superseded, decisions, "
                "questions",
                project_id=project_id, claim_id=claim_id).single()
        if record is None:
            return None
        claim = _load(record["claim"])
        claim.update(run=record["run"], evidence=[_load(e) for e in record["evidence"]],
                     conflicts=[_load(c) for c in record["conflicts"]],
                     duplicates=record["duplicates"], superseded=record["superseded"],
                     decisions=record["decisions"], questions=record["questions"])
        return claim

    def accepted_attribute_claims(self, project_id: str, entity_key: str, attribute: str,
                                  qualifier: str) -> list:
        with self._session() as session:
            result = session.run(
                "MATCH (c:Claim {project_id: $project_id, entity_key: $entity_key, "
                "attribute: $attribute, status: $accepted}) "
                "WHERE coalesce(c.qualifier, '') = $qualifier RETURN c {.*} AS claim",
                project_id=project_id, entity_key=entity_key, attribute=attribute,
                qualifier=qualifier or "", accepted=ACCEPTED)
            return [_load(record["claim"]) for record in result]

    def apply_decision(self, project_id: str, claim_id: str, *, expected_status: str,
                       changes: dict, decision: dict, supersede_ids=()) -> bool:
        """Aplica una decisión humana de forma atómica; falla si el estado cambió entretanto."""
        with self._session() as session:
            return session.execute_write(self._write_decision, project_id, claim_id,
                                         expected_status, changes, decision, list(supersede_ids))

    @staticmethod
    def _write_decision(tx, project_id, claim_id, expected_status, changes, decision,
                        supersede_ids) -> bool:
        now = decision["decided_at"]
        claim = tx.run(
            "MATCH (c:Claim {project_id: $project_id, claim_id: $claim_id, status: $expected}) "
            "SET c += $changes, c.updated_at = $now, c.reviewed_by = $actor, "
            "c.reviewed_at = $now "
            "CREATE (rd:ReviewDecision) SET rd = $decision "
            "MERGE (c)-[:REVIEWED_BY]->(rd) "
            "RETURN c {.*} AS claim",
            project_id=project_id, claim_id=claim_id, expected=expected_status,
            changes={**{field: None for field in REVIEWED_FIELDS}, **changes}, now=now,
            actor=decision["actor_id"], decision=decision).single()
        if claim is None:
            return False
        claim = claim["claim"]
        if supersede_ids:
            tx.run(
                "MATCH (c:Claim {claim_id: $claim_id}) "
                "UNWIND $ids AS other_id "
                "MATCH (o:Claim {project_id: $project_id, claim_id: other_id}) "
                "SET o.status = $superseded, o.updated_at = $now, o.superseded_by_claim = "
                "$claim_id MERGE (c)-[:SUPERSEDES]->(o)",
                claim_id=claim_id, ids=supersede_ids, project_id=project_id,
                superseded=SUPERSEDED, now=now)
        if claim["kind"] == "relation":
            relation = claim["relation_type"]
            if relation not in RELATION_RULES:
                raise ValueError(f"Unknown relation {relation}")
            if claim["status"] == ACCEPTED:
                tx.run(
                    "MATCH (c:Claim {claim_id: $claim_id})-[:SOURCE]->(s:Entity), "
                    "(c)-[:TARGET]->(t:Entity) "
                    f"MERGE (s)-[r:{relation} {{claim_id: $claim_id}}]->(t) "
                    "SET r.accepted_at = $now, r.accepted_by = $actor",
                    claim_id=claim_id, now=now, actor=decision["actor_id"])
            else:
                tx.run(f"MATCH ()-[r:{relation} {{claim_id: $claim_id}}]->() DELETE r",
                       claim_id=claim_id)
        return True

    def list_questions(self, project_id: str, status: str | None = "pending",
                       limit: int = 50, skip: int = 0) -> dict:
        self.ensure_schema()
        where = "WHERE q.status = $status " if status else ""
        with self._session() as session:
            total = session.run(
                f"MATCH (q:ReviewQuestion {{project_id: $project_id}}) {where}"
                "RETURN count(q) AS total", project_id=project_id, status=status
            ).single()["total"]
            result = session.run(
                f"MATCH (q:ReviewQuestion {{project_id: $project_id}}) {where}"
                "OPTIONAL MATCH (q)-[:ABOUT_CLAIM]->(c:Claim) "
                "OPTIONAL MATCH (d:Document)-[:RAISES_QUESTION]->(q) "
                "WITH q, collect(DISTINCT c {.claim_id, .kind, .status, .subject_name, "
                ".attribute, .value_literal, .unit_literal, .name, .entity_type, .upload_id}) "
                "AS claims, collect(DISTINCT d {.upload_id, .filename}) AS documents "
                "RETURN q {.*} AS question, claims, documents "
                "ORDER BY q.created_at DESC SKIP $skip LIMIT $limit",
                project_id=project_id, status=status, skip=skip, limit=limit)
            items = [dict(record["question"], claims=record["claims"],
                          documents=record["documents"],
                          open_claims=sum(c["status"] in OPEN_STATUSES
                                          for c in record["claims"]))
                     for record in result]
        return {"items": items, "total": total, "limit": limit, "skip": skip}

    def resolve_question(self, project_id: str, key: str, *, actor_id: str, status: str,
                         resolution: str) -> dict | None:
        with self._session() as session:
            record = session.run(
                "MATCH (q:ReviewQuestion {project_id: $project_id, key: $key}) "
                "SET q.status = $status, q.resolution = $resolution, q.resolved_by = $actor, "
                "q.resolved_at = $now, q.updated_at = $now RETURN q {.*} AS question",
                project_id=project_id, key=key, status=status, resolution=resolution,
                actor=actor_id, now=int(time.time())).single()
        return record["question"] if record else None

    def entity_map(self, project_id: str, limit: int = 300) -> dict:
        """Entidades con estado de sus afirmaciones y relaciones aceptadas o pendientes."""
        self.ensure_schema()
        with self._session() as session:
            nodes = [dict(record["entity"], claims=record["claims"]) for record in session.run(
                "MATCH (:Project {project_id: $project_id})-[:HAS_ENTITY]->(e:Entity) "
                "OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e) WHERE c.status IN $live "
                "WITH e, collect(c {.claim_id, .kind, .status, .attribute, .value_literal, "
                ".unit_literal, .qualifier}) AS claims "
                "RETURN e {.entity_key, .entity_type, .name} AS entity, claims "
                "ORDER BY e.entity_type, e.name LIMIT $limit",
                project_id=project_id, live=sorted(LIVE_STATUSES), limit=limit)]
            keys = [node["entity_key"] for node in nodes]
            edges = [record.data() for record in session.run(
                "MATCH (c:Claim {project_id: $project_id, kind: 'relation'})"
                "-[:SOURCE]->(s:Entity), (c)-[:TARGET]->(t:Entity) "
                "WHERE c.status IN $live AND s.entity_key IN $keys AND t.entity_key IN $keys "
                "RETURN c.claim_id AS claim_id, c.relation_type AS type, c.status AS status, "
                "s.entity_key AS source, t.entity_key AS target LIMIT $limit",
                project_id=project_id, live=sorted(LIVE_STATUSES), keys=keys, limit=limit * 3)]
        return {"nodes": nodes, "edges": edges, "truncated": len(nodes) >= limit}

    def summary(self, project_id: str) -> dict:
        """Conteos para depurar el grafo del proyecto sin recorrer todas las afirmaciones."""
        self.ensure_schema()
        with self._session() as session:
            by_status, by_kind = {}, {}
            for record in session.run(
                    "MATCH (c:Claim {project_id: $project_id}) "
                    "RETURN c.status AS status, c.kind AS kind, count(c) AS n",
                    project_id=project_id):
                by_status[record["status"]] = by_status.get(record["status"], 0) + record["n"]
                by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + record["n"]
            questions = {record["status"]: record["n"] for record in session.run(
                "MATCH (q:ReviewQuestion {project_id: $project_id}) "
                "RETURN q.status AS status, count(q) AS n", project_id=project_id)}
            conflicts = session.run(
                "MATCH (a:Claim {project_id: $project_id})-[:CONTRADICTS]-(b:Claim) "
                "WHERE a.status IN $live AND b.status IN $live AND a.claim_id < b.claim_id "
                "RETURN count(*) AS n", project_id=project_id, live=sorted(LIVE_STATUSES)
            ).single()["n"]
            entities = session.run(
                "MATCH (:Project {project_id: $project_id})-[:HAS_ENTITY]->(e:Entity) "
                "RETURN count(e) AS n", project_id=project_id).single()["n"]
            documents = [_load(record.data()) for record in session.run(
                "MATCH (:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:Document) "
                "OPTIONAL MATCH (r:ExtractionRun {run_id: d.latest_run_id}) "
                "RETURN d.upload_id AS upload_id, d.filename AS filename, "
                "d.mime_type AS mime_type, r.run_id AS run_id, r.status AS run_status, "
                "r.started_at AS started_at, r.metrics_json AS metrics_json "
                "ORDER BY d.filename", project_id=project_id)]
        return {"claims": {"total": sum(by_status.values()), "by_status": by_status,
                           "by_kind": by_kind},
                "questions": questions, "open_conflicts": conflicts, "entities": entities,
                "documents": documents}

    def project_llm_tokens(self, project_id: str) -> int:
        self.ensure_schema()
        with self._session() as session:
            return session.run(
                "MATCH (r:ExtractionRun {project_id: $project_id}) "
                "RETURN coalesce(sum(r.llm_tokens), 0) AS n", project_id=project_id
            ).single()["n"]

    def list_runs(self, project_id: str, upload_id: str | None = None, limit: int = 50) -> list:
        self.ensure_schema()
        where = "AND r.upload_id = $upload_id " if upload_id else ""
        with self._session() as session:
            result = session.run(
                "MATCH (r:ExtractionRun {project_id: $project_id}) "
                f"WHERE true {where}"
                "RETURN r {.*} AS run ORDER BY r.started_at DESC LIMIT $limit",
                project_id=project_id, upload_id=upload_id, limit=limit)
            return [_load(record["run"]) for record in result]

