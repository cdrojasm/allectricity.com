"""Persist async material discovery jobs."""

from alembic import op
from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, JSON, String, Text, inspect


revision = "0017_material_discovery_jobs"
down_revision = "0016_material_catalog"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("material_discovery_jobs"):
        op.create_table(
            "material_discovery_jobs",
            Column("id", String(36), primary_key=True),
            Column("owner_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("status", String(20), nullable=False),
            Column("request", JSON, nullable=False),
            Column("result", JSON),
            Column("error", Text),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=False),
            CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_material_discovery_status"),
        )
        op.create_index("ix_material_discovery_jobs_owner_id", "material_discovery_jobs", ["owner_id"])


def downgrade():
    op.drop_table("material_discovery_jobs")
