from abc import ABC, abstractmethod


class KnowledgeGraphRepository(ABC):
    """Persistencia del grafo de afirmaciones con procedencia."""

    @abstractmethod
    def run_exists(self, run_id: str) -> bool: ...

    @abstractmethod
    def load_project_claims(self, project_id: str, exclude_open_upload_id: str | None = None,
                            limit: int = 5000) -> list: ...

    @abstractmethod
    def save_run(self, run: dict) -> bool: ...

    @abstractmethod
    def list_claims(self, project_id: str, **filters) -> dict: ...

    @abstractmethod
    def get_claim(self, project_id: str, claim_id: str) -> dict | None: ...

    @abstractmethod
    def accepted_attribute_claims(self, project_id: str, entity_key: str, attribute: str,
                                  qualifier: str) -> list: ...

    @abstractmethod
    def apply_decision(self, project_id: str, claim_id: str, *, expected_status: str,
                       changes: dict, decision: dict, supersede_ids=()) -> bool: ...

    @abstractmethod
    def list_questions(self, project_id: str, status: str | None = "pending",
                       limit: int = 50, skip: int = 0) -> dict: ...

    @abstractmethod
    def resolve_question(self, project_id: str, key: str, *, actor_id: str, status: str,
                         resolution: str) -> dict | None: ...

    @abstractmethod
    def entity_map(self, project_id: str, limit: int = 300) -> dict: ...

    @abstractmethod
    def list_runs(self, project_id: str, upload_id: str | None = None, limit: int = 50) -> list: ...

    @abstractmethod
    def summary(self, project_id: str) -> dict: ...
