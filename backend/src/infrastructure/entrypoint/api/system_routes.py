"""Deployment health per component and the soil-resistivity templates served from MinIO."""

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from time import monotonic, time
from urllib.request import urlopen

from fastapi import APIRouter, Depends, HTTPException, Request

from src.infrastructure.entrypoint.api.file_routes import storage_client
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1", tags=["system"])

CHECK_TIMEOUT_S = 4.0
TEMPLATE_CATALOG_KEY = "catalogo.json"
TEMPLATE_CATALOG_MAX_BYTES = 256 * 1024


def check_database(request):
    with request.app.state.services.store.transaction() as db:
        if not db.one("security_lock", id="identity"):
            raise RuntimeError("Migraciones pendientes")


def check_object_storage(request):
    missing = storage_client().missing_buckets()
    if missing:
        raise RuntimeError(f"Buckets faltantes: {', '.join(missing)}")
    if not storage_client().exists(storage_client().allowed_buckets["templates"], TEMPLATE_CATALOG_KEY):
        raise RuntimeError("Catálogo de plantillas no sembrado")


def check_redis(request):
    import redis

    client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
                                  socket_timeout=2, socket_connect_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


def check_worker(request):
    from src.infrastructure.entrypoint.worker.tasks import celery_app

    if not celery_app.control.ping(timeout=2.0):
        raise RuntimeError("Ningún worker respondió")


def check_antivirus(request):
    host, port = os.getenv("CLAMAV_HOST", "clamav"), int(os.getenv("CLAMAV_PORT", "3310"))
    with socket.create_connection((host, port), timeout=3) as connection:
        connection.settimeout(3)
        connection.sendall(b"zPING\0")
        if not connection.recv(64).startswith(b"PONG"):
            raise RuntimeError("Respuesta inesperada")


def check_ocr(request):
    url = os.getenv("OCR_SERVICE_URL", "http://ocr:8080").rstrip("/") + "/health"
    with urlopen(url, timeout=3) as response:
        if json.loads(response.read(4096)).get("status") != "ok":
            raise RuntimeError("Estado distinto de ok")


def check_knowledge_graph(request):
    graph = request.app.state.services.knowledge_graph
    if graph is None:
        raise LookupError("No configurado")
    graph.driver.verify_connectivity()


def check_potential_engine(request):
    from src.infrastructure.calculations.potential_engine_client import (
        PotentialEngineClient,
    )

    client = PotentialEngineClient()
    if client.remote_url:
        with urlopen(client.remote_url + "/health", timeout=3) as response:
            if json.loads(response.read(4096)).get("status") != "ok":
                raise RuntimeError("Estado distinto de ok")
        return
    executable = client.executable
    if not os.access(executable, os.X_OK):
        raise RuntimeError("Binario no encontrado o sin permiso de ejecución")


# (id, label, check, required). An optional component that is not configured reports "disabled".
COMPONENTS = [
    ("database", "Base de datos", check_database, True),
    ("object_storage", "Almacenamiento de objetos", check_object_storage, True),
    ("queue", "Cola de tareas", check_redis, True),
    ("worker", "Worker de procesamiento", check_worker, True),
    ("antivirus", "Antivirus", check_antivirus, True),
    ("ocr", "Servicio OCR", check_ocr, True),
    ("knowledge_graph", "Grafo de conocimiento", check_knowledge_graph, False),
    ("potential_engine", "Motor de potenciales", check_potential_engine, True),
]


def _run(check, request):
    started = monotonic()
    try:
        check(request)
        status, detail = "ok", None
    except LookupError as exc:
        status, detail = "disabled", str(exc)
    except Exception as exc:
        # Messages may carry hosts or credentials from drivers; only show our own messages.
        status = "error"
        detail = str(exc) if isinstance(exc, RuntimeError) else f"Sin respuesta ({type(exc).__name__})"
    return {"status": status, "detail": detail, "latency_ms": round((monotonic() - started) * 1000)}


@router.get("/system/health")
def system_health(request: Request, actor=Depends(require())):
    """Check every dependency in parallel; `status` is "ok" only when all required ones are."""
    pool = ThreadPoolExecutor(max_workers=len(COMPONENTS))
    futures = {cid: pool.submit(_run, check, request) for cid, _, check, _ in COMPONENTS}
    wait(futures.values(), timeout=CHECK_TIMEOUT_S)
    pool.shutdown(wait=False, cancel_futures=True)
    components = []
    for cid, label, _, required in COMPONENTS:
        future = futures[cid]
        result = future.result() if future.done() else {"status": "error", "detail": "Tiempo de espera agotado",
                                                         "latency_ms": round(CHECK_TIMEOUT_S * 1000)}
        components.append({"id": cid, "label": label, "required": required, **result})
    healthy = all(c["status"] == "ok" for c in components if c["required"])
    return {"status": "ok" if healthy else "degraded", "version": request.app.version,
            "checked_at": int(time()), "components": components}


def _template_catalog():
    storage = storage_client()
    try:
        raw = storage.read_object(storage.allowed_buckets["templates"], TEMPLATE_CATALOG_KEY,
                                  TEMPLATE_CATALOG_MAX_BYTES)
        return json.loads(raw)["templates"]
    except Exception as exc:
        raise HTTPException(503, "El catálogo de plantillas no está disponible") from exc


@router.get("/plantillas-medicion")
def list_measurement_templates(actor=Depends(require())):
    """Soil-resistivity field templates published in the MinIO templates bucket."""
    return {"items": _template_catalog()}


@router.get("/plantillas-medicion/{template_id}/{file_format}")
def download_measurement_template(template_id: str, file_format: str, actor=Depends(require())):
    """A short-lived presigned URL; only files listed in the catalog can be downloaded."""
    template = next((t for t in _template_catalog() if t.get("id") == template_id), None)
    entry = next((f for f in (template or {}).get("files", []) if f.get("format") == file_format), None)
    if entry is None:
        raise HTTPException(404, "Plantilla no encontrada")
    storage = storage_client()
    url = storage.presign_download(storage.allowed_buckets["templates"], entry["key"], entry["filename"])
    return {"url": url, "filename": entry["filename"], "expires_in": 300}
