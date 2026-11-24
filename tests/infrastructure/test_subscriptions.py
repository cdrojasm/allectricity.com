import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.domain.identity import ServiceError
from src.infrastructure.billing import events, mercadopago, plans, subscriptions
from src.infrastructure.billing.subscriptions import DAY, Subscriptions
from src.infrastructure.entrypoint.api import subscription_routes
from src.infrastructure.entrypoint.api.fastapi_app import create_app
from src.infrastructure.security.container import build_services
from src.infrastructure.security.providers import FernetMessages
from src.infrastructure.security.settings import Settings

PASSWORD = "Correct-Horse-9-Battery"
IDS = {"essentials": "9f1ca811c2db499598697d156beaf9e9", "standard": "14e257fd31a840fe8138c66676fa296e",
       "ultimate": "62b409bce249407ead542534fed45475"}


ACCOUNT = 3860579022


class Clock:
    def __init__(self):
        self.value = 1_800_000_000

    def __call__(self):
        return self.value

    def advance(self, days):
        self.value += int(days * DAY)


@pytest.fixture
def billing(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'subscriptions.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("MP_MODE", "test")
    monkeypatch.setenv("MP_TEST_ACCESS_TOKEN", "TEST-token")
    monkeypatch.setenv("MP_TEST_PUBLIC_KEY", "TEST-public")
    monkeypatch.setenv("MP_PLAN_NAMES", "ultimate,standard,essentials")
    monkeypatch.setenv("MP_PLAN_IDS", ",".join(IDS[name] for name in ("ultimate", "standard", "essentials")))
    monkeypatch.setenv("MP_PLAN_PRICES_USD", "199,49,19")
    monkeypatch.setenv("MP_PLAN_MONTHLY_TOKENS", "30000000,8000000,3000000")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.example.com")
    config = Path("backend/alembic.ini") if Path("backend/alembic.ini").exists() else Path("alembic.ini")
    command.upgrade(Config(str(config)), "head")
    settings = Settings(database_url=db_url, jwt_secret="test-only-secret-" * 4,
                        mail_key=Fernet.generate_key().decode(), environment="test")
    services = build_services(settings)
    admin = services.admin.bootstrap("admin@example.com", PASSWORD, "Admin")
    admin_actor = services.identity.authenticate(services.identity.login("admin@example.com", PASSWORD)["access_token"])
    user = services.admin.create_user(admin_actor, dict(email="eng@example.com", password=PASSWORD, first_name="Eng",
                                                         last_name="Test", phone=None, locale="es-CO", timezone="UTC"))
    clock = Clock()
    monkeypatch.setattr(subscriptions, "_now", clock)
    monkeypatch.setattr(mercadopago, "_accounts", {})
    yield services, admin, user, clock
    services.store.engine.dispose()


class FakeMercadoPago:
    """Stands in for the SDK's HTTP client: scripted answers per (method, path prefix); records every call."""

    def __init__(self):
        self.calls, self.answers = [], {}

    def answer(self, method, path, status, body):
        self.answers[(method, path)] = (status, body)

    def _reply(self, method, url, data=None, **_):
        path = url.replace("https://api.mercadopago.com", "")
        self.calls.append((method, path, json.loads(data) if isinstance(data, str) else data))
        for (verb, prefix), (status, body) in self.answers.items():
            if verb == method and path.startswith(prefix):
                return {"status": status, "response": body}
        return {"status": 404, "response": {"message": "not found"}}

    def get(self, url, **kwargs):
        return self._reply("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._reply("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._reply("PUT", url, **kwargs)


@pytest.fixture
def mp():
    from mercadopago.http import HttpClient

    fake = type("Fake", (FakeMercadoPago, HttpClient), {})()
    fake.answer("GET", "/users/me", 200, {"id": ACCOUNT, "tags": ["normal"]})
    return fake


def genuine(preapproval_id, tier, **extra):
    """An authorized preapproval that charges our account for `tier`'s plan."""
    return {"id": preapproval_id, "status": "authorized", "collector_id": ACCOUNT, "preapproval_plan_id": IDS[tier],
            **extra}


def budget(store, subscription_id):
    with store.transaction() as db:
        return db.one("budget", id=subscription_id)


def row(store, subscription_id):
    with store.transaction() as db:
        return db.one("billing_subscriptions", id=subscription_id)


def activate(services, user, mp, tier="essentials", preapproval="pre-1"):
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], tier)
    mp.answer("POST", "/preapproval", 201, genuine(preapproval, tier, external_reference=pending["id"]))
    assert service.create_remote(pending["id"], "card-token-1", "payer@testuser.com") == "activated"
    return service, pending["id"]


