"""Add immutable, versioned grounding design artifacts."""

from alembic import op
from sqlalchemy import inspect
from src.infrastructure.persistence.identity_schema import (
    artefacto_diseno_tierras,
    artefacto_diseno_tierras_counters,
)

revision = "0007_artefacto_diseno_tierras"
down_revision = "0006_file_ocr_confidence"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("artefacto_diseno_tierras"):
        artefacto_diseno_tierras.create(op.get_bind())
    if not inspect(op.get_bind()).has_table("artefacto_diseno_tierras_counters"):
        artefacto_diseno_tierras_counters.create(op.get_bind())


def downgrade():
    artefacto_diseno_tierras_counters.drop(op.get_bind(), checkfirst=True)
    artefacto_diseno_tierras.drop(op.get_bind(), checkfirst=True)
