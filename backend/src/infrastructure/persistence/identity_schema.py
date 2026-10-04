"""Relational schema v1. Changes require a new Alembic revision."""

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Text,
    BigInteger,
    Float,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    JSON,
    Index,
)

metadata = MetaData()


def key():
    return Column("id", String(36), primary_key=True)


users = Table(
    "users",
    metadata,
    key(),
    Column("email", String(320), nullable=False, unique=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("phone", String(40)),
    Column("locale", String(20), nullable=False),
    Column("timezone", String(100), nullable=False),
    Column("avatar_url", Text),
    Column("active", Boolean, nullable=False),
    Column("email_verified", Boolean, nullable=False),
    Column("kind", String(12), nullable=False),
    Column("password_hash", Text),
    Column("idp_provider", String(30), nullable=False),
    Column("idp_subject", String(255)),
    Column("idp_issuer", String(255)),
    Column("idp_metadata", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("last_login_at", BigInteger),
    UniqueConstraint("idp_provider", "idp_subject", name="uq_users_idp_subject"),
    CheckConstraint("kind IN ('human', 'm2m')", name="ck_users_kind"),
)
roles = Table(
    "roles",
    metadata,
    key(),
    Column("name", String(60), nullable=False, unique=True),
    Column("description", String(255), nullable=False),
    Column("builtin", Boolean, nullable=False),
)
permissions = Table(
    "permissions",
    metadata,
    key(),
    Column("name", String(60), nullable=False, unique=True),
)
role_permissions = Table(
    "role_permissions",
    metadata,
    key(),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
    Column("permission_id", ForeignKey("permissions.id"), nullable=False),
    UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
)
user_roles = Table(
    "user_roles",
    metadata,
    key(),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("role_id", ForeignKey("roles.id"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
)
auth_sessions = Table(
    "auth_sessions",
    metadata,
    key(),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("created_at", BigInteger, nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("revoked_at", BigInteger),
)
refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    key(),
    Column("session_id", ForeignKey("auth_sessions.id"), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", BigInteger, nullable=False),
    Column("consumed_at", BigInteger),
)
password_resets = Table(
    "password_resets",
    metadata,
    key(),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", BigInteger, nullable=False),
    Column("consumed_at", BigInteger),
)
mail_outbox = Table(
    "mail_outbox",
    metadata,
    key(),
    Column("reset_id", ForeignKey("password_resets.id"), nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("sent_at", BigInteger),
    Column("attempts", BigInteger, nullable=False),
    Column("available_at", BigInteger, nullable=False),
    Column("last_error", String(100)),
)
budget = Table(
    "budget",
    metadata,
    key(),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("total_tokens", BigInteger, nullable=False),
    Column("used_tokens", BigInteger, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    CheckConstraint(
        "total_tokens >= 0 AND used_tokens >= 0 AND used_tokens <= total_tokens",
        name="ck_budget_balance",
    ),
)
budget_usage = Table(
    "budget_usage",
    metadata,
    key(),
    Column("budget_id", ForeignKey("budget.id"), nullable=False, index=True),
    Column("actor_id", ForeignKey("users.id"), nullable=False),
    Column("project_id", String(100), nullable=False, index=True),
    Column("action", String(120), nullable=False),
    Column("model", String(120), nullable=False),
    Column("input_tokens", BigInteger, nullable=False),
    Column("output_tokens", BigInteger, nullable=False),
    Column("total_tokens", BigInteger, nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("budget_id", "idempotency_key", name="uq_usage_idempotency"),
    CheckConstraint(
        "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens = input_tokens + output_tokens AND total_tokens > 0",
        name="ck_usage_tokens",
    ),
)
audit_events = Table(
    "audit_events",
    metadata,
    key(),
    Column("actor_id", String(36)),
    Column("action", String(100), nullable=False),
    Column("target_id", String(128), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)
security_lock = Table(
    "security_lock", metadata, key(), Column("version", BigInteger, nullable=False)
)
file_uploads = Table(
    "file_uploads",
    metadata,
    key(),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("filename", String(180), nullable=False),
    Column("quarantine_key", String(512), nullable=False, unique=True),
    Column("target_bucket", String(63), nullable=False),
    Column("object_key", String(512), nullable=False),
    Column("expected_mime", String(120), nullable=False),
    Column("status", String(20), nullable=False),
    Column("ocr_confidence", Float),
    Column("ocr_low_confidence_ratio", Float),
    Column("ocr_needs_review", Boolean, nullable=False, server_default="false"),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('pending', 'scanning', 'available', 'rejected', 'failed')", name="ck_file_upload_status"),
)
projects = Table(
    "projects",
    metadata,
    key(),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(160), nullable=False),
    Column("description", Text, nullable=False),
    Column("project_type", String(40), nullable=False),
    Column("country", String(120)),
    Column("city", String(120)),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("attachments", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("project_type IN ('land')", name="ck_project_type"),
)
artefacto_diseno_tierras = Table(
    "artefacto_diseno_tierras",
    metadata,
    key(),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("artifact_id", String(36), nullable=False, index=True),
    Column("version", BigInteger, nullable=False),
    Column("name", String(160), nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("created_by", ForeignKey("users.id"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("artifact_id", "version", name="uq_artefacto_diseno_tierras_version"),
)
artefacto_diseno_tierras_counters = Table(
    "artefacto_diseno_tierras_counters",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("last_version", BigInteger, nullable=False),
)
calculos_potencial_tierras = Table(
    "calculos_potencial_tierras",
    metadata,
    key(),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("artifact_id", String(36), nullable=False, index=True),
    Column("artifact_version", BigInteger, nullable=False),
    Column("status", String(20), nullable=False),
    Column("parameters", JSON, nullable=False),
    Column("result", JSON),
    Column("trace", JSON),
    Column("error", Text),
    Column("created_by", ForeignKey("users.id"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint(
        "status IN ('pending', 'running', 'completed', 'failed', 'rejected', 'cancelled')",
        name="ck_calculo_potencial_status",
    ),
)
conversations = Table(
    "conversations",
    metadata,
    key(),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("created_by", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", String(200)),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)
chat_messages = Table(
    "chat_messages",
    metadata,
    key(),
    Column("conversation_id", ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("source", String(20), nullable=False),
    Column("text", Text, nullable=False),
    Column("type", String(20), nullable=False),
    Column("generated_at", BigInteger, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("status", String(20), nullable=False),
    Column("task_id", String(36)),
    CheckConstraint("source IN ('agent', 'user', 'notification')", name="ck_chat_message_source"),
    CheckConstraint("type IN ('text', 'image', 'audio', 'file')", name="ck_chat_message_type"),
    CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_chat_message_status"),
)
message_contents = Table(
    "message_contents",
    metadata,
    key(),
    Column("message_id", ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("format", String(20), nullable=False),
    Column("upload_id", ForeignKey("file_uploads.id", ondelete="RESTRICT"), nullable=False, unique=True),
    Column("filename", String(180), nullable=False),
    Column("mime_type", String(120), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    CheckConstraint("format IN ('image', 'file')", name="ck_message_content_format"),
)
rate_limits = Table(
    "rate_limits",
    metadata,
    key(),
    Column("bucket", String(64), nullable=False, unique=True),
    Column("window_start", BigInteger, nullable=False),
    Column("attempts", BigInteger, nullable=False),
)
Index("ix_outbox_pending", mail_outbox.c.sent_at, mail_outbox.c.available_at)
TABLES = {table.name: table for table in metadata.tables.values()}
