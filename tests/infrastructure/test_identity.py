import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.application.use_cases.identity import now, digest
from src.application.use_cases.reset_mail import DeliverResetMail
from src.domain.identity import ServiceError
from src.infrastructure.entrypoint.api.fastapi_app import create_app
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings

PASSWORD = "Test password with 24 chars!"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_url = os.environ.get("TEST_DATABASE_URL")
    engine = None
    schema = None
    if db_url:
        url = make_url(db_url)
        assert url.database.endswith("_test"), (
            "Only a dedicated _test database is allowed"
        )
        engine = create_engine(db_url)
        schema = "test_" + uuid4().hex
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        db_url = url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        ).render_as_string(hide_password=False)
    else:
        db_url = f"sqlite:///{tmp_path / 'identity.db'}"
    settings = Settings(
        database_url=db_url,
        jwt_secret="test-only-secret-" * 4,
        mail_key=Fernet.generate_key().decode(),
        environment="test",
    )
    monkeypatch.setenv("DATABASE_URL", db_url)
    config_path = (
        Path("backend/alembic.ini")
        if Path("backend/alembic.ini").exists()
        else Path("alembic.ini")
    )
    command.upgrade(Config(str(config_path)), "head")
    services = build_services(settings)
    admin = services.admin.bootstrap("admin@example.com", PASSWORD, "Admin")
    tokens = services.identity.login("admin@example.com", PASSWORD)
    actor = services.identity.authenticate(tokens["access_token"])
    with TestClient(create_app(settings, services)) as client:
        yield settings, services, client, actor, tokens, admin
    services.store.engine.dispose()
    if engine is not None:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def headers(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def human(services, actor, email="user@example.com", role=None):
    user = services.admin.create_user(
        actor,
        dict(
            email=email,
            password=PASSWORD,
            first_name="User",
            last_name="Test",
            phone=None,
            locale="es-CO",
            timezone="UTC",
        ),
    )
    if role:
        services.admin.assign_role(actor, user["id"], role)
    tokens = services.identity.login(email, PASSWORD)
    return user, tokens, services.identity.authenticate(tokens["access_token"])


def test_authentication_and_no_secret_leaks(env):
    _, svc, client, _, tokens, _ = env
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/api/v1/users").status_code == 401
    assert (
        client.get("/api/v1/users", headers={"Authorization": "Basic abc"}).status_code
        == 401
    )
    response = client.get("/api/v1/auth/me", headers=headers(tokens))
    assert response.status_code == 200
    assert response.json()["roles"] == ["super_admin"]
    assert "password_hash" not in response.text and "idp_metadata" not in response.text
    assert response.headers["cache-control"] == "no-store"
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    absent = client.post(
        "/api/v1/auth/login", json={"email": "absent@example.com", "password": "wrong"}
    )
    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()


@pytest.mark.parametrize(
    "case",
    [
        "signature",
        "issuer",
        "audience",
        "expired",
        "future",
        "missing_exp",
        "missing_sid",
        "refresh_kind",
        "algorithm",
        "none",
    ],
)
def test_reject_invalid_jwts(env, case):
    settings, _, client, _, tokens, _ = env
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    key = settings.jwt_secret
    algorithm = "HS256"
    if case == "signature":
        key = "wrong-secret" * 6
    if case == "issuer":
        claims["iss"] = "attacker"
    if case == "audience":
        claims["aud"] = "another-api"
    if case == "expired":
        claims["exp"] = now() - 10
    if case == "future":
        claims["nbf"] = now() + 100
    if case == "missing_exp":
        claims.pop("exp")
    if case == "missing_sid":
        claims.pop("sid")
    if case == "refresh_kind":
        claims["token_use"] = "refresh"
    if case == "algorithm":
        algorithm = "HS384"
    if case == "none":
        algorithm, key = "none", ""
    forged = jwt.encode(claims, key, algorithm=algorithm)
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + forged}
        ).status_code
        == 401
    )


def test_refresh_reuse_commits_family_revocation(env):
    _, svc, client, _, first, _ = env
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get("/api/v1/auth/me", headers=headers(second)).status_code == 200
    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers(second)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
        ).status_code
        == 401
    )
    with svc.store.transaction() as db:
        row = db.one("refresh_tokens", token_hash=digest(first["refresh_token"]))
        assert first["refresh_token"] not in str(row)


