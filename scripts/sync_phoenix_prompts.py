"""Publish the repository's prompt seeds as new Phoenix versions and tag them.

    PHOENIX_SEED_TAG=staging (default) | production

Each application keeps the model chosen in Phoenix: a new version reuses the model of the version that holds
the tag (or of the "production"/"staging" one); OPENROUTER_MODEL is only used for a prompt that has none yet.
A seed identical to the tagged version is skipped, so running it twice creates nothing.
"""

import os
from pathlib import Path

from phoenix.client.types import PromptVersion

from src.infrastructure.agents.phoenix_prompt_catalog import phoenix_client
from src.infrastructure.agents.uow import APPLICATIONS

# One Phoenix prompt per unit-of-work application (name → checked-in seed).
PROMPTS = APPLICATIONS


def current(client, name, tags):
    for tag in tags:
        try:
            return client.prompts.get(prompt_identifier=name, tag=tag)
        except Exception:
            continue
    return None


def system_text(version) -> str:
    try:
        return "\n".join(str(m.get("content", "")) for m in version.format(sdk="openai").messages
                         if m.get("role") == "system")
    except Exception:
        return ""


def main() -> None:
    prompt_dir = Path(__file__).resolve().parents[1] / "prompts" / "phoenix"
    default_model = os.getenv("OPENROUTER_MODEL", "").strip()
    tag = os.getenv("PHOENIX_SEED_TAG", "staging")
    client = phoenix_client()  # PHOENIX_ENDPOINT / PHOENIX_API_KEY, like the app
    for name, filename in PROMPTS.items():
        content = (prompt_dir / filename).read_text()
        existing = current(client, name, dict.fromkeys([tag, "production", "staging"]))
        model = (getattr(existing, "_model_name", None) if existing else None) or default_model
        if not model:
            raise SystemExit(f"{name}: no model in Phoenix; define OPENROUTER_MODEL (e.g. openai/gpt-4.1)")
        tagged = current(client, name, [tag])
        if tagged is not None and system_text(tagged) == content and getattr(tagged, "_model_name", None) == model:
            print(f"{name}: unchanged, already tagged {tag!r} ({model})")
            continue
        prompt = client.prompts.create(
            name=name,
            prompt_description=f"SPAT seed for {name}",
            version=PromptVersion(
                [{"role": "system", "content": content}],
                model_name=model,
                model_provider="OPENAI",
                template_format="NONE",
            ),
        )
        if prompt.id:
            try:
                client.prompts.tags.create(
                    prompt_version_id=prompt.id,
                    name=tag,
                    description="Seed published from the SPAT repository.",
                )
            except Exception as exc:
                print(f"{name}: version created ({prompt.id}); tag {tag!r} not assigned: {exc}")
            else:
                print(f"{name}: version created and tagged {tag!r} ({model}, {prompt.id})")
        else:
            print(f"{name}: version created; Phoenix returned no version ID")


if __name__ == "__main__":
    main()
