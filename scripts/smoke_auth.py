"""Run inside the API container: verify HTTP -> PostgreSQL -> Celery -> SMTP.

Creates one temporary local viewer and disables it in finally. No credentials
or reset tokens are printed. Does not provision the first super administrator.
"""

import json
import os
import secrets
import time
import urllib.request
from uuid import uuid4

from src.application.use_cases.identity import (
    new_user,
    assign,
    revoke_sessions,
    invalidate_resets,
)
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings


def request(path, payload):
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1" + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def main():
    if (
        os.environ.get("SPAT_ENVIRONMENT") != "local"
        or os.environ.get("SMTP_HOST") != "mailpit"
    ):
        raise SystemExit("Smoke test requires the local Mailpit environment")
    svc = build_services(Settings.from_env())
    email = "smoke-" + uuid4().hex + "@example.com"
    password = secrets.token_urlsafe(32)
    with svc.store.transaction(write=True) as db:
        user = new_user(
            db,
            email=email,
            first_name="Docker smoke test",
            password_hash=svc.identity.passwords.hash(password),
        )
        assign(db, user["id"], "viewer")
    try:
        tokens = request("/auth/login", {"email": email, "password": password})
        request("/auth/forgot-password", {"email": email})
        with svc.store.transaction() as db:
            reset = db.one("password_resets", user_id=user["id"])
            message = db.one("mail_outbox", reset_id=reset["id"])
            # Normally Beat dispatches within 15s; retrieve encrypted payload before send.
            if not message["payload"]:
                raise RuntimeError(
                    "Outbox already delivered before test could inspect its token"
                )
            reset_token = json.loads(svc.identity.cipher.decrypt(message["payload"]))[
                "url"
            ].split("#token=")[1]
        deadline = time.monotonic() + 50
        delivered = False
        while time.monotonic() < deadline:
            with svc.store.transaction() as db:
                current = db.one("mail_outbox", id=message["id"])
                delivered = (
                    current["sent_at"] is not None and current["last_error"] is None
                )
            if delivered:
                break
            time.sleep(1)
        if not delivered:
            raise RuntimeError(
                "Celery/SMTP delivery did not complete within 50 seconds"
            )
        new_password = secrets.token_urlsafe(32)
        request(
            "/auth/reset-password", {"token": reset_token, "password": new_password}
        )
        request("/auth/login", {"email": email, "password": new_password})
        from src.domain.identity import ServiceError

        try:
            svc.identity.authenticate(tokens["access_token"])
        except ServiceError as exc:
            assert exc.status == 401
        else:
            raise AssertionError("Original session was not revoked")
        print(
            "PASS: HTTP login, reset outbox, Celery Beat/worker, SMTP delivery, password reset and session revocation"
        )
    finally:
        with svc.store.transaction(write=True) as db:
            db.change("users", user["id"], active=False)
            revoke_sessions(db, user["id"])
            invalidate_resets(db, user["id"])
        svc.store.engine.dispose()


if __name__ == "__main__":
    main()
