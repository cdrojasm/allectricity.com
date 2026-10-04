"""Starter document extraction and electrical asset graph projection."""

import csv
import base64
import hashlib
import io
import json
import os
import re
from urllib.request import Request, urlopen


def extract_document(data: bytes, mime_type: str) -> tuple[str, dict]:
    if mime_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages), {}
    if mime_type == "text/csv":
        text = data.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(text))
        return "\n".join(" | ".join(row) for row in rows), {}
    if mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        return "\n".join(
            " | ".join(str(value) for value in row if value is not None)
            for sheet in workbook.worksheets
            for row in sheet.iter_rows(values_only=True)
        ), {}
    if mime_type in {"image/png", "image/jpeg"}:
        endpoint = os.getenv("OCR_SERVICE_URL", "http://ocr:8080").rstrip("/") + "/v1/ocr"
        request = Request(
            endpoint,
            data=json.dumps({"image_base64": base64.b64encode(data).decode("ascii"), "language": "eng+spa"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read())
            return result["text"], {
                "mean_confidence": result["mean_confidence"],
                "low_confidence_ratio": result["low_confidence_ratio"],
                "word_count": result["word_count"],
                "needs_review": result["needs_review"],
            }
    raise ValueError("No parser is configured for this file type")


def extract_text(data: bytes, mime_type: str) -> str:
    """Compatibility wrapper returning only extracted text."""
    return extract_document(data, mime_type)[0]


def extract_electrical_entities(text: str) -> list[dict]:
    """Extract candidate electrical entities and retain exact source spans."""
    patterns = (
        ("Transformer", r"\b(?:transformer|transformador)(?:\s*[-:#]?\s*((?:T|TR|TX)[- ]?\d+[A-Z0-9-]*))?"),
        ("Motor", r"\b(?:motor|MTR)(?:\s*[-:#]?\s*((?:M|MTR)[- ]?\d+[A-Z0-9-]*))?"),
        ("Circuit", r"\b(?:circuit|circuito|feeder|alimentador)(?:\s*[-:#]?\s*([A-Z]{1,5}[- ]?\d+[A-Z0-9-]*))?"),
        ("GroundingGrid", r"\b(?:grounding grid|malla de puesta a tierra|malla a tierra)\b"),
    )
    entities = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            label = (match.group(1) or match.group(0)).strip(" .,:;\n")
            entities.append({
                "type": kind,
                "name": label,
                "start": match.start(),
                "end": match.end(),
                "source_excerpt": text[max(0, match.start()-100):match.end()+160],
            })
    parameter_pattern = re.compile(
        r"\b(voltage|tension|current|corriente|power|potencia|frequency|frecuencia|"
        r"resistance|resistencia|short[- ]circuit|cortocircuito)\b\s*[:=]?\s*"
        r"([0-9]+(?:[.,][0-9]+)?)\s*(kV|V|A|kA|MW|kW|MVA|kVA|Hz|ohm|Ω)\b",
        re.IGNORECASE,
    )
    for match in parameter_pattern.finditer(text):
        entities.append({
            "type": "ElectricalParameter",
            "name": match.group(1).casefold(),
            "value": match.group(2).replace(",", "."),
            "unit": match.group(3),
            "start": match.start(),
            "end": match.end(),
            "source_excerpt": text[max(0, match.start()-100):match.end()+100],
        })
    return sorted(entities, key=lambda entity: (entity["start"], entity["end"], entity["type"]))


def _stable_key(*parts: str) -> str:
    value = "\x1f".join(str(part).strip().casefold() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_electrical_graph(
    upload: dict,
    entities: list[dict],
    ocr: dict | None = None,
    consolidation: dict | None = None,
) -> dict:
    """Build a deterministic, source-traceable project graph from extracted candidates."""
    project_id = upload.get("project_id")
    if not project_id:
        raise ValueError("An upload must belong to a project before graph construction")
    document = {
        "upload_id": upload["id"],
        "project_id": project_id,
        "owner_id": upload["owner_id"],
        "filename": upload.get("filename", ""),
        "object_key": upload["object_key"],
        "mime_type": upload["expected_mime"],
        "ocr_confidence": (ocr or {}).get("mean_confidence"),
        "ocr_low_confidence_ratio": (ocr or {}).get("low_confidence_ratio"),
        "ocr_needs_review": (ocr or {}).get("needs_review", False),
        "agent_summary": (consolidation or {}).get("summary", ""),
        "extractor_prompt_name": (consolidation or {}).get("extractor_prompt_name"),
        "extractor_prompt_version": (consolidation or {}).get("extractor_prompt_version"),
        "consolidator_prompt_name": (consolidation or {}).get("consolidator_prompt_name"),
        "consolidator_prompt_version": (consolidation or {}).get("consolidator_prompt_version"),
        "prompt_label": (consolidation or {}).get("prompt_label"),
    }
    assets, parameters, mentions = {}, {}, []
    for entity in entities:
        kind = entity["type"]
        normalized_name = re.sub(r"\s+", " ", entity["name"]).strip().casefold()
        is_parameter = kind == "ElectricalParameter"
        identity = (
            (project_id, "parameter", normalized_name, entity["value"], entity["unit"].casefold())
            if is_parameter
            else (project_id, "asset", kind, normalized_name)
        )
        key = _stable_key(*identity)
        if is_parameter:
            parameters.setdefault(key, {
                "key": key,
                "name": normalized_name,
                "value": entity["value"],
                "unit": entity["unit"],
            })
        else:
            assets.setdefault(key, {"key": key, "name": entity["name"], "kind": kind})
        mentions.append({
            "node_key": key,
            "node_type": "parameter" if is_parameter else "asset",
            "evidence_id": _stable_key(upload["id"], kind, str(entity["start"]), str(entity["end"])),
            "source_excerpt": entity["source_excerpt"],
            "source_start": entity["start"],
            "source_end": entity["end"],
            "confidence": (ocr or {}).get("mean_confidence"),
            "needs_review": entity.get("needs_review", False) or (ocr or {}).get("needs_review", False),
            "extraction_method": entity.get("extraction_method", "rules"),
            "finding_id": entity.get("finding_id"),
        })
    questions = []
    for question in (consolidation or {}).get("questions", []):
        question_text = question.get("question", "").strip()
        if question_text:
            questions.append({
                "key": _stable_key(upload["id"], "review-question", question_text),
                "question": question_text,
                "finding_ids": question.get("finding_ids", []),
            })
    return {"document": document, "assets": list(assets.values()),
            "parameters": list(parameters.values()), "mentions": mentions,
            "questions": questions}


def persist_graph(
    upload: dict,
    entities: list[dict],
    ocr: dict | None = None,
    consolidation: dict | None = None,
) -> None:
    uri = os.getenv("NEO4J_URI")
    if not uri:
        return
    graph = build_electrical_graph(upload, entities, ocr, consolidation)
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")))
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            session.execute_write(_write_graph, graph)
    finally:
        driver.close()


def load_project_graph_context(project_id: str, limit: int = 100) -> list[dict]:
    """Return a bounded summary of existing project graph facts for consolidation."""
    uri = os.getenv("NEO4J_URI")
    if not uri:
        return []
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        uri, auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
    )
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            result = session.run(
                "MATCH (p:Project {project_id: $project_id})-[:HAS_ASSET|HAS_PARAMETER]->(n) "
                "OPTIONAL MATCH (d:Document {project_id: $project_id})-"
                "[r:MENTIONS|CONTAINS_PARAMETER]->(n) "
                "RETURN labels(n) AS labels, n.name AS name, n.kind AS kind, "
                "n.value AS value, n.unit AS unit, "
                "collect(DISTINCT d.filename)[0..5] AS source_files, "
                "collect(DISTINCT r.source_excerpt)[0..3] AS evidence "
                "LIMIT $limit",
                project_id=project_id,
                limit=limit,
            )
            return [record.data() for record in result]
    finally:
        driver.close()


def _write_graph(tx, graph: dict) -> None:
    document = graph["document"]
    tx.run(
        "MERGE (p:Project {project_id: $project_id}) "
        "MERGE (d:Document {upload_id: $upload_id}) "
        "SET d.project_id=$project_id, d.owner_id=$owner_id, d.filename=$filename, "
        "d.object_key=$object_key, d.mime_type=$mime_type, "
        "d.ocr_confidence=$ocr_confidence, "
        "d.ocr_low_confidence_ratio=$ocr_low_confidence_ratio, "
        "d.ocr_needs_review=$ocr_needs_review, d.agent_summary=$agent_summary, "
        "d.extractor_prompt_name=$extractor_prompt_name, "
        "d.extractor_prompt_version=$extractor_prompt_version, "
        "d.consolidator_prompt_name=$consolidator_prompt_name, "
        "d.consolidator_prompt_version=$consolidator_prompt_version, "
        "d.prompt_label=$prompt_label "
        "MERGE (p)-[:HAS_DOCUMENT]->(d)",
        **document,
    )
    for asset in graph["assets"]:
        tx.run(
            "MATCH (p:Project {project_id: $project_id}) "
            "MERGE (a:ElectricalAsset {key: $key}) "
            "SET a.name=$name, a.kind=$kind, a.project_id=$project_id "
            "MERGE (p)-[:HAS_ASSET]->(a)",
            project_id=document["project_id"], **asset,
        )
    for parameter in graph["parameters"]:
        tx.run(
            "MATCH (p:Project {project_id: $project_id}) "
            "MERGE (v:ElectricalParameter {key: $key}) "
            "SET v.name=$name, v.value=$value, v.unit=$unit, v.project_id=$project_id "
            "MERGE (p)-[:HAS_PARAMETER]->(v)",
            project_id=document["project_id"], **parameter,
        )
    for mention in graph["mentions"]:
        label = "ElectricalParameter" if mention["node_type"] == "parameter" else "ElectricalAsset"
        relation = "CONTAINS_PARAMETER" if mention["node_type"] == "parameter" else "MENTIONS"
        tx.run(
            f"MATCH (d:Document {{upload_id: $upload_id}}) "
            f"MATCH (n:{label} {{key: $node_key}}) "
            f"MERGE (d)-[r:{relation} {{evidence_id: $evidence_id}}]->(n) "
            "SET r.source_excerpt=$source_excerpt, r.source_start=$source_start, "
            "r.source_end=$source_end, r.confidence=$confidence, "
            "r.needs_review=$needs_review, r.extraction_method=$extraction_method, "
            "r.finding_id=$finding_id",
            upload_id=document["upload_id"], **mention,
        )
    for question in graph["questions"]:
        tx.run(
            "MATCH (d:Document {upload_id: $upload_id}) "
            "MERGE (q:ReviewQuestion {key: $key}) "
            "SET q.project_id=$project_id, q.question=$question, "
            "q.finding_ids=$finding_ids, q.status='pending' "
            "MERGE (d)-[:RAISES_QUESTION]->(q)",
            upload_id=document["upload_id"], project_id=document["project_id"], **question,
        )