def test_plans_come_from_aligned_env_lists_ranked_by_price(monkeypatch, billing):
    assert [(plan.name, plan.rank, plan.monthly_tokens) for plan in plans.configured()] == [
        ("essentials", 0, 3_000_000), ("standard", 1, 8_000_000), ("ultimate", 2, 30_000_000)]
    monkeypatch.setenv("MP_PLAN_PRICES_USD", "199,49")
    with pytest.raises(plans.PlanConfigError):
        plans.configured()
    monkeypatch.setenv("MP_PLAN_PRICES_USD", "199,49,$19")
    with pytest.raises(plans.PlanConfigError):
        plans.configured()


def test_checkout_activates_the_tier_and_loads_its_tokens(billing, mp):
    services, _, user, clock = billing
    service, subscription_id = activate(services, user, mp)
    method, path, body = mp.calls[0]
    assert (method, path) == ("POST", "/preapproval")
    assert body == {"preapproval_plan_id": IDS["essentials"], "card_token_id": "card-token-1",
                    "payer_email": "payer@testuser.com", "external_reference": subscription_id,
                    "back_url": "https://app.example.com/plans", "status": "authorized"}
    current = row(services.store, subscription_id)
    assert current["status"] == "authorized" and current["provider_ref"] == "pre-1"
    assert current["period_end"] == clock.value + 30 * DAY
    assert (budget(services.store, subscription_id)["total_tokens"], budget(services.store, subscription_id)["used_tokens"]) == (3_000_000, 0)
    summary = service.summary(user["id"])
    assert summary["subscription"]["tier"] == "essentials" and summary["checkout"] is None
    assert summary["subscription"]["tokens"] == {"total": 3_000_000, "used": 0}


def test_enforce_loads_the_budget_of_an_active_subscription_that_has_none(billing, mp, monkeypatch):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "essentials")
    mp.answer("POST", "/preapproval", 201, genuine("pre-1", "essentials", external_reference=pending["id"]))
    # The worker that activated it could not read the tiers (MP_PLAN_* missing in its environment).
    with monkeypatch.context() as env:
        env.delenv("MP_PLAN_NAMES")
        env.delenv("MP_PLAN_IDS")
        env.delenv("MP_PLAN_PRICES_USD")
        env.delenv("MP_PLAN_MONTHLY_TOKENS")
        assert service.create_remote(pending["id"], "card-token-1", "payer@testuser.com") == "activated"
    assert row(services.store, pending["id"])["status"] == "authorized" and budget(services.store, pending["id"]) is None
    assert service.enforce()["repaired"] == 1
    assert budget(services.store, pending["id"])["total_tokens"] == 3_000_000
    assert service.enforce()["repaired"] == 0


@pytest.mark.parametrize("preapproval, reason", [
    (genuine("pre-x", "essentials", collector_id=111), "no es para la cuenta"),     # money to another account
    (genuine("pre-x", "essentials", preapproval_plan_id=IDS["ultimate"]), "plan"),  # another plan
])
def test_a_preapproval_that_is_not_ours_never_unlocks_the_tier(billing, mp, preapproval, reason):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "essentials")
    mp.answer("POST", "/preapproval", 201, {**preapproval, "external_reference": pending["id"]})
    assert service.create_remote(pending["id"], "token", "payer@testuser.com") == "rejected"
    failed = row(services.store, pending["id"])
    assert failed["status"] == "failed" and reason in failed["error"] and budget(services.store, pending["id"]) is None
    assert service.summary(user["id"])["subscription"] is None


