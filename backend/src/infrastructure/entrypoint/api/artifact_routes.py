"""Versioned land grounding design artifact endpoints."""

from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.infrastructure.entrypoint.api.schemas import GroundingArtifactRequest, PotentialCalculationRequest
from src.infrastructure.entrypoint.worker.tasks import calculate_artifact_potential
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefactos-diseno-tierras", tags=["artefactos-diseno-tierras"])


def owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def snapshot(payload):
    return payload.model_dump(mode="json")


@router.post("", status_code=201)
def create_artifact(project_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    now, artifact_id = int(time()), str(uuid4())
    row = {"id": str(uuid4()), "project_id": project_id, "artifact_id": artifact_id,
           "version": 1, "name": payload.name, "snapshot": snapshot(payload),
           "created_by": actor.user_id, "created_at": now}
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        db.add("artefacto_diseno_tierras_counters", id=artifact_id, project_id=project_id, last_version=1)
        db.add("artefacto_diseno_tierras", **row)
    return row


@router.get("")
def list_artifacts(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        rows = db.many("artefacto_diseno_tierras", project_id=project_id, limit=10000)
    newest = {}
    for row in rows:
        current = newest.get(row["artifact_id"])
        if current is None or row["version"] > current["version"]:
            newest[row["artifact_id"]] = row
    return sorted(newest.values(), key=lambda row: row["created_at"], reverse=True)


@router.get("/{artifact_id}/versions")
def list_versions(project_id: str, artifact_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        rows = db.many("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, limit=10000)
    if not rows:
        raise HTTPException(404, "Artifact not found")
    return sorted(rows, key=lambda row: row["version"], reverse=True)


@router.get("/{artifact_id}/versions/{version}")
def get_version(project_id: str, artifact_id: str, version: int, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, version=version)
    if not row:
        raise HTTPException(404, "Artifact version not found")
    return row


@router.post("/{artifact_id}/versions", status_code=201)
@router.put("/{artifact_id}", status_code=201)
def create_version(project_id: str, artifact_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        counter = db.one("artefacto_diseno_tierras_counters", id=artifact_id, project_id=project_id)
        if not counter:
            raise HTTPException(404, "Artifact not found")
        row = {"id": str(uuid4()), "project_id": project_id, "artifact_id": artifact_id,
               "version": counter["last_version"] + 1, "name": payload.name,
               "snapshot": snapshot(payload), "created_by": actor.user_id, "created_at": now}
        db.change("artefacto_diseno_tierras_counters", artifact_id, last_version=row["version"])
        db.add("artefacto_diseno_tierras", **row)
    return row


@router.delete("/{artifact_id}/versions/{version}", status_code=204)
def delete_version(project_id: str, artifact_id: str, version: int, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        row = db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, version=version)
        if not row:
            raise HTTPException(404, "Artifact version not found")
        db.remove("artefacto_diseno_tierras", row["id"])
    return Response(status_code=204)


@router.post("/{artifact_id}/versions/{version}/calculos-potencial", status_code=202)
def request_potential_calculation(project_id: str, artifact_id: str, version: int, payload: PotentialCalculationRequest,
                                  request: Request, actor=Depends(require("designs:write"))):
    """Queue a potential-engine calculation for one immutable artifact version."""
    now = int(time())
    row = {"id": str(uuid4()), "project_id": project_id, "artifact_id": artifact_id, "artifact_version": version,
           "status": "pending", "parameters": payload.model_dump(), "result": None, "trace": None, "error": None,
           "created_by": actor.user_id, "created_at": now, "updated_at": now}
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        if not db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, version=version):
            raise HTTPException(404, "Artifact version not found")
        db.add("calculos_potencial_tierras", **row)
    # Dispatch only after the database transaction has committed.
    try:
        calculate_artifact_potential.apply_async(args=[row["id"]], task_id=row["id"])
    except Exception as exc:
        with request.app.state.services.store.transaction(write=True) as db:
            db.change("calculos_potencial_tierras", row["id"], status="failed",
                      error="No se pudo encolar el cálculo", updated_at=int(time()))
        raise HTTPException(503, "Unable to queue potential calculation") from exc
    return row


@router.get("/{artifact_id}/versions/{version}/calculos-potencial")
def list_potential_calculations(project_id: str, artifact_id: str, version: int, request: Request,
                                actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        rows = db.many("calculos_potencial_tierras", project_id=project_id, artifact_id=artifact_id,
                       artifact_version=version, limit=1000)
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


@router.get("/{artifact_id}/calculos-potencial/{calculation_id}")
def get_potential_calculation(project_id: str, artifact_id: str, calculation_id: str, request: Request,
                              actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.one("calculos_potencial_tierras", id=calculation_id, project_id=project_id, artifact_id=artifact_id)
    if not row:
        raise HTTPException(404, "Calculation not found")
    return row


@router.post("/{artifact_id}/calculos-potencial/{calculation_id}/cancelar")
def cancel_potential_calculation(project_id: str, artifact_id: str, calculation_id: str, request: Request,
                                 actor=Depends(require("designs:write"))):
    """Cancel a queued or running calculation; a running engine finishes but its result is discarded."""
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        row = db.one("calculos_potencial_tierras", id=calculation_id, project_id=project_id, artifact_id=artifact_id)
        if not row:
            raise HTTPException(404, "Calculation not found")
        if row["status"] not in {"pending", "running"}:
            raise HTTPException(409, f"Calculation is already {row['status']}")
        db.change("calculos_potencial_tierras", calculation_id, status="cancelled", updated_at=int(time()))
        return {**row, "status": "cancelled"}
