"""Phoenix-prompted extraction and consolidation agents for document ingestion.

The extractor reads the source only through bounded search/read tools and returns a
payload in the versioned extraction contract; it never writes to Neo4j. The consolidator
can only flag claims for review and raise questions: it cannot accept, reject or drop them.
"""

import json
import os
import time

from src.domain.knowledge_graph.contract import (
    EXTRACTION_SCHEMA, SCHEMA_VERSION, split_item_errors, structural_errors,
)
from src.domain.knowledge_graph.taxonomy import taxonomy_summary
from src.domain.knowledge_graph.validation import validate_extraction
from src.infrastructure.agents import llm_provider, uow
from src.infrastructure.agents.runtime import (
    clients as _clients, new_usage as _new_usage, TokenLimitExceeded, tool as _tool,
)

MAX_SUBMISSIONS = 3
READ_CHARS = 4000


def enabled() -> bool:
    setting = os.getenv("DOCUMENT_AGENTS_ENABLED", "auto").lower()
    if setting in {"true", "1", "yes"}:
        return True
    if setting in {"false", "0", "no"}:
        return False
    return bool((os.getenv("PHOENIX_ENDPOINT") or os.getenv("PHOENIX_COLLECTOR_ENDPOINT"))
                and llm_provider.configured())


APPLICATIONS = {"extractor": "spat-document-extractor", "consolidator": "spat-document-consolidator"}


def load_prompts() -> dict:
    """Prompts del extractor y consolidador con su versión (forman parte del ID de ejecución)."""
    extractor = uow.load_prompt(APPLICATIONS["extractor"])
    consolidator = uow.load_prompt(APPLICATIONS["consolidator"])
    return {
        "extractor": extractor,
        "consolidator": consolidator,
        "meta": {
            "extractor_prompt_name": extractor.name,
            "extractor_prompt_version": extractor.version,
            "consolidator_prompt_name": consolidator.name,
            "consolidator_prompt_version": consolidator.version,
            "prompt_label": os.getenv("PHOENIX_PROMPT_TAG", "production"),
            "model": llm_provider.model(extractor.model_name),
            "consolidator_model": llm_provider.model(consolidator.model_name),
        },
    }


def _work(key: str, prompts: dict, context: uow.WorkContext | None) -> uow.UnitOfWork:
    return uow.UnitOfWork(APPLICATIONS[key], context, client=_clients()[1], prompt=prompts[key])


def _search(source, query: str, limit: int = 8) -> dict:
    needle = query.casefold().strip()
    if not needle:
        return {"matches": []}
    matches = []
    for segment in source.segments:
        text = source.segment_text(segment)
        position = text.casefold().find(needle)
        if position < 0:
            continue
        start, end = max(0, position - 250), min(len(text), position + len(needle) + 250)
        matches.append({"segment": segment.id, "locator": segment.locator,
                        "snippet": text[start:end], "ocr_quality": segment.quality})
        if len(matches) >= limit:
            break
    return {"matches": matches}


def _read(source, segment_id: str, offset: int = 0) -> dict:
    segment = source.segment(segment_id)
    if segment is None:
        return {"error": "Unknown segment"}
    text = source.segment_text(segment)
    offset = max(0, min(int(offset or 0), len(text)))
    end = min(len(text), offset + READ_CHARS)
    return {"segment": segment.id, "locator": segment.locator, "offset": offset,
            "text": text[offset:end], "next_offset": end if end < len(text) else None,
            "ocr_quality": segment.quality}


def _outline(source, offset: int = 0, limit: int = 60) -> dict:
    offset = max(0, int(offset or 0))
    items = [{"segment": s.id, "locator": s.locator,
              "preview": source.segment_text(s)[:100]}
             for s in source.segments[offset:offset + limit]]
    next_offset = offset + limit if offset + limit < len(source.segments) else None
    return {"segments": items, "total": len(source.segments), "next_offset": next_offset}


def _document_tools(source):
    tools = [
        _tool("list_segments", "List source segments (page, sheet row, paragraph...) with "
              "their locators.", {"offset": {"type": "integer"}}, []),
        _tool("search_document", "Find literal text in the source; returns segment IDs.",
              {"query": {"type": "string"}}, ["query"]),
        _tool("read_segment", "Read a source segment by ID, in chunks of 4000 characters.",
              {"segment": {"type": "string"}, "offset": {"type": "integer"}}, ["segment"]),
    ]
    handlers = {
        "list_segments": lambda args: _outline(source, args.get("offset", 0)),
        "search_document": lambda args: _search(source, args["query"]),
        "read_segment": lambda args: _read(source, args["segment"], args.get("offset", 0)),
    }
    return tools, handlers


