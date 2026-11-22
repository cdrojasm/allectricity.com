"""AI assistance for grounding-material recommendations; it does not quote prices."""

from __future__ import annotations

from typing import Literal

from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.domain.jobs import JobKind
from src.infrastructure.entrypoint.api.job_routes import queue_job, require_llm_capacity
from src.infrastructure.services import material_catalog_discovery
from src.infrastructure.security.middleware import require


router = APIRouter(prefix="/api/v1/material-catalog", tags=["material-catalog"])


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=5000)


class CatalogAssistantRequest(BaseModel):
    geography: dict[str, str] = Field(default_factory=dict)
    design_context: str = Field(default="", max_length=12000)
    messages: list[AssistantMessage] = Field(min_length=1, max_length=16)


class CatalogAssistantConversation(BaseModel):
    messages: list[AssistantMessage] = Field(max_length=100)


class MaterialDiscoveryGeography(BaseModel):
    country: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    radius_km: float | None = Field(default=None, ge=0, le=5000)
    currency: str = Field(default="", max_length=3)


class MaterialDiscoveryRequest(BaseModel):
    geography: MaterialDiscoveryGeography = Field(default_factory=MaterialDiscoveryGeography)
    category: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=8, ge=1, le=10)


# The system prompt is the spat-material-assistant application (Phoenix; seed prompts/phoenix/material-assistant.md).


@router.post("/assistant", status_code=202)
def material_catalog_assistant(payload: CatalogAssistantRequest, request: Request, _actor=Depends(require())):
    """Queue project-specific material suggestions; poll /api/v1/jobs/{job_id}. Prices and sources are never generated."""
    require_llm_capacity(request, _actor.user_id)
    return queue_job(request, kind=JobKind.MATERIAL_ASSISTANT, owner_id=_actor.user_id, project_id=None,
                     payload=payload.model_dump(mode="json"))


@router.get("/assistant/conversation")
def get_material_catalog_conversation(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        project = db.one("projects", id=project_id)
        if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
            raise HTTPException(404, "Project not found")
        conversation = db.one("material_catalog_conversations", project_id=project_id, owner_id=actor.user_id)
    return {"messages": conversation["messages"] if conversation else []}


@router.put("/assistant/conversation")
def save_material_catalog_conversation(project_id: str, payload: CatalogAssistantConversation,
                                       request: Request, actor=Depends(require("designs:write"))):
    current_time = int(time())
    messages = [message.model_dump() for message in payload.messages][-100:]
    with request.app.state.services.store.transaction(write=True) as db:
        project = db.one("projects", id=project_id)
        if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
            raise HTTPException(404, "Project not found")
        current = db.one("material_catalog_conversations", project_id=project_id)
        if current:
            if current["owner_id"] != actor.user_id and not actor.privileged:
                raise HTTPException(404, "Project not found")
            db.change("material_catalog_conversations", project_id,
                      owner_id=actor.user_id, messages=messages, updated_at=current_time)
        else:
            db.add("material_catalog_conversations", project_id=project_id, owner_id=actor.user_id,
                   messages=messages, updated_at=current_time)
    return {"saved": True, "updated_at": current_time}


@router.post("/discover", status_code=202)
def discover_materials(payload: MaterialDiscoveryRequest, request: Request, _actor=Depends(require())):
    """Queue traceable web discovery; clients poll the returned job id."""
    from src.infrastructure.entrypoint.worker.tasks import discover_materials_job

    job_id = uuid4().hex
    current_time = int(time())
    request_data = payload.model_dump()
    store = request.app.state.services.store
    with store.transaction(write=True) as db:
        db.add("material_discovery_jobs", id=job_id, owner_id=_actor.user_id,
               status="queued", request=request_data, result=None, error=None,
               created_at=current_time, updated_at=current_time)
    try:
        discover_materials_job.delay(job_id)
    except Exception as exc:
        with store.transaction(write=True) as db:
            db.change("material_discovery_jobs", job_id, status="failed",
                      error="No se pudo encolar la búsqueda. Inténtalo de nuevo.", updated_at=int(time()))
        raise HTTPException(503, "El worker de búsqueda no está disponible.") from exc
    return {"job_id": job_id, "status": "queued", "poll_after_ms": 1200}


@router.get("/discover/{job_id}")
def get_discovery_job(job_id: str, request: Request, _actor=Depends(require())):
    """Return an owned discovery job for polling."""
    store = request.app.state.services.store
    with store.transaction() as db:
        job = db.one("material_discovery_jobs", id=job_id, owner_id=_actor.user_id)
    if not job:
        raise HTTPException(404, "Búsqueda no encontrada.")
    stale_after = 360 if job["status"] == "running" else 900
    if job["status"] in {"queued", "running"} and int(time()) - job["updated_at"] > stale_after:
        with store.transaction(write=True) as db:
            db.change("material_discovery_jobs", job_id, status="failed",
                      error="La búsqueda tardó demasiado o el worker se interrumpió. Inicia una nueva búsqueda.",
                      updated_at=int(time()))
        with store.transaction() as db:
            job = db.one("material_discovery_jobs", id=job_id, owner_id=_actor.user_id)
    return {"job_id": job["id"], "status": job["status"], "result": job["result"],
            "error": job["error"], "poll_after_ms": 1200 if job["status"] in {"queued", "running"} else None,
            "created_at": job["created_at"], "updated_at": job["updated_at"]}
