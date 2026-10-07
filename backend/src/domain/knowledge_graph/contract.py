"""Contrato versionado de la salida del extractor (EG-01).

El LLM entrega entidades, atributos y relaciones, cada uno respaldado por citas con
localizador. Este módulo define el JSON Schema estricto y la validación estructural; la
verificación contra el documento fuente vive en `validation.py`.
"""

from jsonschema import Draft202012Validator

from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, ENTITY_TYPES, RELATION_RULES

SCHEMA_VERSION = "1.1"
SUPPORTED_VERSIONS = ("1.0", "1.1")

_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"}
_CONFIDENCE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["level", "reason"],
    "properties": {
        "level": {"enum": ["high", "medium", "low"]},
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
}
_LOCATOR = {
    "type": "object",
    "additionalProperties": False,
    "minProperties": 1,
    "description": "Use `segment` con el identificador devuelto por las herramientas; "
                   "page/sheet/row/paragraph/table/cell se aceptan como alternativa.",
    "properties": {
        "segment": {"type": "string", "minLength": 1, "maxLength": 120},
        "page": {"type": "integer", "minimum": 1},
        "sheet": {"type": "string", "minLength": 1, "maxLength": 120},
        "row": {"type": "integer", "minimum": 1},
        "paragraph": {"type": "integer", "minimum": 1},
        "table": {"type": "integer", "minimum": 1},
        "cell": {"type": "integer", "minimum": 1},
    },
}

_INLINE_EVIDENCE = {
    "type": "array",
    "minItems": 1,
    "maxItems": 5,
    "description": "Citas literales que respaldan este hallazgo (contrato 1.1).",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["quote", "locator"],
        "properties": {
            "quote": {"type": "string", "minLength": 1, "maxLength": 1200},
            "locator": _LOCATOR,
        },
    },
}

EXTRACTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"https://spat.local/schemas/extraction/{SCHEMA_VERSION}",
    "title": "SPAT document extraction",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "entities", "attributes", "relations", "uncertainties"],
    "properties": {
        "schema_version": {"enum": list(SUPPORTED_VERSIONS)},
        "entities": {"type": "array", "maxItems": 300, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name", "confidence"],
            "properties": {
                "id": _ID,
                "type": {"enum": sorted(t for t, spec in ENTITY_TYPES.items()
                                        if spec.llm_extractable)},
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "aliases": {"type": "array", "maxItems": 10,
                            "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                "confidence": _CONFIDENCE,
                "evidence": _INLINE_EVIDENCE,
            },
        }},
        "attributes": {"type": "array", "maxItems": 600, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "subject_id", "name", "value", "confidence"],
            "properties": {
                "id": _ID,
                "subject_id": _ID,
                "name": {"enum": sorted(ATTRIBUTES)},
                "value": {"type": "string", "minLength": 1, "maxLength": 120},
                "unit": {"type": "string", "maxLength": 20,
                         "description": "Unidad literal; omitir o \"\" si es adimensional o texto."},
                "qualifier": {"type": "string", "maxLength": 200},
                "confidence": _CONFIDENCE,
                "evidence": _INLINE_EVIDENCE,
            },
        }},
        "relations": {"type": "array", "maxItems": 300, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "source_id", "target_id", "confidence"],
            "properties": {
                "id": _ID,
                "type": {"enum": sorted(name for name, rule in RELATION_RULES.items()
                                        if rule.llm_extractable)},
                "source_id": _ID,
                "target_id": _ID,
                "confidence": _CONFIDENCE,
                "evidence": _INLINE_EVIDENCE,
            },
        }},
        "evidence": {"type": "array", "maxItems": 600, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["finding_ids", "quote", "locator"],
            "properties": {
                "finding_ids": {"type": "array", "minItems": 1, "maxItems": 50, "items": _ID},
                "quote": {"type": "string", "minLength": 1, "maxLength": 1200},
                "locator": _LOCATOR,
            },
        }},
        "uncertainties": {"type": "array", "maxItems": 100, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["finding_ids", "description"],
            "properties": {
                "finding_ids": {"type": "array", "maxItems": 50, "items": _ID},
                "description": {"type": "string", "minLength": 1, "maxLength": 1000},
            },
        }},
    },
}

_VALIDATOR = Draft202012Validator(EXTRACTION_SCHEMA)


def structural_errors(payload) -> list[str]:
    """Errores de esquema legibles, con la ruta JSON de cada uno."""
    errors = sorted(_VALIDATOR.iter_errors(payload), key=lambda error: list(error.absolute_path))
    return [f"{'/'.join(str(part) for part in error.absolute_path) or '(raíz)'}: {error.message}"
            for error in errors[:50]]


def split_item_errors(payload) -> tuple[dict, list, list]:
    """Separa errores de hallazgos individuales de errores de la raíz.

    Devuelve (payload sin los ítems inválidos, ítems descartados, errores de raíz). Un
    hallazgo mal formado se descarta con su motivo sin invalidar los demás.
    """
    errors = list(_VALIDATOR.iter_errors(payload))
    collections = {"entities", "attributes", "relations", "evidence", "uncertainties"}
    bad, root = {}, []
    for error in errors:
        path = list(error.absolute_path)
        if len(path) >= 2 and path[0] in collections and isinstance(path[1], int):
            location = "/".join(str(part) for part in path[2:]) or "(ítem)"
            bad.setdefault((path[0], path[1]), []).append(f"{location}: {error.message}")
        else:
            root.append(f"{'/'.join(str(part) for part in path) or '(raíz)'}: {error.message}")
    if root or not bad:
        return payload, [], root[:50]
    pruned = dict(payload)
    dropped = []
    for collection in collections & set(payload):
        kept = []
        for index, item in enumerate(payload.get(collection, [])):
            if (collection, index) in bad:
                item_id = item.get("id") if isinstance(item, dict) else None
                dropped.append({"finding_id": item_id or f"{collection}/{index}",
                                "code": "schema", "message": "; ".join(bad[(collection, index)])})
            else:
                kept.append(item)
        pruned[collection] = kept
    return pruned, dropped, []


def empty_extraction() -> dict:
    return {"schema_version": SCHEMA_VERSION, "entities": [], "attributes": [], "relations": [],
            "evidence": [], "uncertainties": []}
