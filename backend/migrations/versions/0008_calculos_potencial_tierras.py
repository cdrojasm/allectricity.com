"""Add traceable potential-engine calculations linked to grounding artifact versions."""

from alembic import op
from sqlalchemy import inspect
from src.infrastructure.persistence.identity_schema import calculos_potencial_tierras

revision = "0008_calculos_potencial_tierras"
down_revision = "0007_artefacto_diseno_tierras"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("calculos_potencial_tierras"):
        calculos_potencial_tierras.create(op.get_bind())


def downgrade():
    calculos_potencial_tierras.drop(op.get_bind(), checkfirst=True)
