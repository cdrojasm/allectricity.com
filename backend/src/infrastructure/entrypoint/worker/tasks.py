import os
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache

from celery import Celery
from src.application.use_cases.identity import now
from src.application.use_cases.reset_mail import DeliverResetMail
from src.infrastructure.persistence.identity_store import SQLIdentityStore
from src.infrastructure.security.providers import FernetMessages
from src.infrastructure.storage.object_storage import ObjectStorage
from src.infrastructure.processing.knowledge_extraction import extract_knowledge
from src.infrastructure.persistence.knowledge_graph_store import Neo4jKnowledgeGraph

celery_app = Celery(
    "spat", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "reset-mail-outbox": {"task": "spat.dispatch_reset_mail", "schedule": 15.0},
        "reconcile-file-uploads": {"task": "spat.reconcile_file_uploads", "schedule": 60.0},
    },
)


class SMTPMailer:
    def send_reset(self, recipient, reset_url, message_id):
        host = os.environ["SMTP_HOST"]
        port = int(os.getenv("SMTP_PORT", "587"))
        starttls = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
        if not starttls and os.getenv("SPAT_ENVIRONMENT", "local") not in {
            "local",
            "test",
        }:
            raise ValueError("SMTP STARTTLS is required outside local/test")
        message = EmailMessage()
        message["Subject"] = "Restablecer contraseña — SPAT"
        message["From"] = os.environ["SMTP_FROM"]
        message["To"] = recipient
        message["Message-ID"] = f"<{message_id}@spat.local>"
        message.set_content(
            "Recibimos una solicitud para restablecer tu contraseña.\n\n"
            + reset_url
            + "\n\nEl enlace expira y solo puede usarse una vez. "
            "Si no hiciste esta solicitud, puedes ignorar este correo."
        )
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if starttls:
                smtp.starttls(context=ssl.create_default_context())
            if os.getenv("SMTP_USERNAME"):
                smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)


@lru_cache
def dependencies():
    store = SQLIdentityStore(os.environ["DATABASE_URL"])
    return store, DeliverResetMail(
        store, FernetMessages(os.environ["AUTH_MAIL_ENCRYPTION_KEY"]), SMTPMailer()
    )


@lru_cache
def knowledge_graph():
    return Neo4jKnowledgeGraph.from_env()


@lru_cache
def upload_store():
    return SQLIdentityStore(os.environ["DATABASE_URL"])


@celery_app.task(name="spat.dispatch_reset_mail")
def dispatch_reset_mail():
    store, _ = dependencies()
    with store.transaction() as db:
        pending = [
            row["id"]
            for row in db.many("mail_outbox", sent_at=None)
            if row["available_at"] <= now()
        ][:100]
    for message_id in pending:
        send_reset_mail.delay(message_id)


@celery_app.task(
    name="spat.send_reset_mail",
    autoretry_for=(RuntimeError,),
    retry_backoff=60,
    retry_jitter=True,
    max_retries=5,
)
def send_reset_mail(message_id):
    _, delivery = dependencies()
    delivery.execute(message_id)


@celery_app.task(name="spat.agent_run_step", soft_time_limit=540, time_limit=600)
def agent_run_step(run_id):
    """One resumable step of the grounding design agent for a run."""
    from src.application.use_cases.agent_runs import run_step
    from src.infrastructure.agents import design_agent

    store = upload_store()
    run_step(store, run_id, design_agent.GroundingDesignAgent(store) if design_agent.enabled() else None,
             dispatch_calculation=lambda calculation_id: calculate_artifact_potential.apply_async(
                 args=[calculation_id], task_id=calculation_id))


def enqueue_agent_step(run_id):
    from uuid import uuid4

    agent_run_step.apply_async(args=[run_id], task_id=f"{run_id}:{uuid4().hex[:12]}")


