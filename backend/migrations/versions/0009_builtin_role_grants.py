"""Seed permissions and built-in role grants added after 0001 (files:read, files:write).

0001 seeded the RBAC catalog from the code of its time, so databases created before the
file permissions existed never received them. Only missing rows are inserted; existing
permissions and grants are left untouched.
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
from sqlalchemy import select
from src.domain.identity import BUILTIN_ROLES, PERMISSIONS
from src.infrastructure.persistence.identity_schema import (
    permissions,
    role_permissions,
    roles,
)

revision = "0009_builtin_role_grants"
down_revision = "0008_calculos_potencial_tierras"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    known = set(bind.execute(select(permissions.c.id)).scalars())
    missing = sorted(PERMISSIONS - known)
    if missing:
        op.bulk_insert(permissions, [{"id": name, "name": name} for name in missing])
    existing_roles = set(bind.execute(select(roles.c.id)).scalars())
    granted = set(bind.execute(select(role_permissions.c.role_id,
                                      role_permissions.c.permission_id)).all())
    rows = [
        {"id": str(uuid5(NAMESPACE_URL, role + permission)), "role_id": role,
         "permission_id": permission}
        for role, grants in BUILTIN_ROLES.items() if role in existing_roles
        for permission in sorted(grants) if (role, permission) not in granted
    ]
    if rows:
        op.bulk_insert(role_permissions, rows)


def downgrade():
    # Los permisos sembrados pueden estar en uso; no se retiran.
    pass