def test_production_refuses_the_credentials_of_a_test_account(billing, mp, monkeypatch):
    services, _, user, _ = billing
    monkeypatch.setenv("MP_MODE", "prod")
    monkeypatch.setenv("MP_PROD_ACCESS_TOKEN", "APP_USR-test-seller")
    mp.answer("GET", "/users/me", 200, {"id": ACCOUNT, "tags": ["test_user", "normal"]})  # test cards work here
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "essentials")
    mp.answer("POST", "/preapproval", 201, genuine("pre-1", "essentials", external_reference=pending["id"]))
    assert service.create_remote(pending["id"], "token", "payer@testuser.com") == "rejected"
    assert "cuenta de prueba" in row(services.store, pending["id"])["error"]
    assert budget(services.store, pending["id"]) is None


def test_a_first_charge_activates_only_through_its_verified_preapproval(billing, mp):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "standard")
    with services.store.transaction(write=True) as db:
        db.change("billing_subscriptions", pending["id"], provider_ref="pre-5")
    charge = {"id": 601, "preapproval_id": "pre-5", "status": "processed", "payment": {"id": 9101, "status": "approved"}}
    mp.answer("GET", "/preapproval/pre-5", 200, genuine("pre-5", "standard", collector_id=999))
    assert service.apply_authorized_payment(charge) == "rejected"
    assert budget(services.store, pending["id"]) is None
    with services.store.transaction(write=True) as db:  # a fresh checkout row for the genuine case
        db.change("billing_subscriptions", pending["id"], status="pending", error=None)
    mp.answer("GET", "/preapproval/pre-5", 200, genuine("pre-5", "standard"))
    assert service.apply_authorized_payment(charge) == "activated"
    assert budget(services.store, pending["id"])["total_tokens"] == 8_000_000
    assert service.apply_authorized_payment(charge) == "duplicate"


def test_rejected_card_fails_the_checkout_with_mercado_pagos_reason(billing, mp):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "standard")
    with pytest.raises(ServiceError) as busy:  # one checkout at a time
        service.start_checkout(user["id"], "standard")
    assert busy.value.status == 409
    mp.answer("POST", "/preapproval", 400, {"message": "Invalid card_token_id", "cause": [{"description": "Card rejected"}]})
    assert service.create_remote(pending["id"], "bad", "payer@testuser.com") == "failed"
    failed = row(services.store, pending["id"])
    assert failed["status"] == "failed" and "Card rejected" in failed["error"]
    assert service.summary(user["id"])["checkout"]["status"] == "failed"


def test_a_retry_reuses_the_preapproval_created_by_a_lost_attempt(billing, mp):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "essentials")
    mp.answer("POST", "/preapproval", 503, {"message": "unavailable"})
    with pytest.raises(mercadopago.ResourceUnavailable):
        service.create_remote(pending["id"], "token", "payer@testuser.com")
    mp.answer("GET", "/preapproval/search", 200, {"results": [genuine("pre-9", "essentials")]})
    assert service.create_remote(pending["id"], "token", "payer@testuser.com", retry=True) == "activated"
    assert [call[:2] for call in mp.calls].count(("POST", "/preapproval")) == 1  # never a second creation
    assert row(services.store, pending["id"])["provider_ref"] == "pre-9"


