"""Persist OP-06 optimizer runs and feasible alternatives (OP-19)."""

from alembic import op

from src.infrastructure.persistence.identity_schema import optimizer_alternatives, optimizer_runs


revision = "0021_optimizer_runs"
down_revision = "0020_material_structured_options"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    optimizer_runs.create(bind, checkfirst=True)
    optimizer_alternatives.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    optimizer_alternatives.drop(bind, checkfirst=True)
    optimizer_runs.drop(bind, checkfirst=True)
