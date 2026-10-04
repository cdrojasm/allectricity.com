"""Add user-owned land projects."""

from alembic import op
from sqlalchemy import inspect
from src.infrastructure.persistence.identity_schema import projects

revision = "0003_projects"
down_revision = "0002_file_uploads"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("projects"):
        projects.create(op.get_bind())


def downgrade():
    projects.drop(op.get_bind(), checkfirst=True)
