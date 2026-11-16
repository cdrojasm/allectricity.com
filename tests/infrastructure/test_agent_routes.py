import json

import pytest

from src.application.use_cases.agent_runs import FAILED_TEXT, UNAVAILABLE_TEXT, AgentRuns, run_step
from src.infrastructure.entrypoint.api import chat_routes
from tests.infrastructure.test_identity import env, headers, human  # noqa: F401

ARTIFACT = {"name": "Malla S/E", "geometry": {"length_m": 40, "width_m": 30, "conductor_spacing_m": 5},
            "soil_layers": [{"resistivity_ohm_m": 100}], "fault": {"current_a": 5000, "clearing_time_s": 0.5}}


@pytest.fixture
def chat(env, monkeypatch):  # noqa: F811
    _, services, client, admin_actor, tokens, _ = env
    queued = []
    monkeypatch.setattr(chat_routes, "enqueue_agent_step", queued.append)
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    conversation = client.post(f"/api/v1/projects/{project['id']}/conversations", json={},
                               headers=headers(tokens)).json()
    return services, client, tokens, project, conversation, queued, admin_actor


def send(client, tokens, conversation, text):
    response = client.post(f"/api/v1/conversations/{conversation['id']}/messages", json={"text": text},
                           headers=headers(tokens))
    assert response.status_code == 201, response.text
    return response.json()


def events(client, tokens, conversation, after=None):
    params = {} if after is None else {"after": after}
    response = client.get(f"/api/v1/conversations/{conversation['id']}/agent-events", params=params,
                          headers=headers(tokens))
    assert response.status_code == 200, response.text
    return response.json()


def stream(client, tokens, conversation, **params):
    with client.stream("GET", f"/api/v1/conversations/{conversation['id']}/agent-stream", params=params,
                       headers=headers(tokens)) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    parsed = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def messages(client, tokens, conversation):
    return client.get(f"/api/v1/conversations/{conversation['id']}/messages/first",
                      headers=headers(tokens)).json()


def by_id(listed):
    return {m["id"]: m for m in listed}


def test_message_starts_run_and_polling_reports_progress(chat):
    services, client, tokens, _, conversation, queued, _ = chat
    first = send(client, tokens, conversation, "Diseña la malla")
    assert first["run_id"] and queued == [first["run_id"]]
    polled = events(client, tokens, conversation)
    assert polled["active_run"]["status"] == "queued" and polled["active_run"]["mode"] == "asistido"
    assert polled["poll_after_ms"] == 1500 and polled["events"] == []

    # A message while the run is active goes to its inbox: no second run, no new step.
    second = send(client, tokens, conversation, "Usa varillas de 3 m")
    assert second["run_id"] == first["run_id"] and len(queued) == 1

    run_step(services.store, first["run_id"])
    polled = events(client, tokens, conversation, after=0)
    assert [e["type"] for e in polled["events"]] == ["message.received", "run.started", "run.completed"]
    assert [e["seq"] for e in polled["events"]] == [1, 2, 3] and polled["next_after"] == 3
    assert polled["active_run"] is None and polled["poll_after_ms"] is None
    assert events(client, tokens, conversation, after=3)["events"] == []

    listed = messages(client, tokens, conversation)
    found = by_id(listed)
    assert found[first["id"]]["status"] == found[second["id"]]["status"] == "completed"
    answers = [m for m in listed if m["source"] == "agent"]
    assert [m["text"] for m in answers] == [UNAVAILABLE_TEXT] and answers[0]["run_id"] == first["run_id"]
    since = client.get(f"/api/v1/conversations/{conversation['id']}/messages/since",
                       params={"after": listed[0]["id"]}, headers=headers(tokens)).json()
    assert [m["id"] for m in since] == [m["id"] for m in listed[1:]]

    # A repeated step (broker redelivery) does nothing.
    run_step(services.store, first["run_id"])
    assert len(messages(client, tokens, conversation)) == len(listed)

    # The next message after completion starts a new run.
    third = send(client, tokens, conversation, "Ahora recalcula")
    assert third["run_id"] != first["run_id"] and queued[-1] == third["run_id"]


def test_stream_announces_ready_message_then_closes(chat):
    services, client, tokens, _, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Hola")
    timeout = stream(client, tokens, conversation, wait=1)
    assert timeout == [("timeout", {"run_id": sent["run_id"], "status": "queued"})]

    run_step(services.store, sent["run_id"])
    received = stream(client, tokens, conversation)
    assert [name for name, _ in received] == ["message.ready", "run.idle"]
    ready = received[0][1]
    assert ready["source"] == "agent" and ready["run_id"] == sent["run_id"]
    assert received[1][1]["status"] == "completed"

    with client.stream("GET", f"/api/v1/conversations/{conversation['id']}/agent-stream",
                       headers={**headers(tokens), "Last-Event-ID": ready["id"]}) as response:
        assert "message.ready" not in "".join(response.iter_text())


