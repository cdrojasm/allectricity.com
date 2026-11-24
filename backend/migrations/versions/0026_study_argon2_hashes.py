"""Allow Argon2id password hashes for shared studies."""

from alembic import op
import sqlalchemy as sa

revision = "0026_study_argon2_hashes"
down_revision = "0025_profile_scopes_and_defaults"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("studies") as batch:
        batch.alter_column(
            "password_hash",
            existing_type=sa.String(length=64),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade():
    # Keep the wider column on downgrade; narrowing could truncate live Argon2id hashes.
    pass
