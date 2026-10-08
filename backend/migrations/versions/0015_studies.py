"""Persist shareable studies pinned to immutable artifact versions."""

from alembic import op
from sqlalchemy import BigInteger, Column, ForeignKey, JSON, String, Text, inspect

revision = "0015_studies"
down_revision = "0014_project_context_memory"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("studies"):
        op.create_table(
            "studies",
            Column("id", String(36), primary_key=True),
            Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            Column("owner_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("slug", String(120), nullable=False, unique=True),
            Column("artifact_id", String(36), nullable=False),
            Column("artifact_version", BigInteger, nullable=False),
            Column("title", String(240), nullable=False),
            Column("access", String(20), nullable=False),
            Column("status", String(20), nullable=False),
            Column("config", JSON, nullable=False),
            Column("password_hash", String(64)),
            Column("expires_at", BigInteger),
            Column("published_at", BigInteger),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=False),
            Column("pdf_key", String(512)),
            Column("pdf_status", String(20), nullable=False, server_default="none"),
            Column("pdf_error", Text),
            Column("pdf_updated_at", BigInteger),
        )
        op.create_index("ix_studies_project_id", "studies", ["project_id"])
        op.create_index("ix_studies_owner_id", "studies", ["owner_id"])
    else:
        existing = {column["name"] for column in inspect(op.get_bind()).get_columns("studies")}
        for name, column in (("pdf_key", String(512)), ("pdf_status", String(20)), ("pdf_error", Text), ("pdf_updated_at", BigInteger)):
            if name not in existing:
                op.add_column("studies", Column(name, column, nullable=name != "pdf_status", server_default="none" if name == "pdf_status" else None))


def downgrade():
    op.drop_table("studies")
