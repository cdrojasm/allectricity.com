"""Run inside the API container: create or retire the temporary viewer used by smoke_local.

    python -m scripts.smoke_session create          # prints {"user_id", "email", "password"}
    python -m scripts.smoke_session cleanup <id>    # disables the user and revokes its sessions

The credentials only go to the calling process through stdout; the user is a local viewer
and is always disabled by `cleanup`, so repeated runs leave no active accounts behind.
"""

import json
import os
import secrets
import sys
from uuid import uuid4

from src.application.use_cases.identity import assign, new_user, revoke_sessions
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings


def main(argv):
    if os.environ.get("SPAT_ENVIRONMENT") != "local":
        raise SystemExit("The smoke session only runs in the local environment")
    services = build_services(Settings.from_env())
    if argv[:1] == ["create"]:
        email = f"smoke-{uuid4().hex}@example.com"
        password = secrets.token_urlsafe(32)
        with services.store.transaction(write=True) as db:
            user = new_user(db, email=email, first_name="Smoke test",
                            password_hash=services.identity.passwords.hash(password))
            assign(db, user["id"], "viewer")
        print(json.dumps({"user_id": user["id"], "email": email, "password": password}))
    elif argv[:1] == ["cleanup"] and len(argv) == 2:
        with services.store.transaction(write=True) as db:
            db.change("users", argv[1], active=False)
            revoke_sessions(db, argv[1])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
