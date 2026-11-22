"""Versioned land grounding design artifact endpoints."""

from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.application.use_cases import potential_calculations
from src.domain.spat.artifact_contract import snapshot_fields, validate_artifact
from src.domain.agent.patches import diff
from src.domain.spat.grid_geometry import (MAX_CONDUCTORS, MAX_RODS, area_grid, geometry_conflicts, geometry_warnings,
                                           missing_for_calculation)
from src.domain.spat.input_coherence import coherence_diagnostics
from src.domain.spat.plan_revisions import compare_plan_revisions
from src.infrastructure.entrypoint.api.schemas import (GroundingArtifactRequest, PotentialCalculationRequest,
                                                       SoilFileImportRequest, SoilMeasurementsRequest)
from src.domain.spat import soil_materials
from src.infrastructure.calculations.conductor_thermal_profiles import thermal_profile_catalog
from src.application.use_cases.agent_runs import AgentRuns
from src.infrastructure.entrypoint.worker.tasks import calculate_artifact_potential, enqueue_agent_step
from src.infrastructure.security.middleware import require
from src.infrastructure.entrypoint.api.file_routes import storage_client
from src.infrastructure.processing.measurement_tables import XLSX_MIME
from src.infrastructure.processing.dxf_import import import_dxf
from src.domain.jobs import JobKind
from src.infrastructure.entrypoint.api.job_routes import queue_job, require_llm_capacity

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefactos-diseno-tierras", tags=["artefactos-diseno-tierras"])
catalog_router = APIRouter(prefix="/api/v1", tags=["catalogos"])


class DxfImportRequest(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)


class BackgroundCalibrationRequest(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)
    source_page: int | None = Field(default=None, ge=1)
    width_px: int = Field(gt=0, le=100000)
    height_px: int = Field(gt=0, le=100000)
    scale_m_per_pixel: float = Field(gt=0, le=1000)
    offset_x_m: float = 0
    offset_y_m: float = 0
    calibration_points: list[dict] = Field(default_factory=list, max_length=2)
    calibration_distance_m: float | None = Field(default=None, gt=0)
    pixel_distance: float | None = Field(default=None, gt=0)


class PlanVisionRequest(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)
    source_page: int | None = Field(default=None, ge=1)


class PlanRevisionRequest(PlanVisionRequest):
    """A new construction-plan source to compare with the current artifact geometry."""


class GeometryCheckRequest(BaseModel):
    """A plan being edited, possibly invalid: it is checked, never stored."""
    geometry: dict


class AreaGridRequest(GeometryCheckRequest):
    areas: list[str | int] = Field(default_factory=list, max_length=100,
                                   description="Intervenible areas the grid uses (labels or indexes)")
    spacing_x_m: float = Field(gt=0, le=1e4)
    spacing_y_m: float = Field(gt=0, le=1e4)
    bounds: dict[str, float] | None = Field(default=None, description="x_min, x_max, y_min, y_max inside the areas")


def _plan_check(geometry: dict) -> dict:
    for key, limit in (("conductors", MAX_CONDUCTORS), ("rods", MAX_RODS), ("structures", 500), ("areas", 100)):
        if not isinstance(geometry.get(key) or [], list) or len(geometry.get(key) or []) > limit:
            raise HTTPException(422, f"geometry.{key} must be a list of at most {limit} items")
    try:
        return {"conflicts": geometry_conflicts(geometry), "warnings": geometry_warnings(geometry)}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise HTTPException(422, f"Malformed geometry: {exc}") from exc


