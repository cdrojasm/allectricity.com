"""Allow personal catalog entries and store source-aware contact fields."""

import sqlalchemy as sa
from alembic import op


revision = "0029_catalog_provenance"
down_revision = "0028_service_catalog_details"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in ("material_catalog_items", "material_catalog_versions"):
        columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table)}
        if columns["project_id"]["nullable"] is False:
            with op.batch_alter_table(table) as batch:
                batch.alter_column("project_id", existing_type=sa.String(36), nullable=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("material_catalog_items")}
    for name in ("contact_data", "availability", "field_provenance"):
        if name not in columns:
            op.add_column("material_catalog_items", sa.Column(name, sa.JSON(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("material_catalog_items")}
    if "ix_material_catalog_personal_owner" not in indexes:
        op.create_index("ix_material_catalog_personal_owner", "material_catalog_items", ["created_by", "status"])


def downgrade():
    op.drop_index("ix_material_catalog_personal_owner", table_name="material_catalog_items")
    for name in ("field_provenance", "availability", "contact_data"):
        op.drop_column("material_catalog_items", name)
    # Personal rows intentionally prevent making project_id NOT NULL again.
