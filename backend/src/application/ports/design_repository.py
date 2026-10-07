"""Port for the versioned land grounding design artifact.

Versions are immutable: each change appends `version = last + 1`, and version numbers are never
reused, not even after deleting a version. Adapters work inside the caller's transaction, so a
version is created atomically with whatever else that transaction writes (messages, run state).
Rows are dicts with: id, project_id, artifact_id, version, name, snapshot, origin, created_by,
created_at.
"""

from abc import ABC, abstractmethod
from time import time
from uuid import uuid4

from src.domain.identity import ServiceError


class DesignRepository(ABC):
    def create(self, project_id: str, name: str, snapshot: dict, actor_id: str, origin: dict) -> dict:
        """Create an artifact with its version 1."""
        row = self._row(project_id, str(uuid4()), 1, name, snapshot, actor_id, origin)
        self._insert(row, first=True)
        return row

    def append_version(self, project_id: str, artifact_id: str, name: str, snapshot: dict, actor_id: str,
                       origin: dict, expected_version: int | None = None) -> dict:
        """Append a version. With `expected_version` it fails if someone else versioned first."""
        last = self._last_version(project_id, artifact_id)
        if last is None:
            raise ServiceError(404, "Artifact not found")
        if expected_version is not None and last != expected_version:
            raise ServiceError(409, "The artifact changed since the proposal was prepared")
        row = self._row(project_id, artifact_id, last + 1, name, snapshot, actor_id, origin)
        self._insert(row, first=False)
        return row

    def exists(self, project_id: str, artifact_id: str) -> bool:
        return self._last_version(project_id, artifact_id) is not None

    @abstractmethod
    def get_version(self, project_id: str, artifact_id: str, version: int) -> dict | None: ...

    @abstractmethod
    def latest(self, project_id: str, artifact_id: str) -> dict | None:
        """Highest existing version of the artifact."""

    @abstractmethod
    def versions(self, project_id: str, artifact_id: str) -> list[dict]:
        """Every existing version, newest first."""

    @abstractmethod
    def latest_by_artifact(self, project_id: str) -> list[dict]:
        """The latest version of each artifact in the project, most recently versioned first."""

    @abstractmethod
    def delete_version(self, project_id: str, artifact_id: str, version: int) -> bool: ...

    @abstractmethod
    def _last_version(self, project_id: str, artifact_id: str) -> int | None:
        """Last version number ever assigned, or None when the artifact does not exist."""

    @abstractmethod
    def _insert(self, row: dict, *, first: bool) -> None: ...

    @staticmethod
    def _row(project_id, artifact_id, version, name, snapshot, actor_id, origin) -> dict:
        return {"id": str(uuid4()), "project_id": project_id, "artifact_id": artifact_id, "version": version,
                "name": name, "snapshot": snapshot, "origin": origin, "created_by": actor_id,
                "created_at": int(time())}
