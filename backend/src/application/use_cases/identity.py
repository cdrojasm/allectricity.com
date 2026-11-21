import hashlib
import json
import secrets
import time
from uuid import uuid4

from src.application.ports.identity import (
    IdentityStore,
    TokenProvider,
    PasswordHasher,
    ExternalIdentityProvider,
    MessageCipher,
)
from src.domain.identity import Principal, ServiceError


def uid():
    return str(uuid4())


def now():
    return int(time.time())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_user(user):
    return {k: v for k, v in user.items() if k not in {"password_hash", "idp_metadata"}}


def audit(db, actor_id, action, target_id):
    db.add(
        "audit_events",
        id=uid(),
        actor_id=actor_id,
        action=action,
        target_id=target_id,
        created_at=now(),
    )


def revoke_sessions(db, user_id):
    for session in db.many("auth_sessions", user_id=user_id, revoked_at=None):
        db.change("auth_sessions", session["id"], revoked_at=now())


def invalidate_resets(db, user_id):
    for reset in db.many("password_resets", user_id=user_id, consumed_at=None):
        db.change("password_resets", reset["id"], consumed_at=now())


def new_user(
    db, *, email, first_name, last_name="", password_hash=None, kind="human", **extra
):
    values = dict(
        id=uid(),
        email=email.lower().strip(),
        first_name=first_name,
        last_name=last_name,
        phone=None,
        locale="es-CO",
        timezone="America/Bogota",
        avatar_url=None,
        active=True,
        email_verified=False,
        kind=kind,
        password_hash=password_hash,
        idp_provider="local",
        idp_subject=None,
        idp_issuer=None,
        idp_metadata={},
        created_at=now(),
        updated_at=now(),
        last_login_at=None,
    )
    values.update(extra)
    return db.add("users", **values)


def assign(db, user_id, role_id):
    return db.add(
        "user_roles", id=uid(), user_id=user_id, role_id=role_id, created_at=now()
    )


def principal_for(db, user, session_id):
    roles, grants = set(), set()
    for assignment in db.many("user_roles", user_id=user["id"]):
        role = db.one("roles", id=assignment["role_id"])
        roles.add(role["name"])
        for grant in db.many("role_permissions", role_id=role["id"]):
            permission = db.one("permissions", id=grant["permission_id"])
            grants.add(permission["name"])
    return Principal(
        user["id"], session_id, user["kind"], frozenset(roles), frozenset(grants)
    )


