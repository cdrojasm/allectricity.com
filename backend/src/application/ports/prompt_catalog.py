"""Application contract for loading immutable, versioned chat prompts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PromptSnapshot:
    name: str
    version: str
    messages: list[dict[str, str]]
    model_name: str | None = None


class PromptCatalog(Protocol):
    def load(self, name: str, *, tag: str | None = None,
             version_id: str | None = None) -> PromptSnapshot: ...
