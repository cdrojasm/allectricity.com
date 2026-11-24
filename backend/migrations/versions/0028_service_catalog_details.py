"""Add explicit service scope, pricing mode, acceptance, and duration fields."""

import sqlalchemy as sa
from alembic import op


revision = "0028_service_catalog_details"
down_revision = "0027_scrub_billing_payload"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("material_catalog_items")}
    if "service_details" not in columns:
        op.add_column("material_catalog_items", sa.Column("service_details", sa.JSON(), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("material_catalog_items")}
    if "service_details" in columns:
        op.drop_column("material_catalog_items", "service_details")
