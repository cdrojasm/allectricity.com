"""Profile scopes (default / catalog / personal) and the shipped IEEE 80-2013 and RETIE 2026 profiles.

A fresh database already gets the new columns from 0019 (it creates the tables from the current definitions),
so every step checks what is there first.
"""

from time import time

import sqlalchemy as sa
from alembic import op

from src.domain.spat.default_normative_profiles import DEFAULT_PROFILES
from src.infrastructure.persistence.constraint_profile_repository import ConstraintProfileRepository


revision = "0025_profile_scopes_and_defaults"
down_revision = "0024_async_jobs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("constraint_profiles")}
    version_columns = {column["name"]: column for column in inspector.get_columns("constraint_profile_versions")}
    checks = {check["name"] for check in inspector.get_check_constraints("constraint_profiles")}
    indexes = {index["name"] for index in inspector.get_indexes("constraint_profiles")}

    # Only an existing database needs the ALTERs (on SQLite a batch rebuilds the table, so skip it when not needed).
    needs = ("scope" not in columns or "owner_id" not in columns or columns["created_by"]["nullable"] is False
             or "ck_constraint_profile_scope" not in checks)
    if needs:
        with op.batch_alter_table("constraint_profiles") as batch:
            if "scope" not in columns:
                batch.add_column(sa.Column("scope", sa.String(16), nullable=False, server_default="catalog"))
            if "owner_id" not in columns:
                batch.add_column(sa.Column("owner_id", sa.String(36), sa.ForeignKey(
                    "users.id", ondelete="CASCADE", name="fk_constraint_profiles_owner"), nullable=True))
            if not columns["created_by"]["nullable"]:
                batch.alter_column("created_by", existing_type=sa.String(36), nullable=True)
            if "ck_constraint_profile_scope" not in checks:
                batch.create_check_constraint("ck_constraint_profile_scope", "scope IN ('default', 'catalog', 'personal')")
    if "ix_constraint_profiles_owner" not in indexes:
        op.create_index("ix_constraint_profiles_owner", "constraint_profiles", ["owner_id"])
    if not version_columns["created_by"]["nullable"]:
        with op.batch_alter_table("constraint_profile_versions") as batch:
            batch.alter_column("created_by", existing_type=sa.String(36), nullable=True)

    ConstraintProfileRepository(bind).ensure_defaults(DEFAULT_PROFILES, int(time()))


def downgrade():
    bind = op.get_bind()
    for item in DEFAULT_PROFILES:
        bind.execute(sa.text("DELETE FROM project_constraint_profiles WHERE profile_id = :id"), {"id": item["profile_id"]})
        bind.execute(sa.text("DELETE FROM constraint_profile_versions WHERE profile_id = :id"), {"id": item["profile_id"]})
        bind.execute(sa.text("DELETE FROM constraint_profiles WHERE profile_id = :id"), {"id": item["profile_id"]})
    op.drop_index("ix_constraint_profiles_owner", table_name="constraint_profiles")
    with op.batch_alter_table("constraint_profiles") as batch:
        batch.drop_constraint("ck_constraint_profile_scope", type_="check")
        batch.drop_column("owner_id")
        batch.drop_column("scope")
