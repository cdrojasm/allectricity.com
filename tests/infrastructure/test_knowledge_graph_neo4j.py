"""Integración con Neo4j real; se ejecuta solo si NEO4J_TEST_URI está definido."""

import os
from uuid import uuid4

import pytest

from src.application.use_cases.knowledge_review import KnowledgeReview
from src.domain.knowledge_graph.claims import ACCEPTED, ReviewError, SUPERSEDED
from src.infrastructure.processing.document_sources import DOCX_MIME
from src.infrastructure.processing.knowledge_extraction import extract_knowledge
from tests.infrastructure.test_knowledge_extraction import LLM_PAYLOAD, MEMORIA, FakeAgents, docx

pytestmark = pytest.mark.skipif(not os.getenv("NEO4J_TEST_URI"),
                                reason="NEO4J_TEST_URI no configurado")


@pytest.fixture
def graph():
    from src.infrastructure.persistence.knowledge_graph_store import Neo4jKnowledgeGraph

    store = Neo4jKnowledgeGraph(os.environ["NEO4J_TEST_URI"],
                                os.getenv("NEO4J_TEST_USER", "neo4j"),
                                os.getenv("NEO4J_TEST_PASSWORD", ""),
                                os.getenv("NEO4J_TEST_DATABASE", "neo4j"))
    project_id = f"test-{uuid4()}"
    yield store, project_id
    with store._session() as session:
        session.run("MATCH (:Claim {project_id: $p})-[:REVIEWED_BY]->(d) DETACH DELETE d",
                    p=project_id).consume()
        session.run("MATCH (e:Evidence) WHERE e.upload_id STARTS WITH $p DETACH DELETE e",
                    p=project_id).consume()
        session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=project_id).consume()
    store.close()


def _upload(project_id, upload_id):
    return {"id": f"{project_id}-{upload_id}", "project_id": project_id, "owner_id": "user-1",
            "filename": f"{upload_id}.docx", "object_key": f"user-1/{upload_id}.docx"}


def _count(store, query, **params):
    with store._session() as session:
        return session.run(query, **params).single()[0]


def test_persistence_is_atomic_idempotent_and_reviewable(graph):
    store, project_id = graph
    upload = _upload(project_id, "memoria")
    _, run = extract_knowledge(upload, MEMORIA, DOCX_MIME, store, agents=FakeAgents(LLM_PAYLOAD))
    claims = _count(store, "MATCH (c:Claim {project_id: $p}) RETURN count(c)", p=project_id)
    evidence = _count(store, "MATCH (:Claim {project_id: $p})-[:SUPPORTED_BY]->(e:Evidence) "
                             "RETURN count(DISTINCT e)", p=project_id)
    assert claims >= 5 and evidence >= 2

    # Reintento: mismo run_id, nada duplicado; guardar el mismo run directamente tampoco.
    _, again = extract_knowledge(upload, MEMORIA, DOCX_MIME, store, agents=FakeAgents(LLM_PAYLOAD))
    assert again["status"] == "already_processed"
    assert store.project_llm_tokens(project_id) == 1550  # el reintento no suma tokens
    assert _count(store, "MATCH (c:Claim {project_id: $p}) RETURN count(c)", p=project_id) == claims
    assert _count(store, "MATCH (e:Entity {project_id: $p}) RETURN count(e)", p=project_id) == 2

    listed = store.list_claims(project_id, kind="attribute", attribute="rated_voltage")
    voltage = listed["items"][0]
    assert voltage["evidence"][0]["locator"]["paragraph"] == 1
    detail = store.get_claim(project_id, voltage["claim_id"])
    assert detail["run"]["model"] == "fake-model" and detail["evidence"][0]["filename"]

    review = KnowledgeReview(store)
    review.decide(project_id, voltage["claim_id"], "reviewer", "accept", "Placa del equipo")
    relation = store.list_claims(project_id, kind="relation")["items"][0]
    review.decide(project_id, relation["claim_id"], "reviewer", "accept", "Unifilar")
    assert _count(store, "MATCH (:Entity {project_id: $p})-[r:SUPPLIES]->(:Entity) "
                         "RETURN count(r)", p=project_id) == 1
    entity_map = store.entity_map(project_id)
    assert {edge["status"] for edge in entity_map["edges"]} == {ACCEPTED}

    other = dict(LLM_PAYLOAD, evidence=[dict(LLM_PAYLOAD["evidence"][0],
                                              quote=LLM_PAYLOAD["evidence"][0]["quote"]
                                              .replace("13,8", "13,2"))],
                 attributes=[dict(LLM_PAYLOAD["attributes"][0], value="13,2")])
    extract_knowledge(_upload(project_id, "placa"),
                      docx("El transformador T1, 13,2 kV, alimenta el tablero TD-2."),
                      DOCX_MIME, store, agents=FakeAgents(other))
    second = next(c for c in store.list_claims(project_id, attribute="rated_voltage")["items"]
                  if c["claim_id"] != voltage["claim_id"])
    assert second["conflict_count"] == 1
    questions = store.list_questions(project_id)["items"]
    assert any(q["kind"] == "conflict" for q in questions)
    summary = store.summary(project_id)
    assert summary["open_conflicts"] == 1 and summary["entities"] == 2
    assert summary["claims"]["total"] == sum(summary["claims"]["by_status"].values())
    assert len(summary["documents"]) == 2 and summary["documents"][0]["metrics"]["claims"]
    with pytest.raises(ReviewError):
        review.decide(project_id, second["claim_id"], "reviewer", "accept", "Placa en sitio")
    review.decide(project_id, second["claim_id"], "reviewer", "accept", "Placa en sitio",
                  supersede_claim_ids=[voltage["claim_id"]])
    assert store.get_claim(project_id, voltage["claim_id"])["status"] == SUPERSEDED

    # Una versión nueva de prompt reemplaza solo propuestas abiertas del documento.
    extract_knowledge(upload, MEMORIA, DOCX_MIME, store,
                      agents=FakeAgents(LLM_PAYLOAD, version=2))
    assert store.get_claim(project_id, relation["claim_id"])["status"] == ACCEPTED
    runs = store.list_runs(project_id, upload["id"])
    assert len(runs) == 2
    assert {run.get("superseded_by") for run in runs} == {None, *(r["run_id"] for r in runs
                                                                    if not r.get("superseded_by"))}


def test_schema_migrations_are_repeatable(graph):
    store, _ = graph
    store._schema_ready = False
    assert store.ensure_schema() == store.ensure_schema()
    names = {record["name"] for record in store.driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN name", database_=store.database).records}
    assert {"claim_unique", "evidence_unique", "extraction_run_unique"} <= names
