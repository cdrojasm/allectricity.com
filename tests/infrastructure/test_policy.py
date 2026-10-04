import pytest
from fastapi import FastAPI, Depends
from src.infrastructure.security.middleware import validate_endpoint_policies, require
from src.infrastructure.security.settings import Settings


def test_private_endpoint_without_policy_is_rejected():
    app = FastAPI()

    @app.get("/api/v1/forgotten-policy")
    def unprotected():
        return {}

    with pytest.raises(RuntimeError, match="Missing authorization policy"):
        validate_endpoint_policies(app)


def test_private_endpoint_with_explicit_policy_is_accepted():
    app = FastAPI()

    @app.get("/api/v1/protected")
    def protected(actor=Depends(require("designs:read"))):
        return {}

    validate_endpoint_policies(app)


def test_short_secret_rejected():
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(database_url="unused", jwt_secret="short", mail_key="unused")