@router.post("/{artifact_id}/import-dxf")
def import_artifact_dxf(project_id: str, artifact_id: str, payload: DxfImportRequest,
                        request: Request, actor=Depends(require("designs:write"))):
    """Return a version-independent DXF proposal; the client applies it explicitly."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        upload = db.one("file_uploads", id=payload.upload_id, project_id=project_id,
                        owner_id=actor.user_id, status="available")
        artifact = db.designs.latest(project_id, artifact_id)
    if not upload:
        raise HTTPException(404, "Scanned DXF file not found")
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    if upload["expected_mime"] not in {"application/dxf", "application/x-dxf", "image/vnd.dxf"}:
        raise HTTPException(415, "The upload is not a DXF file")
    try:
        data = storage_client().read_object(upload["target_bucket"], upload["object_key"], 50 * 1024 * 1024)
        return {"artifact_id": artifact_id, "base_version": artifact["version"],
                "source": {"upload_id": payload.upload_id, "filename": upload["filename"]},
                **import_dxf(data)}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{artifact_id}/revisions/compare")
def compare_artifact_revisions(project_id: str, artifact_id: str, from_version: int, to_version: int,
                               request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        previous = db.designs.get_version(project_id, artifact_id, from_version)
        current = db.designs.get_version(project_id, artifact_id, to_version)
    if not previous or not current:
        raise HTTPException(404, "Artifact revision not found")
    return {"artifact_id": artifact_id, "from_version": from_version, "to_version": to_version,
            **compare_plan_revisions(previous["snapshot"].get("geometry") or {},
                                     current["snapshot"].get("geometry") or {})}


@router.post("/{artifact_id}/versions/{version}/background", status_code=201)
def attach_plan_background(project_id: str, artifact_id: str, version: int,
                           payload: BackgroundCalibrationRequest, request: Request,
                           actor=Depends(require("designs:write"))):
    """Attach a calibrated image/PDF page by creating a new artifact version."""
    store = request.app.state.services.store
    with store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        previous = db.designs.get_version(project_id, artifact_id, version)
        upload = db.one("file_uploads", id=payload.upload_id, project_id=project_id,
                        owner_id=actor.user_id, status="available")
        if not previous:
            raise HTTPException(404, "Artifact version not found")
        if not upload or upload["expected_mime"] not in {"application/pdf", "image/png", "image/jpeg"}:
            raise HTTPException(415, "The background must be an available PDF or image")
        next_snapshot = dict(previous["snapshot"])
        geometry = dict(next_snapshot.get("geometry") or {})
        geometry["background"] = {"upload_id": payload.upload_id, "source_page": payload.source_page,
                                   "width_px": payload.width_px, "height_px": payload.height_px,
                                   "scale_m_per_pixel": payload.scale_m_per_pixel,
                                   "offset_x_m": payload.offset_x_m, "offset_y_m": payload.offset_y_m,
                                   "calibrated": True, "calibration_points": payload.calibration_points,
                                   "calibration_distance_m": payload.calibration_distance_m,
                                   "pixel_distance": payload.pixel_distance}
        next_snapshot["geometry"] = geometry
        try:
            next_snapshot = snapshot(GroundingArtifactRequest.model_validate(next_snapshot))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        row = db.designs.append_version(project_id, artifact_id, previous["name"], next_snapshot,
                                        actor.user_id, {"kind": "user", "background_upload_id": payload.upload_id},
                                        expected_version=version)
        announce_user_artifact_update(db, project_id, row, previous, "Se adjuntó y calibró el plano de fondo")
        return row


def _queue_plan_vision(kind: JobKind, project_id: str, artifact_id: str, version: int, upload_id: str,
                       source_page: int | None, request: Request, actor) -> dict:
    """Validate the source cheaply here; rasterizing and the vision model run on the documents worker."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
        upload = db.one("file_uploads", id=upload_id, project_id=project_id,
                        owner_id=actor.user_id, status="available")
    if not row or not upload:
        raise HTTPException(404, "Artifact version or source plan not found")
    if upload["expected_mime"] not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(415, "The plan must be a PDF, PNG or JPEG source")
    require_llm_capacity(request, actor.user_id)
    return queue_job(request, kind=kind, owner_id=actor.user_id, project_id=project_id,
                     payload={"artifact_id": artifact_id, "version": version, "upload_id": upload_id,
                              "source_page": source_page})


@router.post("/{artifact_id}/versions/{version}/plan-proposal", status_code=202)
def propose_plan(project_id: str, artifact_id: str, version: int, payload: PlanVisionRequest,
                 request: Request, actor=Depends(require("designs:read"))):
    """Queue a vision proposal of obstacles/zone (a reviewable proposal only); poll /api/v1/jobs/{job_id}."""
    return _queue_plan_vision(JobKind.PLAN_PROPOSAL, project_id, artifact_id, version, payload.upload_id,
                              payload.source_page, request, actor)


