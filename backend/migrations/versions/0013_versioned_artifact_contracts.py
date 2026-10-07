"""Version existing artifact snapshots and retain legacy calculation record shapes."""

from alembic import op
from sqlalchemy import MetaData, Table, select, update

revision = "0013_artifact_contracts"
down_revision = "0012_upload_recovery"
branch_labels = None
depends_on = None


def _mark_contract(table_name, column_name, version="1.0"):
    bind = op.get_bind()
    table = Table(table_name, MetaData(), autoload_with=bind)
    rows = bind.execute(select(table.c.id, table.c[column_name])).mappings()
    for row in rows:
        document = row[column_name]
        if isinstance(document, dict) and "schema_version" not in document:
            bind.execute(update(table).where(table.c.id == row["id"])
                         .values({column_name: {**document, "schema_version": version}}))


def upgrade():
    _mark_contract("artefacto_diseno_tierras", "snapshot")
    _mark_contract("calculos_potencial_tierras", "result", "0.legacy")
    _mark_contract("calculos_potencial_tierras", "trace", "0.legacy")


def downgrade():
    # Keep markers: removing them would erase the version used to interpret the data.
    pass