def test_concurrent_refresh_allows_one_rotation_then_revokes(env):
    _, svc, _, _, tokens, _ = env

    def rotate(_):
        try:
            return svc.identity.refresh(tokens["refresh_token"])
        except ServiceError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 401 in results
    with pytest.raises(ServiceError):
        svc.identity.authenticate(
            next(r for r in results if isinstance(r, dict))["access_token"]
        )


def test_revoke_all_and_session_ownership(env):
    _, svc, client, admin, first, _ = env
    _, other_tokens, _ = human(svc, admin)
    second = svc.identity.login("admin@example.com", PASSWORD)
    assert (
        client.delete(
            f"/api/v1/auth/sessions/{first['session_id']}",
            headers=headers(other_tokens),
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/auth/revoke", json={"all_sessions": True}, headers=headers(first)
        ).status_code
        == 204
    )
    for tokens in (first, second):
        assert client.get("/api/v1/auth/me", headers=headers(tokens)).status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers=headers(other_tokens)).status_code == 200
    )


def test_rbac_and_immediate_role_removal(env):
    _, svc, client, admin, root_tokens, _ = env
    user, tokens, _ = human(svc, admin)
    assert client.get("/api/v1/users", headers=headers(tokens)).status_code == 403
    assert (
        client.post(
            "/api/v1/roles", headers=headers(tokens), json={"name": "rogue"}
        ).status_code
        == 403
    )
    assignment = svc.admin.assign_role(admin, user["id"], "user_admin")
    assert client.get("/api/v1/users", headers=headers(tokens)).status_code == 200
    assert (
        client.post(
            "/api/v1/user-roles",
            headers=headers(tokens),
            json={"user_id": user["id"], "role_id": "super_admin"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/users/{admin.user_id}",
            headers=headers(tokens),
            json={"email": "attacker@example.com"},
        ).status_code
        == 403
    )
    svc.admin.unassign_role(admin, assignment["id"])
    assert client.get("/api/v1/users", headers=headers(tokens)).status_code == 403
    assert (
        client.delete(
            f"/api/v1/users/{admin.user_id}", headers=headers(root_tokens)
        ).status_code
        == 409
    )


def test_role_crud_and_constraints(env):
    _, svc, client, admin, tokens, _ = env
    auth = headers(tokens)
    role = client.post(
        "/api/v1/roles",
        headers=auth,
        json={"name": "auditor", "permissions": ["users:read"]},
    )
    assert role.status_code == 201
    rid = role.json()["id"]
    assert (
        client.put(
            f"/api/v1/roles/{rid}",
            headers=auth,
            json={"name": "auditor", "permissions": ["unknown"]},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/roles/super_admin",
            headers=auth,
            json={"name": "super_admin", "permissions": []},
        ).status_code
        == 409
    )
    user, _, _ = human(svc, admin)
    assigned = client.post(
        "/api/v1/user-roles", headers=auth, json={"user_id": user["id"], "role_id": rid}
    )
    assert assigned.status_code == 201
    assert client.delete(f"/api/v1/roles/{rid}", headers=auth).status_code == 409
    assert (
        client.delete(
            f"/api/v1/user-roles/{assigned.json()['id']}", headers=auth
        ).status_code
        == 204
    )
    assert client.delete(f"/api/v1/roles/{rid}", headers=auth).status_code == 204
    assert (
        client.post(
            "/api/v1/user-roles",
            headers=auth,
            json={"user_id": user["id"], "role_id": "m2m"},
        ).status_code
        == 400
    )


def test_m2m_flow_and_rotation(env):
    _, _, client, _, tokens, _ = env
    auth = headers(tokens)
    created = client.post(
        "/api/v1/auth/clients",
        headers=auth,
        json={"name": "worker", "email": "worker@example.com"},
    )
    assert created.status_code == 201
    body = created.json()
    credentials = {
        "client_id": body["client_id"],
        "client_secret": body["client_secret"],
    }
    machine = client.post("/api/v1/auth/token", json=credentials).json()
    assert "refresh_token" not in machine
    assert (
        client.post(
            "/api/v1/roles", headers=headers(machine), json={"name": "machine_role"}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "worker@example.com", "password": body["client_secret"]},
        ).status_code
        == 401
    )
    rotated = client.post(
        f"/api/v1/auth/clients/{body['client_id']}/rotate-secret", headers=auth
    )
    assert rotated.status_code == 200
    assert client.post("/api/v1/auth/token", json=credentials).status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers(machine)).status_code == 401
    assert client.post("/api/v1/auth/token", json=rotated.json()).status_code == 200


