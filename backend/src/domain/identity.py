from dataclasses import dataclass


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str
    kind: str
    roles: frozenset[str]
    permissions: frozenset[str]

    @property
    def privileged(self) -> bool:
        return "super_admin" in self.roles or (
            self.kind == "m2m" and "m2m" in self.roles
        )


PERMISSIONS = frozenset(
    {
        "users:read",
        "users:write",
        "designs:read",
        "designs:write",
        "budgets:read",
        "budgets:write",
        "budget_usage:write",
        "files:read",
        "files:write",
    }
)
BUILTIN_ROLES = {
    "super_admin": PERMISSIONS,
    "m2m": PERMISSIONS,
    "user_admin": frozenset({"users:read", "users:write"}),
    "designer": frozenset({"designs:read", "designs:write", "budgets:read", "files:read", "files:write"}),
    "viewer": frozenset({"designs:read", "budgets:read", "files:read"}),
}
