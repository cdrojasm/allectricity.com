from fastapi import APIRouter, Depends, Request, Query, Response
from src.application.use_cases.identity import public_user
from src.application.use_cases.identity_admin import require_record
from src.application.use_cases.budgets import check_budget_owner
from src.domain.identity import PERMISSIONS, ServiceError
from src.infrastructure.security.middleware import require
from src.infrastructure.entrypoint.api import identity_schemas as s

router = APIRouter(prefix="/api/v1")


def services(request: Request):
    return request.app.state.services


@router.post("/auth/login", tags=["auth"])
def login(data: s.Login, svc=Depends(services)):
    return svc.identity.login(str(data.email), data.password)


@router.post("/auth/google", tags=["auth"])
def google(data: s.TokenInput, svc=Depends(services)):
    return svc.identity.google(data.token)


@router.post("/auth/token", tags=["auth"])
def token(data: s.ClientCredentials, svc=Depends(services)):
    return svc.identity.client_credentials(data.client_id, data.client_secret)


@router.post("/auth/refresh", tags=["auth"])
def refresh(data: s.RefreshInput, svc=Depends(services)):
    return svc.identity.refresh(data.refresh_token)


@router.post("/auth/revoke", tags=["auth"], status_code=204)
def revoke(data: s.RevokeInput, actor=Depends(require()), svc=Depends(services)):
    svc.identity.revoke(actor, data.all_sessions)
    return Response(status_code=204)


@router.get("/auth/me", tags=["auth"])
def me(actor=Depends(require()), svc=Depends(services)):
    with svc.store.transaction() as db:
        return {
            **public_user(require_record(db, "users", actor.user_id)),
            "roles": sorted(actor.roles),
            "permissions": sorted(actor.permissions),
        }


