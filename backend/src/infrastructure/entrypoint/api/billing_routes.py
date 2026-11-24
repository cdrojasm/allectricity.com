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


def _signed_mode(url_mode, signature, request_id, data_id):
    """The mode whose secret signed the notification, trying the URL's mode first.

    Mercado Pago picks the URL by the kind of credentials, not by our mode: a test seller account uses APP_USR
    ("production") credentials, so its notifications arrive at the production URL signed with the test secret.
    The secret, not the URL, says which account (and access token) the resource belongs to."""
    for mode in (url_mode, *(m for m in mercadopago.MODES if m != url_mode)):
        secret = mercadopago.webhook_secret(mode)
        if secret and mercadopago.valid_signature(secret, signature, request_id, data_id):
            return mode
    return None


async def _receive(url_mode, request: Request):
    if not mercadopago.webhook_secret(url_mode):
        raise HTTPException(503, f"Mercado Pago {url_mode} webhook is not configured")
    chunks, body_size = [], 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_BODY_BYTES:
            raise HTTPException(413, "Notification too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    query = request.query_params
    request_id = request.headers.get("x-request-id", "")
    mode = _signed_mode(url_mode, request.headers.get("x-signature"), request_id, query.get("data.id", ""))
    if mode is None:
        log.warning("Mercado Pago %s webhook rejected: invalid x-signature", url_mode)
        raise HTTPException(401, "Invalid Mercado Pago signature")
    if mode != url_mode:
        log.info("Mercado Pago notification at the %s URL is signed with the %s secret", url_mode, mode)
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
        # Keep only the normalized fields above. Never persist an untrusted webhook body,
        # which could contain payer or card data not needed to reconcile the event.
        "payload": {},
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
