"""Background jobs for slow requests (LLM calls, plan rasterizing, soil fits)."""

from alembic import op

from src.infrastructure.persistence.identity_schema import async_jobs


revision = "0024_async_jobs"
down_revision = "0023_billing_subscriptions"
branch_labels = None
depends_on = None


def upgrade():
    async_jobs.create(op.get_bind(), checkfirst=True)


def downgrade():
    async_jobs.drop(op.get_bind(), checkfirst=True)
