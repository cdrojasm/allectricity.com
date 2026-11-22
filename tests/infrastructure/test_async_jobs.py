"""Background jobs: slow routes answer 202, a worker runs the job, clients poll /api/v1/jobs/{id}."""

import json
from types import SimpleNamespace

import pytest

from src.application.use_cases import async_jobs
from src.application.use_cases.async_jobs import JobFailure
from src.domain import jobs
from src.domain.jobs import InvalidJobTransition, JobKind, JobStatus
from src.infrastructure.entrypoint.worker import tasks
from src.infrastructure.services import async_job_handlers
from src.infrastructure.services.async_job_handlers import HANDLERS
from tests.infrastructure.test_identity import PASSWORD, env, headers, human  # noqa: F401

READINGS = [{"spacing_m": a, "apparent_resistivity_ohm_m": r} for a, r in
            [(1, 180), (2, 160), (4, 130), (8, 105), (16, 90), (32, 85)]]


def test_job_lifecycle_only_moves_forward():
    assert jobs.transition("queued", "running") == JobStatus.RUNNING
    assert jobs.transition("running", "completed") == JobStatus.COMPLETED
    assert jobs.transition("queued", "failed") == JobStatus.FAILED  # lost before a worker took it
    for current, target in (("completed", "running"), ("failed", "completed"), ("queued", "completed"),
                            ("running", "queued")):
        with pytest.raises(InvalidJobTransition):
            jobs.transition(current, target)
    assert jobs.sources("running") == {JobStatus.QUEUED}
    assert jobs.poll_after_ms("running") == 1000 and jobs.poll_after_ms("completed") is None


def test_every_kind_has_a_queue_with_a_worker_and_a_handler():
    served = {"agent", "documents", "calculations"}  # queues the agent, document and calculation workers listen on
    assert set(jobs.QUEUES) == set(JobKind) and set(jobs.QUEUES.values()) <= served
    assert set(HANDLERS) == {kind.value for kind in JobKind}


@pytest.fixture
def site(env, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    queued = []
    monkeypatch.setattr(tasks, "send_async_job", queued.append)
    h = headers(tokens)
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=h).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    return services, client, h, project, base, queued


def test_soil_fit_is_queued_run_by_the_worker_and_polled(site, env):  # noqa: F811
    services, client, h, project, base, queued = site
    accepted = client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h)
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["status"] == "queued" and body["kind"] == "soil_fit" and body["poll_after_ms"] == 1000
    [job] = queued
    assert job["id"] == body["job_id"] and job["project_id"] == project["id"]
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()["status"] == "queued"

    async_jobs.run(services.store, job["id"], HANDLERS)
    done = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()
    assert done["status"] == "completed" and done["poll_after_ms"] is None and done["error"] is None
    assert done["result"]["layer_count"] == 2 and done["result"]["soil_layers"][-1]["depth_m"] is None

    # A redelivered task is a no-op: the result stays the one already stored.
    async_jobs.run(services.store, job["id"], {"soil_fit": lambda _: pytest.fail("ran twice")})
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()["result"] == done["result"]


def test_job_is_private_to_its_owner(site, env):  # noqa: F811
    services, client, h, _, base, queued = site
    _, _, _, actor, _, _ = env
    job_id = client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h).json()["job_id"]
    human(services, actor, email="other@example.com")
    other = services.identity.login("other@example.com", PASSWORD)
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers(other)).status_code == 404
    assert client.get(f"/api/v1/jobs/{job_id}").status_code in (401, 403)


def test_handler_failure_keeps_the_http_status_the_route_used_to_answer(site):
    services, client, h, _, base, queued = site
    client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h)
    [job] = queued

    def refuse(_):
        raise JobFailure(422, "La serie no se puede ajustar.")
    async_jobs.run(services.store, job["id"], {"soil_fit": refuse})
    failed = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()
    assert (failed["status"], failed["error_code"], failed["error"]) == ("failed", 422, "La serie no se puede ajustar.")


