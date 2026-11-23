"""Study publication and read-only sharing endpoints (E5 / H3)."""

from hashlib import sha256
import re
import os
from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.domain.agent.patches import unconfirmed_critical
from src.domain.jobs import JobKind
from src.infrastructure.entrypoint.api.job_routes import queue_job, require_llm_capacity
from src.infrastructure.security.middleware import require
from src.infrastructure.services.study_text import denies_results as _denies_results  # noqa: F401
from src.infrastructure.services.study_text import latest_completed as _latest_completed
from src.infrastructure.services.study_text import plain_codes as _plain_codes  # noqa: F401
from src.infrastructure.services.bill_of_materials import bill_of_materials as _bill_of_materials

router = APIRouter(prefix="/api/v1/projects/{project_id}/studies", tags=["studies"])
public_router = APIRouter(prefix="/api/v1/public/studies", tags=["public-studies"])

DEFAULT_CONFIG = {
    "sections": [
        {"id": "summary", "label": "Resumen", "enabled": True, "text": ""},
        {"id": "inputs", "label": "Entradas", "enabled": True, "text": ""},
        {"id": "results", "label": "Resultado", "enabled": True, "text": ""},
        {"id": "references", "label": "Referencias", "enabled": True, "text": ""},
    ],
    "logo_upload_id": None,
    "show_allectricity_brand": True,
    "traceability": "appendix",
}


class StudyRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=36)
    artifact_version: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    access: str = Field(default="link", pattern="^(public|link|password)$")
    password: str | None = Field(default=None, min_length=8, max_length=128)
    expires_at: int | None = Field(default=None, gt=0)
    config: dict | None = None



class PublishRequest(BaseModel):
    status: str = Field(pattern="^(draft|published|revoked)$")
    confirm_non_compliant: bool = False


class PublicAccessRequest(BaseModel):
    password: str | None = None


class StudyAccessRequest(BaseModel):
    access: str = Field(pattern="^(public|link|password)$")
    password: str | None = Field(default=None, min_length=8, max_length=128)
    expires_at: int | None = Field(default=None, gt=0)


class SectionGenerationRequest(BaseModel):
    instruction: str | None = Field(default=None, max_length=1000)


def _merge_study_config(base: dict | None, updates: dict | None) -> dict:
    base, updates = base or {}, updates or {}
    merged = {**base, **updates}
    if "show_allectricity_brand" in updates:
        merged["show_allectricity_brand"] = updates["show_allectricity_brand"]
    elif "show_terra_brand" in updates:
        # Older clients still send this field.
        merged["show_allectricity_brand"] = updates["show_terra_brand"]
    elif "show_allectricity_brand" in base:
        merged["show_allectricity_brand"] = base["show_allectricity_brand"]
    elif "show_terra_brand" in merged:
        # Existing studies and older clients still send this field.
        merged["show_allectricity_brand"] = merged["show_terra_brand"]
    else:
        merged["show_allectricity_brand"] = True
    return merged


def _hash(value):
    return sha256(value.encode("utf-8")).hexdigest() if value else None


def _slug(title):
    import re
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value[:100] or "estudio"


def _artifact_version(db, project_id, artifact_id, version=None):
    if version is not None:
        return db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, version=version)
    rows = db.many("artefacto_diseno_tierras", project_id=project_id, artifact_id=artifact_id, limit=None)
    return max(rows, key=lambda row: row["version"]) if rows else None


def _owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def _public_study(db, slug, access=None, render=False):
    study = db.one("studies", slug=slug)
    now = int(time())
    # Say why a link does not open. A draft is reported as missing so its existence is not disclosed.
    if study and study["status"] == "revoked":
        raise HTTPException(410, {"code": "revoked", "message": "El enlace existe, pero el estudio fue revocado.", "revoked_at": study["updated_at"]})
    if not study or study["status"] != "published":
        raise HTTPException(404, {"code": "not_found", "message": "No existe un estudio publicado con este enlace."})
    if study["expires_at"] and study["expires_at"] <= now:
        raise HTTPException(410, {"code": "expired", "message": "El enlace existe, pero venció.", "expired_at": study["expires_at"]})
    if not render and access and study["access"] == "password" and study["password_hash"] != _hash(access.password or ""):
        raise HTTPException(401, "Study password required")
    return study


# max_touch_v / max_step_v place the worst points in the report's 3D view.
RESULT_DETAIL_KEYS = ("grid_resistance_ohm", "gpr_v", "injected_current_a", "safety", "conductor_thermal", "surface_potential", "model_warnings", "max_touch_v", "max_step_v")


