"""Add grounding design agent runs, progress events and conversation memory.

Earlier revisions create chat_messages and artefacto_diseno_tierras from the current
schema, so fresh databases already have the new columns; existing ones get them here.
"""

from alembic import op
from sqlalchemy import JSON, Column, String, inspect
from src.infrastructure.persistence.identity_schema import (
    agent_conversation_state,
    agent_events,
    agent_runs,
)

revision = "0010_agent_runs"
down_revision = "0009_builtin_role_grants"
branch_labels = None
depends_on = None

MESSAGE_STATUS = "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')"
PREVIOUS_MESSAGE_STATUS = "status IN ('pending', 'processing', 'completed', 'failed')"


def has_column(inspector, table, name):
    return inspector.has_table(table) and any(
        column["name"] == name for column in inspector.get_columns(table)
    )


def _message_status_check(condition):
    # SQLite cannot alter CHECK constraints in place; fresh SQLite databases already get
    # the current constraint from revision 0004.
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_chat_message_status", "chat_messages", type_="check")
        op.create_check_constraint("ck_chat_message_status", "chat_messages", condition)


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not has_column(inspector, "chat_messages", "run_id"):
        op.add_column("chat_messages", Column("run_id", String(36), nullable=True))
        op.create_index("ix_chat_messages_run_id", "chat_messages", ["run_id"])
        _message_status_check(MESSAGE_STATUS)
    if not has_column(inspector, "artefacto_diseno_tierras", "origin"):
        op.add_column("artefacto_diseno_tierras", Column("origin", JSON, nullable=True))
    for table in (agent_runs, agent_events, agent_conversation_state):
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in (agent_conversation_state, agent_events, agent_runs):
        table.drop(bind, checkfirst=True)
    inspector = inspect(bind)
    if has_column(inspector, "artefacto_diseno_tierras", "origin"):
        op.drop_column("artefacto_diseno_tierras", "origin")
    if has_column(inspector, "chat_messages", "run_id"):
        op.execute("UPDATE chat_messages SET status = 'failed' WHERE status = 'cancelled'")
        _message_status_check(PREVIOUS_MESSAGE_STATUS)
        op.drop_index("ix_chat_messages_run_id", table_name="chat_messages")
        op.drop_column("chat_messages", "run_id")
