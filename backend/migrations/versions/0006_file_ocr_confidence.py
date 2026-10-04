"""Persist OCR confidence and review recommendation for uploads."""

from alembic import op
from sqlalchemy import Boolean, Column, Float, inspect, text

revision = "0006_file_ocr_confidence"
down_revision = "0005_project_location_names"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("file_uploads")}
    if "ocr_confidence" not in columns:
        op.add_column("file_uploads", Column("ocr_confidence", Float, nullable=True))
    if "ocr_low_confidence_ratio" not in columns:
        op.add_column("file_uploads", Column("ocr_low_confidence_ratio", Float, nullable=True))
    if "ocr_needs_review" not in columns:
        op.add_column(
            "file_uploads",
            Column("ocr_needs_review", Boolean, nullable=False, server_default=text("false")),
        )


def downgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("file_uploads")}
    for name in ("ocr_needs_review", "ocr_low_confidence_ratio", "ocr_confidence"):
        if name in columns:
            op.drop_column("file_uploads", name)
