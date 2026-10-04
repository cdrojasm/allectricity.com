"""Create new versioned Langfuse prompt resources from the checked-in seeds."""

import os
from pathlib import Path

from langfuse import get_client


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "spat-document-extractor": "prompts/langfuse/document-extractor.md",
    "spat-document-consolidator": "prompts/langfuse/document-consolidator.md",
}


def main():
    client = get_client()
    label = os.getenv("LANGFUSE_SEED_LABEL", "staging")
    for name, relative_path in PROMPTS.items():
        prompt = client.create_prompt(
            name=name,
            type="chat",
            prompt=[{"role": "system", "content": (ROOT / relative_path).read_text()}],
            labels=[label],
        )
        print(f"Created {name} version {prompt.version} with label {label}")


if __name__ == "__main__":
    main()