def test_upgrade_only_and_the_old_subscription_is_cancelled_once_the_new_one_is_active(billing, mp):
    services, _, user, _ = billing
    service, old_id = activate(services, user, mp, "standard", "pre-old")
    for tier in ("essentials", "standard"):
        with pytest.raises(ServiceError) as lower:
            service.start_checkout(user["id"], tier)
        assert lower.value.status == 409
    new = service.start_checkout(user["id"], "ultimate")
    assert new["replaces_id"] == old_id and row(services.store, old_id)["status"] == "authorized"
    mp.answer("POST", "/preapproval", 201, genuine("pre-new", "ultimate"))
    mp.answer("PUT", "/preapproval/pre-old", 200, {"id": "pre-old", "status": "cancelled"})
    assert service.create_remote(new["id"], "token", "payer@testuser.com") == "activated"
    assert ("PUT", "/preapproval/pre-old", {"status": "cancelled"}) in mp.calls
    old = row(services.store, old_id)
    assert old["status"] == "replaced" and old["error"] is None and budget(services.store, old_id)["active"] is False
    assert budget(services.store, new["id"])["total_tokens"] == 30_000_000
    assert service.summary(user["id"])["subscription"]["tier"] == "ultimate"


def test_a_failed_remote_cancellation_is_retried_by_enforce(billing, mp):
    services, _, user, _ = billing
    service, old_id = activate(services, user, mp, "essentials", "pre-old")
    new = service.start_checkout(user["id"], "standard")
    mp.answer("POST", "/preapproval", 201, genuine("pre-new", "standard"))
    mp.answer("PUT", "/preapproval/pre-old", 503, {})
    service.create_remote(new["id"], "token", "payer@testuser.com")
    assert row(services.store, old_id)["error"] == subscriptions.REMOTE_CANCEL_PENDING
    mp.answer("PUT", "/preapproval/pre-old", 200, {"status": "cancelled"})
    service.enforce()
    assert row(services.store, old_id)["error"] is None


def test_monthly_charges_reset_the_budget_and_failures_suspend_after_the_grace_period(billing, mp):
    services, _, user, clock = billing
    service, subscription_id = activate(services, user, mp)
    store = services.store
    with store.transaction(write=True) as db:
        db.change("budget", subscription_id, used_tokens=2_500_000)
    first = {"id": 501, "preapproval_id": "pre-1", "status": "processed", "payment": {"id": 9001, "status": "approved"}}
    assert service.apply_authorized_payment(first) == "paid"  # the first charge, right after activation
    assert budget(store, subscription_id)["used_tokens"] == 2_500_000
    assert service.apply_authorized_payment(first) == "duplicate"

    clock.advance(30)
    renewal = {"id": 502, "preapproval_id": "pre-1", "status": "processed", "payment": {"id": 9002, "status": "approved"}}
    assert service.apply_authorized_payment(renewal) == "renewed"
    assert budget(store, subscription_id)["used_tokens"] == 0  # unused tokens are not carried over

    clock.advance(30)
    failed = {"id": 503, "preapproval_id": "pre-1", "status": "recycling", "payment": {"id": 9003, "status": "rejected"}}
    assert service.apply_authorized_payment(failed) == "past_due"
    assert row(store, subscription_id)["grace_until"] == clock.value + 7 * DAY
    clock.advance(6)
    service.enforce()
    assert row(store, subscription_id)["status"] == "past_due" and budget(store, subscription_id)["active"] is True
    clock.advance(2)
    assert service.enforce()["suspended"] == 1
    assert row(store, subscription_id)["status"] == "suspended" and budget(store, subscription_id)["active"] is False
    assert service.summary(user["id"])["subscription"] is None

    recovered = {"id": 504, "preapproval_id": "pre-1", "status": "processed", "payment": {"id": 9004, "status": "approved"}}
    assert service.apply_authorized_payment(recovered) == "renewed"
    assert row(store, subscription_id)["status"] == "authorized" and budget(store, subscription_id)["active"] is True


