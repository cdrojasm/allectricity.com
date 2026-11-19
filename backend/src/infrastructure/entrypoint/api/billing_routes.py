"""Mercado Pago webhooks: one URL for test mode and one for production mode.

Configure them in Mercado Pago → Tus integraciones → Webhooks:
- Modo de prueba:    https://<frontend>/api/v1/billing/mercadopago/webhooks/test
- Modo productivo:   https://<frontend>/api/v1/billing/mercadopago/webhooks/prod
The route verifies `x-signature`, stores the notification and answers right away (Mercado Pago waits at most
22 s and then retries); the billing worker re-reads the resource from the API asynchronously.
"""

import hashlib
import json
import logging
from time import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from src.infrastructure.billing import mercadopago
from src.infrastructure.entrypoint.worker.tasks import process_mercadopago_event

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
MAX_BODY_BYTES = 64 * 1024


def _text(value, limit):
    return None if value in (None, "") else str(value)[:limit]


def _store(store, event):
    """Insert the event; returns (stored event, duplicate?)."""
    try:
        with store.transaction() as db:
            existing = db.one("billing_webhook_events", provider="mercadopago", mode=event["mode"],
                              dedup_key=event["dedup_key"])
            if existing:
                return existing, True
            db.add("billing_webhook_events", **event)
            return event, False
    except IntegrityError:  # the same notification arrived twice at the same time
        with store.transaction() as db:
            return db.one("billing_webhook_events", provider="mercadopago", mode=event["mode"],
                          dedup_key=event["dedup_key"]), True


async def _receive(mode, request: Request):
    secret = mercadopago.webhook_secret(mode)
    if not secret:
        raise HTTPException(503, f"Mercado Pago {mode} webhook is not configured")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Notification too large")
    query = request.query_params
    request_id = request.headers.get("x-request-id", "")
    if not mercadopago.valid_signature(secret, request.headers.get("x-signature"), request_id,
                                       query.get("data.id", "")):
        log.warning("Mercado Pago %s webhook rejected: invalid x-signature", mode)
        raise HTTPException(401, "Invalid Mercado Pago signature")
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    topic = _text(payload.get("type") or query.get("type") or query.get("topic"), 60) or "unknown"
    resource_id = _text(query.get("data.id") or data.get("id") or query.get("id"), 64)
    action = _text(payload.get("action"), 60)
    notification_id = _text(payload.get("id"), 64)
    dedup = f"{topic}|{resource_id}|{action}|{notification_id or request_id}"
    known = topic in mercadopago.RESOURCES and resource_id
    now = int(time())
    event = {
        "id": str(uuid4()),
        "provider": "mercadopago",
        "mode": mode,
        "dedup_key": hashlib.sha256(dedup.encode()).hexdigest(),
        "topic": topic,
        "action": action,
        "resource_id": resource_id,
        "notification_id": notification_id,
        "request_id": _text(request_id, 128),
        "live_mode": payload.get("live_mode") if isinstance(payload.get("live_mode"), bool) else None,
        "payload": payload,
        "status": "received" if known else "ignored",
        "attempts": 0,
        "received_at": now,
        "updated_at": now,
        "processed_at": None if known else now,
    }
    stored, duplicate = await run_in_threadpool(_store, request.app.state.services.store, event)
    if stored["status"] == "received":
        try:
            process_mercadopago_event.delay(stored["id"])
        except Exception:  # the event is already persisted: the reconciler enqueues it later
            log.exception("Mercado Pago event %s stored but not queued", stored["id"])
    return {"received": True, "duplicate": duplicate}


@router.post("/mercadopago/webhooks/test", include_in_schema=False)
async def mercadopago_webhook_test(request: Request):
    return await _receive("test", request)


@router.post("/mercadopago/webhooks/prod", include_in_schema=False)
async def mercadopago_webhook_prod(request: Request):
    return await _receive("prod", request)
