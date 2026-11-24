"""Persist user-declared BOM surplus per project design version."""

from alembic import op

from src.infrastructure.persistence.bom_adjustment_repository import bom_adjustments


revision = "0030_bom_adjustments"
down_revision = "0029_catalog_provenance"
branch_labels = None
depends_on = None


def upgrade():
    bom_adjustments.create(op.get_bind(), checkfirst=True)


def downgrade():
    bom_adjustments.drop(op.get_bind(), checkfirst=True)
