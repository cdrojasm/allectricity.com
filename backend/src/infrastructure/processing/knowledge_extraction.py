"""Orquestación de la extracción documental hacia el grafo de conocimiento.

parseo con localizadores → reglas → extractor LLM (opcional) → validación determinista →
consolidación contra el grafo → consolidador LLM (opcional) → persistencia atómica.
"""

import hashlib
import logging
import os
import time
from collections import Counter

from src.domain.knowledge_graph.claims import NEEDS_REVIEW, claim_id, stable_key
from src.domain.knowledge_graph.consolidation import consolidate
from src.domain.knowledge_graph.contract import SCHEMA_VERSION
from src.domain.knowledge_graph.source import normalized_text
from src.domain.knowledge_graph.taxonomy import TAXONOMY_VERSION
from src.domain.knowledge_graph.validation import merge_claims, validate_extraction
from src.infrastructure.processing import document_agents
from src.infrastructure.processing.document_sources import PARSER_VERSION, parse_document
from src.infrastructure.processing.rule_extraction import rules_extraction

RULES_VERSION = "rules/3"
logger = logging.getLogger(__name__)


def run_identity(upload: dict, data: bytes, meta: dict) -> str:
    """Misma entrada, parser, taxonomía, contrato, prompts y modelo ⇒ misma ejecución."""
    return stable_key(
        "extraction-run", upload["id"], hashlib.sha256(data).hexdigest(), PARSER_VERSION,
        RULES_VERSION, TAXONOMY_VERSION, SCHEMA_VERSION, meta.get("extractor_prompt_name", ""),
        meta.get("extractor_prompt_version", ""), meta.get("consolidator_prompt_name", ""),
        meta.get("consolidator_prompt_version", ""), meta.get("model", ""),
    )


def extract_knowledge(upload: dict, data: bytes, mime_type: str, graph, agents=document_agents):
    """Procesa un archivo y persiste su ejecución; devuelve (fuente, resumen de la ejecución)."""
    if not upload.get("project_id"):
        raise ValueError("An upload must belong to a project before graph construction")
    started = time.time()
    source = parse_document(data, mime_type)
    use_agents = agents.enabled()
    project_id = upload["project_id"]
    errors = []
    token_limit = _token_limit(graph, project_id) if use_agents else None
    if token_limit == 0:
        # Sin presupuesto LLM el documento se procesa solo con reglas; al ampliar el límite,
        # reprocesarlo crea una ejecución nueva (otro ID) con los agentes.
        use_agents = False
        errors.append("límite de tokens LLM del proyecto agotado: extracción solo con reglas")
    prompts = agents.load_prompts() if use_agents else None
    meta = prompts["meta"] if prompts else {}
    run_id = run_identity(upload, data, meta)
    if graph is not None and _graph_call(graph.run_exists, run_id):
        return source, {"run_id": run_id, "status": "already_processed"}

    rule_payload = rules_extraction(source)
    rules = validate_extraction(rule_payload, source, project_id=project_id, method="rules")
    errors.extend(f"reglas: {error}" for error in rules["errors"])
    rejected = [dict(item, method="rules") for item in rules["rejected"]]
    notes = list(rules["notes"])
    llm_claims, usage = [], {}
    if use_agents:
        try:
            extraction = agents.run_llm_extraction(source, rule_payload, upload.get("filename", ""),
                                                   prompts, max_tokens=token_limit)
        except Exception as exc:
            raise RuntimeError("Document extraction agent failed") from exc
        usage["extractor"] = extraction["usage"]
        if extraction["payload"] is None:
            errors.extend(f"extractor LLM: {error}" for error in extraction["errors"])
        else:
            llm = validate_extraction(extraction["payload"], source, project_id=project_id,
                                      method="llm")
            llm_claims = llm["claims"]
            errors.extend(f"extractor LLM: {error}" for error in llm["errors"])
            rejected.extend(dict(item, method="llm") for item in llm["rejected"])
            notes.extend(llm["notes"])

    claims = merge_claims(rules["claims"], llm_claims)
    for claim in claims:
        claim["claim_id"] = claim_id(run_id, claim)
    existing = _graph_call(graph.load_project_claims, project_id,
                           exclude_open_upload_id=upload["id"]) if graph is not None else []
    questions = consolidate(project_id, claims, existing)["questions"]

    summary = ""
    remaining = (None if token_limit is None
                 else token_limit - _tokens(usage.get("extractor", {})))
    if use_agents and claims and remaining is not None and remaining <= 0:
        errors.append("límite de tokens LLM alcanzado: se omitió el consolidador")
    elif use_agents and claims:
        try:
            review = agents.run_llm_consolidation(
                source, claims, questions, _context(existing), upload.get("filename", ""), prompts,
                max_tokens=remaining)
        except Exception as exc:
            raise RuntimeError("Document consolidation agent failed") from exc
        usage["consolidator"] = review["usage"]
        if review["usage"].get("token_limit_exceeded"):
            errors.append("límite de tokens LLM alcanzado durante la consolidación")
        summary = review["summary"]
        flagged = set(review["review_claim_ids"])
        for claim in claims:
            if claim["claim_id"] in flagged:
                claim["status"] = NEEDS_REVIEW
                claim["review_reasons"].append("El consolidador solicitó revisión")
        known = {normalized_text(q["question"]) for q in questions}
        for question in review["questions"]:
            if normalized_text(question["question"]) in known:
                continue
            known.add(normalized_text(question["question"]))
            questions.append({"key": stable_key(project_id, "question", "llm", run_id,
                                                question["question"]),
                              "kind": "consolidator", **question})

    status = "completed"
    if errors or rejected:
        status = "completed_with_errors"
    if not source.complete:
        status = "partial"
    counts = Counter(claim["status"] for claim in claims)
    llm_tokens = sum(_tokens(part) for part in usage.values())
    llm_cost = _cost(usage)
    run = {
        "run_id": run_id, "project_id": project_id, "upload_id": upload["id"],
        "owner_id": upload.get("owner_id"), "filename": upload.get("filename", ""),
        "object_key": upload.get("object_key"), "mime_type": mime_type,
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "text_sha256": source.content_hash, "parser_version": PARSER_VERSION,
        "rules_version": RULES_VERSION, "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": SCHEMA_VERSION, "method": "rules+llm" if use_agents else "rules", **meta,
        "started_at": int(started), "finished_at": int(time.time()), "status": status,
        "coverage": source.coverage, "ocr": source.ocr, "errors": errors[:200],
        "rejected": rejected[:500], "notes": notes[:200], "summary": summary,
        "llm_tokens": llm_tokens, "llm_cost_usd": llm_cost,
        "metrics": {"claims": len(claims), "by_status": dict(counts),
                    "rejected": len(rejected), "questions": len(questions),
                    "segments": len(source.segments), "usage": usage,
                    "llm_tokens": llm_tokens, "llm_cost_usd": llm_cost,
                    "duration_seconds": round(time.time() - started, 3)},
        "claims": claims, "questions": questions,
    }
    if graph is not None:
        _graph_call(graph.save_run, run)
    # Solo conteos y metadatos: nunca texto del documento en los logs (EG-13).
    logger.info("extraction run %s upload=%s status=%s claims=%s rejected=%d questions=%d "
                "llm_tokens=%d llm_cost_usd=%s", run_id[:12], upload["id"], status, dict(counts),
                len(rejected), len(questions), llm_tokens, llm_cost)
    return source, {key: run[key] for key in ("run_id", "status", "metrics")}


