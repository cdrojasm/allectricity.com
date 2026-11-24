"""Persist reusable owner-scoped quotation templates."""

from alembic import op

from src.infrastructure.persistence.quotation_repository import quotation_templates


revision = "0032_quotation_templates"
down_revision = "0031_quotations"
branch_labels = None
depends_on = None


def upgrade():
    quotation_templates.create(op.get_bind(), checkfirst=True)


def downgrade():
    quotation_templates.drop(op.get_bind(), checkfirst=True)