@router.post("/{artifact_id}/versions/{version}/plan-revision", status_code=202)
def compare_plan_revision(project_id: str, artifact_id: str, version: int, payload: PlanRevisionRequest,
                          request: Request, actor=Depends(require("designs:write"))):
    """Queue the analysis of a newly uploaded plan against the current geometry (it alerts the chat when done)."""
    return _queue_plan_vision(JobKind.PLAN_REVISION, project_id, artifact_id, version, payload.upload_id,
                              payload.source_page, request, actor)


@router.post("/geometria/validar")
def check_geometry(project_id: str, payload: GeometryCheckRequest, request: Request,
                   actor=Depends(require("designs:read"))):
    """Conflicts (collisions with structures and zones, drawing errors) and warnings of a plan being edited."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
    return _plan_check(payload.geometry)


@router.post("/geometria/malla-en-areas")
def grid_in_areas(project_id: str, payload: AreaGridRequest, request: Request,
                  actor=Depends(require("designs:read"))):
    """Conductors of a regular grid inside the chosen intervenible areas, cut around obstacles."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
    _plan_check(payload.geometry)
    try:
        conductors = area_grid(payload.geometry, payload.spacing_x_m, payload.spacing_y_m,
                               payload.areas or None, payload.bounds)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"conductors": conductors, **_plan_check({**payload.geometry, "conductors": conductors})}


@catalog_router.get("/perfiles-termicos")
def thermal_profiles(actor=Depends(require())):
    """Standards a conductor can be sized with, and for each the materials and the inputs that apply."""
    return thermal_profile_catalog()


@catalog_router.get("/materiales-suelo")
def soil_material_table(q: str | None = None, resistividad_ohm_m: float | None = None,
                        actor=Depends(require())):
    """Indicative soil resistivity by material (orientation only; never replaces a sounding)."""
    if resistividad_ohm_m is not None and resistividad_ohm_m <= 0:
        raise HTTPException(422, "resistividad_ohm_m must be positive")
    if q is None and resistividad_ohm_m is None:
        return soil_materials.table()
    return soil_materials.search(q, resistividad_ohm_m, limit=50)


@router.post("/mediciones-suelo/ajustar", status_code=202)
def fit_soil_measurements(project_id: str, payload: SoilMeasurementsRequest, request: Request,
                          actor=Depends(require("designs:write"))):
    """Queue the fit of a Wenner/Schlumberger sounding to a 2-layer (image series) or 3-8-layer soil model.

    The job result's `soil_layers` use the artifact format (`depth_m` = layer thickness, null for the
    bottom half-space) and stay within the potential engine's limits, so they can be stored in an
    artifact and calculated directly. Poll /api/v1/jobs/{job_id}.
    """
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
    return queue_job(request, kind=JobKind.SOIL_FIT, owner_id=actor.user_id, project_id=project_id,
                     payload={"measurements": [item.model_dump() for item in payload.measurements],
                              "array": payload.array, "layer_count": payload.layer_count,
                              "outlier_threshold": payload.outlier_threshold})