def _tokens(usage: dict) -> int:
    return int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))


def _cost(usage: dict) -> float | None:
    """Coste estimado en USD con los precios por millón de tokens configurados (EG-13)."""
    input_price = os.getenv("LLM_PRICE_INPUT_USD_PER_MTOK")
    output_price = os.getenv("LLM_PRICE_OUTPUT_USD_PER_MTOK")
    if not input_price or not output_price:
        return None
    prompt = sum(int(part.get("prompt_tokens", 0)) for part in usage.values())
    completion = sum(int(part.get("completion_tokens", 0)) for part in usage.values())
    return round((prompt * float(input_price) + completion * float(output_price)) / 1e6, 6)


def _token_limit(graph, project_id: str) -> int | None:
    """Tokens disponibles para este archivo: el menor entre el límite por archivo y lo que
    queda del límite del proyecto. None significa sin límite; 0, presupuesto agotado."""
    per_file = int(os.getenv("DOCUMENT_LLM_MAX_TOKENS_PER_FILE", "0")) or None
    per_project = int(os.getenv("DOCUMENT_LLM_MAX_TOKENS_PER_PROJECT", "0")) or None
    if per_project is None or graph is None:
        return per_file
    remaining = max(0, per_project - _graph_call(graph.project_llm_tokens, project_id))
    return remaining if per_file is None else min(per_file, remaining)


def _graph_call(function, *args, **kwargs):
    """Los fallos de Neo4j son de infraestructura: la tarea los reintenta."""
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        raise RuntimeError("Knowledge graph operation failed") from exc


def _context(existing: list, limit: int = 100) -> list:
    """Resumen acotado del grafo previo para el consolidador LLM (evidencia, no verdad)."""
    context = []
    for claim in existing[:limit]:
        item = {"claim_id": claim["claim_id"], "kind": claim["kind"], "status": claim["status"],
                "filename": claim.get("filename")}
        if claim["kind"] == "attribute":
            item.update(subject=claim.get("subject_name"), attribute=claim["attribute"],
                        value=claim.get("reviewed_value_literal") or claim.get("value_literal"),
                        unit=claim.get("unit_literal"))
        elif claim["kind"] == "entity":
            item.update(entity_type=claim.get("entity_type"), name=claim.get("name"))
        else:
            item.update(relation=claim.get("relation_type"), source=claim.get("source_name"),
                        target=claim.get("target_name"))
        context.append(item)
    return context