def run_llm_extraction(source, rule_payload: dict, filename: str, prompts: dict,
                       max_tokens: int | None = None, work_context: uow.WorkContext | None = None) -> dict:
    """Extractor ReAct: devuelve el payload del contrato o errores explícitos."""
    work = _work("extractor", prompts, work_context)
    usage, started = _new_usage(), time.monotonic()
    tools, handlers = _document_tools(source)
    parameters = {key: value for key, value in EXTRACTION_SCHEMA.items()
                  if key not in {"$schema", "$id", "title"}}
    submit = {"type": "function", "function": {
        "name": "submit_extraction",
        "description": "Return grounded entities, attributes and relations in the extraction "
                       "contract. Every finding needs evidence with an exact quote and locator.",
        "parameters": parameters,
    }}
    attempts = {"count": 0, "errors": []}

    def finalize(arguments):
        attempts["count"] += 1
        # Models write the version as a JSON number (1.1) even with the enum of strings in the tool schema, and
        # keep doing it after the error; it is unambiguous, so it is read as its string.
        if isinstance(arguments.get("schema_version"), (int, float)) and not isinstance(
                arguments["schema_version"], bool):
            arguments["schema_version"] = f"{float(arguments['schema_version']):.1f}"
        errors = structural_errors(arguments)
        # Tras el último intento, los errores de ítems sueltos los descarta la validación;
        # solo un payload inválido en su raíz anula la extracción.
        attempts["errors"] = split_item_errors(arguments)[2] if errors else []
        # Retroalimentación con la misma validación determinista que se aplicará después.
        report = validate_extraction(arguments, source, project_id="preview", method="llm")
        problems = errors + [f"{item['finding_id']}: {item['code']} — {item['message']}"
                             for item in report["rejected"]]
        if problems and attempts["count"] < MAX_SUBMISSIONS:
            return False, {"accepted": False, "errors": problems[:60],
                           "instruction": "These findings would be discarded. Fix them (copy "
                           "quotes verbatim from read_segment, list every finding id in "
                           "evidence.finding_ids, use the segment locator) or drop them, then "
                           "call submit_extraction again with the full payload."}
        return True, {"accepted": not errors}

    try:
        payload = work.run_tools(
            [{"role": "user", "content": json.dumps({
                "filename": filename,
                "schema_version": SCHEMA_VERSION,
                "taxonomy": taxonomy_summary(),
                "document": {"segments": len(source.segments), "coverage": source.coverage,
                             "ocr": source.ocr},
                "outline": _outline(source)["segments"],
                "rule_candidates": rule_payload,
                "next_step": "Inspect the source with tools, then call submit_extraction.",
            }, ensure_ascii=False)}],
            [*tools, submit], handlers, "submit_extraction", finalize, usage,
            max_tokens=max_tokens,
        )
    except TokenLimitExceeded as exc:
        usage["token_limit_exceeded"] = True
        attempts["errors"] = [str(exc)]
    usage["duration_seconds"] = round(time.monotonic() - started, 3)
    usage["submissions"] = attempts["count"]
    if attempts["errors"]:
        return {"payload": None, "errors": attempts["errors"], "usage": usage}
    return {"payload": payload, "errors": [], "usage": usage}



def _claim_brief(claim: dict) -> dict:
    if claim["kind"] == "entity":
        content = f"{claim['entity_type']} «{claim['name']}»"
    elif claim["kind"] == "attribute":
        content = (f"{claim['subject_name']}.{claim['attribute']} = "
                   f"{claim['value_literal']} {claim['unit_literal']}".strip())
    else:
        content = f"{claim['source_name']} {claim['relation_type']} {claim['target_name']}"
    return {"claim_id": claim["claim_id"], "kind": claim["kind"], "content": content,
            "status": claim["status"], "review_reasons": claim["review_reasons"],
            "evidence": [{"quote": e["quote"][:400], "locator": e["locator"]}
                         for e in claim["evidence"][:2]]}


def run_llm_consolidation(source, claims: list, questions: list, project_context: list,
                          filename: str, prompts: dict, max_tokens: int | None = None,
                          work_context: uow.WorkContext | None = None) -> dict:
    """El consolidador solo puede marcar revisión y formular preguntas."""
    work = _work("consolidator", prompts, work_context)
    usage, started = _new_usage(), time.monotonic()
    tools, handlers = _document_tools(source)
    finalize_tool = _tool(
        "finalize_consolidation", "Return claim IDs that need review, questions and a summary.",
        {"review_claim_ids": {"type": "array", "items": {"type": "string"}},
         "questions": {"type": "array", "items": {"type": "object",
             "properties": {"question": {"type": "string"},
                            "claim_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["question", "claim_ids"], "additionalProperties": False}},
         "summary": {"type": "string"}},
        ["review_claim_ids", "questions", "summary"],
    )
    try:
        result = work.run_tools(
            [{"role": "user", "content": json.dumps({
                "filename": filename,
                "claims": [_claim_brief(claim) for claim in claims],
                "deterministic_questions": [q["question"] for q in questions],
                "existing_project_graph": project_context,
                "instruction": "Use source tools to check conflicts before finalizing.",
            }, ensure_ascii=False)}],
            [*tools, finalize_tool], handlers, "finalize_consolidation",
            lambda arguments: (True, {"accepted": True}), usage, max_tokens=max_tokens,
        )
    except TokenLimitExceeded:
        # Sin consolidación LLM las afirmaciones conservan su estado y preguntas deterministas.
        result = {}
        usage["token_limit_exceeded"] = True
    usage["duration_seconds"] = round(time.monotonic() - started, 3)
    known = {claim["claim_id"] for claim in claims}
    return {
        "review_claim_ids": sorted(set(result.get("review_claim_ids", [])) & known),
        "questions": [
            {"question": str(q.get("question", "")).strip()[:1000],
             "claim_ids": sorted(set(q.get("claim_ids", [])) & known)}
            for q in result.get("questions", []) if str(q.get("question", "")).strip()
        ],
        "summary": str(result.get("summary", ""))[:3000],
        "usage": usage,
    }