@router.post("/mediciones-suelo/archivo/ajustar", status_code=202)
def fit_soil_file(project_id: str, payload: SoilFileImportRequest, request: Request,
                  actor=Depends(require("designs:write"))):
    """Queue the import of explicit CSV/XLSX columns from a scanned project upload and the sounding fit."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        upload = db.one("file_uploads", id=payload.upload_id, project_id=project_id,
                        owner_id=actor.user_id)
    if not upload or upload["status"] != "available":
        raise HTTPException(404, "Scanned project file not found")
    if upload["expected_mime"] not in {"text/csv", XLSX_MIME}:
        raise HTTPException(415, "Only scanned CSV and XLSX files can be imported")
    return queue_job(request, kind=JobKind.SOIL_FILE_FIT, owner_id=actor.user_id, project_id=project_id,
                     payload=payload.model_dump(mode="json"))


def owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def snapshot(payload):
    return validate_artifact(snapshot_fields(payload.model_dump(mode="json")))


def with_calculation_freshness(db, row: dict) -> dict:
    """Attach calculation freshness derived from immutable artifact versions."""
    calculations = db.many("calculos_potencial_tierras", project_id=row["project_id"],
                            artifact_id=row["artifact_id"], limit=1000)
    latest = max(calculations, key=lambda item: (item["created_at"], item["updated_at"])) if calculations else None
    if not latest:
        status = "sin_calculo"
    elif latest["artifact_version"] != row["version"]:
        status = "desactualizado"
    elif latest["status"] in {"pending", "running"}:
        status = "calculando"
    elif latest["status"] == "completed":
        status = "al_dia"
    else:
        status = "error"
    return {**row, "calculation_status": status,
            "calculation_version": latest["artifact_version"] if latest else None,
            "latest_calculation_id": latest["id"] if latest else None,
            "calculation_verdict": _version_verdict(calculations, row["version"])}


def _version_verdict(calculations: list, version: int) -> str:
    """Stored safety verdict of the newest completed calculation of this exact version."""
    from src.infrastructure.agents.calculation_summary import summarize
    done = [c for c in calculations if c["artifact_version"] == version and c["status"] == "completed"]
    return summarize(max(done, key=lambda c: (c["created_at"], c["updated_at"])))["verdict"] if done else "no_evaluado"


def design_status(db, project_id: str) -> dict:
    """One state per project: sin_diseno, borrador, no_cumple or cumple, plus whether a study is published."""
    rows = db.designs.latest_by_artifact(project_id)
    count = len(db.many("studies", project_id=project_id, status="published", limit=100))
    published = count > 0
    if not rows:
        return {"state": "sin_diseno", "published": published, "published_count": count}
    newest = max(rows, key=lambda r: r["created_at"])
    verdict = with_calculation_freshness(db, newest)["calculation_verdict"]
    return {"state": verdict if verdict in {"cumple", "no_cumple"} else "borrador", "published": published, "published_count": count}


def announce_user_artifact_update(db, project_id: str, row: dict, previous: dict | None, summary: str) -> None:
    """Mirror direct artifact edits in the project's active conversation."""
    states = db.many("agent_conversation_state", project_id=project_id, artifact_id=row["artifact_id"], limit=1)
    if not states:
        return
    conversation_id = states[0]["id"]
    now = int(time())
    previous_snapshot = previous["snapshot"] if previous else None
    payload = {
        "kind": "artifact.updated",
        "artifact_id": row["artifact_id"],
        "version": row["version"],
        "previous_version": previous["version"] if previous else None,
        "name": row["name"],
        "summary": summary,
        "changes": diff(previous_snapshot, row["snapshot"]),
        "missing_for_calculation": missing_for_calculation(row["snapshot"]),
    }
    db.add("chat_messages", id=str(uuid4()), conversation_id=conversation_id, source="notification",
           text=f"Se editó el diseño «{row['name']}» (versión {row['version']}): {summary}",
           type="text", generated_at=now, created_at=now, updated_at=now, status="completed",
           task_id=None, run_id=None, payload=payload, created_ms=now * 1000)
    db.change("conversations", conversation_id, updated_at=now)