@celery_app.task(name="spat.resolve_chat_message")
def resolve_chat_message(message_id):
    """Legacy entry point kept for messages queued before agent runs existed."""
    with upload_store().transaction() as db:
        message = db.one("chat_messages", id=message_id)
    if message and message.get("run_id"):
        agent_run_step(message["run_id"])


@celery_app.task(name="spat.calculate_artifact_potential", soft_time_limit=540, time_limit=600)
def calculate_artifact_potential(calculation_id):
    """Run the C++ potential engine for an artifact version and persist result and trace."""
    from src.application.use_cases.agent_runs import AgentRuns
    from src.infrastructure.calculations.artifact_potential import run_potential_calculation

    try:
        run_potential_calculation(upload_store(), calculation_id)
    finally:
        # An agent run waiting for this calculation continues with its result.
        run_id = AgentRuns(upload_store()).calculation_finished(calculation_id)
        if run_id:
            enqueue_agent_step(run_id)


@celery_app.task(name="spat.scan_file_upload", bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_jitter=True, max_retries=5)
def scan_file_upload(self, upload_id):
    from time import time

    store = upload_store()
    with store.transaction(write=True) as db:
        upload = db.one("file_uploads", id=upload_id)
        if not upload or upload["status"] in {"available", "rejected", "expired"}:
            return
        started_at = int(time())
        db.change("file_uploads", upload_id, status="scanning", updated_at=started_at,
                  processing_started_at=started_at,
                  attempt_count=int(upload.get("attempt_count") or 0) + 1, last_error=None)

    storage = ObjectStorage()
    maximum = int(os.getenv("UPLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
    try:
        if not storage.exists(storage.quarantine_bucket, upload["quarantine_key"]):
            if storage.exists(upload["target_bucket"], upload["object_key"]):
                with store.transaction(write=True) as db:
                    db.change("file_uploads", upload_id, status="available", updated_at=int(time()),
                              processing_started_at=None, last_error=None)
                return
            with store.transaction(write=True) as db:
                db.change("file_uploads", upload_id, status="failed", updated_at=int(time()),
                          processing_started_at=None,
                          last_error="No se encontró el archivo en cuarentena. Sube el archivo de nuevo.")
            return
        data = storage.read(upload["quarantine_key"], maximum)
        detected = storage.detected_mime(data)
        if detected != upload["expected_mime"]:
            raise ValueError("File content does not match the declared MIME type")
        storage.scan(data)
        source, _ = extract_knowledge(upload, data, detected, knowledge_graph())
        ocr = source.ocr
        storage.promote(
            upload["quarantine_key"], upload["target_bucket"], upload["object_key"], detected
        )
    except ValueError:
        with store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status="rejected", updated_at=int(time()),
                      processing_started_at=None,
                      last_error="El archivo no superó la validación de seguridad o formato.")
        return
    except Exception as exc:
        # Infrastructure errors remain retryable and never make the object available.
        retrying = self.request.retries < self.max_retries
        retry_status = "scanning" if retrying else "failed"
        retry_error = ("Error temporal durante el procesamiento. Reintentando automáticamente."
                       if retrying else
                       f"No se pudo completar el procesamiento ({type(exc).__name__}). Puedes reintentar.")
        with store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status=retry_status, updated_at=int(time()),
                      processing_started_at=started_at if not retrying else None,
                      last_error=retry_error)
        raise
    with store.transaction(write=True) as db:
        db.change(
            "file_uploads",
            upload_id,
            status="available",
            processing_started_at=None,
            ocr_confidence=ocr.get("mean_confidence"),
            ocr_low_confidence_ratio=ocr.get("low_confidence_ratio"),
            ocr_needs_review=ocr.get("needs_review", False),
            last_error=None,
            updated_at=int(time()),
        )


