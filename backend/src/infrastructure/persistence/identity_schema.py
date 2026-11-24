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
    ForeignKeyConstraint,
    UniqueConstraint,
    CheckConstraint,
    JSON,
    Index,
    text,
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
    Column("attempt_count", BigInteger, nullable=False, server_default="0"),
    Column("processing_started_at", BigInteger),
    Column("last_error", Text),
    Column("quarantine_deleted_at", BigInteger),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('pending', 'scanning', 'available', 'rejected', 'failed', 'expired')", name="ck_file_upload_status"),
)
Index("ix_file_uploads_status_updated", file_uploads.c.status, file_uploads.c.updated_at)
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
    # {"kind": "user" | "agent", "run_id", "summary", "provenance": {path: {kind, ref}}}
    Column("origin", JSON),
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
studies = Table(
    "studies",
    metadata,
    key(),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("slug", String(120), nullable=False, unique=True),
    Column("artifact_id", String(36), nullable=False),
    Column("artifact_version", BigInteger, nullable=False),
    Column("title", String(240), nullable=False),
    Column("access", String(20), nullable=False),
    Column("status", String(20), nullable=False),
    Column("config", JSON, nullable=False),
    Column("password_hash", String(255)),
    Column("expires_at", BigInteger),
    Column("published_at", BigInteger),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("pdf_key", String(512)),
    Column("pdf_status", String(20), nullable=False, server_default="none"),
    Column("pdf_error", Text),
    Column("pdf_updated_at", BigInteger),
    CheckConstraint("access IN ('public', 'link', 'password')", name="ck_study_access"),
    CheckConstraint("status IN ('draft', 'published', 'revoked')", name="ck_study_status"),
    UniqueConstraint("project_id", "slug", name="uq_study_project_slug"),
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
    # Agent run that produced or consumed the message. No FK: agent_runs references
    # chat_messages and is created by a later revision.
    Column("run_id", String(36), index=True),
    # Structured data for the client, e.g. {"kind": "artifact.updated", "artifact_id", "version", ...}.
    Column("payload", JSON),
    # Millisecond creation time: orders messages created within the same second.
    Column("created_ms", BigInteger),
    CheckConstraint("source IN ('agent', 'user', 'notification')", name="ck_chat_message_source"),
    CheckConstraint("type IN ('text', 'image', 'audio', 'file')", name="ck_chat_message_type"),
    CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')", name="ck_chat_message_status"),
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
AGENT_RUN_STATUSES = ("'queued', 'running', 'waiting_user', 'waiting_calculation', "
                      "'cancelling', 'completed', 'failed', 'cancelled'")
AGENT_ACTIVE_FILTER = "status NOT IN ('completed', 'failed', 'cancelled')"
AGENT_MODES = "'consulta', 'asistido', 'autonomo'"
agent_runs = Table(
    "agent_runs",
    metadata,
    key(),
    Column("conversation_id", ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("trigger_message_id", ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
    Column("artifact_id", String(36)),
    Column("base_version", BigInteger),
    Column("mode", String(20), nullable=False),
    Column("status", String(24), nullable=False),
    Column("plan", JSON, nullable=False),
    Column("current_step", String(80)),
    Column("draft_snapshot", JSON),
    Column("pending_calculation_id", String(36)),
    Column("pending_question", JSON),
    Column("inbox", JSON, nullable=False),
    Column("usage", JSON, nullable=False),
    Column("error", Text),
    Column("created_by", ForeignKey("users.id"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger),
    CheckConstraint(f"status IN ({AGENT_RUN_STATUSES})", name="ck_agent_run_status"),
    CheckConstraint(f"mode IN ({AGENT_MODES})", name="ck_agent_run_mode"),
)
# At most one non-terminal run per conversation.
Index("uq_agent_runs_active", agent_runs.c.conversation_id, unique=True,
      postgresql_where=text(AGENT_ACTIVE_FILTER), sqlite_where=text(AGENT_ACTIVE_FILTER))
agent_events = Table(
    "agent_events",
    metadata,
    key(),
    Column("conversation_id", ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("run_id", ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("seq", BigInteger, nullable=False),
    Column("type", String(40), nullable=False),
    Column("level", String(12), nullable=False),
    Column("title", String(200), nullable=False),
    Column("detail", Text),
    Column("payload", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("conversation_id", "seq", name="uq_agent_event_seq"),
    CheckConstraint("level IN ('info', 'progress', 'warning', 'error', 'success')", name="ck_agent_event_level"),
)
agent_conversation_state = Table(
    "agent_conversation_state",
    metadata,
    Column("id", ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("artifact_id", String(36)),
    Column("mode", String(20), nullable=False),
    Column("summary", Text, nullable=False),
    Column("assumptions", JSON, nullable=False),
    Column("open_questions", JSON, nullable=False),
    Column("decisions", JSON, nullable=False),
    Column("last_event_seq", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint(f"mode IN ({AGENT_MODES})", name="ck_agent_state_mode"),
)
project_context_memory = Table(
    "project_context_memory",
    metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("summary", Text, nullable=False),
    Column("items", JSON, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)
material_discovery_jobs = Table(
    "material_discovery_jobs",
    metadata,
    key(),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("status", String(20), nullable=False),
    Column("request", JSON, nullable=False),
    Column("result", JSON),
    Column("error", Text),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_material_discovery_status"),
)
# Slow requests the API accepts with 202 and a worker finishes (src/domain/jobs.py holds the lifecycle).
async_jobs = Table(
    "async_jobs",
    metadata,
    key(),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), index=True),
    Column("kind", String(40), nullable=False),
    Column("status", String(20), nullable=False),
    Column("request", JSON, nullable=False),
    Column("result", JSON),
    Column("error", Text),
    # The HTTP status the synchronous endpoint used to answer with (402 budget, 422 bad input, 502 provider…).
    Column("error_code", BigInteger),
    Column("created_at", BigInteger, nullable=False),
    Column("started_at", BigInteger),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_async_jobs_status"),
)
material_catalog_conversations = Table(
    "material_catalog_conversations",
    metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("owner_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("messages", JSON, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)
optimizer_runs = Table(
    "optimizer_runs",
    metadata,
    key(),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    # Artifact versions are immutable but use a composite identity in the artifact table,
    # so keep this reference as a snapshot instead of an incomplete foreign key.
    Column("artifact_id", String(36), nullable=False),
    Column("artifact_version", BigInteger, nullable=False),
    Column("status", String(20), nullable=False),
    # Freeze the resolved context, selected profile/domain/catalog versions, and search config.
    Column("request_snapshot", JSON, nullable=False),
    Column("result_summary", JSON),
    Column("error", Text),
    Column("created_by", ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'rejected', 'cancelled')",
                    name="ck_optimizer_run_status"),
    CheckConstraint("artifact_version > 0", name="ck_optimizer_run_artifact_version"),
    UniqueConstraint("project_id", "id", name="uq_optimizer_run_project_id"),
)
Index("ix_optimizer_runs_project_created", optimizer_runs.c.project_id,
      optimizer_runs.c.created_at.desc(), optimizer_runs.c.id)
optimizer_alternatives = Table(
    "optimizer_alternatives",
    metadata,
    key(),
    Column("run_id", String(36), nullable=False),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("candidate_sha256", String(64), nullable=False),
    # Rank is optional because mixed currencies cannot be compared without an explicit policy.
    Column("rank", BigInteger),
    Column("recommended", Boolean, nullable=False, server_default="false"),
    Column("candidate_snapshot", JSON, nullable=False),
    Column("evaluation_snapshot", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    ForeignKeyConstraint(
        ["project_id", "run_id"],
        ["optimizer_runs.project_id", "optimizer_runs.id"],
        ondelete="CASCADE",
        name="fk_optimizer_alternative_project_run",
    ),
    UniqueConstraint("run_id", "candidate_sha256", name="uq_optimizer_alternative_candidate"),
    UniqueConstraint("run_id", "rank", name="uq_optimizer_alternative_rank"),
    CheckConstraint("rank IS NULL OR rank > 0", name="ck_optimizer_alternative_rank"),
)
Index("ix_optimizer_alternatives_run_rank", optimizer_alternatives.c.run_id,
      optimizer_alternatives.c.rank)
rate_limits = Table(
    "rate_limits",
    metadata,
    key(),
    Column("bucket", String(64), nullable=False, unique=True),
    Column("window_start", BigInteger, nullable=False),
    Column("attempts", BigInteger, nullable=False),
)
Index("ix_outbox_pending", mail_outbox.c.sent_at, mail_outbox.c.available_at)
# Inbox of Mercado Pago notifications: the webhook stores the event and answers at once; the billing worker
# re-reads the notified resource from the API. `dedup_key` makes a redelivered notification a no-op.
billing_webhook_events = Table(
    "billing_webhook_events",
    metadata,
    key(),
    Column("provider", String(20), nullable=False),
    Column("mode", String(10), nullable=False),
    Column("dedup_key", String(64), nullable=False),
    Column("topic", String(60), nullable=False),
    Column("action", String(60)),
    Column("resource_id", String(64)),
    Column("notification_id", String(64)),
    Column("request_id", String(128)),
    Column("live_mode", Boolean),
    Column("payload", JSON, nullable=False),
    Column("status", String(12), nullable=False),
    Column("attempts", BigInteger, nullable=False, server_default="0"),
    Column("resource_status", String(40)),
    Column("resource", JSON),
    Column("last_error", Text),
    Column("received_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("processed_at", BigInteger),
    UniqueConstraint("provider", "mode", "dedup_key", name="uq_billing_webhook_event_dedup"),
    CheckConstraint("mode IN ('test', 'prod')", name="ck_billing_webhook_event_mode"),
    CheckConstraint("status IN ('received', 'fetched', 'ignored', 'failed')",
                    name="ck_billing_webhook_event_status"),
)
Index("ix_billing_webhook_events_pending", billing_webhook_events.c.status,
      billing_webhook_events.c.updated_at)
Index("ix_billing_webhook_events_resource", billing_webhook_events.c.topic,
      billing_webhook_events.c.resource_id)
# A user's right to a tier, paid through Mercado Pago or granted by a license code. Its token budget uses the
# same id (budget.id = subscription.id), so each monthly charge resets exactly that budget.
billing_subscriptions = Table(
    "billing_subscriptions",
    metadata,
    key(),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("provider", String(20), nullable=False),
    Column("mode", String(10)),
    Column("tier", String(40), nullable=False),
    Column("plan_id", String(64)),
    Column("provider_ref", String(64)),
    Column("status", String(12), nullable=False),
    Column("period_end", BigInteger),
    Column("grace_until", BigInteger),
    Column("ends_at", BigInteger),
    Column("last_reset_at", BigInteger),
    Column("last_payment_ref", String(64)),
    Column("replaces_id", String(36)),
    Column("error", Text),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    UniqueConstraint("provider", "provider_ref", name="uq_billing_subscription_provider_ref"),
    CheckConstraint("provider IN ('mercadopago', 'license')", name="ck_billing_subscription_provider"),
    CheckConstraint("status IN ('pending', 'authorized', 'past_due', 'cancelled', 'suspended', 'expired', "
                    "'replaced', 'failed')", name="ck_billing_subscription_status"),
)
Index("ix_billing_subscriptions_status", billing_subscriptions.c.status, billing_subscriptions.c.updated_at)
# One code per person, single use. Only a hash of the code is stored; the plain code is shown once at creation.
billing_licenses = Table(
    "billing_licenses",
    metadata,
    key(),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("code_hint", String(8), nullable=False),
    Column("tier", String(40), nullable=False),
    Column("months", BigInteger, nullable=False),
    Column("note", String(200)),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", BigInteger, nullable=False),
    Column("redeem_before", BigInteger),
    Column("redeemed_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("redeemed_at", BigInteger),
    Column("revoked_at", BigInteger),
    CheckConstraint("months > 0", name="ck_billing_license_months"),
)
TABLES ={table.name: table for table in metadata.tables.values()}
