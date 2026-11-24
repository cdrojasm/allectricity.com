"""Remove raw webhook bodies; reconciliation uses normalized event fields only."""

from alembic import op
import sqlalchemy as sa

revision = "0027_scrub_billing_payload"
down_revision = "0026_study_argon2_hashes"
branch_labels = None
depends_on = None


def upgrade():
    events = sa.table("billing_webhook_events", sa.column("payload", sa.JSON))
    op.get_bind().execute(sa.update(events).values(payload={}))


def downgrade():
    # The original notification bodies are intentionally unrecoverable after scrubbing.
    pass
