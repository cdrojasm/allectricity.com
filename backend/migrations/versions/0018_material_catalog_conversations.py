"""Persist material assistant conversations by project."""

from alembic import op
from sqlalchemy import BigInteger, Column, ForeignKey, JSON, String, inspect


revision = "0018_catalog_chat"
down_revision = "0017_material_discovery_jobs"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("material_catalog_conversations"):
        op.create_table(
            "material_catalog_conversations",
            Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
            Column("owner_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("messages", JSON, nullable=False),
            Column("updated_at", BigInteger, nullable=False),
        )
        op.create_index("ix_material_catalog_conversations_owner_id", "material_catalog_conversations", ["owner_id"])


def downgrade():
    op.drop_table("material_catalog_conversations")
