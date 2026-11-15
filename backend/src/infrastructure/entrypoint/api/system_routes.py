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


# ---- BL-26 (minimal): queue metrics and basic alerts -------------------------------------------------------------

# Every Celery queue a worker listens on (tasks.py routes) and the worker time limit of its longest task.
QUEUES = (("agent", 600), ("documents", None), ("calculations", 600), ("optimizer", 3300), ("render", None),
          ("mail", None), ("default", None))
QUEUE_DEPTH_WARN = int(os.getenv("QUEUE_DEPTH_WARN", "20"))          # messages waiting in one queue
QUEUE_WAIT_WARN_S = int(os.getenv("QUEUE_WAIT_WARN_S", "600"))       # oldest pending job age before it is a problem


def _queue_depths() -> dict[str, int | None]:
    """Messages waiting per queue (Celery keeps one Redis list per queue); None when Redis cannot be read."""
    import redis

    client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
                                  socket_timeout=2, socket_connect_timeout=2)
    try:
        return {name: int(client.llen(name)) for name, _ in QUEUES}
    except Exception:
        return {name: None for name, _ in QUEUES}
    finally:
        client.close()


def _work_in_progress(db, now: int) -> dict[str, dict]:
    """Queued and running jobs recorded in the database, with the age of the oldest of each."""
    def summarize(rows, waiting_states, running_states):
        waiting = [r for r in rows if r["status"] in waiting_states]
        running = [r for r in rows if r["status"] in running_states]
        return {"waiting": len(waiting), "running": len(running),
                "oldest_waiting_s": max((now - int(r["created_at"]) for r in waiting), default=None),
                "oldest_running_s": max((now - int(r["updated_at"]) for r in running), default=None)}

    calculations = [r for status in ("pending", "running") for r in db.many("calculos_potencial_tierras", status=status)]
    runs = [r for status in ("queued", "running") for r in db.many("optimizer_runs", status=status)]
    return {"calculations": summarize(calculations, ("pending",), ("running",)),
            "optimizer": summarize(runs, ("queued",), ("running",))}


def queue_report(request: Request) -> dict:
    now = int(time())
    depths = _queue_depths()
    with request.app.state.services.store.transaction() as db:
        work = _work_in_progress(db, now)
    limits = dict(QUEUES)
    alerts = []
    if all(depth is None for depth in depths.values()):
        alerts.append({"severity": "error", "queue": None, "message": "No se pudo leer el broker (Redis); se desconoce la profundidad de las colas."})
    for name, depth in depths.items():
        if depth is not None and depth > QUEUE_DEPTH_WARN:
            alerts.append({"severity": "warning", "queue": name,
                           "message": f"La cola «{name}» tiene {depth} tareas en espera (umbral {QUEUE_DEPTH_WARN})."})
    for kind, queue, label in (("calculations", "calculations", "cálculos de potencial"), ("optimizer", "optimizer", "corridas del optimizador")):
        summary = work[kind]
        if summary["oldest_waiting_s"] is not None and summary["oldest_waiting_s"] > QUEUE_WAIT_WARN_S:
            alerts.append({"severity": "warning", "queue": queue,
                           "message": f"Hay {label} esperando desde hace {summary['oldest_waiting_s'] // 60} min "
                                      f"(umbral {QUEUE_WAIT_WARN_S // 60} min); revisa el worker de «{queue}»."})
        limit = limits.get(queue)
        if limit and summary["oldest_running_s"] is not None and summary["oldest_running_s"] > limit:
            alerts.append({"severity": "error", "queue": queue,
                           "message": f"Hay {label} marcados «en ejecución» desde hace {summary['oldest_running_s'] // 60} min, más que el "
                                      f"límite del worker ({limit // 60} min): el worker murió o el estado quedó huérfano."})
    status = "error" if any(a["severity"] == "error" for a in alerts) else "warning" if alerts else "ok"
    return {"status": status, "checked_at": now, "thresholds": {"depth": QUEUE_DEPTH_WARN, "wait_s": QUEUE_WAIT_WARN_S},
            "queues": [{"name": name, "depth": depths[name], "time_limit_s": limit} for name, limit in QUEUES],
            "work": work, "alerts": alerts}


@router.get("/system/queues")
def system_queues(request: Request, actor=Depends(require())):
    """Depth of every work queue, jobs waiting or running per kind, and the alerts the thresholds raise."""
    return queue_report(request)


@router.get("/system/metrics")
def system_metrics(request: Request, actor=Depends(require())):
    """The same report in Prometheus text format, for an external scraper or alert rule."""
    from fastapi.responses import PlainTextResponse

    report = queue_report(request)
    lines = ["# HELP spat_queue_depth Messages waiting in a Celery queue.", "# TYPE spat_queue_depth gauge"]
    lines += [f'spat_queue_depth{{queue="{q["name"]}"}} {q["depth"]}' for q in report["queues"] if q["depth"] is not None]
    for metric, key in (("spat_jobs_waiting", "waiting"), ("spat_jobs_running", "running"),
                        ("spat_jobs_oldest_waiting_seconds", "oldest_waiting_s"), ("spat_jobs_oldest_running_seconds", "oldest_running_s")):
        lines += [f"# TYPE {metric} gauge"]
        lines += [f'{metric}{{kind="{kind}"}} {summary[key]}' for kind, summary in report["work"].items() if summary[key] is not None]
    lines += ["# TYPE spat_queue_alerts gauge", f"spat_queue_alerts {len(report['alerts'])}",
              "# TYPE spat_queue_status gauge", f'spat_queue_status{{status="{report["status"]}"}} 1', ""]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")


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