def _calculation_detail(calculation):
    """What the public study draws from a completed calculation: the same fields the workspace results panel
    shows, so the study and the workspace cannot reach different conclusions from the same stored result."""
    result = calculation.get("result") or {}
    parameters = calculation.get("parameters") or {}
    return {"result": {key: result[key] for key in RESULT_DETAIL_KEYS if key in result},
            "parameters": {key: parameters.get(key) for key in ("touch_reach_m", "safety_standards")}}


def _verdict(db, study) -> str:
    """The stored safety verdict of the pinned version (never the model's opinion)."""
    from src.infrastructure.agents.calculation_summary import summarize
    latest = _latest_completed(db, study)
    return summarize(latest)["verdict"] if latest else "no_evaluado"


def _optimization(db, project_id, origin):
    """What the study says about an optimizer-applied version: the applied alternative against the base design,
    where the rates came from and the run's warnings. Read from the stored run, never recomputed, so the study
    cannot differ from the workspace comparison. None when the version did not come from the optimizer."""
    applied = (origin or {}).get("optimizer")
    if not applied or not applied.get("run_id"):
        return None
    from src.application.use_cases.optimizer_topology_job import compare_alternatives
    from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository
    repository = OptimizerRunRepository(db.connection)
    run = repository.get_run(project_id, applied["run_id"])
    if not run:
        return {"available": False, "certified": False, "run_id": applied["run_id"]}
    comparison = compare_alternatives(run, repository.list_alternatives(project_id, applied["run_id"]))
    alternative = next((row for row in comparison["alternatives"] if row["alternative_id"] == applied.get("alternative_id")), None)
    base = comparison["base"] or {}
    electrical = base.get("electrical") if isinstance(base.get("electrical"), dict) else {}
    summary = run.get("result_summary") or {}
    return {
        "available": True, "run_id": run["id"], "algorithm": comparison["algorithm"], "based_on_version": applied.get("based_on_version"),
        # With «1 por unidad» rates the costs count material, not money: the study must not print them as pesos.
        "certified": False, "currency": "u. relativas" if comparison.get("relative_costs") else comparison["currency"],
        "relative_costs": bool(comparison.get("relative_costs")), "alternative": alternative,
        "base": {"cost": base.get("cost"), "cost_status": base.get("cost_status"), "status": electrical.get("status"),
                 "feasible": electrical.get("feasible"), "ratio": electrical.get("ratio")},
        "saving": comparison["saving_vs_base"], "solver_calls": summary.get("solver_calls_total"),
        "rates": [{"item": key, **{k: value.get(k) for k in ("source_type", "source", "unit", "catalog_version")}}
                  for key, value in sorted((comparison["rate_provenance"] or {}).items())],
        "warnings": comparison["warnings"],
    }


def _client_assumptions(provenance: dict) -> list[str]:
    """Design values the agent assumed and nobody confirmed: the study must read as a draft while they remain.

    Only paths that change the engineering result count; the generated name and editor metadata do not.
    """
    ignored = {"name", "schema_version", "geometry.snap_m"}
    return sorted(path for path, value in (provenance or {}).items()
                  if isinstance(value, dict) and value.get("kind") == "assumption" and path not in ignored)


