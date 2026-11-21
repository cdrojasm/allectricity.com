"""Publish the repository's prompt seeds as new Phoenix versions and tag them.

    PHOENIX_SEED_TAG=staging (default) | production
    PHOENIX_SEED_MODEL=anthropic/claude-haiku-5.5   (optional: switch the applications to this model)
    PHOENIX_SEED_ONLY=spat-study-writer,spat-agent-orchestrator   (optional: only these applications)
    PHOENIX_SEED_REASONING=low|medium|high   (optional: reasoning effort of those versions; "none" removes it)

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


def effort(version):
    try:
        return ((version._invocation_parameters or {}).get("openai") or {}).get("reasoning_effort")
    except Exception:
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
    only = {n.strip() for n in os.getenv("PHOENIX_SEED_ONLY", "").split(",") if n.strip()}
    if unknown := only - set(PROMPTS):
        raise SystemExit(f"Unknown applications in PHOENIX_SEED_ONLY: {', '.join(sorted(unknown))}")
    for name, filename in PROMPTS.items():
        if only and name not in only:
            continue
        content = (prompt_dir / filename).read_text()
        existing = current(client, name, dict.fromkeys([tag, "production", "staging"]))
        model = (os.getenv("PHOENIX_SEED_MODEL", "").strip()
                 or (getattr(existing, "_model_name", None) if existing else None) or default_model)
        if not model:
            raise SystemExit(f"{name}: no model in Phoenix; define OPENROUTER_MODEL (e.g. openai/gpt-4.1)")
        reasoning = os.getenv("PHOENIX_SEED_REASONING", "").strip().lower()
        if not reasoning:  # keep the effort the application already has
            reasoning = effort(existing) or ""
        reasoning = "" if reasoning == "none" else reasoning
        tagged = current(client, name, [tag])
        if (tagged is not None and system_text(tagged) == content and getattr(tagged, "_model_name", None) == model
                and (effort(tagged) or "") == reasoning):
            print(f"{name}: unchanged, already tagged {tag!r} ({model})")
            continue
        version = PromptVersion(
            [{"role": "system", "content": content}],
            model_name=model,
            model_provider="OPENAI",
            template_format="NONE",
        )
        if reasoning:
            version._invocation_parameters = {"type": "openai", "openai": {"reasoning_effort": reasoning}}
        prompt = client.prompts.create(name=name, prompt_description=f"SPAT seed for {name}", version=version)
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
                print(f"{name}: version created and tagged {tag!r} ({model}{', ' + reasoning if reasoning else ''})")
        else:
            print(f"{name}: version created; Phoenix returned no version ID")


if __name__ == "__main__":
    main()
