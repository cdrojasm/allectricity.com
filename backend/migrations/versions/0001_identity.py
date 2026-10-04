"""Identity, RBAC, sessions, mail outbox and token accounting schema v1."""

from alembic import op
from src.infrastructure.persistence.identity_schema import (
    metadata,
    security_lock,
    roles,
    permissions,
    role_permissions,
)
from src.domain.identity import BUILTIN_ROLES, PERMISSIONS

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())
    op.bulk_insert(security_lock, [{"id": "identity", "version": 0}])
    for permission in sorted(PERMISSIONS):
        op.bulk_insert(permissions, [{"id": permission, "name": permission}])
    for name, grants in BUILTIN_ROLES.items():
        op.bulk_insert(
            roles, [{"id": name, "name": name, "description": name, "builtin": True}]
        )
        for permission in sorted(grants):
            # Stable identifiers; max length 36 for cross-database portability.
            from uuid import uuid5, NAMESPACE_URL

            op.bulk_insert(
                role_permissions,
                [
                    {
                        "id": str(uuid5(NAMESPACE_URL, name + permission)),
                        "role_id": name,
                        "permission_id": permission,
                    }
                ],
            )


def downgrade():
    metadata.drop_all(op.get_bind())