@celery_app.task(name="spat.reconcile_file_uploads")
def reconcile_file_uploads():
    """Recover lost scan jobs and expire abandoned uploads without deleting their records."""
    from time import time

    store = upload_store()
    storage = ObjectStorage()
    now = int(time())
    pending_after = int(os.getenv("UPLOAD_PENDING_RECOVERY_SECONDS", "300"))
    queued_after = int(os.getenv("UPLOAD_QUEUED_STALE_SECONDS", "1200"))
    scanning_after = int(os.getenv("UPLOAD_SCAN_STALE_SECONDS", "2700"))
    orphan_after = int(os.getenv("UPLOAD_ORPHAN_EXPIRY_SECONDS", "86400"))
    retention = int(os.getenv("UPLOAD_QUARANTINE_RETENTION_SECONDS", "2592000"))
    max_attempts = int(os.getenv("UPLOAD_MAX_ATTEMPTS", "10"))

    def transition(upload, expected_status, **changes):
        with store.transaction(write=True) as db:
            current = db.one("file_uploads", id=upload["id"])
            if (not current or current["status"] != expected_status
                    or current["updated_at"] != upload["updated_at"]):
                return False
            db.change("file_uploads", upload["id"], **changes)
            return True

    for status in ("pending", "scanning"):
        with store.transaction() as db:
            candidates = db.ordered("file_uploads", "updated_at", limit=1000, status=status)
        for upload in candidates:
            age = now - int(upload["updated_at"])
            started_at = upload.get("processing_started_at")
            stale_age = now - int(started_at or upload["updated_at"])
            stale_after = pending_after if status == "pending" else scanning_after if started_at else queued_after
            if stale_age < stale_after:
                continue
            quarantine_exists = storage.exists(storage.quarantine_bucket, upload["quarantine_key"])
            if not quarantine_exists:
                promoted = storage.exists(upload["target_bucket"], upload["object_key"])
                if promoted:
                    transition(upload, status, status="available", updated_at=now, processing_started_at=None, last_error=None)
                elif status == "pending" and age >= orphan_after:
                    transition(upload, status, status="expired", updated_at=now,
                               processing_started_at=None,
                               last_error="La carga expiró antes de completarse. Sube el archivo de nuevo.")
                elif status == "scanning":
                    transition(upload, status, status="failed", updated_at=now,
                               processing_started_at=None,
                               last_error="No se encontró el archivo cargado. Sube el archivo de nuevo.")
                continue
            attempts = int(upload.get("attempt_count") or 0)
            if attempts >= max_attempts:
                transition(upload, status, status="failed", updated_at=now, processing_started_at=None,
                           last_error="Se agotaron los reintentos automáticos. Puedes reintentar el archivo.")
                continue
            if not transition(upload, status, status="scanning", updated_at=now, processing_started_at=None,
                              last_error=None):
                continue
            try:
                scan_file_upload.delay(upload["id"])
            except Exception:
                with store.transaction(write=True) as db:
                    current = db.one("file_uploads", id=upload["id"])
                    if current and current["status"] == "scanning" and current["updated_at"] == now:
                        db.change("file_uploads", upload["id"], status="pending", updated_at=now, processing_started_at=None,
                                  last_error="No se pudo poner el archivo en cola. Se volverá a intentar.")

    cleanup_candidates = []
    with store.transaction() as db:
        for status in ("expired", "rejected"):
            cleanup_candidates.extend(
                db.ordered(
                    "file_uploads",
                    "updated_at",
                    limit=1000,
                    status=status,
                    quarantine_deleted_at=None,
                )
            )
    for upload in cleanup_candidates:
        if now - int(upload["updated_at"]) < retention:
            continue
        if storage.exists(storage.quarantine_bucket, upload["quarantine_key"]):
            storage.remove_quarantine(upload["quarantine_key"])
        with store.transaction(write=True) as db:
            current = db.one("file_uploads", id=upload["id"])
            if current and current["status"] in {"expired", "rejected"} and current.get("quarantine_deleted_at") is None:
                db.change("file_uploads", upload["id"], quarantine_deleted_at=now)
