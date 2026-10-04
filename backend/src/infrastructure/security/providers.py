import time
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token

from src.domain.identity import ServiceError


class HS256Tokens:
    def __init__(self, settings):
        self.settings = settings

    def issue(self, subject: str, session_id: str, kind: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "sub": subject,
                "sid": session_id,
                "kind": kind,
                "token_use": "access",
                "jti": str(uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + self.settings.access_seconds,
                "iss": self.settings.issuer,
                "aud": self.settings.audience,
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )

    def verify(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=["HS256"],
                issuer=self.settings.issuer,
                audience=self.settings.audience,
                options={
                    "require": [
                        "sub",
                        "sid",
                        "jti",
                        "iat",
                        "nbf",
                        "exp",
                        "iss",
                        "aud",
                        "token_use",
                        "kind",
                    ]
                },
            )
            if claims["token_use"] != "access" or claims["kind"] not in {
                "human",
                "m2m",
            }:
                raise ValueError()
            if any(
                not isinstance(claims[k], str) or not claims[k]
                for k in ("sub", "sid", "jti")
            ):
                raise ValueError()
            return claims
        except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
            raise ServiceError(401, "Invalid or expired access token") from exc


class ArgonPasswords:
    def __init__(self):
        self.hasher = PasswordHasher()

    def hash(self, password):
        return self.hasher.hash(password)

    def verify(self, encoded, password):
        try:
            return self.hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False


class FernetMessages:
    def __init__(self, key):
        self.cipher = Fernet(key.encode())

    def encrypt(self, value):
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value):
        return self.cipher.decrypt(value.encode()).decode()


class GoogleIdentity:
    def __init__(self, client_id):
        self.client_id = client_id

    def verify(self, token):
        if not self.client_id:
            raise ServiceError(503, "Google identity provider is not configured")
        try:
            claims = id_token.verify_oauth2_token(token, Request(), self.client_id)
            if not claims.get("sub") or claims.get("email_verified") is not True:
                raise ValueError()
            if claims.get("azp", self.client_id) != self.client_id:
                raise ValueError()
            return {
                "subject": claims["sub"],
                "issuer": "https://accounts.google.com",
                "email": claims["email"].strip().lower(),
                "name": claims.get("name", ""),
                "picture": claims.get("picture"),
                "email_verified": True,
            }
        except (ValueError, KeyError) as exc:
            raise ServiceError(401, "Invalid Google identity token") from exc
        except GoogleAuthError as exc:
            raise ServiceError(503, "Google identity service unavailable") from exc
