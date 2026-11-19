"""Shared LLM runtime for SPAT agents: OpenAI-compatible client, Phoenix prompts and a
bounded ReAct tool loop. Used by document ingestion and by the grounding design agent."""

import json
import logging
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


def read_prompt_seed(filename: str) -> str:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "prompts" / "phoenix" / filename
        if candidate.exists():
            return candidate.read_text()
    raise FileNotFoundError(filename)


@lru_cache
def clients():
    from openai import OpenAI

    from src.infrastructure.agents.phoenix_prompt_catalog import PhoenixPromptCatalog

    options = {"api_key": os.environ["LLM_API_KEY"]}
    if os.getenv("LLM_BASE_URL"):
        options["base_url"] = os.environ["LLM_BASE_URL"]
    return PhoenixPromptCatalog(), OpenAI(**options)


def load_prompt(name_env: str, default_name: str, fallback: str | None = None):
    """Load a Phoenix chat prompt; use the checked-in seed if Phoenix is unavailable."""
    catalog, _ = clients()
    name = os.getenv(name_env, default_name)
    tag = os.getenv("PHOENIX_PROMPT_TAG", "production")
    version_env = name_env.replace("NAME", "VERSION")
    version_id = os.getenv(version_env)
    try:
        prompt = catalog.load(name, tag=tag, version_id=version_id)
        return name, prompt, deepcopy(prompt.messages)
    except Exception:
        if fallback is None:
            raise
        logger.warning("Could not load prompt %s from Phoenix; using the checked-in seed", name,
                       exc_info=True)
        from src.application.ports.prompt_catalog import PromptSnapshot

        prompt = PromptSnapshot(name=name, version="local", messages=[{"role": "system",
                                                                          "content": fallback}])
        return name, prompt, deepcopy(prompt.messages)


def tool(name: str, description: str, properties: dict, required: list[str]):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


class TokenLimitExceeded(RuntimeError):
    """El agente agotó el presupuesto de tokens asignado; no se reintenta automáticamente."""


def run_tool_agent(client, model, messages, tools, handlers, final_tool, finalize, usage,
                    max_rounds=10, max_tokens=None):
    """Bucle ReAct acotado. `finalize(args)` devuelve (terminado, respuesta para el agente).

    Si el modelo responde con texto en lugar de herramientas se le recuerda la herramienta
    final, y en la última ronda se le obliga a llamarla. `max_tokens` corta el bucle cuando
    los tokens acumulados en `usage` lo superan.
    """
    reminders = 0
    for round_number in range(max_rounds):
        forced = round_number == max_rounds - 1 or reminders >= 2
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=({"type": "function", "function": {"name": final_tool}}
                         if forced else "auto"),
            temperature=0,
        )
        usage["rounds"] += 1
        if getattr(response, "usage", None):
            prompt_tokens = response.usage.prompt_tokens or 0
            completion_tokens = response.usage.completion_tokens or 0
            usage["prompt_tokens"] += prompt_tokens
            usage["completion_tokens"] += completion_tokens
            per_model = usage.setdefault("models", {}).setdefault(
                model, {"prompt_tokens": 0, "completion_tokens": 0})
            per_model["prompt_tokens"] += prompt_tokens
            per_model["completion_tokens"] += completion_tokens
        if max_tokens and usage["prompt_tokens"] + usage["completion_tokens"] > max_tokens:
            raise TokenLimitExceeded(f"Agent exceeded its token limit ({max_tokens})")
        message = response.choices[0].message
        if not message.tool_calls:
            if forced:
                raise RuntimeError("Agent returned without its required structured result")
            reminders += 1
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append({"role": "user", "content": f"Call {final_tool} now with your "
                             "result; plain-text answers are ignored."})
            continue
        messages.append(message.model_dump(exclude_none=True))
        final_result = None
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments, result = None, {"error": "Arguments are not valid JSON"}
            if arguments is None:
                pass
            elif name == final_tool:
                done, result = finalize(arguments)
                if done or forced:  # la entrega forzada se acepta; la validación filtra
                    final_result = arguments
            elif name in handlers:
                try:
                    result = handlers[name](arguments)
                except (KeyError, TypeError, ValueError):
                    result = {"error": "Invalid tool arguments"}
            else:
                result = {"error": "Unknown tool"}
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        if final_result is not None:
            return final_result
    raise RuntimeError("Agent exceeded its tool-call limit")


def new_usage():
    return {"rounds": 0, "prompt_tokens": 0, "completion_tokens": 0, "duration_seconds": 0.0}
