from fastapi import Request, Depends
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from src.domain.identity import ServiceError
from fastapi.routing import APIRoute

PUBLIC = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/google"),
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
}
TRUSTED_WEBHOOKS = {("POST", "/api/v1/files/events/minio")}
bearer = HTTPBearer(auto_error=False)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip("/")
        try:
            if path.startswith("/api/"):
                identity = request.app.state.services.identity
                if (request.method, path) in TRUSTED_WEBHOOKS:
                    # The route validates MinIO's shared webhook token.
                    pass
                elif (request.method, path) in PUBLIC:
                    # Do not trust arbitrary X-Forwarded-For from clients.
                    peer = request.client.host if request.client else "unknown"
                    await run_in_threadpool(
                        identity.throttle, "public_auth_ip", peer, 60, 60
                    )
                else:
                    scheme, _, token = request.headers.get(
                        "authorization", ""
                    ).partition(" ")
                    if scheme.lower() != "bearer" or not token or len(token) > 12000:
                        raise ServiceError(401, "Bearer token required")
                    request.state.principal = await run_in_threadpool(
                        identity.authenticate, token
                    )
            response = await call_next(request)
        except ServiceError as exc:
            response = JSONResponse({"detail": exc.message}, status_code=exc.status)
            if exc.status == 401:
                response.headers["WWW-Authenticate"] = "Bearer"
            if exc.status == 429:
                response.headers["Retry-After"] = "300"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def require(permission=None, *, privileged=False):
    def authorize(request: Request, credentials=Depends(bearer)):
        actor = getattr(request.state, "principal", None)
        if actor is None:
            raise ServiceError(401, "Authentication required")
        if privileged and not actor.privileged:
            raise ServiceError(
                403, "Requires super_admin or an authorized M2M principal"
            )
        if permission and permission not in actor.permissions:
            raise ServiceError(403, "Permission denied")
        return actor

    authorize.spat_authorization_policy = True
    return authorize


def validate_endpoint_policies(app):
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if all((method, route.path) in PUBLIC for method in route.methods):
            continue
        if all((method, route.path) in TRUSTED_WEBHOOKS for method in route.methods):
            continue
        if not any(
            getattr(dep.call, "spat_authorization_policy", False)
            for dep in route.dependant.dependencies
        ):
            raise RuntimeError(f"Missing authorization policy on {route.path}")
