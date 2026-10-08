"""Add shared, provenance-linked long-term memory for project conversations."""

from alembic import op

from src.infrastructure.persistence.identity_schema import project_context_memory

revision = "0013_project_context_memory"
down_revision = "0012_upload_recovery"
branch_labels = None
depends_on = None


def upgrade():
    project_context_memory.create(op.get_bind(), checkfirst=True)


def downgrade():
    project_context_memory.drop(op.get_bind(), checkfirst=True)
