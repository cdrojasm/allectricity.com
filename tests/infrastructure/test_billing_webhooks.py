import hashlib
import hmac
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.infrastructure.billing import events, mercadopago
from src.infrastructure.entrypoint.api import billing_routes
from src.infrastructure.entrypoint.api.fastapi_app import create_app
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings

SECRETS = {"test": "test-webhook-secret", "prod": "prod-webhook-secret"}
URL = "/api/v1/billing/mercadopago/webhooks/{}"


@pytest.fixture
def billing(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'billing.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    for mode, secret in SECRETS.items():
        monkeypatch.setenv(f"MP_{mode.upper()}_WEBHOOK_SECRET", secret)
        monkeypatch.setenv(f"MP_{mode.upper()}_ACCESS_TOKEN", f"{mode.upper()}-token")
    config = Path("backend/alembic.ini") if Path("backend/alembic.ini").exists() else Path("alembic.ini")
    command.upgrade(Config(str(config)), "head")
    settings = Settings(database_url=db_url, jwt_secret="test-only-secret-" * 4,
                        mail_key=Fernet.generate_key().decode(), environment="test")
    services = build_services(settings)
    queued = []
    monkeypatch.setattr(billing_routes.process_mercadopago_event, "delay", queued.append)
    with TestClient(create_app(settings, services)) as client:
        yield client, services.store, queued
    services.store.engine.dispose()


def signed(mode, data_id, request_id="req-1", ts="1704908010"):
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(SECRETS[mode].encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": request_id}


def notify(client, mode="test", data_id="123456", topic="subscription_preapproval", notification_id=1,
           headers=None, **payload):
    body = {"id": notification_id, "live_mode": mode == "prod", "type": topic,
            "action": "updated", "data": {"id": data_id}, **payload}
    return client.post(URL.format(mode) + f"?data.id={data_id}&type={topic}", content=json.dumps(body),
                       headers=headers if headers is not None else signed(mode, data_id))


def rows(store):
    with store.transaction() as db:
        return db.many("billing_webhook_events")


def test_signature_follows_the_official_template():
    secret = "secret"
    manifest = "id:ord01jq4s4ky8hwq6na5pxb65b3d3;request-id:abc;ts:1704908010;"
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    header = f"ts=1704908010,v1={v1}"
    # data.id is lowercased before signing, exactly as the documentation shows.
    assert mercadopago.valid_signature(secret, header, "abc", "ORD01JQ4S4KY8HWQ6NA5PXB65B3D3")
    assert not mercadopago.valid_signature(secret, header, "other", "ORD01JQ4S4KY8HWQ6NA5PXB65B3D3")
    assert not mercadopago.valid_signature("wrong", header, "abc", "ORD01JQ4S4KY8HWQ6NA5PXB65B3D3")
    # Values missing from the notification are dropped from the manifest.
    assert mercadopago.signature_manifest("", "", "1") == "ts:1;"
    assert mercadopago.signature_manifest("42", "", "1") == "id:42;ts:1;"
    assert not mercadopago.valid_signature(secret, "", "abc", "x")
    assert not mercadopago.valid_signature(secret, "ts=1", "abc", "x")


def test_valid_notification_is_stored_and_queued_once(billing):
    client, store, queued = billing
    first = notify(client)
    assert first.status_code == 200 and first.json() == {"received": True, "duplicate": False}
    again = notify(client)  # Mercado Pago redelivers the same notification
    assert again.status_code == 200 and again.json()["duplicate"] is True
    [event] = rows(store)
    assert event["mode"] == "test" and event["topic"] == "subscription_preapproval"
    assert event["resource_id"] == "123456" and event["status"] == "received"
    assert queued == [event["id"], event["id"]]  # still pending, so the redelivery re-queues it


def test_the_secret_that_signed_the_notification_decides_its_mode(billing):
    client, store, _ = billing
    assert notify(client, mode="prod").status_code == 200
    # A test seller account (APP_USR credentials) notifies the production URL, signed with the test secret: the
    # resource belongs to the test account, so it is read with the test access token.
    assert notify(client, mode="prod", data_id="777", notification_id=2,
                  headers=signed("test", "777")).status_code == 200
    assert notify(client, mode="test", headers={"x-signature": "ts=1,v1=00", "x-request-id": "r"}).status_code == 401
    assert sorted((event["mode"], event["resource_id"]) for event in rows(store)) == [("prod", "123456"),
                                                                                    ("test", "777")]


def test_rejects_bad_signatures_and_unconfigured_modes(billing, monkeypatch):
    client, store, queued = billing
    assert notify(client, headers={}).status_code == 401
    assert notify(client, headers=signed("test", "999999")).status_code == 401  # signed for another resource
    monkeypatch.delenv("MP_PROD_WEBHOOK_SECRET")
    assert notify(client, mode="prod").status_code == 503
    assert rows(store) == [] and queued == []


def test_unknown_topics_are_recorded_but_not_fetched(billing):
    client, store, queued = billing
    assert notify(client, topic="topic_claims_integration_wh").status_code == 200
    [event] = rows(store)
    assert event["status"] == "ignored" and queued == []


def test_broker_outage_still_acknowledges_the_notification(billing, monkeypatch):
    client, store, _ = billing

    def down(_):
        raise ConnectionError("redis down")

    monkeypatch.setattr(billing_routes.process_mercadopago_event, "delay", down)
    assert notify(client).status_code == 200
    [event] = rows(store)
    assert event["status"] == "received"  # the reconciler enqueues it once it is stale
    assert events.stale_events(store, now=event["updated_at"] + 10_000) == [event["id"]]


class FakeHttp:
    """Stands in for the SDK's requests-based client and records the URLs the real SDK builds."""

    def __init__(self, status, response):
        self.status, self.response, self.urls = status, response, []

    def get(self, url, **_):
        self.urls.append(url)
        return {"status": self.status, "response": self.response}


@pytest.fixture
def fake_http(monkeypatch):
    from mercadopago.http import HttpClient

    def build(status, response=None):
        fake = type("Fake", (FakeHttp, HttpClient), {})(status, response)
        return fake

    return build


def stored_event(client, store, notification_id=1, **kwargs):
    assert notify(client, notification_id=notification_id, **kwargs).status_code == 200
    with store.transaction() as db:
        return db.one("billing_webhook_events", notification_id=str(notification_id))["id"]


def test_worker_stores_a_snapshot_without_payer_data(billing, fake_http):
    client, store, _ = billing
    event_id = stored_event(client, store)
    http = fake_http(200, {"id": "123456", "status": "authorized", "preapproval_plan_id": "plan-1",
                           "external_reference": "user-1", "payer_email": "payer@example.com",
                           "card_id": 99, "next_payment_date": "2026-12-19T00:00:00.000-04:00"})
    assert events.process_event(store, event_id, http) == "fetched"
    assert http.urls == ["https://api.mercadopago.com/preapproval/123456"]
    [event] = rows(store)
    assert event["status"] == "fetched" and event["resource_status"] == "authorized"
    assert event["resource"]["external_reference"] == "user-1"
    assert "payer_email" not in event["resource"] and "card_id" not in event["resource"]
    assert events.process_event(store, event_id, http) is None  # already resolved: no second lookup
    assert len(http.urls) == 1


@pytest.mark.parametrize("topic, path", [
    ("payment", "/v1/payments/77"),
    ("subscription_authorized_payment", "/authorized_payments/77"),
    ("subscription_preapproval_plan", "/preapproval_plan/77"),
])
def test_worker_reads_each_topic_from_its_endpoint(billing, fake_http, topic, path):
    client, store, _ = billing
    event_id = stored_event(client, store, data_id="77", topic=topic)
    http = fake_http(200, {"id": 77, "status": "approved"})
    assert events.process_event(store, event_id, http) == "fetched"
    assert http.urls == ["https://api.mercadopago.com" + path]


def test_worker_failures(billing, fake_http, monkeypatch):
    client, store, _ = billing
    missing = stored_event(client, store, notification_id=1)
    assert events.process_event(store, missing, fake_http(404)) == "failed"
    transient = stored_event(client, store, notification_id=2)
    with pytest.raises(mercadopago.ResourceUnavailable):
        events.process_event(store, transient, fake_http(503))
    monkeypatch.setenv("MP_EVENT_MAX_ATTEMPTS", "2")
    assert events.process_event(store, transient, fake_http(503)) == "failed"
    no_token = stored_event(client, store, notification_id=3)
    monkeypatch.delenv("MP_TEST_ACCESS_TOKEN")
    assert events.process_event(store, no_token, fake_http(200, {})) == "failed"
    by_id = {event["id"]: event for event in rows(store)}
    assert "no existe" in by_id[missing]["last_error"]
    assert by_id[transient]["attempts"] == 2 and "sin más reintentos" in by_id[transient]["last_error"]
    assert "MP_TEST_ACCESS_TOKEN" in by_id[no_token]["last_error"]
