"""Track quarantined uploads."""

from alembic import op
from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, String, inspect

revision = "0002_file_uploads"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 builds from the current metadata during a fresh install, so it may
    # already have created this table before Alembic reaches this revision.
    if inspect(op.get_bind()).has_table("file_uploads"):
        return
    op.create_table(
        "file_uploads",
        Column("id", String(36), primary_key=True),
        Column("owner_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        Column("quarantine_key", String(512), nullable=False, unique=True),
        Column("target_bucket", String(63), nullable=False),
        Column("object_key", String(512), nullable=False),
        Column("expected_mime", String(120), nullable=False),
        Column("status", String(20), nullable=False),
        Column("created_at", BigInteger, nullable=False),
        Column("updated_at", BigInteger, nullable=False),
        CheckConstraint("status IN ('pending', 'scanning', 'available', 'rejected', 'failed')", name="ck_file_upload_status"),
    )


def downgrade():
    op.drop_table("file_uploads")
