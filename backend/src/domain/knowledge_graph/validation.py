"""Validación determinista de una extracción contra el documento fuente (EG-03, EG-05).

Comprueba esquema, IDs, tipos, compatibilidad de extremos, unidades/rangos y que cada
hallazgo tenga al menos una cita literal que exista en el pasaje designado por su
localizador. Los hallazgos inválidos se descartan con un error explícito; los dudosos
pasan a revisión con su motivo. La confianza del LLM y la calidad OCR se guardan por
separado y ninguna de las dos acepta nada automáticamente.
"""

import re

from src.domain.knowledge_graph.claims import content_key, entity_key, initial_status
from src.domain.knowledge_graph.contract import split_item_errors
from src.domain.knowledge_graph.source import SourceDocument, normalized_text
from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, RELATION_RULES, parse_quantity

MIN_OCR_QUALITY = 60.0


def _issue(finding_id, code, message):
    return {"finding_id": finding_id, "code": code, "message": message}


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def validate_extraction(payload: dict, source: SourceDocument, *, project_id: str,
                        method: str) -> dict:
    """Devuelve afirmaciones validadas, hallazgos descartados y errores de ejecución."""
    payload, rejected, errors = split_item_errors(payload)
    if errors:
        return {"claims": [], "rejected": [], "errors": errors, "notes": []}

    findings = {}
    seen = set()
    for collection, kind in (("entities", "entity"), ("attributes", "attribute"),
                             ("relations", "relation")):
        for item in payload[collection]:
            if item["id"] in seen:
                rejected.append(_issue(item["id"], "duplicate_id",
                                       "Identificador repetido en la extracción"))
                findings.pop(item["id"], None)
                continue
            seen.add(item["id"])
            findings[item["id"]] = (kind, item)

    reviews = {finding_id: [] for finding_id in findings}
    notes = []
    for uncertainty in payload["uncertainties"]:
        targets = [fid for fid in uncertainty["finding_ids"] if fid in reviews]
        for fid in targets:
            reviews[fid].append(f"Incertidumbre del extractor: {uncertainty['description']}")
        if not targets:
            notes.append(uncertainty["description"])

    # Evidencia: cada cita debe existir en el pasaje que señala su localizador.
    evidence = {finding_id: [] for finding_id in findings}
    problems = {finding_id: [] for finding_id in findings}
    # Evidencia compartida (1.0) más la evidencia en línea de cada hallazgo (1.1).
    citations = list(payload.get("evidence", []))
    for _, item in findings.values():
        citations.extend({"finding_ids": [item["id"]], **citation}
                         for citation in item.get("evidence", []))
    for index, item in enumerate(citations):
        segments = source.resolve(item["locator"])
        span = source.find_quote(item["quote"], segments) if segments else None
        if span is None:
            problem = (f"evidencia {index + 1}: " + ("la cita no aparece en el pasaje señalado"
                                                      if segments else "el localizador no existe"))
            for fid in item["finding_ids"]:
                problems.setdefault(fid, []).append(problem)
            notes.append(f"Evidencia {index + 1} descartada: {problem}")
            continue
        start, end = span
        quality, ocr_review = source.quality_for(start, end)
        record = {"quote": source.text[start:end], "start": start, "end": end,
                  "locator": source.locator_for(start, end), "ocr_quality": quality,
                  "ocr_needs_review": ocr_review or (quality is not None
                                                     and quality < MIN_OCR_QUALITY)}
        for fid in item["finding_ids"]:
            if fid in evidence:
                evidence[fid].append(record)
            else:
                notes.append(f"Evidencia {index + 1} cita un hallazgo inexistente «{fid}»")

    claims, valid = {}, {}
    entities = {fid: item for fid, (kind, item) in findings.items() if kind == "entity"}

    def reject(fid, code, message):
        if code == "missing_evidence" and problems.get(fid):
            message = f"{message} ({'; '.join(problems[fid])})"
        rejected.append(_issue(fid, code, message))

    def grounded(fid, needles) -> bool:
        quotes = [normalized_text(record["quote"]) for record in evidence[fid]]
        return all(any(normalized_text(needle) in quote for quote in quotes) for needle in needles)

    def base(fid, item, kind):
        records = evidence[fid]
        qualities = [r["ocr_quality"] for r in records if r["ocr_quality"] is not None]
        return {"kind": kind, "finding_ids": [f"{method}:{fid}"], "methods": [method],
                "confidence": item.get("confidence"), "evidence": records,
                "review_reasons": list(reviews[fid]),
                "ocr_quality": min(qualities) if qualities else None,
                "ocr_needs_review": any(r["ocr_needs_review"] for r in records),
                "feeds_calculation": False}

    for fid, item in entities.items():
        if not evidence[fid]:
            reject(fid, "missing_evidence", "La entidad no tiene una cita verificable")
            continue
        if not grounded(fid, [item["name"]]):
            reject(fid, "name_not_in_quote", f"«{item['name']}» no aparece en su cita")
            continue
        claim = base(fid, item, "entity")
        claim.update(entity_type=item["type"], name=item["name"].strip(),
                     aliases=sorted({a.strip() for a in item.get("aliases", [])}),
                     entity_key=entity_key(project_id, item["type"], item["name"]))
        claims[fid], valid[fid] = claim, item

    for fid, (kind, item) in findings.items():
        if kind != "attribute":
            continue
        spec = ATTRIBUTES[item["name"]]
        subject = valid.get(item["subject_id"])
        if subject is None:
            reject(fid, "unresolved_subject", f"El sujeto «{item['subject_id']}» no es una "
                                              "entidad válida de esta extracción")
            continue
        if subject["type"] not in spec.subjects:
            reject(fid, "incompatible_subject",
                   f"{spec.name} no aplica a entidades {subject['type']}")
            continue
        if not evidence[fid]:
            reject(fid, "missing_evidence", "El atributo no tiene una cita verificable")
            continue
        claim = base(fid, item, "attribute")
        value, unit = item["value"].strip(), item.get("unit", "").strip()
        claim.update(entity_key=claims[item["subject_id"]]["entity_key"],
                     entity_type=subject["type"], subject_name=subject["name"],
                     attribute=spec.name, value_literal=value, unit_literal=unit,
                     qualifier=(item.get("qualifier") or "").strip(),
                     feeds_calculation=spec.feeds_calculation,
                     value=None, value_si=None, unit=None, dimension=None)
        quotes = [r["quote"] for r in evidence[fid]]
        if spec.is_quantity:
            try:
                quantity = parse_quantity(value, unit)
            except ValueError as exc:
                reject(fid, "invalid_quantity", str(exc))
                continue
            if quantity.dimension not in spec.dimensions:
                reject(fid, "incompatible_unit", f"«{unit}» no es una unidad de {spec.name}")
                continue
            if spec.si_range and not spec.si_range[0] <= quantity.value_si <= spec.si_range[1]:
                reject(fid, "out_of_range", f"{spec.name} = {value} {unit} fuera del rango "
                                            "físico admitido")
                continue
            if not any(_digits(value) in _digits(quote) for quote in quotes):
                reject(fid, "value_not_in_quote", f"El valor «{value}» no aparece en su cita")
                continue
            if unit and not grounded(fid, [unit]):
                reject(fid, "unit_not_in_quote", f"La unidad «{unit}» no aparece en su cita")
                continue
            claim.update(value=quantity.value, value_si=quantity.value_si, unit=quantity.unit,
                         dimension=quantity.dimension)
            claim["review_reasons"].extend(quantity.notes)
        else:
            if spec.choices and value.casefold() not in spec.choices:
                reject(fid, "invalid_choice", f"Valor no admitido para {spec.name}")
                continue
            if not grounded(fid, [value]):
                reject(fid, "value_not_in_quote", f"El valor «{value}» no aparece en su cita")
                continue
        if not grounded(fid, [subject["name"]]):
            claim["review_reasons"].append(
                f"La cita no nombra a «{subject['name']}»; el sujeto se infirió del contexto")
        if spec.feeds_calculation:
            claim["review_reasons"].append(
                "Parámetro de entrada de cálculo: requiere aceptación humana explícita")
        claims[fid] = claim

    for fid, (kind, item) in findings.items():
        if kind != "relation":
            continue
        rule = RELATION_RULES[item["type"]]
        source_entity, target_entity = valid.get(item["source_id"]), valid.get(item["target_id"])
        if source_entity is None or target_entity is None:
            reject(fid, "unresolved_endpoint", "Un extremo de la relación no es una entidad "
                                               "válida de esta extracción")
            continue
        if item["source_id"] == item["target_id"]:
            reject(fid, "self_relation", "Una relación no puede unir una entidad consigo misma")
            continue
        if not rule.allows(source_entity["type"], target_entity["type"]):
            reject(fid, "incompatible_endpoints",
                   f"{rule.name} no admite {source_entity['type']} → {target_entity['type']}")
            continue
        if not evidence[fid]:
            reject(fid, "missing_evidence", "La relación no tiene una cita verificable")
            continue
        claim = base(fid, item, "relation")
        claim.update(relation_type=rule.name, symmetric=rule.symmetric,
                     source_key=claims[item["source_id"]]["entity_key"],
                     target_key=claims[item["target_id"]]["entity_key"],
                     source_type=source_entity["type"], target_type=target_entity["type"],
                     source_name=source_entity["name"], target_name=target_entity["name"])
        if not grounded(fid, [source_entity["name"], target_entity["name"]]):
            claim["review_reasons"].append(
                "La cita no nombra ambos extremos; la relación se infirió por contexto")
        # Toda relación topológica propuesta requiere confirmación (EG-14, EG-15).
        claim["review_reasons"].append("Relación topológica: requiere confirmación")
        claims[fid] = claim

    for claim in claims.values():
        claim["content_key"] = content_key(claim)
    return {"claims": list(claims.values()), "rejected": rejected, "errors": [], "notes": notes}


def merge_claims(*claim_lists) -> list:
    """Une afirmaciones idénticas propuestas por reglas y LLM, conservando toda la evidencia."""
    merged = {}
    for claims in claim_lists:
        for claim in claims:
            current = merged.get(claim["content_key"])
            if current is None:
                merged[claim["content_key"]] = dict(claim, evidence=list(claim["evidence"]),
                                                    review_reasons=list(claim["review_reasons"]))
                continue
            spans = {(r["start"], r["end"]) for r in current["evidence"]}
            current["evidence"].extend(r for r in claim["evidence"]
                                       if (r["start"], r["end"]) not in spans)
            for field in ("finding_ids", "methods", "review_reasons"):
                current[field] = list(dict.fromkeys(current[field] + claim[field]))
            if claim.get("confidence") and "llm" in claim["methods"]:
                current["confidence"] = claim["confidence"]
            current["ocr_needs_review"] = current["ocr_needs_review"] or claim["ocr_needs_review"]
            qualities = [q for q in (current["ocr_quality"], claim["ocr_quality"]) if q is not None]
            current["ocr_quality"] = min(qualities) if qualities else None
    for claim in merged.values():
        claim["status"] = initial_status(claim)
    return list(merged.values())