def test_user_deactivation_and_validation(env):
    _, svc, client, admin, tokens, _ = env
    user, user_tokens, _ = human(svc, admin)
    path = f"/api/v1/users/{user['id']}"
    assert (
        client.patch(
            path, headers=headers(tokens), json={"first_name": None}
        ).status_code
        == 422
    )
    assert (
        client.patch(path, headers=headers(tokens), json={"kind": "m2m"}).status_code
        == 422
    )
    assert (
        client.patch(path, headers=headers(tokens), json={"phone": "+571234"}).json()[
            "phone"
        ]
        == "+571234"
    )
    assert client.delete(path, headers=headers(tokens)).status_code == 204
    assert (
        client.get("/api/v1/auth/me", headers=headers(user_tokens)).status_code == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": user_tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_password_reset_outbox_single_use_and_session_revocation(env):
    _, svc, client, _, tokens, _ = env
    before = client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    actual = client.post(
        "/api/v1/auth/forgot-password", json={"email": "admin@example.com"}
    )
    assert (
        before.status_code == actual.status_code == 202
        and before.json() == actual.json()
    )
    with svc.store.transaction() as db:
        message = db.many("mail_outbox")[0]
        payload = json.loads(svc.identity.cipher.decrypt(message["payload"]))
        raw = payload["url"].split("#token=")[1]
        assert (
            raw not in str(db.many("password_resets")) and raw not in message["payload"]
        )
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "password": "New password with 24 chars!"},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(tokens)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": raw, "password": PASSWORD}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.com",
                "password": "New password with 24 chars!",
            },
        ).status_code
        == 200
    )


def test_change_password_revokes_refresh(env):
    _, _, client, _, tokens, _ = env
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers(tokens),
            json={"current_password": PASSWORD, "password": "Brand new password 123!"},
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_mail_delivery_retry_and_dedup(env):
    _, svc, _, _, _, _ = env
    svc.identity.forgot_password("admin@example.com")
    with svc.store.transaction() as db:
        row = db.many("mail_outbox")[0]

    class Mail:
        sent = []
        fail = True

        def send_reset(self, recipient, url, message_id):
            if self.fail:
                raise OSError("SMTP unavailable")
            self.sent.append((recipient, url, message_id))

    mail = Mail()
    delivery = DeliverResetMail(svc.store, svc.identity.cipher, mail)
    with pytest.raises(RuntimeError, match="delivery failed"):
        delivery.execute(row["id"])
    with svc.store.transaction(write=True) as db:
        assert db.one("mail_outbox", id=row["id"])["last_error"] == "delivery_failed"
        db.change("mail_outbox", row["id"], available_at=now() - 1)
    mail.fail = False
    delivery.execute(row["id"])
    delivery.execute(row["id"])
    assert len(mail.sent) == 1
    with svc.store.transaction() as db:
        assert db.one("mail_outbox", id=row["id"])["payload"] == ""


def test_google_adapter_boundary_and_no_automatic_linking(env):
    _, svc, _, _, _, _ = env

    class Google:
        email = "google@example.com"

        def verify(self, token):
            return {
                "email": self.email,
                "subject": "google-unique-sub",
                "issuer": "https://accounts.google.com",
                "name": "Google User",
            }

    google = Google()
    svc.identity.external = google
    token = svc.identity.google("verified-by-adapter")
    actor = svc.identity.authenticate(token["access_token"])
    assert actor.roles == frozenset({"designer"})
    with svc.store.transaction() as db:
        assert db.one("users", id=actor.user_id)["idp_subject"] == "google-unique-sub"

    class Conflict:
        def verify(self, token):
            return {
                "email": "admin@example.com",
                "subject": "other-sub",
                "issuer": "https://accounts.google.com",
                "name": "Other",
            }

    svc.identity.external = Conflict()
    with pytest.raises(ServiceError) as exc:
        svc.identity.google("verified-by-adapter")
    assert exc.value.status == 409


