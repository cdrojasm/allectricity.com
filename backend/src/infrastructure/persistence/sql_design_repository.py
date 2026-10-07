"""PostgreSQL adapter of `DesignRepository` over `artefacto_diseno_tierras` (migrations 0007/0008).

It runs on the connection of an `SQLIdentityStore` transaction. Write transactions are serialized
by the store's lock and `uq_artefacto_diseno_tierras_version` rejects any duplicate version.
"""

from sqlalchemy import delete, func, insert, select, update

from src.application.ports.design_repository import DesignRepository
from src.infrastructure.persistence.identity_schema import (
    artefacto_diseno_tierras as versions,
    artefacto_diseno_tierras_counters as counters,
)


class SQLDesignRepository(DesignRepository):
    def __init__(self, connection) -> None:
        self._connection = connection

    def get_version(self, project_id, artifact_id, version):
        return self._first(self._scope(project_id, artifact_id).where(versions.c.version == version))

    def latest(self, project_id, artifact_id):
        return self._first(self._scope(project_id, artifact_id).order_by(versions.c.version.desc()).limit(1))

    def versions(self, project_id, artifact_id):
        return self._all(self._scope(project_id, artifact_id).order_by(versions.c.version.desc()))

    def latest_by_artifact(self, project_id):
        newest = (select(versions.c.artifact_id, func.max(versions.c.version).label("version"))
                  .where(versions.c.project_id == project_id).group_by(versions.c.artifact_id).subquery())
        stmt = (select(versions)
                .join(newest, (versions.c.artifact_id == newest.c.artifact_id)
                      & (versions.c.version == newest.c.version))
                .order_by(versions.c.created_at.desc(), versions.c.artifact_id))
        return self._all(stmt)

    def delete_version(self, project_id, artifact_id, version):
        stmt = delete(versions).where(versions.c.project_id == project_id, versions.c.artifact_id == artifact_id,
                                      versions.c.version == version)
        return self._connection.execute(stmt).rowcount == 1

    def _last_version(self, project_id, artifact_id):
        stmt = select(counters.c.last_version).where(counters.c.id == artifact_id,
                                                     counters.c.project_id == project_id)
        return self._connection.execute(stmt).scalar_one_or_none()

    def _insert(self, row, *, first):
        if first:
            self._connection.execute(insert(counters).values(id=row["artifact_id"], project_id=row["project_id"],
                                                             last_version=row["version"]))
        else:
            self._connection.execute(update(counters).where(counters.c.id == row["artifact_id"])
                                     .values(last_version=row["version"]))
        self._connection.execute(insert(versions).values(**row))

    @staticmethod
    def _scope(project_id, artifact_id):
        return select(versions).where(versions.c.project_id == project_id, versions.c.artifact_id == artifact_id)

    def _first(self, stmt):
        row = self._connection.execute(stmt).mappings().first()
        return dict(row) if row else None

    def _all(self, stmt):
        return [dict(row) for row in self._connection.execute(stmt).mappings()]