@router.get("/auth/sessions", tags=["auth"])
def sessions(
    actor=Depends(require()),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        return db.many(
            "auth_sessions", user_id=actor.user_id, limit=limit, offset=offset
        )


@router.delete("/auth/sessions/{session_id}", tags=["auth"], status_code=204)
def revoke_session(session_id: str, actor=Depends(require()), svc=Depends(services)):
    from src.application.use_cases.identity import now

    with svc.store.transaction(write=True) as db:
        session = require_record(db, "auth_sessions", session_id)
        if session["user_id"] != actor.user_id:
            raise ServiceError(404, "Session not found")
        db.change("auth_sessions", session_id, revoked_at=now())
    return Response(status_code=204)


@router.post("/auth/forgot-password", tags=["auth"], status_code=202)
def forgot(data: s.ForgotPassword, svc=Depends(services)):
    return svc.identity.forgot_password(str(data.email))


@router.post("/auth/reset-password", tags=["auth"], status_code=204)
def reset(data: s.ResetPassword, svc=Depends(services)):
    svc.identity.reset_password(data.token, data.password)
    return Response(status_code=204)


@router.post("/auth/change-password", tags=["auth"], status_code=204)
def change_password(
    data: s.ChangePassword, actor=Depends(require()), svc=Depends(services)
):
    svc.identity.change_password(actor, data.current_password, data.password)
    return Response(status_code=204)


@router.post("/auth/clients", tags=["M2M"], status_code=201)
def create_client(
    data: s.ClientCreate, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    return svc.admin.create_client(actor, data.name, str(data.email))


@router.post("/auth/clients/{client_id}/rotate-secret", tags=["M2M"])
def rotate_client(
    client_id: str, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    return svc.admin.rotate_client(actor, client_id)


@router.get("/users", tags=["users"])
def users(
    actor=Depends(require("users:read")),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        return [
            public_user(user) for user in db.many("users", limit=limit, offset=offset)
        ]


@router.get("/users/{user_id}", tags=["users"])
def user(user_id: str, actor=Depends(require()), svc=Depends(services)):
    if actor.user_id != user_id and "users:read" not in actor.permissions:
        raise ServiceError(403, "Permission denied")
    with svc.store.transaction() as db:
        return public_user(require_record(db, "users", user_id))


@router.post("/users", tags=["users"], status_code=201)
def create_user(
    data: s.UserCreate, actor=Depends(require("users:write")), svc=Depends(services)
):
    return svc.admin.create_user(actor, data.model_dump())


@router.patch("/users/{user_id}", tags=["users"])
def update_user(
    user_id: str,
    data: s.UserUpdate,
    actor=Depends(require("users:write")),
    svc=Depends(services),
):
    return svc.admin.update_user(actor, user_id, data.model_dump(exclude_unset=True))


@router.delete("/users/{user_id}", tags=["users"], status_code=204)
def deactivate(
    user_id: str, actor=Depends(require("users:write")), svc=Depends(services)
):
    svc.admin.update_user(actor, user_id, {"active": False})
    return Response(status_code=204)


@router.get("/permissions", tags=["roles"])
def permissions(actor=Depends(require(privileged=True))):
    return sorted(PERMISSIONS)


@router.get("/roles", tags=["roles"])
def roles(
    actor=Depends(require(privileged=True)),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        return [
            {
                **role,
                "permissions": [
                    g["permission_id"]
                    for g in db.many("role_permissions", role_id=role["id"])
                ],
            }
            for role in db.many("roles", limit=limit, offset=offset)
        ]


@router.get("/roles/{role_id}", tags=["roles"])
def role(role_id: str, actor=Depends(require(privileged=True)), svc=Depends(services)):
    with svc.store.transaction() as db:
        return {
            **require_record(db, "roles", role_id),
            "permissions": [
                g["permission_id"] for g in db.many("role_permissions", role_id=role_id)
            ],
        }


@router.post("/roles", tags=["roles"], status_code=201)
def create_role(
    data: s.RoleInput, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    return svc.admin.role(actor, data.model_dump())


@router.put("/roles/{role_id}", tags=["roles"])
def update_role(
    role_id: str,
    data: s.RoleInput,
    actor=Depends(require(privileged=True)),
    svc=Depends(services),
):
    return svc.admin.role(actor, data.model_dump(), role_id)


@router.delete("/roles/{role_id}", tags=["roles"], status_code=204)
def delete_role(
    role_id: str, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    svc.admin.delete_role(actor, role_id)
    return Response(status_code=204)


@router.get("/user-roles", tags=["roles"])
def assignments(
    user_id: str | None = None,
    actor=Depends(require(privileged=True)),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        return db.many(
            "user_roles",
            limit=limit,
            offset=offset,
            **({"user_id": user_id} if user_id else {}),
        )


@router.post("/user-roles", tags=["roles"], status_code=201)
def assign(
    data: s.Assignment, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    return svc.admin.assign_role(actor, data.user_id, data.role_id)


@router.delete("/user-roles/{assignment_id}", tags=["roles"], status_code=204)
def unassign(
    assignment_id: str, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    svc.admin.unassign_role(actor, assignment_id)
    return Response(status_code=204)


@router.post("/budgets", tags=["budget"], status_code=201)
def create_budget(
    data: s.BudgetCreate, actor=Depends(require(privileged=True)), svc=Depends(services)
):
    return svc.budgets.create(actor, data.model_dump())


@router.get("/budgets", tags=["budget"])
def budgets(
    actor=Depends(require("budgets:read")),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        return db.many(
            "budget",
            limit=limit,
            offset=offset,
            **({} if actor.privileged else {"user_id": actor.user_id}),
        )


@router.get("/budgets/{budget_id}", tags=["budget"])
def budget(
    budget_id: str, actor=Depends(require("budgets:read")), svc=Depends(services)
):
    with svc.store.transaction() as db:
        record = require_record(db, "budget", budget_id)
        check_budget_owner(actor, record)
        return {
            **record,
            "remaining_tokens": record["total_tokens"] - record["used_tokens"],
        }


@router.patch("/budgets/{budget_id}", tags=["budget"])
def update_budget(
    budget_id: str,
    data: s.BudgetUpdate,
    actor=Depends(require(privileged=True)),
    svc=Depends(services),
):
    return svc.budgets.update(actor, budget_id, data.model_dump(exclude_unset=True))


@router.post("/budgets/{budget_id}/usage", tags=["budget"], status_code=201)
def usage(
    budget_id: str,
    data: s.UsageInput,
    actor=Depends(require(privileged=True)),
    svc=Depends(services),
):
    return svc.budgets.consume(actor, budget_id, data.model_dump())


@router.get("/budgets/{budget_id}/usage", tags=["budget"])
def usages(
    budget_id: str,
    project_id: str | None = None,
    actor=Depends(require("budgets:read")),
    svc=Depends(services),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with svc.store.transaction() as db:
        check_budget_owner(actor, require_record(db, "budget", budget_id))
        return db.many(
            "budget_usage",
            budget_id=budget_id,
            limit=limit,
            offset=offset,
            **({"project_id": project_id} if project_id else {}),
        )
