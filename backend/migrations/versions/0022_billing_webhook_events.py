"""Inbox of Mercado Pago webhook notifications (subscriptions and payments)."""

from alembic import op

from src.infrastructure.persistence.identity_schema import billing_webhook_events


revision = "0022_billing_webhook_events"
down_revision = "0021_optimizer_runs"
branch_labels = None
depends_on = None


def upgrade():
    billing_webhook_events.create(op.get_bind(), checkfirst=True)


def downgrade():
    billing_webhook_events.drop(op.get_bind(), checkfirst=True)
