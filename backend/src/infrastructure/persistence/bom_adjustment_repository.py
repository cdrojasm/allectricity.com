"""Project/version scoped BOM surplus decisions, separate from geometric takeoff."""

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, JSON, String, Table, select, update

from src.infrastructure.persistence.identity_schema import metadata


bom_adjustments = Table(
    "bom_adjustments", metadata,
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("artifact_id", String(36), nullable=False, primary_key=True),
    Column("artifact_version", Integer, primary_key=True),
    Column("adjustments", JSON, nullable=False),
    Column("updated_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)


class BomAdjustmentRepository:
    def __init__(self, connection):
        self.connection = connection

    def get(self, project_id, artifact_id, version):
        row = self.connection.execute(select(bom_adjustments).where(
            bom_adjustments.c.project_id == project_id,
            bom_adjustments.c.artifact_id == artifact_id,
            bom_adjustments.c.artifact_version == version,
        )).mappings().first()
        return dict(row) if row else None

    def save(self, project_id, artifact_id, version, adjustments, actor_id, now):
        values = {"adjustments": adjustments, "updated_by": actor_id, "updated_at": now}
        current = self.get(project_id, artifact_id, version)
        if current:
            self.connection.execute(update(bom_adjustments).where(
                bom_adjustments.c.project_id == project_id,
                bom_adjustments.c.artifact_id == artifact_id,
                bom_adjustments.c.artifact_version == version,
            ).values(**values))
        else:
            self.connection.execute(bom_adjustments.insert().values(
                project_id=project_id, artifact_id=artifact_id, artifact_version=version, **values,
            ))
        return self.get(project_id, artifact_id, version)