def _payload(db, study):
    artifact = db.one("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], version=study["artifact_version"])
    project = db.one("projects", id=study["project_id"])
    if not artifact or not project:
        raise HTTPException(409, "The pinned artifact version is no longer available")
    latest = db.one("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], version=max(r["version"] for r in db.many("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], limit=None)))
    snapshot = artifact["snapshot"]
    origin = artifact.get("origin") or {}
    provenance = origin.get("provenance") or {}
    unconfirmed = (snapshot.get("unconfirmed_critical") or origin.get("unconfirmed_critical")
                   or unconfirmed_critical(snapshot, provenance))
    assumptions = [path for path in _client_assumptions(provenance) if path not in (unconfirmed or [])]
    config = dict(study["config"] or {})
    logo_id = config.get("logo_upload_id")
    if logo_id:
        from src.infrastructure.entrypoint.api.file_routes import storage_client
        logo = db.one("file_uploads", id=logo_id, project_id=study["project_id"], status="available")
        if logo:
            config["logo_url"] = storage_client().presign_download(logo["target_bucket"], logo["object_key"], logo["filename"])
    # Schema metadata and editor snapping are implementation details, not client-facing references.
    internal_reference_paths = {"schema_version", "geometry.snap_m"}
    references = [{"path": path, "reference": value} for path, value in provenance.items()
                  if value and path not in internal_reference_paths
                  and (not isinstance(value, dict) or value.get("kind") != "schema_default")]
    calculation_detail = None
    calculations = [row for row in db.many("calculos_potencial_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], artifact_version=study["artifact_version"], limit=1000) if row["status"] == "completed"]
    if calculations:
        from src.infrastructure.agents.calculation_summary import summarize
        latest_calculation = max(calculations, key=lambda row: row["created_at"])
        snapshot = {**snapshot, "result": summarize(latest_calculation)}
        calculation_detail = _calculation_detail(latest_calculation)
    return {"study": {**{k: study[k] for k in ("id", "slug", "title", "access", "status", "artifact_id", "artifact_version", "expires_at", "published_at", "updated_at")}, "config": config}, "project": {"name": project["name"], "description": project["description"], "city": project.get("city"), "country": project.get("country")}, "artifact": snapshot, "calculation": calculation_detail, "references": references, "optimization": _optimization(db, study["project_id"], artifact.get("origin")), "bill_of_materials": _bill_of_materials(snapshot, artifact.get("origin"), db, study["project_id"]), "draft": bool(unconfirmed) or bool(origin.get("draft")) or bool(assumptions), "unconfirmed_critical": unconfirmed, "assumptions": assumptions, "non_compliant": _verdict(db, study) == "no_cumple", "has_newer_version": bool(latest and latest["version"] > study["artifact_version"])}




@router.get("")
def list_studies(project_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        return db.many("studies", project_id=project_id, limit=100)


@router.post("", status_code=201)
def create_study(project_id: str, data: StudyRequest, request: Request, actor=Depends(require("designs:write"))):
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        if data.access == "password" and not data.password:
            raise HTTPException(422, "password is required for password-protected studies")
        artifact = _artifact_version(db, project_id, data.artifact_id, data.artifact_version)
        if not artifact:
            raise HTTPException(404, "Artifact version not found")
        # The public link is an opaque UUID: it does not reveal the project or the study's title. Existing
        # title-based links keep working.
        slug = data.slug or str(uuid4())
        if db.one("studies", slug=slug):
            slug = str(uuid4())
        row = {"id": str(uuid4()), "project_id": project_id, "owner_id": actor.user_id, "slug": slug, "artifact_id": data.artifact_id, "artifact_version": artifact["version"], "title": data.title, "access": data.access, "status": "draft", "config": _merge_study_config(DEFAULT_CONFIG, data.config), "password_hash": _hash(data.password), "expires_at": data.expires_at, "published_at": None, "created_at": now, "updated_at": now}
        db.add("studies", **row)
        return row


@router.patch("/{study_id}")
def update_study(project_id: str, study_id: str, data: StudyRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        if not study: raise HTTPException(404, "Study not found")
        version = data.artifact_version or study["artifact_version"]
        if not db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=data.artifact_id, version=version): raise HTTPException(404, "Artifact version not found")
        changes = {"artifact_id": data.artifact_id, "artifact_version": version, "title": data.title, "access": data.access, "password_hash": _hash(data.password) if data.password else study["password_hash"], "expires_at": data.expires_at, "config": _merge_study_config(study["config"], data.config), "updated_at": int(time())}
        db.change("studies", study_id, **changes)
        return db.one("studies", id=study_id)


@router.post("/{study_id}/publish")
def publish_study(project_id: str, study_id: str, data: PublishRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        if not study: raise HTTPException(404, "Study not found")
        artifact = db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=study["artifact_id"], version=study["artifact_version"])
        if data.status == "published" and artifact is None: raise HTTPException(409, "Pinned artifact version is unavailable")
        if data.status == "published" and not data.confirm_non_compliant and _verdict(db, study) == "no_cumple":
            raise HTTPException(409, {"code": "non_compliant", "message": "El diseño no cumple la norma. Confirma que quieres publicarlo con la banda «Diseño no conforme»."})
        db.change("studies", study_id, status=data.status, published_at=int(time()) if data.status == "published" else study["published_at"], updated_at=int(time()))
        return db.one("studies", id=study_id)


@router.patch("/{study_id}/access")
def update_study_access(project_id: str, study_id: str, data: StudyAccessRequest, request: Request, actor=Depends(require("designs:write"))):
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        if not study: raise HTTPException(404, "Study not found")
        if data.access == "password" and not data.password and not study["password_hash"]: raise HTTPException(422, "password is required for password-protected studies")
        db.change("studies", study_id, access=data.access, password_hash=_hash(data.password) if data.password else study["password_hash"], expires_at=data.expires_at, updated_at=int(time()))
        return db.one("studies", id=study_id)


@router.post("/{study_id}/sections/{section_id}/generate", status_code=202)
def generate_study_section(project_id: str, study_id: str, section_id: str, data: SectionGenerationRequest, request: Request, actor=Depends(require("designs:write"))):
    """Queue the section text; poll /api/v1/jobs/{job_id} for {section_id, text}."""
    # Fixed sections, or a free text block the user added to the report («bloque-…»).
    if section_id not in {"summary", "inputs", "results", "references"} and not re.fullmatch(r"bloque-[a-z0-9]{4,32}", section_id):
        raise HTTPException(404, "Study section not found")
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        artifact = db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=study["artifact_id"], version=study["artifact_version"]) if study else None
    if not study or not artifact: raise HTTPException(404, "Study or artifact not found")
    require_llm_capacity(request, actor.user_id)
    return queue_job(request, kind=JobKind.STUDY_SECTION, owner_id=actor.user_id, project_id=project_id,
                     payload={"study_id": study_id, "section_id": section_id, "instruction": data.instruction})


@router.post("/{study_id}/republish", status_code=201)
def republish_study(project_id: str, study_id: str, data: StudyRequest, request: Request, actor=Depends(require("designs:write"))):
    """Create a new immutable publication; the previous slug remains historical."""
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        previous = db.one("studies", id=study_id, project_id=project_id)
        if not previous: raise HTTPException(404, "Study not found")
        artifact = _artifact_version(db, project_id, data.artifact_id, data.artifact_version)
        if not artifact: raise HTTPException(404, "Artifact version not found")
        slug = data.slug or str(uuid4())
        if db.one("studies", slug=slug): slug = str(uuid4())
        row = {"id": str(uuid4()), "project_id": project_id, "owner_id": actor.user_id, "slug": slug, "artifact_id": data.artifact_id, "artifact_version": artifact["version"], "title": data.title, "access": data.access, "status": "published", "config": _merge_study_config(previous["config"], data.config), "password_hash": _hash(data.password) or previous["password_hash"], "expires_at": data.expires_at, "published_at": now, "created_at": now, "updated_at": now}
        db.add("studies", **row)
        return row


@router.post("/{study_id}/pdf", status_code=202)
def request_study_pdf(project_id: str, study_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction(write=True) as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        if not study: raise HTTPException(404, "Study not found")
        if study["status"] != "published": raise HTTPException(409, "Only published studies can be rendered")
        db.change("studies", study_id, pdf_status="pending", pdf_error=None, pdf_updated_at=int(time()))
    try:
        from src.infrastructure.entrypoint.worker.tasks import render_study_pdf
        render_study_pdf.delay(study_id)
    except Exception as exc:
        with request.app.state.services.store.transaction(write=True) as db:
            db.change("studies", study_id, pdf_status="failed", pdf_error="No se pudo poner el PDF en cola", pdf_updated_at=int(time()))
        raise HTTPException(503, "Unable to queue study PDF") from exc
    return {"study_id": study_id, "pdf_status": "pending"}


@router.get("/{study_id}/pdf")
def get_study_pdf(project_id: str, study_id: str, request: Request, actor=Depends(require("designs:read"))):
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
    if not study: raise HTTPException(404, "Study not found")
    result = {"study_id": study_id, "pdf_status": study["pdf_status"], "error": study["pdf_error"], "updated_at": study["pdf_updated_at"]}
    if study["pdf_status"] == "ready" and study["pdf_key"]:
        from src.infrastructure.entrypoint.api.file_routes import storage_client
        result["url"] = storage_client().presign_download(storage_client().allowed_buckets["designs"], study["pdf_key"], f"{_slug(study['title'])}.pdf")
    return result


@public_router.post("/{slug}/access")
def public_study_access(slug: str, data: PublicAccessRequest, request: Request):
    with request.app.state.services.store.transaction() as db:
        return _payload(db, _public_study(db, slug, data))


@public_router.get("/{slug}")
def public_study(slug: str, request: Request):
    with request.app.state.services.store.transaction() as db:
        render = bool(os.getenv("STUDY_RENDER_TOKEN") and request.headers.get("x-study-render-token") == os.getenv("STUDY_RENDER_TOKEN"))
        study = _public_study(db, slug, render=render)
        if study["access"] == "password" and not render:
            return {"study": {"slug": slug, "title": study["title"], "access": "password"}, "requires_password": True}
        return _payload(db, study)
