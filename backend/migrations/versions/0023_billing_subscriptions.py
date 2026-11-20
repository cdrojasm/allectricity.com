"""Subscriptions (Mercado Pago or license) and single-use license codes."""

from alembic import op

from src.infrastructure.persistence.identity_schema import billing_licenses, billing_subscriptions


revision = "0023_billing_subscriptions"  # alembic_version is VARCHAR(32)
down_revision = "0022_billing_webhook_events"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    billing_subscriptions.create(bind, checkfirst=True)
    billing_licenses.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    billing_licenses.drop(bind, checkfirst=True)
    billing_subscriptions.drop(bind, checkfirst=True)