def test_unexpected_error_fails_the_job_without_leaking_details(site):
    services, client, h, _, base, queued = site
    client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h)
    [job] = queued

    def crash(_):
        raise RuntimeError("password=secret host=db")
    with pytest.raises(RuntimeError):
        async_jobs.run(services.store, job["id"], {"soil_fit": crash})
    failed = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()
    assert failed["status"] == "failed" and failed["error_code"] == 500 and "secret" not in failed["error"]


def test_broker_failure_answers_503_and_fails_the_job(site, monkeypatch):
    services, client, h, _, base, _ = site

    def down(_):
        raise ConnectionError("redis down")
    monkeypatch.setattr(tasks, "send_async_job", down)
    response = client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h)
    assert response.status_code == 503
    with services.store.transaction() as db:
        [row] = db.many("async_jobs")
    assert row["status"] == "failed" and row["error_code"] == 503


def test_a_lost_job_is_failed_when_polled(site):
    services, client, h, _, base, queued = site
    client.post(f"{base}/mediciones-suelo/ajustar", json={"measurements": READINGS}, headers=h)
    [job] = queued
    with services.store.transaction(write=True) as db:
        db.change("async_jobs", job["id"], created_at=job["created_at"] - jobs.STALE_AFTER_S[JobStatus.QUEUED] - 1)
    lost = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()
    assert lost["status"] == "failed" and lost["error_code"] == 504
    # A worker that finally picks it up does not resurrect it.
    async_jobs.run(services.store, job["id"], {"soil_fit": lambda _: pytest.fail("ran a failed job")})


def test_plan_routes_validate_before_queuing(site):
    _, client, h, _, base, queued = site
    artifact = client.post(base, json={"name": "Malla", "geometry": {"length_m": 40, "width_m": 30, "burial_depth_m": 0.5,
                                                                      "conductor_spacing_m": 5, "rods_count": 4, "rod_length_m": 2.4},
                                       "soil_layers": [{"resistivity_ohm_m": 100}]}, headers=h).json()
    for route in ("plan-proposal", "plan-revision"):
        missing = client.post(f"{base}/{artifact['artifact_id']}/versions/1/{route}",
                              json={"upload_id": "0" * 36}, headers=h)
        assert missing.status_code == 404
    assert queued == []


def test_material_assistant_is_queued_and_its_output_validated(site, monkeypatch):
    services, client, h, _, _, queued = site
    accepted = client.post("/api/v1/material-catalog/assistant",
                           json={"messages": [{"role": "user", "content": "¿Qué varilla uso?"}]}, headers=h)
    assert accepted.status_code == 202, accepted.text
    [job] = queued
    assert job["kind"] == "material_assistant" and job["project_id"] is None

    reply = {"reply": "Usa varilla copperweld.", "questions": ["¿Profundidad?"],
             "recommendations": [{"name": "Varilla", "category": "Varilla", "why": "suelo"},
                                 {"name": "Inventado", "category": "Otro"}]}
    fake = SimpleNamespace(require_capacity=lambda: None, complete=lambda *a, **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))]))
    monkeypatch.setattr("src.infrastructure.agents.uow.UnitOfWork", lambda *a, **k: fake)
    monkeypatch.setattr(async_job_handlers, "_store", lambda: services.store)
    async_jobs.run(services.store, job["id"], HANDLERS)
    result = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()["result"]
    assert result["reply"] == "Usa varilla copperweld." and [r["name"] for r in result["recommendations"]] == ["Varilla"]

    with pytest.raises(JobFailure) as invalid:
        async_job_handlers.material_assistant_output("no es json")
    assert invalid.value.code == 502


def test_system_health_is_reused_between_close_calls(env, monkeypatch):  # noqa: F811
    from src.infrastructure.entrypoint.api import system_routes

    _, _, client, _, tokens, _ = env
    calls = []

    def counted(_):
        calls.append(1)
    monkeypatch.setattr(system_routes, "COMPONENTS", [("database", "Base de datos", counted, True)])
    first = client.get("/api/v1/system/health", headers=headers(tokens)).json()
    second = client.get("/api/v1/system/health", headers=headers(tokens)).json()
    assert first == second and len(calls) == 1
