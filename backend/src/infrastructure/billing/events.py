"""Billing worker side of the Mercado Pago inbox: resolve each stored notification against the API.

States: received → fetched (resource snapshot stored) | failed (permanent: no credentials, not found, rejected)
| ignored (topic we do not handle). Transient errors keep the event `received` and are retried, first by the
Celery task and then by the reconciler, up to MP_EVENT_MAX_ATTEMPTS.
"""

import os
from time import time

from src.infrastructure.billing import mercadopago

TABLE = "billing_webhook_events"


def max_attempts():
    return int(os.getenv("MP_EVENT_MAX_ATTEMPTS", "10"))


def _finish(store, event_id, **changes):
    """Apply the outcome only while the event is still pending (a parallel delivery may have finished it)."""
    with store.transaction() as db:
        current = db.one(TABLE, id=event_id)
        if not current or current["status"] != "received":
            return False
        db.change(TABLE, event_id, updated_at=int(time()), **changes)
        return True


def process_event(store, event_id, http_client=None):
    """Fetch the notified resource; raises mercadopago.ResourceUnavailable when it must be retried."""
    with store.transaction() as db:
        event = db.one(TABLE, id=event_id)
        if not event or event["status"] != "received":
            return None
        attempts = int(event["attempts"] or 0) + 1
        db.change(TABLE, event_id, attempts=attempts, updated_at=int(time()))
    mode, topic = event["mode"], event["topic"]
    try:
        status, resource = mercadopago.fetch_resource(mode, topic, event["resource_id"], http_client)
    except LookupError as exc:  # credentials of this mode are not configured
        _finish(store, event_id, status="failed", last_error=str(exc), processed_at=int(time()))
        return "failed"
    except mercadopago.ResourceUnavailable as exc:
        if attempts >= max_attempts():
            _finish(store, event_id, status="failed", last_error=f"{exc} (sin más reintentos)",
                    processed_at=int(time()))
            return "failed"
        _finish(store, event_id, last_error=str(exc))
        raise
    if status == 200 and isinstance(resource, dict):
        resource_status = resource.get("status")
        _finish(store, event_id, status="fetched", resource=mercadopago.snapshot(resource),
                resource_status=None if resource_status is None else str(resource_status)[:40],
                last_error=None, processed_at=int(time()))
        return "fetched"
    reason = {
        401: "Mercado Pago rechazó el access token de este modo",
        403: "Mercado Pago rechazó el access token de este modo",
        404: f"El recurso no existe en modo {mode} (¿notificación simulada o credenciales de otro modo?)",
    }.get(status, f"Mercado Pago respondió {status}")
    _finish(store, event_id, status="failed", last_error=reason, processed_at=int(time()))
    return "failed"


def stale_events(store, now=None):
    """Events still `received` after MP_EVENT_STALE_SECONDS: their task was lost or exhausted its retries."""
    now = now or int(time())
    stale_after = int(os.getenv("MP_EVENT_STALE_SECONDS", "120"))
    with store.transaction() as db:
        pending = db.ordered(TABLE, "updated_at", limit=500, status="received")
    ready, exhausted = [], []
    for event in pending:
        if now - int(event["updated_at"]) < stale_after:
            continue
        (exhausted if int(event["attempts"] or 0) >= max_attempts() else ready).append(event["id"])
    for event_id in exhausted:
        _finish(store, event_id, status="failed", last_error="Se agotaron los reintentos automáticos",
                processed_at=now)
    return ready
