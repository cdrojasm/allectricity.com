"""Publish the repository's prompt seeds as new Phoenix versions tagged for review."""

import os
from pathlib import Path

from phoenix.client import Client
from phoenix.client.types import PromptVersion

from src.infrastructure.agents.uow import APPLICATIONS

# One Phoenix prompt per unit-of-work application (name → checked-in seed).
PROMPTS = APPLICATIONS


def main() -> None:
    prompt_dir = Path(__file__).resolve().parents[1] / "prompts" / "phoenix"
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not model:
        raise SystemExit("Define OPENROUTER_MODEL (por ejemplo openai/gpt-4.1)")
    tag = os.getenv("PHOENIX_SEED_TAG", "staging")
    client = Client()
    for name, filename in PROMPTS.items():
        content = (prompt_dir / filename).read_text()
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
                    description="Seed published from the SPAT repository; review before production.",
                )
            except Exception as exc:
                print(f"{name}: version created ({prompt.id}); tag {tag!r} not assigned: {exc}")
            else:
                print(f"{name}: version created and tagged {tag!r} ({prompt.id})")
        else:
            print(f"{name}: version created; Phoenix returned no version ID")


if __name__ == "__main__":
    main()