@router.post("", status_code=201)
def create_artifact(project_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        row = db.designs.create(project_id, payload.name, snapshot(payload), actor.user_id, {"kind": "user"})
        announce_user_artifact_update(db, project_id, row, None, "Se creó desde el editor")
        return row


@router.get("")
def list_artifacts(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        return [with_calculation_freshness(db, row) for row in db.designs.latest_by_artifact(project_id)]


@router.get("/{artifact_id}/versions")
def list_versions(project_id: str, artifact_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        rows = [with_calculation_freshness(db, row) for row in db.designs.versions(project_id, artifact_id)]
    if not rows:
        raise HTTPException(404, "Artifact not found")
    return rows


@router.get("/{artifact_id}/versions/{version}")
def get_version(project_id: str, artifact_id: str, version: int, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
        enriched = with_calculation_freshness(db, row) if row else None
    if not row:
        raise HTTPException(404, "Artifact version not found")
    return enriched


@router.get("/{artifact_id}/versions/{version}/materiales")
def version_bill_of_materials(project_id: str, artifact_id: str, version: int, request: Request,
                              actor=Depends(require("designs:read"))):
    """Bill of materials taken off this version's geometry: the same quantities the published study shows."""
    from src.infrastructure.services.bill_of_materials import bill_of_materials
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
        if not row:
            raise HTTPException(404, "Artifact version not found")
        bom = bill_of_materials(row["snapshot"], row.get("origin"), db, project_id)
    return {"artifact_id": artifact_id, "version": version, "bill_of_materials": bom}


@router.get("/{artifact_id}/versions/{version}/coherencia")
def check_version_coherence(project_id: str, artifact_id: str, version: int, request: Request,
                            actor=Depends(require("designs:read"))):
    """BL-15: deterministic coherence diagnostics of the version's calculation inputs (ranges, t_c >= t_s,
    surface layer against the soil). Errors block `calculos-potencial`; warnings travel with the result."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
    if not row:
        raise HTTPException(404, "Artifact version not found")
    diagnostics = coherence_diagnostics(row["snapshot"])
    return {"artifact_id": artifact_id, "version": version, "diagnostics": diagnostics,
            "errors": [d for d in diagnostics if d["severity"] == "error"],
            "warnings": [d for d in diagnostics if d["severity"] == "warning"],
            "missing": missing_for_calculation(row["snapshot"])}


@router.post("/{artifact_id}/versions", status_code=201)
@router.put("/{artifact_id}", status_code=201)
def create_version(project_id: str, artifact_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        previous = db.designs.latest(project_id, artifact_id)
        row = db.designs.append_version(project_id, artifact_id, payload.name, snapshot(payload), actor.user_id,
                                        {"kind": "user"})
        announce_user_artifact_update(db, project_id, row, previous, "Cambios guardados desde el editor")
        return row


@router.post("/{artifact_id}/versions/{version}/restaurar", status_code=201)
def restore_version(project_id: str, artifact_id: str, version: int, request: Request,
                    actor=Depends(require("designs:write"))):
    """Undo: append a new version with the snapshot of an earlier one (history is never rewritten)."""
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
        if not row:
            raise HTTPException(404, "Artifact version not found")
        previous = db.designs.latest(project_id, artifact_id)
        restored = db.designs.append_version(project_id, artifact_id, row["name"], row["snapshot"], actor.user_id,
                                             {"kind": "user", "restored_from": version,
                                              "provenance": (row.get("origin") or {}).get("provenance")})
        announce_user_artifact_update(db, project_id, restored, previous, f"Se restauró la versión {version}")
        return restored


@router.delete("/{artifact_id}/versions/{version}", status_code=204)
def delete_version(project_id: str, artifact_id: str, version: int, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        if not db.designs.delete_version(project_id, artifact_id, version):
            raise HTTPException(404, "Artifact version not found")
    return Response(status_code=204)


@router.post("/{artifact_id}/versions/{version}/calculos-potencial", status_code=202)
def request_potential_calculation(project_id: str, artifact_id: str, version: int, payload: PotentialCalculationRequest,
                                  request: Request, actor=Depends(require("designs:write"))):
    """Queue a potential-engine calculation for one immutable artifact version."""
    store = request.app.state.services.store
    with store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        try:
            row = potential_calculations.create_calculation(db, project_id, artifact_id, version,
                                                            payload.model_dump(), actor.user_id)
        except potential_calculations.CalculationBlocked as exc:
            raise HTTPException(exc.status, exc.detail) from exc
    # Dispatch only after the database transaction has committed.
    try:
        calculate_artifact_potential.apply_async(args=[row["id"]], task_id=row["id"])
    except Exception as exc:
        potential_calculations.mark_dispatch_failed(store, row["id"])
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
    # An agent run waiting for this calculation continues (and reports the cancellation).
    run_id = AgentRuns(request.app.state.services.store).calculation_finished(calculation_id)
    if run_id:
        try:
            enqueue_agent_step(run_id)
        except Exception:
            AgentRuns(request.app.state.services.store).fail(run_id, "Unable to queue agent step after cancellation")
    return {**row, "status": "cancelled"}
