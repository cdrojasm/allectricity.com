"""Versioned land grounding design artifact endpoints."""

from time import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from hashlib import sha256
from zipfile import BadZipFile

from src.application.use_cases import potential_calculations
from src.domain.spat.artifact_contract import validate_artifact
from src.infrastructure.entrypoint.api.schemas import (GroundingArtifactRequest, PotentialCalculationRequest,
                                                       SoilFileImportRequest, SoilMeasurementsRequest)
from src.domain.spat import soil_materials
from src.infrastructure.calculations.soil_sounding import fit_sounding
from src.application.use_cases.agent_runs import AgentRuns
from src.infrastructure.entrypoint.worker.tasks import calculate_artifact_potential, enqueue_agent_step
from src.infrastructure.security.middleware import require
from src.infrastructure.entrypoint.api.file_routes import storage_client
from src.infrastructure.processing.measurement_tables import XLSX_MIME, extract, read_table
from src.domain.spat.soundings import apparent_resistivity

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefactos-diseno-tierras", tags=["artefactos-diseno-tierras"])
catalog_router = APIRouter(prefix="/api/v1", tags=["catalogos"])


@catalog_router.get("/materiales-suelo")
def soil_material_table(q: str | None = None, resistividad_ohm_m: float | None = None,
                        actor=Depends(require())):
    """Indicative soil resistivity by material (orientation only; never replaces a sounding)."""
    if resistividad_ohm_m is not None and resistividad_ohm_m <= 0:
        raise HTTPException(422, "resistividad_ohm_m must be positive")
    if q is None and resistividad_ohm_m is None:
        return soil_materials.table()
    return soil_materials.search(q, resistividad_ohm_m, limit=50)


@router.post("/mediciones-suelo/ajustar")
def fit_soil_measurements(project_id: str, payload: SoilMeasurementsRequest, request: Request,
                          actor=Depends(require("designs:write"))):
    """Fit a Wenner/Schlumberger sounding to a 2-layer (image series) or 3-8-layer soil model.

    The returned `soil_layers` use the artifact format (`depth_m` = layer thickness, null for the
    bottom half-space) and stay within the potential engine's limits, so they can be stored in an
    artifact and calculated directly.
    """
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
    try:
        return fit_sounding([item.model_dump() for item in payload.measurements], payload.array,
                            payload.layer_count, payload.outlier_threshold)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/mediciones-suelo/archivo/ajustar")
def fit_soil_file(project_id: str, payload: SoilFileImportRequest, request: Request,
                  actor=Depends(require("designs:write"))):
    """Import explicit CSV/XLSX columns from a scanned project upload and fit the sounding."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        upload = db.one("file_uploads", id=payload.upload_id, project_id=project_id,
                        owner_id=actor.user_id)
    if not upload or upload["status"] != "available":
        raise HTTPException(404, "Scanned project file not found")
    mime = upload["expected_mime"]
    if mime not in {"text/csv", XLSX_MIME}:
        raise HTTPException(415, "Only scanned CSV and XLSX files can be imported")
    try:
        data = storage_client().read_object(upload["target_bucket"], upload["object_key"], 25 * 1024 * 1024)
        sheets = read_table(data, mime)
        table = extract(sheets, sheet=payload.sheet, spacing_column=payload.spacing_column,
                        value_column=payload.value_column, potential_column=payload.potential_column,
                        first_row=payload.first_row, last_row=payload.last_row, decimal=payload.decimal)
        factor = {"m": 1.0, "cm": 0.01, "mm": 0.001}[payload.spacing_unit]
        potential_factor = {"m": 1.0, "cm": 0.01, "mm": 0.001}[payload.potential_spacing_unit]
        value_factor = {"ohm_m": 1.0, "ohm_cm": 0.01, "ohm": 1.0}[payload.value_unit]
        readings = []
        for item in table["readings"]:
            spacing = item["spacing_m"] * factor
            potential = item.get("potential_spacing_m")
            if potential is not None:
                potential *= potential_factor
            if payload.value_kind == "resistance":
                if payload.value_unit != "ohm":
                    raise ValueError("Resistance readings must use value_unit='ohm'")
                rho = apparent_resistivity(payload.array, spacing, item["value"], potential)
            else:
                if payload.value_unit == "ohm":
                    raise ValueError("Apparent resistivity readings need value_unit='ohm_m' or 'ohm_cm'")
                rho = item["value"] * value_factor
            reading = {"spacing_m": spacing, "apparent_resistivity_ohm_m": rho,
                       "locator": item["locator"]}
            if potential is not None:
                reading["potential_spacing_m"] = potential
            readings.append(reading)
        source = {"kind": "file", "upload_id": payload.upload_id, "filename": upload["filename"],
                  "mime_type": mime, "sha256": sha256(data).hexdigest(), "sheet": table["sheet"],
                  "rows": [r["locator"] for r in readings],
                  "skipped_rows": table["skipped_rows"], "value_kind": payload.value_kind,
                  "spacing_unit": payload.spacing_unit, "value_unit": payload.value_unit}
        fit = fit_sounding([{k: v for k, v in row.items() if k != "locator"} for row in readings],
                           payload.array, payload.layer_count, payload.outlier_threshold)
        return {**fit, "source": source, "measurements": readings}
    except (ValueError, ArithmeticError, UnicodeDecodeError, BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc


def owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def snapshot(payload):
    return validate_artifact(payload.model_dump(mode="json"))


@router.post("", status_code=201)
def create_artifact(project_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        return db.designs.create(project_id, payload.name, snapshot(payload), actor.user_id, {"kind": "user"})


@router.get("")
def list_artifacts(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        return db.designs.latest_by_artifact(project_id)


@router.get("/{artifact_id}/versions")
def list_versions(project_id: str, artifact_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        rows = db.designs.versions(project_id, artifact_id)
    if not rows:
        raise HTTPException(404, "Artifact not found")
    return rows


@router.get("/{artifact_id}/versions/{version}")
def get_version(project_id: str, artifact_id: str, version: int, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
    if not row:
        raise HTTPException(404, "Artifact version not found")
    return row


@router.post("/{artifact_id}/versions", status_code=201)
@router.put("/{artifact_id}", status_code=201)
def create_version(project_id: str, artifact_id: str, payload: GroundingArtifactRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        return db.designs.append_version(project_id, artifact_id, payload.name, snapshot(payload), actor.user_id,
                                         {"kind": "user"})


@router.post("/{artifact_id}/versions/{version}/restaurar", status_code=201)
def restore_version(project_id: str, artifact_id: str, version: int, request: Request,
                    actor=Depends(require("designs:write"))):
    """Undo: append a new version with the snapshot of an earlier one (history is never rewritten)."""
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        row = db.designs.get_version(project_id, artifact_id, version)
        if not row:
            raise HTTPException(404, "Artifact version not found")
        return db.designs.append_version(project_id, artifact_id, row["name"], row["snapshot"], actor.user_id,
                                         {"kind": "user", "restored_from": version,
                                                 "provenance": (row.get("origin") or {}).get("provenance")})


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
