"""Extracción determinista por reglas, emitida en el contrato de extracción (EG-01).

Las reglas solo proponen lo que el texto dice de forma explícita: equipos con etiqueta
y parámetros con valor y unidad cuando la misma oración
nombra un único equipo. No crean relaciones topológicas.
"""

import re

from src.domain.knowledge_graph.contract import empty_extraction
from src.domain.knowledge_graph.source import SourceDocument
from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, UNITS, normalize_unit

_RULE_CONFIDENCE = {"level": "medium", "reason": "Coincidencia de patrón determinista"}

_ENTITY_PATTERNS = (
    ("Transformer", r"\b(?:transformer|transformador)\s*[-:#]?\s*((?:T|TR|TX)[- ]?\d+[A-Z0-9-]*)"),
    ("Motor", r"\bmotor\s*[-:#]?\s*((?:M|MTR)[- ]?\d+[A-Z0-9-]*)"),
    ("Circuit", r"\b(?:circuit|circuito)\s*[-:#]?\s*([A-Z]{1,5}[- ]?\d+[A-Z0-9-]*)"),
    ("Feeder", r"\b(?:feeder|alimentador)\s*[-:#]?\s*([A-Z]{1,5}[- ]?\d+[A-Z0-9-]*)"),
    ("ElectricalPanel", r"\b(?:tablero|panel)\s*[-:#]?\s*((?:TD|TG|TP|PNL|P)[- ]?\d+[A-Z0-9-]*)"),
)
_PARAMETER = re.compile(
    r"\b(voltage|tensi[oó]n|current|corriente|power|potencia|frequency|frecuencia|"
    r"short[- ]circuit current|corriente de cortocircuito|cortocircuito|"
    r"resistance|resistencia)\b\s*(?:nominal\s*)?(?:de\s+malla\s*)?[:=]?\s*"
    r"([0-9]+(?:[.,][0-9]+)?)\s*(kV|V|kA|A|MW|kW|MVA|kVA|Hz|ohm|Ω)(?![A-Za-z])",
    re.IGNORECASE,
)
_ATTRIBUTE_BY_LABEL = (
    ("cortocircuito", "fault_current"), ("short", "fault_current"),
    ("volt", "rated_voltage"), ("tensi", "rated_voltage"),
    ("curr", "rated_current"), ("corriente", "rated_current"),
    ("pow", "rated_power"), ("potencia", "rated_power"),
    ("freq", "frequency"), ("frecuencia", "frequency"),
    ("resist", "reported_grid_resistance"),
)
_SENTENCE = re.compile(r"(?:[^.;\n]|\.(?=\S))+[.;]?")  # «13.8» no corta la oración


def _attribute_for(label: str) -> str:
    label = label.casefold()
    return next(name for prefix, name in _ATTRIBUTE_BY_LABEL if label.startswith(prefix)
                or prefix in label)


def rules_extraction(source: SourceDocument) -> dict:
    payload = empty_extraction()
    entity_ids = {}

    def entity(kind, name, quote, segment_id):
        key = (kind, " ".join(name.split()).casefold())
        if key not in entity_ids:
            entity_ids[key] = f"e{len(entity_ids) + 1}"
            payload["entities"].append({"id": entity_ids[key], "type": kind, "name": name,
                                        "confidence": _RULE_CONFIDENCE})
        payload["evidence"].append({"finding_ids": [entity_ids[key]], "quote": quote,
                                    "locator": {"segment": segment_id}})
        return entity_ids[key], kind

    for segment in source.segments:
        text = source.segment_text(segment)
        for sentence_match in _SENTENCE.finditer(text):
            sentence = sentence_match.group(0).strip()
            if not sentence:
                continue
            found = []
            for kind, pattern in _ENTITY_PATTERNS:
                for match in re.finditer(pattern, sentence, re.IGNORECASE):
                    name = match.group(1).strip(" .,:;")
                    found.append(entity(kind, name, sentence[:1200], segment.id))
            subjects = list(dict.fromkeys(found))
            for match in _PARAMETER.finditer(sentence):
                if len(subjects) != 1:
                    continue  # sin sujeto único la regla no atribuye el valor
                subject_id, subject_type = subjects[0]
                attribute = _attribute_for(match.group(1))
                spec = ATTRIBUTES[attribute]
                unit = match.group(3)
                dimension = UNITS.get(normalize_unit(unit), ("",))[0]
                if subject_type not in spec.subjects or dimension not in spec.dimensions:
                    continue
                attribute_id = f"a{len(payload['attributes']) + 1}"
                payload["attributes"].append({
                    "id": attribute_id, "subject_id": subject_id, "name": attribute,
                    "value": match.group(2), "unit": unit, "confidence": _RULE_CONFIDENCE,
                })
                payload["evidence"].append({"finding_ids": [attribute_id],
                                            "quote": sentence[:1200],
                                            "locator": {"segment": segment.id}})
    return payload
