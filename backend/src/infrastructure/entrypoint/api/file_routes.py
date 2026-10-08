from functools import lru_cache
import hmac
import os
from time import time
from urllib.parse import unquote_plus
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.entrypoint.worker.tasks import scan_file_upload
from src.infrastructure.security.middleware import require
from src.infrastructure.storage.object_storage import ObjectStorage

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@lru_cache
def storage_client():
    return ObjectStorage()


ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=1, max_length=120)
    category: str = Field(pattern="^(documents|designs)$")
    project_id: str = Field(min_length=1, max_length=36)
    retry_upload_id: str | None = Field(default=None, min_length=36, max_length=36)


@router.post("/events/minio", include_in_schema=False)
async def minio_object_event(
    payload: dict,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Accept MinIO bucket notifications and enqueue matching quarantine uploads."""
    expected = os.getenv("MINIO_WEBHOOK_AUTH_TOKEN", "")
    # MinIO sends "Bearer <token>" unless the configured token contains a space.
    provided = (authorization or "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid MinIO notification credentials")
    queued = 0
    for record in payload.get("Records", []):
        bucket = record.get("s3", {}).get("bucket", {}).get("name")
        object_info = record.get("s3", {}).get("object", {})
        event_name = record.get("eventName", "")
        if bucket != storage_client().quarantine_bucket or not event_name.startswith("s3:ObjectCreated:"):
            continue
        key = unquote_plus(object_info.get("key", ""))
        with request.app.state.services.store.transaction(write=True) as db:
            upload = db.one("file_uploads", quarantine_key=key)
            if not upload or upload["status"] not in {"pending", "failed"}:
                continue
            db.change("file_uploads", upload["id"], status="scanning", updated_at=int(time()),
                      processing_started_at=None, last_error=None)
        try:
            scan_file_upload.delay(upload["id"])
        except Exception as exc:
            with request.app.state.services.store.transaction(write=True) as db:
                db.change("file_uploads", upload["id"], status="pending", updated_at=int(time()),
                          last_error="No se pudo poner el archivo en cola. Vuelve a intentarlo.")
            raise HTTPException(503, "Unable to queue file processing") from exc
        queued += 1
    return {"queued": queued}



@router.post("/presign", status_code=201)
def presign_upload(
    payload: UploadRequest, request: Request, actor=Depends(require("files:write"))
):
    if payload.mime_type not in ALLOWED_MIME:
        raise HTTPException(415, "Unsupported file type")
    with request.app.state.services.store.transaction() as db:
        project = db.one("projects", id=payload.project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    upload_id = str(uuid4())
    suffix = payload.filename.rsplit(".", 1)[-1].lower() if "." in payload.filename else "bin"
    quarantine_key = f"{actor.user_id}/{upload_id}.{suffix}"
    object_key = f"{actor.user_id}/{upload_id}.{suffix}"
    now = int(time())
    with request.app.state.services.store.transaction(write=True) as db:
        existing = next((item for item in db.many("file_uploads", project_id=payload.project_id,
                                                   owner_id=actor.user_id, limit=1000)
                         if item["filename"].casefold() == payload.filename.casefold()), None)
        if existing:
            if payload.retry_upload_id != existing["id"] or existing["status"] != "expired":
                raise HTTPException(409, "Ya existe un archivo con ese nombre en este proyecto.")
            upload_id = existing["id"]
            db.change("file_uploads", upload_id, quarantine_key=quarantine_key, object_key=object_key,
                      expected_mime=payload.mime_type, status="pending", updated_at=now,
                      last_error=None, processing_started_at=None, quarantine_deleted_at=None)
        else:
            db.add(
                "file_uploads",
                id=upload_id,
                owner_id=actor.user_id,
                project_id=payload.project_id,
                filename=payload.filename,
                quarantine_key=quarantine_key,
                target_bucket=storage_client().allowed_buckets["documents"],
                object_key=object_key,
                expected_mime=payload.mime_type,
                status="pending",
                created_at=now,
                updated_at=now,
            )
    return {
        "upload_id": upload_id,
        "upload_url": storage_client().presign_upload(quarantine_key, payload.mime_type),
        "method": "PUT",
        "expires_in": 900,
        "required_headers": {},
        "status": "pending",
    }


@router.post("/{upload_id}/complete", status_code=202)
def complete_upload(
    upload_id: str, request: Request, actor=Depends(require("files:write"))
):
    with request.app.state.services.store.transaction(write=True) as db:
        upload = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
        if not upload:
            raise HTTPException(404, "Upload not found")
        if upload["status"] == "available":
            return {"upload_id": upload_id, "status": "available"}
        if upload["status"] == "rejected":
            raise HTTPException(409, f"Upload is {upload['status']}")
        if upload["status"] == "expired":
            raise HTTPException(409, "Upload expired; upload the file again")
        if upload["status"] == "failed":
            raise HTTPException(409, "Upload failed; use the retry endpoint")
        if upload["status"] == "scanning":
            return {"upload_id": upload_id, "status": "scanning"}
        db.change("file_uploads", upload_id, status="scanning", updated_at=int(time()),
                  processing_started_at=None, last_error=None)
    try:
        scan_file_upload.delay(upload_id)
    except Exception as exc:
        with request.app.state.services.store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status="pending", updated_at=int(time()),
                      last_error="No se pudo poner el archivo en cola. Se reintentará automáticamente.")
        raise HTTPException(503, "Unable to queue file scan") from exc
    return {"upload_id": upload_id, "status": "scanning"}


@router.post("/{upload_id}/retry", status_code=202)
def retry_upload(upload_id: str, request: Request, actor=Depends(require("files:write"))):
    store = request.app.state.services.store
    with store.transaction() as db:
        upload = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload["status"] == "available":
        return {"upload_id": upload_id, "status": "available"}
    if upload["status"] != "failed":
        raise HTTPException(409, f"Upload cannot be retried while it is {upload['status']}")

    storage = storage_client()
    if storage.exists(upload["target_bucket"], upload["object_key"]):
        with store.transaction(write=True) as db:
            current = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
            if current and current["status"] == "failed":
                db.change("file_uploads", upload_id, status="available", updated_at=int(time()),
                          processing_started_at=None, last_error=None)
        return {"upload_id": upload_id, "status": "available"}
    if not storage.exists(storage.quarantine_bucket, upload["quarantine_key"]):
        with store.transaction(write=True) as db:
            current = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
            if current and current["status"] == "failed":
                db.change("file_uploads", upload_id, status="expired", updated_at=int(time()),
                          processing_started_at=None,
                          last_error="El archivo ya no está disponible en cuarentena. Vuelve a cargarlo.")
        raise HTTPException(409, "The original upload is no longer available; upload the file again")

    with store.transaction(write=True) as db:
        current = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
        if not current:
            raise HTTPException(404, "Upload not found")
        if current["status"] != "failed":
            return {"upload_id": upload_id, "status": current["status"]}
        db.change("file_uploads", upload_id, status="scanning", updated_at=int(time()),
                  processing_started_at=None, last_error=None)
    try:
        scan_file_upload.delay(upload_id)
    except Exception as exc:
        with store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status="failed", updated_at=int(time()),
                      processing_started_at=None,
                      last_error="No se pudo poner el archivo en cola. Vuelve a intentarlo.")
        raise HTTPException(503, "Unable to queue file retry") from exc
    return {"upload_id": upload_id, "status": "scanning"}


@router.get("/{upload_id}")
def upload_status(
    upload_id: str, request: Request, actor=Depends(require("files:read"))
):
    with request.app.state.services.store.transaction() as db:
        upload = db.one("file_uploads", id=upload_id, owner_id=actor.user_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    return {
        "upload_id": upload_id,
        "status": upload["status"],
        "ocr_confidence": upload.get("ocr_confidence"),
        "ocr_needs_review": upload.get("ocr_needs_review", False),
        "attempt_count": upload.get("attempt_count", 0),
        "last_error": upload.get("last_error"),
        "created_at": upload["created_at"],
        "updated_at": upload["updated_at"],
    }
