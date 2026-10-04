"""Add project chat messages, contents and project-bound uploads."""

from alembic import op
from sqlalchemy import Column, ForeignKey, String, inspect
from src.infrastructure.persistence.identity_schema import conversations, chat_messages, message_contents

revision = "0004_project_chat"
down_revision = "0003_projects"
branch_labels = None
depends_on = None


def has_column(inspector, table, name):
    return inspector.has_table(table) and any(
        column["name"] == name for column in inspector.get_columns(table)
    )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not has_column(inspector, "file_uploads", "project_id"):
        op.add_column("file_uploads", Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True))
        op.create_index("ix_file_uploads_project_id", "file_uploads", ["project_id"])
    if not has_column(inspector, "file_uploads", "filename"):
        op.add_column("file_uploads", Column("filename", String(180), nullable=True))
    if inspector.has_table("chat_messages") and not has_column(inspector, "chat_messages", "task_id"):
        op.add_column("chat_messages", Column("task_id", String(36), nullable=True))
    for table in (conversations, chat_messages, message_contents):
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    message_contents.drop(bind, checkfirst=True)
    chat_messages.drop(bind, checkfirst=True)
    conversations.drop(bind, checkfirst=True)
    inspector = inspect(bind)
    if has_column(inspector, "file_uploads", "filename"):
        op.drop_column("file_uploads", "filename")
    if has_column(inspector, "file_uploads", "project_id"):
        op.drop_index("ix_file_uploads_project_id", table_name="file_uploads")
        op.drop_column("file_uploads", "project_id")
    if has_column(inspector, "chat_messages", "task_id"):
        op.drop_column("chat_messages", "task_id")
