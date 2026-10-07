"""Track upload retries, errors, expiry and quarantine cleanup."""

from alembic import op
from sqlalchemy import BigInteger, Column, Text, inspect

revision = "0012_upload_recovery"
down_revision = "0011_chat_message_payload"
branch_labels = None
depends_on = None

CHECK = "status IN ('pending', 'scanning', 'available', 'rejected', 'failed', 'expired')"
PREVIOUS_CHECK = "status IN ('pending', 'scanning', 'available', 'rejected', 'failed')"
COLUMNS = (
    ("attempt_count", BigInteger, "0"),
    ("processing_started_at", BigInteger, None),
    ("last_error", Text, None),
    ("quarantine_deleted_at", BigInteger, None),
)


def _snapshot():
    inspector = inspect(op.get_bind())
    names = {column["name"] for column in inspector.get_columns("file_uploads")}
    checks = {check["name"]: check.get("sqltext", "") for check in inspector.get_check_constraints("file_uploads")}
    return names, checks


def upgrade():
    names, checks = _snapshot()
    has_new_check = "expired" in checks.get("ck_file_upload_status", "")
    needs_columns = any(name not in names for name, _, _ in COLUMNS)
    if op.get_bind().dialect.name == "sqlite":
        if needs_columns or not has_new_check:
            with op.batch_alter_table("file_uploads", recreate="always") as batch:
                for name, kind, default in COLUMNS:
                    if name not in names:
                        batch.add_column(Column(name, kind, nullable=default is None, server_default=default))
                if "ck_file_upload_status" in checks:
                    batch.drop_constraint("ck_file_upload_status", type_="check")
                batch.create_check_constraint("ck_file_upload_status", CHECK)
    else:
        for name, kind, default in COLUMNS:
            if name not in names:
                batch_kwargs = {"nullable": default is None}
                if default is not None:
                    batch_kwargs["server_default"] = default
                op.add_column("file_uploads", Column(name, kind, **batch_kwargs))
        if not has_new_check:
            if "ck_file_upload_status" in checks:
                op.drop_constraint("ck_file_upload_status", "file_uploads", type_="check")
            op.create_check_constraint("ck_file_upload_status", "file_uploads", CHECK)
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("file_uploads")}
    if "ix_file_uploads_status_updated" not in indexes:
        op.create_index("ix_file_uploads_status_updated", "file_uploads", ["status", "updated_at"])


def downgrade():
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("file_uploads")}
    if "ix_file_uploads_status_updated" in indexes:
        op.drop_index("ix_file_uploads_status_updated", table_name="file_uploads")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("UPDATE file_uploads SET status = 'failed' WHERE status = 'expired'")
        names, _ = _snapshot()
        with op.batch_alter_table("file_uploads", recreate="always") as batch:
            batch.drop_constraint("ck_file_upload_status", type_="check")
            batch.create_check_constraint("ck_file_upload_status", PREVIOUS_CHECK)
            for name, _, _ in reversed(COLUMNS):
                if name in names:
                    batch.drop_column(name)
    else:
        op.execute("UPDATE file_uploads SET status = 'failed' WHERE status = 'expired'")
        op.drop_constraint("ck_file_upload_status", "file_uploads", type_="check")
        op.create_check_constraint("ck_file_upload_status", "file_uploads", PREVIOUS_CHECK)
        names, _ = _snapshot()
        for name, _, _ in reversed(COLUMNS):
            if name in names:
                op.drop_column("file_uploads", name)
