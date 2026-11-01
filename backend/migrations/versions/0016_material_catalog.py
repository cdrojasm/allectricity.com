"""Persist project material catalog entries and immutable quote history."""

from alembic import op

from src.infrastructure.persistence.material_catalog_repository import (
    material_catalog_items,
    material_catalog_versions,
)

revision = "0016_material_catalog"
down_revision = "0015_studies"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    material_catalog_items.create(bind, checkfirst=True)
    material_catalog_versions.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    material_catalog_versions.drop(bind, checkfirst=True)
    material_catalog_items.drop(bind, checkfirst=True)