def test_cancelled_by_the_payer_keeps_access_until_the_paid_period_ends(billing, mp):
    services, _, user, clock = billing
    service, subscription_id = activate(services, user, mp)
    period_end = row(services.store, subscription_id)["period_end"]
    clock.advance(10)
    assert service.apply_preapproval({"id": "pre-1", "status": "cancelled"}) == "cancelled"
    assert row(services.store, subscription_id)["ends_at"] == period_end
    assert service.summary(user["id"])["subscription"]["status"] == "cancelled"
    clock.advance(21)
    assert service.enforce()["expired"] == 1
    assert service.summary(user["id"])["subscription"] is None


def test_webhook_events_are_applied_to_the_subscription(billing, mp):
    services, _, user, _ = billing
    service = Subscriptions(services.store, mp)
    pending = service.start_checkout(user["id"], "standard")
    with services.store.transaction(write=True) as db:
        db.add("billing_webhook_events", id="evt-1", provider="mercadopago", mode="test", dedup_key="k", topic=
               "subscription_preapproval", action="updated", resource_id="pre-7", notification_id="1", request_id="r",
               live_mode=False, payload={}, status="received", attempts=0, received_at=1, updated_at=1)
    mp.answer("GET", "/preapproval/pre-7", 200, genuine("pre-7", "standard", external_reference=pending["id"],
                                                         payer_email="x@y.z"))
    assert events.process_event(services.store, "evt-1", mp) == "fetched"
    assert row(services.store, pending["id"])["status"] == "authorized"
    with services.store.transaction() as db:
        assert db.one("billing_webhook_events", id="evt-1")["resource"]["applied"] == "activated"


def test_license_codes_are_single_use_and_recharge_every_month(billing):
    services, admin, user, clock = billing
    service = Subscriptions(services.store)
    [license_code] = service.create_licenses(admin["id"], "standard", months=2, count=1, note="ACME")
    code = license_code["code"]
    assert code.startswith("ALLECTRICITY-") and len(code) == 27
    with services.store.transaction() as db:
        stored = db.one("billing_licenses", id=license_code["id"])
    assert code not in json.dumps(stored) and stored["code_hint"] == code.replace("-", "")[-4:]
    with pytest.raises(ServiceError) as wrong:
        service.redeem(user["id"], "TERRA-AAAA-BBBB-CCCC")
    assert wrong.value.status == 404

    granted = service.redeem(user["id"], code.lower())  # case and dashes do not matter
    assert granted["tier"] == "standard" and granted["provider"] == "license"
    assert granted["tokens"] == {"total": 8_000_000, "used": 0}
    with pytest.raises(ServiceError) as reused:
        service.redeem(user["id"], code)
    assert reused.value.status == 409

    with services.store.transaction(write=True) as db:
        db.change("budget", granted["id"], used_tokens=5_000_000)
    clock.advance(31)
    assert service.enforce()["recharged"] == 1
    assert budget(services.store, granted["id"])["used_tokens"] == 0
    clock.advance(30)
    assert service.enforce()["expired"] == 1
    assert service.summary(user["id"])["subscription"] is None


def test_revoking_a_redeemed_license_ends_its_access(billing):
    services, admin, user, _ = billing
    service = Subscriptions(services.store)
    [license_code] = service.create_licenses(admin["id"], "essentials", months=1, count=1)
    granted = service.redeem(user["id"], license_code["code"])
    service.revoke_license(admin["id"], license_code["id"])
    assert row(services.store, granted["id"])["status"] == "expired"
    assert budget(services.store, granted["id"])["active"] is False
    [unused] = service.create_licenses(admin["id"], "essentials", months=1, count=1)
    service.revoke_license(admin["id"], unused["id"])
    with pytest.raises(ServiceError) as revoked:
        service.redeem(user["id"], unused["code"])
    assert revoked.value.status == 404


