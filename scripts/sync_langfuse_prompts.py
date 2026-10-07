"""Create new versioned Langfuse prompt resources from the checked-in seeds."""

import os
from pathlib import Path

from langfuse import get_client


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "spat-document-extractor": "prompts/langfuse/document-extractor.md",
    "spat-document-consolidator": "prompts/langfuse/document-consolidator.md",
    "spat-agent-orchestrator": "prompts/langfuse/agent-orchestrator.md",
    "spat-agent-grid-designer": "prompts/langfuse/agent-grid-designer.md",
    "spat-agent-soil-modeler": "prompts/langfuse/agent-soil-modeler.md",
    "spat-agent-safety-analyst": "prompts/langfuse/agent-safety-analyst.md",
}


def main():
    missing = [key for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.getenv(key)]
    if missing:
        raise SystemExit(
            f"Faltan {', '.join(missing)} en .env. Crea un par de llaves en el proyecto de "
            "Langfuse (Settings → API Keys) y define también LANGFUSE_BASE_URL si no usas "
            "https://cloud.langfuse.com."
        )
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
