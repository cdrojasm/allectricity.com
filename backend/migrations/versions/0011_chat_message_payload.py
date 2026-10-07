"""Structured payload on chat messages (artifact.updated notifications for the client) and a
millisecond creation time to order messages created within the same second."""

from alembic import op
from sqlalchemy import JSON, BigInteger, Column, inspect

revision = "0011_chat_message_payload"
down_revision = "0010_agent_runs"
branch_labels = None
depends_on = None


def has_column(inspector, table, name):
    return inspector.has_table(table) and any(
        column["name"] == name for column in inspector.get_columns(table)
    )


COLUMNS = (("payload", JSON), ("created_ms", BigInteger))


def upgrade():
    inspector = inspect(op.get_bind())
    for name, kind in COLUMNS:
        if not has_column(inspector, "chat_messages", name):
            op.add_column("chat_messages", Column(name, kind, nullable=True))


def downgrade():
    inspector = inspect(op.get_bind())
    for name, _ in COLUMNS:
        if has_column(inspector, "chat_messages", name):
            op.drop_column("chat_messages", name)
