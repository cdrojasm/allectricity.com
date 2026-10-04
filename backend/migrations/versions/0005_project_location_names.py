"""Store optional country and city names on projects."""

from alembic import op
from sqlalchemy import Column, String, inspect

revision = "0005_project_location_names"
down_revision = "0004_project_chat"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("projects")}
    if "country" not in columns:
        op.add_column("projects", Column("country", String(120), nullable=True))
    if "city" not in columns:
        op.add_column("projects", Column("city", String(120), nullable=True))


def downgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("projects")}
    if "city" in columns:
        op.drop_column("projects", "city")
    if "country" in columns:
        op.drop_column("projects", "country")
