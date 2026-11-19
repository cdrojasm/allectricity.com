"""The single LLM provider of the platform: OpenRouter, through its OpenAI-compatible API.

Variables:
- OPENROUTER_API_KEY   key (required).
- OPENROUTER_MODEL     default model, e.g. `openai/gpt-4.1` (required).
- OPENROUTER_BASE_URL  optional; only to point at a local stub in smoke tests.
Per-task overrides (AGENT_*_MODEL, PLAN_VISION_MODEL, STUDY_WRITER_MODEL, MATERIAL_CATALOG_*_MODEL) keep working.
"""

import os

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# OpenRouter names models `<provider>/<model>`; a bare name (from an older Phoenix prompt version or
# an override written as `gpt-4.1`) is an OpenAI model.
BARE_MODEL_PROVIDER = "openai"


def api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def base_url() -> str:
    return os.getenv("OPENROUTER_BASE_URL", "").strip() or OPENROUTER_URL


def default_model() -> str:
    return os.getenv("OPENROUTER_MODEL", "").strip()


def configured() -> bool:
    return bool(api_key() and default_model())


def qualify(model: str) -> str:
    model = model.strip()
    return model if "/" in model else f"{BARE_MODEL_PROVIDER}/{model}"


def model(*preferred: str | None) -> str:
    """First non-empty choice (prompt version, per-task override), else OPENROUTER_MODEL."""
    for choice in (*preferred, default_model()):
        if choice and choice.strip():
            return qualify(choice)
    raise RuntimeError("Define OPENROUTER_MODEL (por ejemplo openai/gpt-4.1)")


def client():
    from openai import OpenAI

    if not api_key():
        raise RuntimeError("Define OPENROUTER_API_KEY")
    return OpenAI(api_key=api_key(), base_url=base_url())
