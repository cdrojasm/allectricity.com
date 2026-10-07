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
