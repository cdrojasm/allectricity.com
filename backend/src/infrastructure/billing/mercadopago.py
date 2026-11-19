"""Mercado Pago: configuration per mode, webhook signature and resource lookup.

Two modes, each with its own credentials so a test notification is never resolved with production keys:
- test: MP_TEST_ACCESS_TOKEN, MP_TEST_WEBHOOK_SECRET
- prod: MP_PROD_ACCESS_TOKEN, MP_PROD_WEBHOOK_SECRET
The webhook route only needs the secret; the access token is used by the billing worker.
"""

import hashlib
import hmac
import os

MODES = ("test", "prod")

# Topic → (SDK accessor, lookup endpoint). Every notified resource is re-read from the API: the
# notification body only says that something changed, never what the new state is.
RESOURCES = {
    "payment": "payment",
    "subscription_preapproval": "preapproval",
    "subscription_authorized_payment": "invoice",  # /authorized_payments/{id}
    "subscription_preapproval_plan": "plan",
}

# Fields kept from the fetched resource. Payer data and card details stay in Mercado Pago.
SNAPSHOT_FIELDS = (
    "id", "status", "status_detail", "external_reference", "preapproval_id", "preapproval_plan_id",
    "transaction_amount", "currency_id", "date_created", "date_approved", "last_modified",
    "debit_date", "next_payment_date", "payment_id", "retry_attempt", "reason", "summarized",
)


def webhook_secret(mode):
    return os.getenv(f"MP_{mode.upper()}_WEBHOOK_SECRET", "").strip()


def access_token(mode):
    return os.getenv(f"MP_{mode.upper()}_ACCESS_TOKEN", "").strip()


def parse_signature(header):
    """`ts=1704908010,v1=618c…` → (ts, v1); missing parts come back as empty strings."""
    parts = {}
    for item in (header or "").split(","):
        name, _, value = item.partition("=")
        parts[name.strip()] = value.strip()
    return parts.get("ts", ""), parts.get("v1", "")


def signature_manifest(data_id, request_id, ts):
    """Official template `id:[data.id];request-id:[x-request-id];ts:[ts];`.

    `data.id` comes from the URL query and is lowercased when alphanumeric; any value that is missing
    from the notification is dropped from the manifest, as the documentation requires.
    """
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower()};"
    if request_id:
        manifest += f"request-id:{request_id};"
    return manifest + f"ts:{ts};"


def valid_signature(secret, header, request_id, data_id):
    ts, received = parse_signature(header)
    if not secret or not ts or not received:
        return False
    expected = hmac.new(
        secret.encode(), signature_manifest(data_id, request_id, ts).encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received.lower())


def snapshot(resource):
    return {key: resource[key] for key in SNAPSHOT_FIELDS if isinstance(resource, dict) and key in resource}


class ResourceUnavailable(RuntimeError):
    """Mercado Pago did not answer (network, 429 or 5xx): the lookup is retried later."""


def sdk(mode, http_client=None):
    import mercadopago  # billing extra: only the billing worker installs the SDK
    from mercadopago.config import RequestOptions

    token = access_token(mode)
    if not token:
        raise LookupError(f"MP_{mode.upper()}_ACCESS_TOKEN is not configured")
    options = RequestOptions(connection_timeout=20.0)
    return mercadopago.SDK(token, request_options=options, http_client=http_client)


def fetch_resource(mode, topic, resource_id, http_client=None):
    """Return (http status, resource) for a notified resource; raises ResourceUnavailable to retry."""
    client = sdk(mode, http_client)
    accessor = getattr(client, RESOURCES[topic])()
    try:
        result = accessor.get(resource_id)
    except Exception as exc:  # requests/urllib3 errors once the SDK's own retries are exhausted
        raise ResourceUnavailable(f"Mercado Pago lookup failed: {type(exc).__name__}") from exc
    status = int(result.get("status") or 0)
    if status == 429 or status >= 500 or status == 0:
        raise ResourceUnavailable(f"Mercado Pago answered {status}")
    return status, result.get("response")
