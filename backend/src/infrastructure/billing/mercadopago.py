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
    if not isinstance(resource, dict):
        return {}
    kept = {key: resource[key] for key in SNAPSHOT_FIELDS if key in resource}
    if isinstance(resource.get("payment"), dict):  # authorized payments carry the charge result here
        kept["payment"] = {key: resource["payment"].get(key) for key in ("id", "status", "status_detail")}
    return kept


class ResourceUnavailable(RuntimeError):
    """Mercado Pago did not answer (network, 429 or 5xx): the lookup is retried later."""


class GatewayRejected(RuntimeError):
    """Mercado Pago refused the request (4xx): retrying would not help."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _options(mode, idempotency_key=None):
    from mercadopago.config import RequestOptions

    token = access_token(mode)
    if not token:
        raise LookupError(f"MP_{mode.upper()}_ACCESS_TOKEN is not configured")
    options = RequestOptions(access_token=token, connection_timeout=30.0)
    if idempotency_key:
        options.custom_headers = {"x-idempotency-key": idempotency_key}
    return options


def sdk(mode, http_client=None):
    import mercadopago  # billing extra: only the billing worker installs the SDK

    options = _options(mode)  # LookupError when this mode has no credentials
    return mercadopago.SDK(options.access_token, request_options=options, http_client=http_client)


def _message(response) -> str:
    if not isinstance(response, dict):
        return "Mercado Pago rechazó la solicitud"
    causes = [cause.get("description") or cause.get("code") for cause in response.get("cause") or []
              if isinstance(cause, dict)]
    return "; ".join(str(item) for item in [response.get("message"), *causes] if item)[:500] or "Mercado Pago rechazó la solicitud"


def _result(call):
    try:
        result = call()
    except (LookupError, GatewayRejected):
        raise
    except Exception as exc:
        raise ResourceUnavailable(f"Mercado Pago no respondió: {type(exc).__name__}") from exc
    status = int(result.get("status") or 0)
    if status == 429 or status >= 500 or status == 0:
        raise ResourceUnavailable(f"Mercado Pago answered {status}")
    if status >= 400:
        raise GatewayRejected(status, _message(result.get("response")))
    return result.get("response") or {}


def create_preapproval(mode, body: dict, idempotency_key: str, http_client=None) -> dict:
    """POST /preapproval: a subscription to a panel plan, charged to the tokenized card."""
    client = sdk(mode, http_client)
    return _result(lambda: client.preapproval().create(body, _options(mode, idempotency_key)))


def find_preapproval(mode, external_reference: str, http_client=None) -> dict | None:
    """The preapproval created for `external_reference`, if any (used before retrying a creation)."""
    client = sdk(mode, http_client)
    found = _result(lambda: client.preapproval().search({"external_reference": external_reference}, _options(mode)))
    results = found.get("results") if isinstance(found, dict) else None
    return results[0] if results else None


_accounts: dict = {}


def account(mode, http_client=None) -> dict:
    """The Mercado Pago account behind MP_<MODE>_ACCESS_TOKEN: {"id", "test_user"} (cached per process).

    `live_mode` does not tell test money apart (a test seller's payments report live_mode=true); the account's
    `test_user` tag does, and only a test seller accepts test cards."""
    token = access_token(mode)
    if token in _accounts:
        return _accounts[token]
    client = sdk(mode, http_client)
    me = _result(lambda: client.user().get(_options(mode)))
    info = {"id": str(me.get("id") or ""), "test_user": "test_user" in (me.get("tags") or [])}
    if not info["id"]:
        raise ResourceUnavailable("Mercado Pago no devolvió la cuenta de las credenciales")
    _accounts[token] = info
    return info


def cancel_preapproval(mode, preapproval_id: str, http_client=None) -> dict:
    client = sdk(mode, http_client)
    return _result(lambda: client.preapproval().update(preapproval_id, {"status": "cancelled"}, _options(mode)))


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
