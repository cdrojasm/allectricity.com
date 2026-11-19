"""Arize Phoenix adapter for the application prompt catalog port."""

import os
from threading import Lock
from time import monotonic
from functools import lru_cache

from src.application.ports.prompt_catalog import PromptSnapshot


@lru_cache
def phoenix_client():
    from phoenix.client import Client

    options = {}
    if endpoint := os.getenv("PHOENIX_ENDPOINT") or os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
        options["base_url"] = endpoint
    if api_key := os.getenv("PHOENIX_API_KEY"):
        options["api_key"] = api_key
    return Client(**options)


class PhoenixPromptCatalog:
    def __init__(self, client=None):
        self.client = client or phoenix_client()
        self._cache: dict[tuple[str, str | None, str | None], tuple[float, PromptSnapshot]] = {}
        self._lock = Lock()

    def load(self, name: str, *, tag: str | None = None,
             version_id: str | None = None) -> PromptSnapshot:
        key = (name, tag, version_id)
        ttl = max(0, int(os.getenv("PHOENIX_PROMPT_CACHE_SECONDS", "300")))
        now = monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
        prompt = self.client.prompts.get(
            prompt_identifier=None if version_id else name,
            prompt_version_id=version_id,
            tag=None if version_id else tag,
        )
        formatted = prompt.format(sdk="openai")
        snapshot = PromptSnapshot(name=name, version=str(prompt.id or "latest"),
                                  messages=[dict(message) for message in formatted.messages],
                                  # phoenix-client 3.x currently stores this field privately.
                                  model_name=(getattr(prompt, "model_name", None)
                                              or getattr(prompt, "_model_name", None)))
        if ttl:
            with self._lock:
                self._cache[key] = (now + ttl, snapshot)
        return snapshot