class IdentityService:
    def __init__(
        self,
        store: IdentityStore,
        tokens: TokenProvider,
        passwords: PasswordHasher,
        external: ExternalIdentityProvider,
        cipher: MessageCipher,
        settings,
    ):
        self.store, self.tokens, self.passwords = store, tokens, passwords
        self.external, self.cipher, self.settings = external, cipher, settings
        self.dummy_hash = passwords.hash(secrets.token_urlsafe(32))

    def throttle(self, action, key, limit=10, seconds=300):
        bucket = digest(action + ":" + key)
        exceeded = False
        with self.store.transaction(write=True) as db:
            row = db.one("rate_limits", bucket=bucket)
            if row is None:
                db.add(
                    "rate_limits",
                    id=uid(),
                    bucket=bucket,
                    window_start=now(),
                    attempts=1,
                )
            elif row["window_start"] + seconds <= now():
                db.change("rate_limits", row["id"], window_start=now(), attempts=1)
            else:
                db.change("rate_limits", row["id"], attempts=row["attempts"] + 1)
                exceeded = row["attempts"] >= limit
        if exceeded:
            raise ServiceError(429, "Too many attempts; try again later")

    def _session(self, db, user, refresh=True):
        session = db.add(
            "auth_sessions",
            id=uid(),
            user_id=user["id"],
            created_at=now(),
            expires_at=now()
            + (
                self.settings.refresh_seconds
                if refresh
                else self.settings.access_seconds
            ),
            revoked_at=None,
        )
        db.change("users", user["id"], last_login_at=now())
        return self._pair(db, user, session, refresh)

    def _pair(self, db, user, session, refresh=True):
        response = {
            "access_token": self.tokens.issue(user["id"], session["id"], user["kind"]),
            "token_type": "bearer",
            "expires_in": self.settings.access_seconds,
            "session_id": session["id"],
        }
        if refresh:
            raw = secrets.token_urlsafe(48)
            db.add(
                "refresh_tokens",
                id=uid(),
                session_id=session["id"],
                token_hash=digest(raw),
                expires_at=session["expires_at"],
                consumed_at=None,
            )
            response.update(
                refresh_token=raw,
                refresh_expires_in=max(0, session["expires_at"] - now()),
            )
        return response

    def login(self, email, password):
        self.throttle("login_account", email.lower())
        with self.store.transaction(write=True) as db:
            user = db.one("users", email=email.lower())
            valid = self.passwords.verify(
                (user or {}).get("password_hash") or self.dummy_hash, password
            )
            if (
                not user
                or not valid
                or not user["active"]
                or user["kind"] != "human"
                or not user["password_hash"]
            ):
                raise ServiceError(401, "Invalid credentials")
            audit(db, user["id"], "auth.login", user["id"])
            return self._session(db, user)

    def client_credentials(self, client_id, client_secret):
        self.throttle("client", client_id)
        with self.store.transaction(write=True) as db:
            user = db.one("users", id=client_id)
            valid = self.passwords.verify(
                (user or {}).get("password_hash") or self.dummy_hash, client_secret
            )
            if not user or not valid or not user["active"] or user["kind"] != "m2m":
                raise ServiceError(401, "Invalid client credentials")
            audit(db, user["id"], "auth.client_credentials", user["id"])
            return self._session(db, user, refresh=False)

    def google(self, token):
        identity = self.external.verify(token)
        with self.store.transaction(write=True) as db:
            user = db.one(
                "users", idp_provider="google", idp_subject=identity["subject"]
            )
            existing = None if user else db.one("users", email=identity["email"])
            if existing:
                user = self._link_google(db, existing, identity)
            elif user is None:
                user = new_user(
                    db,
                    email=identity["email"],
                    first_name=identity["name"][:100],
                    idp_provider="google",
                    idp_subject=identity["subject"],
                    idp_issuer=identity["issuer"],
                    email_verified=True,
                    avatar_url=identity.get("picture"),
                    idp_metadata={"email_verified": True},
                )
                # Self sign-up: the account can create projects; the agent stays behind a paid plan
                # (AGENT_REQUIRE_BUDGET) so signing up costs nothing.
                assign(db, user["id"], "designer")
                audit(db, user["id"], "auth.google_signup", user["id"])
            if not user["active"] or user["kind"] != "human":
                raise ServiceError(401, "Account unavailable")
            audit(db, user["id"], "auth.google", user["id"])
            return self._session(db, user)

    def _link_google(self, db, user, identity):
        """Google proved the mailbox, so its identity is attached to the account with that email.

        Pre-hijacking guard: a password set on an email nobody ever proved (someone may have
        registered it first) is dropped, with every session and pending reset. A proven email keeps
        its password, so both sign-in methods work. Staff and machine accounts are never linked.
        """
        staff = any(
            a["role_id"] in {"super_admin", "m2m", "user_admin"}
            for a in db.many("user_roles", user_id=user["id"])
        )
        if user["kind"] != "human" or staff or user["idp_provider"] != "local":
            raise ServiceError(
                409,
                "Ya existe una cuenta con ese correo. Inicia sesión con tu correo y contraseña.",
            )
        changes = dict(
            idp_provider="google",
            idp_subject=identity["subject"],
            idp_issuer=identity["issuer"],
            idp_metadata={**(user["idp_metadata"] or {}), "email_verified": True, "linked_at": now()},
            email_verified=True,
            avatar_url=user["avatar_url"] or identity.get("picture"),
            updated_at=now(),
        )
        if not user["email_verified"]:
            changes["password_hash"] = None
            invalidate_resets(db, user["id"])
            revoke_sessions(db, user["id"])
        db.change("users", user["id"], **changes)
        audit(db, user["id"], "auth.google_linked" if user["email_verified"] else "auth.google_linked_password_dropped", user["id"])
        return db.one("users", id=user["id"])

    def authenticate(self, token):
        claims = self.tokens.verify(token)
        with self.store.transaction() as db:
            user = db.one("users", id=claims["sub"])
            session = db.one("auth_sessions", id=claims["sid"])
            if (
                not user
                or not user["active"]
                or not session
                or session["user_id"] != user["id"]
                or session["revoked_at"] is not None
                or session["expires_at"] <= now()
                or user["kind"] != claims["kind"]
            ):
                raise ServiceError(401, "Session revoked or expired")
            return principal_for(db, user, session["id"])

    def refresh(self, token):
        error = None
        result = None
        with self.store.transaction(write=True) as db:
            stored = db.one("refresh_tokens", token_hash=digest(token))
            if not stored:
                raise ServiceError(401, "Invalid refresh token")
            session = db.one("auth_sessions", id=stored["session_id"])
            user = db.one("users", id=session["user_id"])
            if stored["consumed_at"] is not None:
                db.change("auth_sessions", session["id"], revoked_at=now())
                audit(db, user["id"], "auth.refresh_reuse", session["id"])
                error = ServiceError(
                    401, "Refresh token reuse detected; session revoked"
                )
            elif (
                session["revoked_at"] is not None
                or stored["expires_at"] <= now()
                or session["expires_at"] <= now()
                or not user["active"]
                or user["kind"] != "human"
            ):
                error = ServiceError(401, "Invalid refresh token")
            else:
                db.change("refresh_tokens", stored["id"], consumed_at=now())
                # The refresh lifetime is a sliding inactivity window. Active users
                # keep their session; inactive users must return before this expires.
                session["expires_at"] = now() + self.settings.refresh_seconds
                db.change("auth_sessions", session["id"], expires_at=session["expires_at"])
                result = self._pair(db, user, session)
        # Raise AFTER commit so reuse detection really revokes the family.
        if error:
            raise error
        return result

    def revoke(self, principal, all_sessions=False):
        with self.store.transaction(write=True) as db:
            if all_sessions:
                revoke_sessions(db, principal.user_id)
            else:
                db.change("auth_sessions", principal.session_id, revoked_at=now())
            audit(db, principal.user_id, "auth.revoke", principal.session_id)

    def forgot_password(self, email):
        self.throttle("reset_account", email.lower(), limit=3, seconds=900)
        with self.store.transaction(write=True) as db:
            user = db.one("users", email=email.lower())
            if (
                user
                and user["active"]
                and user["kind"] == "human"
            ):
                # Google accounts too: the link reaches the same mailbox, so it can add a password.
                invalidate_resets(db, user["id"])
                token = secrets.token_urlsafe(48)
                reset = db.add(
                    "password_resets",
                    id=uid(),
                    user_id=user["id"],
                    token_hash=digest(token),
                    expires_at=now() + self.settings.reset_seconds,
                    consumed_at=None,
                )
                # Fragment keeps reset credentials out of HTTP access logs and Referer.
                payload = json.dumps(
                    {
                        "recipient": user["email"],
                        "url": self.settings.reset_url + "#token=" + token,
                    }
                )
                db.add(
                    "mail_outbox",
                    id=uid(),
                    reset_id=reset["id"],
                    payload=self.cipher.encrypt(payload),
                    created_at=now(),
                    sent_at=None,
                    attempts=0,
                    available_at=now(),
                    last_error=None,
                )
                audit(db, user["id"], "auth.password_reset_requested", user["id"])
        return {
            "message": "If the account is eligible, a password reset email will be sent"
        }

    def reset_password(self, token, password):
        with self.store.transaction(write=True) as db:
            reset = db.one("password_resets", token_hash=digest(token))
            if (
                not reset
                or reset["consumed_at"] is not None
                or reset["expires_at"] <= now()
            ):
                raise ServiceError(400, "Invalid or expired reset token")
            user = db.one("users", id=reset["user_id"])
            if not user["active"] or user["kind"] != "human":
                raise ServiceError(400, "Invalid or expired reset token")
            # Using the emailed link proves the mailbox.
            db.change(
                "users",
                user["id"],
                password_hash=self.passwords.hash(password),
                email_verified=True,
                updated_at=now(),
            )
            invalidate_resets(db, user["id"])
            revoke_sessions(db, user["id"])
            audit(db, user["id"], "auth.password_reset_completed", user["id"])

    def change_password(self, principal, current, password):
        with self.store.transaction(write=True) as db:
            user = db.one("users", id=principal.user_id)
            if (
                user["kind"] != "human"
                or not user["password_hash"]
                or not self.passwords.verify(
                    user["password_hash"] or self.dummy_hash, current
                )
            ):
                raise ServiceError(400, "Current password could not be verified")
            db.change(
                "users",
                user["id"],
                password_hash=self.passwords.hash(password),
                updated_at=now(),
            )
            invalidate_resets(db, user["id"])
            revoke_sessions(db, user["id"])
            audit(db, user["id"], "auth.password_changed", user["id"])
