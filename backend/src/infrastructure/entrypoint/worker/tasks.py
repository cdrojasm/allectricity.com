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
from src.infrastructure.processing.electrical_documents import (
    extract_electrical_entities,
    extract_document,
    load_project_graph_context,
    persist_graph,
)
from src.infrastructure.processing import document_agents

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
        "reset-mail-outbox": {"task": "spat.dispatch_reset_mail", "schedule": 15.0}
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


@celery_app.task(name="spat.resolve_chat_message")
def resolve_chat_message(message_id):
    """Async refinement entry point; replace the placeholder with the artifact use case."""
    from time import time
    from uuid import uuid4

    store = upload_store()
    with store.transaction(write=True) as db:
        message = db.one("chat_messages", id=message_id)
        if not message or message["status"] in {"completed", "failed"}:
            return
        db.change("chat_messages", message_id, status="processing", updated_at=int(time()))
    # Keep the queue, lifecycle and conversation usable before wiring the future
    # artifact refinement use case into this worker.
    with store.transaction(write=True) as db:
        current = db.one("chat_messages", id=message_id)
        if not current or current["status"] != "processing":
            return
        now = int(time())
        db.add(
            "chat_messages",
            id=str(uuid4()),
            conversation_id=current["conversation_id"],
            source="agent",
            text="Recibí tu solicitud. El refinamiento del artefacto se conectará a este flujo.",
            type="text",
            generated_at=now,
            created_at=now,
            updated_at=now,
            status="completed",
            task_id=None,
        )
        db.change("chat_messages", message_id, status="completed", updated_at=now)
        db.change("conversations", current["conversation_id"], updated_at=now)


@celery_app.task(name="spat.calculate_artifact_potential", soft_time_limit=540, time_limit=600)
def calculate_artifact_potential(calculation_id):
    """Run the C++ potential engine for an artifact version and persist result and trace."""
    from src.infrastructure.calculations.artifact_potential import run_potential_calculation

    run_potential_calculation(upload_store(), calculation_id)


@celery_app.task(name="spat.scan_file_upload", autoretry_for=(RuntimeError,), retry_backoff=30, retry_jitter=True, max_retries=5)
def scan_file_upload(upload_id):
    from time import time

    store = upload_store()
    with store.transaction(write=True) as db:
        upload = db.one("file_uploads", id=upload_id)
        if not upload or upload["status"] in {"available", "rejected"}:
            return
        db.change("file_uploads", upload_id, status="scanning", updated_at=int(time()))

    storage = ObjectStorage()
    maximum = int(os.getenv("UPLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
    try:
        data = storage.read(upload["quarantine_key"], maximum)
        detected = storage.detected_mime(data)
        if detected != upload["expected_mime"]:
            raise ValueError("File content does not match the declared MIME type")
        storage.scan(data)
        text, ocr = extract_document(data, detected)
        entities = extract_electrical_entities(text)
        consolidation = {}
        if document_agents.enabled():
            try:
                agent_result = document_agents.run_document_agents(
                    text,
                    entities,
                    ocr,
                    upload["filename"],
                    load_project_graph_context(upload["project_id"]),
                )
            except Exception as exc:
                raise RuntimeError("Document agent pipeline failed") from exc
            entities = agent_result["findings"]
            consolidation = agent_result["consolidation"]
        persist_graph(upload, entities, ocr, consolidation)
        storage.promote(
            upload["quarantine_key"], upload["target_bucket"], upload["object_key"], detected
        )
    except ValueError:
        with store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status="rejected", updated_at=int(time()))
        return
    except Exception:
        # Infrastructure errors remain retryable and never make the object available.
        with store.transaction(write=True) as db:
            db.change("file_uploads", upload_id, status="failed", updated_at=int(time()))
        raise
    with store.transaction(write=True) as db:
        db.change(
            "file_uploads",
            upload_id,
            status="available",
            ocr_confidence=ocr.get("mean_confidence"),
            ocr_low_confidence_ratio=ocr.get("low_confidence_ratio"),
            ocr_needs_review=ocr.get("needs_review", False),
            updated_at=int(time()),
        )
