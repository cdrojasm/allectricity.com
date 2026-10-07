"""Shared LLM runtime for SPAT agents: OpenAI-compatible client, Langfuse prompts and a
bounded ReAct tool loop. Used by document ingestion and by the grounding design agent."""

import json
import os
from functools import lru_cache


@lru_cache
def clients():
    from langfuse import get_client
    from openai import OpenAI

    langfuse = get_client()
    options = {"api_key": os.environ["LLM_API_KEY"]}
    if os.getenv("LLM_BASE_URL"):
        options["base_url"] = os.environ["LLM_BASE_URL"]
    return langfuse, OpenAI(**options)


def load_prompt(name_env: str, default_name: str, fallback: str | None = None):
    """Chat prompt from Langfuse; `fallback` (a system prompt) is used if it is not published."""
    langfuse, _ = clients()
    name = os.getenv(name_env, default_name)
    label = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    version_env = name_env.replace("NAME", "VERSION")
    version = os.getenv(version_env)
    kwargs = {
        "label": label,
        "type": "chat",
        "cache_ttl_seconds": int(os.getenv("LANGFUSE_PROMPT_CACHE_SECONDS", "300")),
    }
    if version:
        kwargs.pop("label")
        kwargs["version"] = int(version)
    if fallback is not None:
        kwargs["fallback"] = [{"role": "system", "content": fallback}]
    prompt = langfuse.get_prompt(name, **kwargs)
    return name, prompt, prompt.compile()


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


def run_tool_agent(client, model, messages, tools, handlers, final_tool, finalize, usage,
                    max_rounds=10):
    """Bucle ReAct acotado. `finalize(args)` devuelve (terminado, respuesta para el agente).

    Si el modelo responde con texto en lugar de herramientas se le recuerda la herramienta
    final, y en la última ronda se le obliga a llamarla.
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
            usage["prompt_tokens"] += response.usage.prompt_tokens or 0
            usage["completion_tokens"] += response.usage.completion_tokens or 0
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
