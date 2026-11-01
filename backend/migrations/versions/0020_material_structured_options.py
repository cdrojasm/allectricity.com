"""Persist typed, versioned engineering options for material catalog items."""

from alembic import op
import sqlalchemy as sa


revision = "0020_material_structured_options"
down_revision = "0019_constraint_profiles"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("material_catalog_items")}
    if "structured_options" not in columns:
        op.add_column("material_catalog_items", sa.Column("structured_options", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("material_catalog_items")}
    if "structured_options" in columns:
        op.drop_column("material_catalog_items", "structured_options")
