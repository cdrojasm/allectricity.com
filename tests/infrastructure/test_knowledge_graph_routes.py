from src.infrastructure.processing.document_sources import DOCX_MIME
from src.infrastructure.processing.knowledge_extraction import extract_knowledge
from tests.infrastructure.fake_knowledge_graph import InMemoryKnowledgeGraph
from tests.infrastructure.test_identity import env, headers, human  # noqa: F401
from tests.infrastructure.test_knowledge_extraction import (
    LLM_PAYLOAD, MEMORIA, FakeAgents, docx,
)


def _project(client, tokens, services):
    project = client.post("/api/v1/projects", json={"name": "Subestación"},
                          headers=headers(tokens)).json()
    graph = InMemoryKnowledgeGraph()
    services.knowledge_graph = graph
    upload = {"id": "u1", "project_id": project["id"], "owner_id": "x", "filename": "m.docx",
              "object_key": "x/u1.docx"}
    extract_knowledge(upload, MEMORIA, DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    return f"/api/v1/projects/{project['id']}/knowledge-graph", graph, project


def test_review_flow_through_api(env):  # noqa: F811
    _, services, client, _, tokens, _ = env
    base, graph, project = _project(client, tokens, services)

    listed = client.get(f"{base}/claims", params={"kind": "attribute"}, headers=headers(tokens))
    assert listed.status_code == 200
    voltage = next(c for c in listed.json()["items"] if c["attribute"] == "rated_voltage")
    assert voltage["status"] == "needs_review"

    detail = client.get(f"{base}/claims/{voltage['claim_id']}", headers=headers(tokens)).json()
    assert detail["evidence"][0]["locator"]["paragraph"] == 1

    invalid = client.post(f"{base}/claims/{voltage['claim_id']}/decision",
                          json={"decision": "correct", "reason": "Placa", "corrected_value": "x"},
                          headers=headers(tokens))
    assert invalid.status_code == 422

    corrected = client.post(f"{base}/claims/{voltage['claim_id']}/decision",
                            json={"decision": "correct", "reason": "Placa del equipo",
                                  "corrected_value": "13,2", "corrected_unit": "kV"},
                            headers=headers(tokens))
    assert corrected.status_code == 200
    body = corrected.json()
    assert body["status"] == "accepted" and body["value_literal"] == "13,8"
    assert body["decisions"][0]["actor_id"] and body["decisions"][0]["reason"] == "Placa del equipo"

    # Otro documento con 13,8 kV ya no puede aceptarse sin reemplazar el valor corregido.
    upload = {"id": "u2", "project_id": project["id"], "owner_id": "x", "filename": "b.docx",
              "object_key": "x/u2.docx"}
    extract_knowledge(upload, docx("El transformador T1, 13,8 kV, alimenta el tablero TD-2."),
                      DOCX_MIME, graph, agents=FakeAgents(LLM_PAYLOAD))
    second = next(c for c in graph.claims.values()
                  if c["upload_id"] == "u2" and c.get("attribute") == "rated_voltage")
    conflict = client.post(f"{base}/claims/{second['claim_id']}/decision",
                           json={"decision": "accept", "reason": "Memoria nueva"},
                           headers=headers(tokens))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["claim_ids"] == [voltage["claim_id"]]

    summary = client.get(f"{base}/summary", headers=headers(tokens)).json()
    assert summary["open_conflicts"] == 1 and len(summary["documents"]) == 2
    assert summary["claims"]["by_status"]["accepted"] == 1
    assert summary["questions"]["pending"] >= 1

    questions = client.get(f"{base}/questions", headers=headers(tokens)).json()["items"]
    assert questions and questions[0]["kind"] == "conflict"
    resolved = client.post(f"{base}/questions/{questions[0]['key']}/resolution",
                           json={"status": "resolved", "resolution": "Prevalece la placa"},
                           headers=headers(tokens))
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert client.get(f"{base}/runs", headers=headers(tokens)).json()["items"]


def test_project_authorization_and_permissions(env):  # noqa: F811
    _, services, client, admin_actor, tokens, _ = env
    base, graph, _ = _project(client, tokens, services)
    _, other_tokens, _ = human(services, admin_actor, "other@example.com", "designer")
    assert client.get(f"{base}/claims", headers=headers(other_tokens)).status_code == 404
    _, viewer_tokens, _ = human(services, admin_actor, "viewer@example.com")  # rol viewer por defecto
    claim_id = next(iter(graph.claims))
    response = client.post(f"{base}/claims/{claim_id}/decision",
                           json={"decision": "accept", "reason": "ok ok"},
                           headers=headers(viewer_tokens))
    assert response.status_code == 403


def test_graph_not_configured_returns_503(env):  # noqa: F811
    _, services, client, _, tokens, _ = env
    project = client.post("/api/v1/projects", json={"name": "P"}, headers=headers(tokens)).json()
    services.knowledge_graph = None
    response = client.get(f"/api/v1/projects/{project['id']}/knowledge-graph/claims",
                          headers=headers(tokens))
    assert response.status_code == 503
