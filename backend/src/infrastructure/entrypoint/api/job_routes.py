"""Background jobs: routes that used to block on an LLM call or a numeric fit answer 202 with a job;
clients poll it here."""

from fastapi import APIRouter, Depends, HTTPException, Request

from src.application.use_cases import async_jobs
from src.domain.jobs import JobKind
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def send(job: dict) -> None:
    # Imported late so tests can replace the broker call on the tasks module.
    from src.infrastructure.entrypoint.worker import tasks
    tasks.send_async_job(job)


def require_llm_capacity(request: Request, user_id: str) -> None:
    """Answer 402 now instead of queuing an LLM job the user's budget cannot pay for."""
    from src.infrastructure.agents import uow

    block = uow.budget_block(user_id, request.app.state.services.store)
    if block is not None:
        raise HTTPException(402, uow.BudgetUnavailable(block).message)


def queue_job(request: Request, *, kind: JobKind, owner_id: str, project_id: str | None, payload: dict) -> dict:
    """Create a job, dispatch it after commit and return the 202 body. A broker failure answers 503."""
    store = request.app.state.services.store
    with store.transaction(write=True) as tx:
        job = async_jobs.create(tx, kind=kind, owner_id=owner_id, project_id=project_id, request=payload)
    job = async_jobs.dispatch(store, job, send)
    if job["status"] == "failed":
        raise HTTPException(503, job["error"])
    return async_jobs.public(job)


@router.get("/{job_id}")
def get_job(job_id: str, request: Request, actor=Depends(require())):
    job = async_jobs.read(request.app.state.services.store, job_id, actor.user_id, privileged=actor.privileged)
    if job is None:
        raise HTTPException(404, "Tarea no encontrada.")
    return async_jobs.public(job)
