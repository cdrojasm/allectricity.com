"""Langfuse-prompted extraction and consolidation agents for document ingestion."""

import json
import os
import re
from functools import lru_cache


@lru_cache
def _clients():
    from langfuse import get_client
    from openai import OpenAI

    langfuse = get_client()
    options = {"api_key": os.environ["LLM_API_KEY"]}
    if os.getenv("LLM_BASE_URL"):
        options["base_url"] = os.environ["LLM_BASE_URL"]
    return langfuse, OpenAI(**options)


def enabled() -> bool:
    setting = os.getenv("DOCUMENT_AGENTS_ENABLED", "auto").lower()
    if setting in {"true", "1", "yes"}:
        return True
    if setting in {"false", "0", "no"}:
        return False
    return all(os.getenv(key) for key in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LLM_API_KEY"
    ))


def _load_prompt(name_env: str, default_name: str):
    langfuse, _ = _clients()
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
    prompt = langfuse.get_prompt(name, **kwargs)
    return prompt, prompt.compile()


def _search_lines(text: str, query: str, limit: int = 8) -> dict:
    lines = text.splitlines()
    needle = query.casefold().strip()
    if not needle:
        return {"matches": []}
    matches = []
    for index, line in enumerate(lines):
        if needle in line.casefold():
            matches.append({"line": index + 1, "text": line[:1200]})
            if len(matches) >= limit:
                break
    return {"matches": matches}


def _read_lines(text: str, start_line: int, end_line: int) -> dict:
    lines = text.splitlines()
    start = max(1, min(start_line, len(lines) or 1))
    end = max(start, min(end_line, start + 39, len(lines)))
    return {"lines": [{"line": number, "text": lines[number - 1][:1200]}
                       for number in range(start, end + 1)]}


