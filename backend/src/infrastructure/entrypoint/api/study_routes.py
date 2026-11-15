"""Study publication and read-only sharing endpoints (E5 / H3)."""

from hashlib import sha256
import os
from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.security.middleware import require

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
    "show_terra_brand": True,
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
    if not study or study["status"] != "published" or (study["expires_at"] and study["expires_at"] <= now):
        raise HTTPException(404, "Study not found")
    if not render and access and study["access"] == "password" and study["password_hash"] != _hash(access.password or ""):
        raise HTTPException(401, "Study password required")
    return study


RESULT_DETAIL_KEYS = ("grid_resistance_ohm", "gpr_v", "injected_current_a", "safety", "conductor_thermal", "surface_potential", "model_warnings")


def _calculation_detail(calculation):
    """What the public study draws from a completed calculation: the same fields the workspace results panel
    shows, so the study and the workspace cannot reach different conclusions from the same stored result."""
    result = calculation.get("result") or {}
    parameters = calculation.get("parameters") or {}
    return {"result": {key: result[key] for key in RESULT_DETAIL_KEYS if key in result},
            "parameters": {key: parameters.get(key) for key in ("touch_reach_m", "safety_standards")}}


def _latest_completed(db, study):
    rows = [row for row in db.many("calculos_potencial_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], artifact_version=study["artifact_version"], limit=1000) if row["status"] == "completed"]
    return max(rows, key=lambda row: row["created_at"]) if rows else None


def _verdict(db, study) -> str:
    """The stored safety verdict of the pinned version (never the model's opinion)."""
    from src.infrastructure.agents.calculation_summary import summarize
    latest = _latest_completed(db, study)
    return summarize(latest)["verdict"] if latest else "no_evaluado"


def _payload(db, study):
    artifact = db.one("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], version=study["artifact_version"])
    project = db.one("projects", id=study["project_id"])
    if not artifact or not project:
        raise HTTPException(409, "The pinned artifact version is no longer available")
    latest = db.one("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], version=max(r["version"] for r in db.many("artefacto_diseno_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], limit=None)))
    snapshot = artifact["snapshot"]
    unconfirmed = snapshot.get("unconfirmed_critical") or (artifact.get("origin") or {}).get("unconfirmed_critical") or []
    config = dict(study["config"] or {})
    logo_id = config.get("logo_upload_id")
    if logo_id:
        from src.infrastructure.entrypoint.api.file_routes import storage_client
        logo = db.one("file_uploads", id=logo_id, project_id=study["project_id"], status="available")
        if logo:
            config["logo_url"] = storage_client().presign_download(logo["target_bucket"], logo["object_key"], logo["filename"])
    references = [{"path": path, "reference": value} for path, value in ((artifact.get("origin") or {}).get("provenance") or {}).items() if value]
    calculation_detail = None
    calculations = [row for row in db.many("calculos_potencial_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], artifact_version=study["artifact_version"], limit=1000) if row["status"] == "completed"]
    if calculations:
        from src.infrastructure.agents.calculation_summary import summarize
        latest_calculation = max(calculations, key=lambda row: row["created_at"])
        snapshot = {**snapshot, "result": summarize(latest_calculation)}
        calculation_detail = _calculation_detail(latest_calculation)
    return {"study": {**{k: study[k] for k in ("id", "slug", "title", "access", "status", "artifact_id", "artifact_version", "expires_at", "published_at", "updated_at")}, "config": config}, "project": {"name": project["name"], "description": project["description"], "city": project.get("city"), "country": project.get("country")}, "artifact": snapshot, "calculation": calculation_detail, "references": references, "draft": bool(unconfirmed), "unconfirmed_critical": unconfirmed, "non_compliant": _verdict(db, study) == "no_cumple", "has_newer_version": bool(latest and latest["version"] > study["artifact_version"])}


_DENIALS = ("no se cuenta", "no se dispone", "sin resultados", "no hay resultados", "no existen resultados", "aún no se ha calculado", "no se ha realizado")


def _denies_results(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _DENIALS)


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
        slug = data.slug or _slug(data.title)
        if db.one("studies", slug=slug):
            slug = f"{slug}-{uuid4().hex[:6]}"
        row = {"id": str(uuid4()), "project_id": project_id, "owner_id": actor.user_id, "slug": slug, "artifact_id": data.artifact_id, "artifact_version": artifact["version"], "title": data.title, "access": data.access, "status": "draft", "config": {**DEFAULT_CONFIG, **(data.config or {})}, "password_hash": _hash(data.password), "expires_at": data.expires_at, "published_at": None, "created_at": now, "updated_at": now}
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
        changes = {"artifact_id": data.artifact_id, "artifact_version": version, "title": data.title, "access": data.access, "password_hash": _hash(data.password) if data.password else study["password_hash"], "expires_at": data.expires_at, "config": {**study["config"], **(data.config or {})}, "updated_at": int(time())}
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


@router.post("/{study_id}/sections/{section_id}/generate")
def generate_study_section(project_id: str, study_id: str, section_id: str, data: SectionGenerationRequest, request: Request, actor=Depends(require("designs:write"))):
    if section_id not in {"summary", "inputs", "results", "references"}:
        raise HTTPException(404, "Study section not found")
    with request.app.state.services.store.transaction() as db:
        _owned_project(db, project_id, actor)
        study = db.one("studies", id=study_id, project_id=project_id)
        artifact = db.one("artefacto_diseno_tierras", project_id=project_id, artifact_id=study["artifact_id"], version=study["artifact_version"]) if study else None
        latest = _latest_completed(db, study) if study and artifact else None
    if not study or not artifact: raise HTTPException(404, "Study or artifact not found")
    from src.infrastructure.agents.calculation_summary import summarize
    outcome = summarize(latest) if latest else None
    try:
        from src.infrastructure.agents.runtime import clients
        _, client = clients()
        response = client.chat.completions.create(model=os.getenv("STUDY_WRITER_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini")), temperature=0.2, max_tokens=500, messages=[
            {"role": "system", "content": "Escribe un párrafo técnico breve en español para un estudio de puesta a tierra. No inventes valores: si faltan datos, dilo explícitamente. Si se entrega un resultado de cálculo, es la fuente de verdad: cita su veredicto (cumple / no cumple) tal cual y nunca digas que faltan resultados. No uses identificadores internos ni ids; nombra el proyecto por su título. Devuelve solo el párrafo."},
            {"role": "user", "content": f"Sección: {section_id}. Título: {study['title']}. Artefacto: {artifact['snapshot']}. Resultado del cálculo fijado: {outcome if outcome else 'sin cálculo para esta versión'}. Instrucción: {data.instruction or 'Resume esta sección para un revisor técnico.'}"},
        ])
        text = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(503, "El generador de texto no está disponible") from exc
    if outcome and outcome["verdict"] in {"cumple", "no_cumple"} and _denies_results(text):
        # The model denied results that exist: use the stored verdict instead of publishing a false statement.
        text = ("El diseño cumple los criterios evaluados." if outcome["verdict"] == "cumple"
                else "El diseño no cumple los criterios evaluados; ver la tabla de resultados.")
    return {"section_id": section_id, "text": text}


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
        slug = data.slug or f"{previous['slug']}-v{artifact['version']}"
        if db.one("studies", slug=slug): slug = f"{slug}-{uuid4().hex[:6]}"
        row = {"id": str(uuid4()), "project_id": project_id, "owner_id": actor.user_id, "slug": slug, "artifact_id": data.artifact_id, "artifact_version": artifact["version"], "title": data.title, "access": data.access, "status": "published", "config": {**(previous["config"] or {}), **(data.config or {})}, "password_hash": _hash(data.password) or previous["password_hash"], "expires_at": data.expires_at, "published_at": now, "created_at": now, "updated_at": now}
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
        result["url"] = storage_client().presign_download(storage_client().allowed_buckets["designs"], study["pdf_key"], f"{study['slug']}.pdf")
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
