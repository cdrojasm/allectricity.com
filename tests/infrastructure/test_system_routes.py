import json

from src.infrastructure.entrypoint.api import system_routes
from tests.infrastructure.test_identity import env, headers  # noqa: F401

CATALOG = {"version": 1, "templates": [{
    "id": "wenner", "method": "wenner", "title": "Método de Wenner", "description": "", "formula": "ρa = 2·π·a·R",
    "files": [{"format": "xlsx", "key": "wenner/plantilla.xlsx", "filename": "plantilla.xlsx", "size_bytes": 10}],
}]}


class FakeStorage:
    allowed_buckets = {"documents": "documents", "designs": "designs", "templates": "plantillas"}

    def __init__(self, catalog=CATALOG):
        self.catalog = catalog
        self.signed = []

    def read_object(self, bucket, key, max_bytes):
        if self.catalog is None:
            raise ValueError("NoSuchKey")
        assert (bucket, key) == ("plantillas", "catalogo.json")
        return json.dumps(self.catalog).encode()

    def presign_download(self, bucket, key, filename=None):
        self.signed.append((bucket, key, filename))
        return f"http://minio/{bucket}/{key}?signed"


def test_templates_are_listed_and_signed_from_the_catalog(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    storage = FakeStorage()
    monkeypatch.setattr(system_routes, "storage_client", lambda: storage)

    listed = client.get("/api/v1/plantillas-medicion", headers=headers(tokens))
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == "wenner"

    link = client.get("/api/v1/plantillas-medicion/wenner/xlsx", headers=headers(tokens)).json()
    assert link["filename"] == "plantilla.xlsx" and link["url"].endswith("?signed")
    assert storage.signed == [("plantillas", "wenner/plantilla.xlsx", "plantilla.xlsx")]

    # Only catalog entries can be signed: no arbitrary keys from the path.
    assert client.get("/api/v1/plantillas-medicion/wenner/csv", headers=headers(tokens)).status_code == 404
    assert client.get("/api/v1/plantillas-medicion/otra/xlsx", headers=headers(tokens)).status_code == 404
    assert client.get("/api/v1/plantillas-medicion").status_code == 401


def test_templates_report_503_when_the_catalog_is_missing(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    monkeypatch.setattr(system_routes, "storage_client", lambda: FakeStorage(catalog=None))
    assert client.get("/api/v1/plantillas-medicion", headers=headers(tokens)).status_code == 503


def test_system_health_reports_each_component(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env

    def failing(request):
        raise RuntimeError("Buckets faltantes: plantillas")

    def leaking(request):
        raise ConnectionError("redis://:secret@redis:6379 refused")

    def disabled(request):
        raise LookupError("No configurado")

    monkeypatch.setattr(system_routes, "COMPONENTS", [
        ("database", "Base de datos", system_routes.check_database, True),
        ("object_storage", "Almacenamiento", failing, True),
        ("queue", "Cola", leaking, True),
        ("knowledge_graph", "Grafo", disabled, False),
    ])
    assert client.get("/api/v1/system/health").status_code == 401
    body = client.get("/api/v1/system/health", headers=headers(tokens)).json()
    assert body["status"] == "degraded"
    components = {c["id"]: c for c in body["components"]}
    assert components["database"]["status"] == "ok"
    assert components["object_storage"]["detail"] == "Buckets faltantes: plantillas"
    assert components["queue"]["detail"] == "Sin respuesta (ConnectionError)"
    assert components["knowledge_graph"]["status"] == "disabled"

    monkeypatch.setattr(system_routes, "COMPONENTS", [
        ("database", "Base de datos", system_routes.check_database, True),
        ("knowledge_graph", "Grafo", disabled, False),
    ])
    assert client.get("/api/v1/system/health", headers=headers(tokens)).json()["status"] == "ok"


# ---- BL-26 (minimal): queue metrics and basic alerts --------------------------------------------------------------

def _calculation_row(project_id, created_at, status, updated_at=None):
    return {"id": f"calc-{created_at}-{status}", "project_id": project_id, "artifact_id": "a" * 36, "artifact_version": 1,
            "status": status, "parameters": {}, "result": None, "trace": None, "error": None,
            "created_by": None, "created_at": created_at, "updated_at": updated_at or created_at}


def test_queue_report_lists_every_queue_and_raises_alerts_from_the_thresholds(env, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    monkeypatch.setattr(system_routes, "_queue_depths", lambda: {name: (25 if name == "calculations" else 0) for name, _ in system_routes.QUEUES})
    project = client.post("/api/v1/projects", json={"name": "Colas"}, headers=headers(tokens)).json()
    now = int(system_routes.time())
    with services.store.transaction(write=True) as db:
        user = db.many("users", limit=1)[0]["id"]
        db.add("calculos_potencial_tierras", **{**_calculation_row(project["id"], now - 1200, "pending"), "created_by": user})
        db.add("calculos_potencial_tierras", **{**_calculation_row(project["id"], now - 3000, "running", now - 2000), "created_by": user})
        db.add("calculos_potencial_tierras", **{**_calculation_row(project["id"], now - 10, "completed"), "created_by": user})

    report = client.get("/api/v1/system/queues", headers=headers(tokens)).json()
    assert [q["name"] for q in report["queues"]] == ["agent", "documents", "calculations", "optimizer", "render", "mail", "default"]
    assert next(q for q in report["queues"] if q["name"] == "calculations")["depth"] == 25
    work = report["work"]["calculations"]
    assert work["waiting"] == 1 and work["running"] == 1 and work["oldest_waiting_s"] >= 1200 and work["oldest_running_s"] >= 2000
    assert report["work"]["optimizer"] == {"waiting": 0, "running": 0, "oldest_waiting_s": None, "oldest_running_s": None}
    kinds = sorted((a["severity"], a["queue"]) for a in report["alerts"])
    assert kinds == [("error", "calculations"), ("warning", "calculations"), ("warning", "calculations")]
    assert report["status"] == "error" and all(a["message"] for a in report["alerts"])

    metrics = client.get("/api/v1/system/metrics", headers=headers(tokens))
    assert metrics.status_code == 200 and metrics.headers["content-type"].startswith("text/plain")
    assert 'spat_queue_depth{queue="calculations"} 25' in metrics.text
    assert 'spat_jobs_waiting{kind="calculations"} 1' in metrics.text and "spat_queue_alerts 3" in metrics.text


def test_an_unreadable_broker_is_itself_an_alert_and_an_idle_system_is_ok(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    monkeypatch.setattr(system_routes, "_queue_depths", lambda: {name: None for name, _ in system_routes.QUEUES})
    report = client.get("/api/v1/system/queues", headers=headers(tokens)).json()
    assert report["status"] == "error" and report["alerts"][0]["queue"] is None and "Redis" in report["alerts"][0]["message"]
    assert all(q["depth"] is None for q in report["queues"])
    assert 'spat_queue_depth{' not in client.get("/api/v1/system/metrics", headers=headers(tokens)).text

    monkeypatch.setattr(system_routes, "_queue_depths", lambda: {name: 0 for name, _ in system_routes.QUEUES})
    idle = client.get("/api/v1/system/queues", headers=headers(tokens)).json()
    assert idle["status"] == "ok" and idle["alerts"] == [] and idle["thresholds"] == {"depth": 20, "wait_s": 600}
    assert client.get("/api/v1/system/queues").status_code in (401, 403)
