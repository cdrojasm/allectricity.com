"""Add curated versioned constraint profiles and project selections."""

from alembic import op

from src.infrastructure.persistence.constraint_profile_repository import (
    constraint_profile_versions,
    constraint_profiles,
    project_constraint_profiles,
)


revision = "0019_constraint_profiles"
down_revision = "0018_catalog_chat"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    constraint_profiles.create(bind, checkfirst=True)
    constraint_profile_versions.create(bind, checkfirst=True)
    project_constraint_profiles.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    project_constraint_profiles.drop(bind, checkfirst=True)
    constraint_profile_versions.drop(bind, checkfirst=True)
    constraint_profiles.drop(bind, checkfirst=True)