def test_cancel_queued_and_running_runs(chat):
    services, client, tokens, _, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Diseña")
    cancelled = client.post(f"/api/v1/agent-runs/{sent['run_id']}/cancel", headers=headers(tokens))
    assert cancelled.status_code == 202 and cancelled.json()["status"] == "cancelled"
    run_step(services.store, sent["run_id"])  # a late step finds nothing to do
    listed = messages(client, tokens, conversation)
    assert by_id(listed)[sent["id"]]["status"] == "cancelled"
    assert sorted(m["source"] for m in listed) == ["notification", "user"]
    assert events(client, tokens, conversation)["events"][-1]["type"] == "run.cancelled"
    again = client.post(f"/api/v1/agent-runs/{sent['run_id']}/cancel", headers=headers(tokens))
    assert again.status_code == 409

    # A running step finishes its work first; the answer is discarded.
    sent = send(client, tokens, conversation, "Otra vez")
    runs = AgentRuns(services.store)
    assert runs.begin_step(sent["run_id"])["status"] == "running"
    via_message = client.post(f"/api/v1/messages/{sent['id']}/cancel", headers=headers(tokens)).json()
    assert via_message["cancelled"] and via_message["run"]["status"] == "cancelling"
    assert runs.complete(sent["run_id"], "respuesta")["status"] == "cancelled"
    assert not any(m["source"] == "agent" for m in messages(client, tokens, conversation))


def test_failures_close_the_run(chat, monkeypatch):
    services, client, tokens, _, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Diseña")

    def broken(run, runs):
        raise RuntimeError("LLM down")

    with pytest.raises(RuntimeError):
        run_step(services.store, sent["run_id"], agent=broken)
    run = client.get(f"/api/v1/agent-runs/{sent['run_id']}", headers=headers(tokens)).json()
    assert run["status"] == "failed" and "LLM down" in run["error"]
    listed = messages(client, tokens, conversation)
    assert by_id(listed)[sent["id"]]["status"] == "failed"
    assert [m["text"] for m in listed if m["source"] == "agent"] == [FAILED_TEXT]

    def no_broker(run_id):
        raise ConnectionError("redis")

    monkeypatch.setattr(chat_routes, "enqueue_agent_step", no_broker)
    response = client.post(f"/api/v1/conversations/{conversation['id']}/messages", json={"text": "x"},
                           headers=headers(tokens))
    assert response.status_code == 503
    assert events(client, tokens, conversation)["active_run"] is None


def test_agent_state_and_authorization(chat):
    services, client, tokens, project, conversation, _, admin_actor = chat
    base = f"/api/v1/conversations/{conversation['id']}/agent-state"
    state = client.get(base, headers=headers(tokens)).json()
    assert state["mode"] == "asistido" and state["artifact_id"] is None
    assert client.put(base, json={"mode": "autonomo"}, headers=headers(tokens)).json()["mode"] == "autonomo"
    assert client.put(base, json={"mode": "libre"}, headers=headers(tokens)).status_code == 422
    missing = client.put(base, json={"artifact_id": "0" * 36}, headers=headers(tokens))
    assert missing.status_code == 404
    artifact = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=ARTIFACT,
                           headers=headers(tokens)).json()
    assert artifact["origin"] == {"kind": "user"}
    chosen = client.put(base, json={"artifact_id": artifact["artifact_id"]}, headers=headers(tokens)).json()
    assert chosen["artifact_id"] == artifact["artifact_id"]

    sent = send(client, tokens, conversation, "Diseña")
    run = client.get(f"/api/v1/agent-runs/{sent['run_id']}", headers=headers(tokens)).json()
    assert run["mode"] == "autonomo" and run["artifact_id"] == artifact["artifact_id"]
    blocked = client.put(base, json={"artifact_id": "1" * 36}, headers=headers(tokens))
    assert blocked.status_code == 409

    _, other_tokens, _ = human(services, admin_actor, "other@example.com", "designer")
    assert events(client, tokens, conversation)["active_run"]["id"] == sent["run_id"]
    for response in (
        client.get(f"/api/v1/conversations/{conversation['id']}/agent-events", headers=headers(other_tokens)),
        client.get(f"/api/v1/agent-runs/{sent['run_id']}", headers=headers(other_tokens)),
        client.post(f"/api/v1/agent-runs/{sent['run_id']}/cancel", headers=headers(other_tokens)),
        client.get(f"/api/v1/conversations/{conversation['id']}/agent-stream", headers=headers(other_tokens)),
    ):
        assert response.status_code == 404


def test_autonomous_optimization_run_starts_from_the_current_completed_calculation(chat):
    services, client, tokens, project, conversation, _, actor = chat
    artifact = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=ARTIFACT,
                           headers=headers(tokens)).json()
    client.put(f"/api/v1/conversations/{conversation['id']}/agent-state",
               json={"mode": "autonomo", "artifact_id": artifact["artifact_id"]}, headers=headers(tokens))
    calculation_id = "00000000-0000-4000-8000-000000000001"
    with services.store.transaction(write=True) as db:
        db.add("calculos_potencial_tierras", id=calculation_id, project_id=project["id"],
               artifact_id=artifact["artifact_id"], artifact_version=artifact["version"], status="completed",
               parameters={}, result={}, trace=None, error=None, created_by=actor.user_id,
               created_at=1, updated_at=2)

    sent = send(client, tokens, conversation,
                "Optimiza el diseño hasta que cumpla la norma; parte del último cálculo de esta versión")
    with services.store.transaction() as db:
        run = db.one("agent_runs", id=sent["run_id"])
    assert run["mode"] == "autonomo"
    assert run["artifact_id"] == artifact["artifact_id"]
    assert run["pending_calculation_id"] == calculation_id