def test_a_license_cannot_stack_on_an_active_plan(billing, mp):
    services, admin, user, _ = billing
    service, _ = activate(services, user, mp)
    [license_code] = service.create_licenses(admin["id"], "ultimate", months=1, count=1)
    with pytest.raises(ServiceError) as active:
        service.redeem(user["id"], license_code["code"])
    assert active.value.status == 409


def test_routes(billing, monkeypatch):
    services, _, user, _ = billing
    queued = []
    monkeypatch.setattr(subscription_routes.create_mercadopago_subscription, "apply_async",
                        lambda *, args, expires: queued.append((args, expires)))
    monkeypatch.setattr(plans, "details", lambda plan, mode=None: {"available": True, "amount": plan.price_usd * 3300,
                                                                    "currency": "COP"})
    settings = Settings(database_url=services.store.engine.url.render_as_string(hide_password=False),
                        jwt_secret="test-only-secret-" * 4, mail_key=Fernet.generate_key().decode(), environment="test")
    with TestClient(create_app(settings, services)) as client:
        engineer = {"Authorization": "Bearer " + services.identity.login("eng@example.com", PASSWORD)["access_token"]}
        admin = {"Authorization": "Bearer " + services.identity.login("admin@example.com", PASSWORD)["access_token"]}
        public = client.get("/api/v1/billing/catalog")
        assert public.status_code == 200 and public.json()["plans"][0] == {
            "name": "essentials", "rank": 0, "price_usd": 19.0, "monthly_tokens": 3000000}
        catalog = client.get("/api/v1/billing/plans", headers=engineer).json()
        assert catalog["public_key"] == "TEST-public" and catalog["mode"] == "test"
        assert [plan["name"] for plan in catalog["plans"]] == ["essentials", "standard", "ultimate"]
        assert all(plan["available"] for plan in catalog["plans"])
        # Test mode: the public test cards would give tokens away, so only administrators can buy by default.
        assert catalog["checkout"]["enabled"] is False and "licencia" in catalog["checkout"]["reason"]
        assert client.post("/api/v1/billing/checkout", headers=engineer, json={
            "tier": "standard", "card_token": "tok_12345678", "payer_email": "payer@testuser.com"}).status_code == 403
        assert client.get("/api/v1/billing/plans", headers=admin).json()["checkout"]["enabled"] is True
        monkeypatch.setenv("MP_TEST_CHECKOUT", "everyone")
        assert client.get("/api/v1/billing/plans", headers=engineer).json()["checkout"]["enabled"] is True

        started = client.post("/api/v1/billing/checkout", headers=engineer,
                              json={"tier": "standard", "card_token": "tok_12345678", "payer_email": "payer@testuser.com"})
        assert started.status_code == 202 and len(queued) == 1
        (subscription_id, encrypted_token, payer_email), expires = queued[0][0], queued[0][1]
        assert subscription_id == started.json()["subscription_id"] and payer_email == "payer@testuser.com"
        assert FernetMessages(services.identity.settings.mail_key).decrypt(encrypted_token) == "tok_12345678"
        assert expires == 180
        assert client.get("/api/v1/billing/subscription", headers=engineer).json()["checkout"]["status"] == "pending"
        assert client.post("/api/v1/billing/checkout", headers=engineer, json={
            "tier": "standard", "card_token": "tok_12345678", "payer_email": "payer@testuser.com"}).status_code == 409

        assert client.post("/api/v1/billing/licenses", headers=engineer, json={"tier": "standard", "months": 1}).status_code == 403
        made = client.post("/api/v1/billing/licenses", headers=admin, json={"tier": "ultimate", "months": 3, "count": 2})
        assert made.status_code == 201 and len(made.json()["licenses"]) == 2
        listed = client.get("/api/v1/billing/licenses", headers=admin).json()["licenses"]
        assert len(listed) == 2 and "code" not in listed[0]
        assert client.post("/api/v1/billing/licenses/redeem", headers=engineer, json={"code": "TERRA-ZZZZ-ZZZZ-ZZZZ"}).status_code == 404
