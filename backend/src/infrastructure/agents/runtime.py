"""Shared LLM runtime: OpenRouter client, Phoenix prompt catalog, seeds and the bounded ReAct tool loop.
Invocations go through uow.UnitOfWork, which adds Phoenix configuration, tracing and budget debits."""

import json
import logging
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
    from src.infrastructure.agents import llm_provider
    from src.infrastructure.agents.phoenix_prompt_catalog import PhoenixPromptCatalog

    return PhoenixPromptCatalog(), llm_provider.client()


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
                    max_rounds=10, max_tokens=None, parameters=None, on_response=None):
    """Bucle ReAct acotado. `finalize(args)` devuelve (terminado, respuesta para el agente).

    Si el modelo responde con texto en lugar de herramientas se le recuerda la herramienta
    final, y en la última ronda se le obliga a llamarla. `max_tokens` corta el bucle cuando
    los tokens acumulados en `usage` lo superan. `parameters` (temperatura, etc.) viene del
    prompt en Phoenix; `on_response(response)` se llama tras cada respuesta del modelo.
    Úsalo a través de `uow.UnitOfWork.run_tools`, que cobra y traza cada llamada.
    """
    reminders = 0
    for round_number in range(max_rounds):
        forced = round_number == max_rounds - 1 or reminders >= 2
        response = client.chat.completions.create(
            **{"temperature": 0, **(parameters or {})},
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=({"type": "function", "function": {"name": final_tool}}
                         if forced else "auto"),
        )
        if on_response is not None:
            on_response(response)
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
