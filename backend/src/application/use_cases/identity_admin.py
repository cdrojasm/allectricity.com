import secrets
from src.application.use_cases.identity import (
    uid,
    now,
    public_user,
    new_user,
    assign,
    audit,
    revoke_sessions,
    invalidate_resets,
)
from src.domain.identity import ServiceError, PERMISSIONS


def require_record(db, table, record_id):
    record = db.one(table, id=record_id)
    if not record:
        raise ServiceError(404, "Record not found")
    return record


def privileged(actor):
    if not actor.privileged:
        raise ServiceError(403, "Requires super_admin or an authorized M2M principal")


def protect_last_admin(db, user_id):
    if not db.one("user_roles", user_id=user_id, role_id="super_admin"):
        return
    for assignment in db.many("user_roles", role_id="super_admin"):
        user = db.one("users", id=assignment["user_id"])
        if user["id"] != user_id and user["active"] and user["kind"] == "human":
            return
    raise ServiceError(
        409, "Cannot remove or deactivate the last active human super administrator"
    )


class IdentityAdmin:
    def __init__(self, store, passwords):
        self.store, self.passwords = store, passwords

    def bootstrap(self, email, password, first_name):
        with self.store.transaction(write=True) as db:
            if db.one("user_roles", role_id="super_admin"):
                raise ServiceError(409, "A super administrator already exists")
            if db.one("users", email=email.lower()):
                raise ServiceError(409, "Email already exists")
            user = new_user(
                db,
                email=email,
                first_name=first_name,
                password_hash=self.passwords.hash(password),
            )
            assign(db, user["id"], "super_admin")
            audit(db, user["id"], "bootstrap", user["id"])
            return public_user(user)

    def create_user(self, actor, data):
        with self.store.transaction(write=True) as db:
            if db.one("users", email=data["email"].lower()):
                raise ServiceError(409, "Email already exists")
            user = new_user(
                db,
                email=data["email"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                password_hash=self.passwords.hash(data["password"]),
                phone=data["phone"],
                locale=data["locale"],
                timezone=data["timezone"],
            )
            assign(db, user["id"], "viewer")
            audit(db, actor.user_id, "users.create", user["id"])
            return public_user(user)

    def update_user(self, actor, user_id, data):
        with self.store.transaction(write=True) as db:
            user = require_record(db, "users", user_id)
            sensitive = user["kind"] == "m2m" or any(
                a["role_id"] in {"super_admin", "m2m"}
                for a in db.many("user_roles", user_id=user_id)
            )
            if sensitive:
                privileged(actor)
            if "email" in data:
                if user["idp_provider"] != "local":
                    raise ServiceError(
                        409, "Identity-provider email cannot be changed here"
                    )
                email = data["email"].lower()
                existing = db.one("users", email=email)
                if existing and existing["id"] != user_id:
                    raise ServiceError(409, "Email already exists")
                data = {**data, "email": email, "email_verified": False}
                invalidate_resets(db, user_id)
                revoke_sessions(db, user_id)
            if data.get("active") is False:
                protect_last_admin(db, user_id)
                revoke_sessions(db, user_id)
                invalidate_resets(db, user_id)
            db.change("users", user_id, **data, updated_at=now())
            audit(db, actor.user_id, "users.update", user_id)
            return public_user(require_record(db, "users", user_id))

    def create_client(self, actor, name, email):
        privileged(actor)
        secret = secrets.token_urlsafe(48)
        with self.store.transaction(write=True) as db:
            if db.one("users", email=email.lower()):
                raise ServiceError(409, "Email already exists")
            user = new_user(
                db,
                email=email,
                first_name=name,
                kind="m2m",
                password_hash=self.passwords.hash(secret),
            )
            assign(db, user["id"], "m2m")
            audit(db, actor.user_id, "m2m.create", user["id"])
            return {
                "client_id": user["id"],
                "client_secret": secret,
                "user": public_user(user),
            }

    def rotate_client(self, actor, user_id):
        privileged(actor)
        secret = secrets.token_urlsafe(48)
        with self.store.transaction(write=True) as db:
            user = require_record(db, "users", user_id)
            if user["kind"] != "m2m":
                raise ServiceError(400, "Not an M2M client")
            db.change(
                "users",
                user_id,
                password_hash=self.passwords.hash(secret),
                updated_at=now(),
            )
            revoke_sessions(db, user_id)
            audit(db, actor.user_id, "m2m.rotate", user_id)
        return {"client_id": user_id, "client_secret": secret}

    def role(self, actor, data, role_id=None):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            if role_id and require_record(db, "roles", role_id)["builtin"]:
                raise ServiceError(409, "Built-in roles cannot be modified")
            if set(data["permissions"]) - PERMISSIONS:
                raise ServiceError(422, "Unknown permission")
            duplicate = db.one("roles", name=data["name"])
            if duplicate and duplicate["id"] != role_id:
                raise ServiceError(409, "Role name already exists")
            values = {"name": data["name"], "description": data["description"]}
            if role_id:
                db.change("roles", role_id, **values)
                for grant in db.many("role_permissions", role_id=role_id):
                    db.remove("role_permissions", grant["id"])
            else:
                role_id = uid()
                db.add("roles", id=role_id, builtin=False, **values)
            for permission in set(data["permissions"]):
                db.add(
                    "role_permissions",
                    id=uid(),
                    role_id=role_id,
                    permission_id=permission,
                )
            audit(db, actor.user_id, "roles.save", role_id)
            return {"id": role_id, **data, "builtin": False}

    def delete_role(self, actor, role_id):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            role = require_record(db, "roles", role_id)
            if role["builtin"] or db.one("user_roles", role_id=role_id):
                raise ServiceError(409, "Cannot delete a built-in or assigned role")
            db.remove("roles", role_id)
            audit(db, actor.user_id, "roles.delete", role_id)

    def assign_role(self, actor, user_id, role_id):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            user = require_record(db, "users", user_id)
            role = require_record(db, "roles", role_id)
            if (role["name"] == "m2m" and user["kind"] != "m2m") or (
                role["name"] == "super_admin" and user["kind"] != "human"
            ):
                raise ServiceError(400, "Role is incompatible with principal type")
            if db.one("user_roles", user_id=user_id, role_id=role_id):
                raise ServiceError(409, "Role already assigned")
            result = assign(db, user_id, role_id)
            audit(db, actor.user_id, "user_roles.create", result["id"])
            return result

    def unassign_role(self, actor, assignment_id):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            row = require_record(db, "user_roles", assignment_id)
            if row["role_id"] == "super_admin":
                protect_last_admin(db, row["user_id"])
            db.remove("user_roles", assignment_id)
            audit(db, actor.user_id, "user_roles.delete", assignment_id)