def _run_tool_agent(client, model, messages, tools, handlers, final_tool, max_rounds=6):
    for _ in range(max_rounds):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            raise RuntimeError("Agent returned without its required structured result")
        messages.append(message.model_dump(exclude_none=True))
        final_result = None
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Agent emitted invalid arguments for {name}") from exc
            if name not in handlers:
                result = {"error": "Unknown tool"}
            else:
                result = handlers[name](arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
            if name == final_tool:
                final_result = result
        if final_result is not None:
            return final_result
    raise RuntimeError("Agent exceeded its tool-call limit")


def _tool(name: str, description: str, properties: dict, required: list[str]):
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


def _document_tools(text: str):
    tools = [
        _tool("search_document", "Find literal text in the source document.",
              {"query": {"type": "string"}}, ["query"]),
        _tool("read_document_lines", "Read source lines by 1-based line number.",
              {"start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
              ["start_line", "end_line"]),
    ]
    handlers = {
        "search_document": lambda args: _search_lines(text, args["query"]),
        "read_document_lines": lambda args: _read_lines(
            text, args["start_line"], args["end_line"]
        ),
    }
    return tools, handlers


def _valid_extractions(raw: dict, text: str) -> list[dict]:
    allowed = {"Transformer", "Motor", "Circuit", "GroundingGrid", "ElectricalParameter"}
    results = []
    for item in raw.get("findings", []):
        if not isinstance(item, dict) or item.get("type") not in allowed:
            continue
        evidence = item.get("evidence", "")
        name = str(item.get("name", "")).strip()
        if not isinstance(evidence, str) or not evidence or len(evidence) > 1200:
            continue
        start = text.casefold().find(evidence.casefold())
        if start < 0 or not name or name.casefold() not in evidence.casefold():
            continue
        end = start + len(evidence)
        finding = {
            "type": item["type"],
            "name": name,
            "start": start,
            "end": end,
            "source_excerpt": text[max(0, start - 100):min(len(text), end + 100)],
            "extraction_method": "llm_extractor",
            "needs_review": True,
        }
        if item["type"] == "ElectricalParameter":
            value, unit = str(item.get("value", "")).strip(), str(item.get("unit", "")).strip()
            if (not re.fullmatch(r"\d+(?:[.,]\d+)?", value) or not unit
                    or value not in evidence or unit.casefold() not in evidence.casefold()):
                continue
            finding.update(value=value.replace(",", "."), unit=unit)
        results.append(finding)
    return results


def run_document_agents(
    text: str,
    rule_findings: list[dict],
    ocr: dict,
    filename: str,
    project_context: list[dict] | None = None,
) -> dict:
    """Run the ReAct extractor, then the consolidator; all LLM data stays provisional."""
    langfuse, client = _clients()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    extractor_prompt, extractor_messages = _load_prompt(
        "DOCUMENT_EXTRACTOR_PROMPT_NAME", "spat-document-extractor"
    )
    tools, handlers = _document_tools(text)
    handlers["submit_findings"] = lambda args: args
    submit_extraction = _tool(
        "submit_findings", "Return grounded candidate findings and uncertainties.",
        {"findings": {"type": "array", "items": {"type": "object",
          "properties": {"type": {"type": "string"}, "name": {"type": "string"},
            "value": {"type": "string"}, "unit": {"type": "string"},
            "evidence": {"type": "string"}}, "required": ["type", "name", "evidence"],
          "additionalProperties": False}},
         "uncertainties": {"type": "array", "items": {"type": "string"}}},
        ["findings", "uncertainties"],
    )
    extraction = _run_tool_agent(
        client, model,
        [*extractor_messages, {"role": "user", "content": json.dumps({
            "filename": filename,
            "ocr_needs_review": ocr.get("needs_review", False),
            "ocr_confidence": ocr.get("mean_confidence"),
            "rule_candidates": rule_findings,
            "next_step": "Inspect the source with tools, then call submit_findings.",
        }, ensure_ascii=False)}],
        [*tools, submit_extraction], handlers, "submit_findings",
    )
    llm_findings = _valid_extractions(extraction, text)
    findings = [dict(item, extraction_method="rules", needs_review=False)
                for item in rule_findings] + llm_findings
    for index, finding in enumerate(findings):
        finding["finding_id"] = f"f{index + 1}"

    consolidator_prompt, consolidator_messages = _load_prompt(
        "DOCUMENT_CONSOLIDATOR_PROMPT_NAME", "spat-document-consolidator"
    )
    consolidation_tools, consolidation_handlers = _document_tools(text)
    consolidation_handlers["finalize_consolidation"] = lambda args: args
    finalize = _tool(
        "finalize_consolidation", "Return included finding IDs, review IDs and questions.",
        {"include_ids": {"type": "array", "items": {"type": "string"}},
         "review_ids": {"type": "array", "items": {"type": "string"}},
         "questions": {"type": "array", "items": {"type": "object",
             "properties": {"question": {"type": "string"},
               "finding_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["question", "finding_ids"], "additionalProperties": False}},
         "summary": {"type": "string"}},
        ["include_ids", "review_ids", "questions", "summary"],
    )
    consolidated = _run_tool_agent(
        client, model,
        [*consolidator_messages, {"role": "user", "content": json.dumps({
            "filename": filename,
            "findings": findings,
            "existing_project_graph": project_context or [],
            "extractor_uncertainties": extraction.get("uncertainties", []),
            "ocr_needs_review": ocr.get("needs_review", False),
            "instruction": "Use source tools to check conflicts before finalizing.",
        }, ensure_ascii=False)}],
        [*consolidation_tools, finalize], consolidation_handlers, "finalize_consolidation",
    )
    known = {finding["finding_id"] for finding in findings}
    included = set(consolidated.get("include_ids", [])) & known
    review = set(consolidated.get("review_ids", [])) & known
    if not included:
        included = known
        review = known
    selected = []
    for finding in findings:
        if finding["finding_id"] not in included:
            continue
        finding["needs_review"] = (
            finding["needs_review"]
            or finding["finding_id"] in review
            or ocr.get("needs_review", False)
        )
        selected.append(finding)
    valid_questions = []
    for question in consolidated.get("questions", []):
        ids = sorted(set(question.get("finding_ids", [])) & known)
        text_question = str(question.get("question", "")).strip()
        if text_question:
            valid_questions.append({"question": text_question[:1000], "finding_ids": ids})

    return {
        "findings": selected,
        "consolidation": {
            "summary": str(consolidated.get("summary", ""))[:3000],
            "questions": valid_questions,
            "extractor_prompt_name": os.getenv(
                "DOCUMENT_EXTRACTOR_PROMPT_NAME", "spat-document-extractor"
            ),
            "extractor_prompt_version": extractor_prompt.version,
            "consolidator_prompt_name": os.getenv(
                "DOCUMENT_CONSOLIDATOR_PROMPT_NAME", "spat-document-consolidator"
            ),
            "consolidator_prompt_version": consolidator_prompt.version,
            "prompt_label": os.getenv("LANGFUSE_PROMPT_LABEL", "production"),
            "enabled": True,
        },
    }
