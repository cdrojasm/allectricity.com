from copy import deepcopy

from src.application.ports.design_repository import DesignRepository


class InMemoryDesignRepository(DesignRepository):
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, int], dict] = {}
        self._last: dict[tuple[str, str], int] = {}

    def get_version(self, project_id, artifact_id, version):
        row = self._rows.get((project_id, artifact_id, version))
        return deepcopy(row) if row else None

    def latest(self, project_id, artifact_id):
        rows = self.versions(project_id, artifact_id)
        return rows[0] if rows else None

    def versions(self, project_id, artifact_id):
        rows = [row for key, row in self._rows.items() if key[:2] == (project_id, artifact_id)]
        return deepcopy(sorted(rows, key=lambda row: row["version"], reverse=True))

    def latest_by_artifact(self, project_id):
        artifacts = {artifact_id for (project, artifact_id) in self._last if project == project_id}
        rows = [row for row in (self.latest(project_id, a) for a in artifacts) if row]
        return sorted(rows, key=lambda row: (row["created_at"], row["version"]), reverse=True)

    def delete_version(self, project_id, artifact_id, version):
        return self._rows.pop((project_id, artifact_id, version), None) is not None

    def _last_version(self, project_id, artifact_id):
        return self._last.get((project_id, artifact_id))

    def _insert(self, row, *, first):
        self._rows[(row["project_id"], row["artifact_id"], row["version"])] = deepcopy(row)
        self._last[(row["project_id"], row["artifact_id"])] = row["version"]