def test_login_page_learns_the_public_google_client_id(env):
    _, svc, client, _, _, _ = env
    svc.identity.external.client_id = ""
    assert client.get("/api/v1/auth/config").json() == {"google_client_id": None}
    svc.identity.external.client_id = "123-abc.apps.googleusercontent.com"
    assert client.get("/api/v1/auth/config").json() == {"google_client_id": "123-abc.apps.googleusercontent.com"}


def test_budget_ownership_idempotency_and_audit(env):
    _, svc, client, admin, root_tokens, _ = env
    user, tokens, _ = human(svc, admin)
    _, other_tokens, _ = human(svc, admin, email="other@example.com")
    created = client.post(
        "/api/v1/budgets",
        headers=headers(root_tokens),
        json={"user_id": user["id"], "name": "Monthly tokens", "total_tokens": 100},
    )
    assert created.status_code == 201
    path = f"/api/v1/budgets/{created.json()['id']}"
    data = {
        "input_tokens": 20,
        "output_tokens": 10,
        "project_id": "project-1",
        "action": "refine_mesh",
        "model": "demo-model",
        "idempotency_key": "request-1",
    }
    assert (
        client.post(path + "/usage", headers=headers(tokens), json=data).status_code
        == 403
    )
    first = client.post(path + "/usage", headers=headers(root_tokens), json=data)
    second = client.post(path + "/usage", headers=headers(root_tokens), json=data)
    assert first.status_code == 201 and first.json()["id"] == second.json()["id"]
    assert (
        client.post(
            path + "/usage",
            headers=headers(root_tokens),
            json={**data, "input_tokens": 21},
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/usage",
            headers=headers(root_tokens),
            json={**data, "input_tokens": -1},
        ).status_code
        == 422
    )
    assert client.get(path, headers=headers(tokens)).json()["remaining_tokens"] == 70
    assert client.get(path, headers=headers(other_tokens)).status_code == 404
    assert client.get(path + "/usage", headers=headers(other_tokens)).status_code == 404
    assert (
        client.get(
            path + "/usage?project_id=project-1", headers=headers(tokens)
        ).json()[0]["action"]
        == "refine_mesh"
    )
    assert (
        client.patch(
            path, headers=headers(root_tokens), json={"total_tokens": 20}
        ).status_code
        == 409
    )


def test_concurrent_budget_never_overspends(env):
    _, svc, _, actor, _, user = env
    budget = svc.budgets.create(
        actor, {"user_id": user["id"], "name": "limited", "total_tokens": 100}
    )

    def debit(i):
        try:
            return svc.budgets.consume(
                actor,
                budget["id"],
                dict(
                    input_tokens=40,
                    output_tokens=20,
                    project_id="project-1",
                    action="calculate",
                    model="test",
                    idempotency_key=str(i),
                ),
            )
        except ServiceError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(debit, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 409 in results
    with svc.store.transaction() as db:
        assert db.one("budget", id=budget["id"])["used_tokens"] == 60
        assert len(db.many("budget_usage", budget_id=budget["id"])) == 1


def test_account_throttle_persists_and_reset_expiry(env):
    _, svc, _, _, _, _ = env
    for i in range(3):
        svc.identity.forgot_password("admin@example.com")
    with pytest.raises(ServiceError) as exc:
        svc.identity.forgot_password("admin@example.com")
    assert exc.value.status == 429
    with svc.store.transaction(write=True) as db:
        latest = db.one("password_resets", consumed_at=None)
        db.change("password_resets", latest["id"], expires_at=now() - 1)
        outbox = db.one("mail_outbox", reset_id=latest["id"])
        payload = json.loads(svc.identity.cipher.decrypt(outbox["payload"]))
    with pytest.raises(ServiceError):
        svc.identity.reset_password(payload["url"].split("#token=")[1], PASSWORD)
