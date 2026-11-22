"""Create, run and read background jobs (src/domain/jobs.py holds their lifecycle)."""

import logging
from time import time
from typing import Callable
from uuid import uuid4

from src.domain.jobs import (ACTIVE, STALE_AFTER_S, InvalidJobTransition, JobKind, JobStatus,
                             poll_after_ms, transition)

log = logging.getLogger(__name__)
TABLE = "async_jobs"


class JobFailure(Exception):
    """A handler's user-facing failure: `code` is the HTTP status the synchronous endpoint answered with."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def create(db, *, kind: JobKind, owner_id: str, project_id: str | None, request: dict) -> dict:
    """Insert a queued job inside the caller's write transaction; dispatch it after commit."""
    now = int(time())
    row = {"id": str(uuid4()), "owner_id": owner_id, "project_id": project_id, "kind": JobKind(kind).value,
           "status": JobStatus.QUEUED.value, "request": request, "result": None, "error": None,
           "error_code": None, "created_at": now, "started_at": None, "updated_at": now}
    db.add(TABLE, **row)
    return row


def move(store, job_id: str, target: JobStatus, **changes) -> dict | None:
    """Change a job's state if the lifecycle allows it; None when another writer moved it first."""
    with store.transaction(write=True) as db:
        job = db.one(TABLE, id=job_id)
        if job is None:
            return None
        try:
            transition(job["status"], target)
        except InvalidJobTransition:
            return None
        values = {"status": JobStatus(target).value, "updated_at": int(time()), **changes}
        db.change(TABLE, job_id, **values)
        return {**job, **values}


def dispatch(store, job: dict, send: Callable[[dict], None]) -> dict:
    """Hand a committed job to the broker; a broker failure fails the job (and the caller answers 503)."""
    try:
        send(job)
        return job
    except Exception as exc:
        log.warning("Unable to queue job %s: %s", job["id"], exc)
        return move(store, job["id"], JobStatus.FAILED, error="No se pudo poner la tarea en cola.",
                    error_code=503) or job


def run(store, job_id: str, handlers: dict[str, Callable[[dict], dict]]) -> None:
    """Worker side: queued → running → completed/failed. A redelivered or already-finished job is a no-op."""
    job = move(store, job_id, JobStatus.RUNNING, started_at=int(time()))
    if job is None:
        return
    handler = handlers.get(job["kind"])
    try:
        if handler is None:
            raise JobFailure(500, f"Tipo de tarea desconocido: {job['kind']}")
        result = handler(job)
    except JobFailure as failure:
        move(store, job_id, JobStatus.FAILED, error=failure.message[:2000], error_code=failure.code)
        return
    except Exception:
        log.exception("Job %s (%s) failed", job_id, job["kind"])
        move(store, job_id, JobStatus.FAILED, error="Ocurrió un error interno al procesar la solicitud.",
             error_code=500)
        raise
    move(store, job_id, JobStatus.COMPLETED, result=result, error=None, error_code=None)


def read(store, job_id: str, owner_id: str, *, privileged: bool = False) -> dict | None:
    """An owned job, failing it first when its worker is presumed lost."""
    with store.transaction() as db:
        job = db.one(TABLE, id=job_id)
    if job is None or (job["owner_id"] != owner_id and not privileged):
        return None
    if job["status"] in ACTIVE:
        reference = job["started_at"] or job["created_at"] if job["status"] == JobStatus.RUNNING else job["created_at"]
        if int(time()) - reference > STALE_AFTER_S[JobStatus(job["status"])]:
            job = move(store, job_id, JobStatus.FAILED, error_code=504,
                       error="La tarea tardó demasiado o el worker se interrumpió. Inténtalo de nuevo.") or job
            with store.transaction() as db:
                job = db.one(TABLE, id=job_id)
    return job


def public(job: dict) -> dict:
    """What a client sees: the 202 body and each poll answer share this shape."""
    return {"job_id": job["id"], "kind": job["kind"], "status": job["status"], "result": job["result"],
            "error": job["error"], "error_code": job["error_code"], "poll_after_ms": poll_after_ms(job["status"]),
            "created_at": job["created_at"], "updated_at": job["updated_at"]}
