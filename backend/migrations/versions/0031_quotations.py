"""Persist grouped project quotations and immutable versions."""

from alembic import op

from src.infrastructure.persistence.quotation_repository import quotation_versions, quotations


revision = "0031_quotations"
down_revision = "0030_bom_adjustments"
branch_labels = None
depends_on = None


def upgrade():
    quotations.create(op.get_bind(), checkfirst=True)
    quotation_versions.create(op.get_bind(), checkfirst=True)


def downgrade():
    quotation_versions.drop(op.get_bind(), checkfirst=True)
    quotations.drop(op.get_bind(), checkfirst=True)
