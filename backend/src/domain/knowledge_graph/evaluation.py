"""Evaluación de la extracción contra un conjunto anotado (EG-12).

Compara las afirmaciones de una ejecución con el gold de su documento y mide precisión y
recobrado por tipo de entidad, atributo y relación, exactitud del localizador de la
evidencia, abstención ante lo prohibido, duplicados, invariantes de estado y preguntas
esperadas. Es determinista y no depende del proveedor LLM: el mismo informe sirve para
comparar modelos, prompts y arquitecturas, y para bloquear regresiones.

Formato del gold (un archivo por documento; las `ref` se comparten dentro de un caso):

- entidad: `{"ref", "type", "names": [..] | null, "locator"?, "optional"?}`; `names: null`
  acepta cualquier nombre de ese tipo.
- atributo: `{"subject": ref | [refs], "name", "value_si" | "values_si" | "value" | "values",
  "locator"?, "optional"?}`.
- relación: `{"type", "source", "target", "locator"?, "optional"?}`.
- prohibido: `{"kind": "attribute", "subject", "name"}` o
  `{"kind": "relation", "type" | "*", "source", "target"}` (en cualquier sentido).
- pregunta: `{"kind", "mentions": [..]}`; basta una pregunta de ese tipo que nombre todo.

Lo opcional no suma acierto ni penaliza: describe extracciones correctas pero no exigidas.
"""

from collections import defaultdict

from src.domain.knowledge_graph.claims import ACCEPTED, NEEDS_REVIEW
from src.domain.knowledge_graph.source import normalized_text

KINDS = ("entities", "attributes", "relations")
REL_TOLERANCE = 1e-6


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _counts():
    return {"tp": 0, "fp": 0, "fn": 0}


def _resolve_entity(gold_entities: list, entity_type: str, name: str) -> dict | None:
    """Entidad del gold que corresponde a un tipo y nombre extraídos (nombres exactos)."""
    wanted = normalized_text(name or "")
    fallback = None
    for entity in gold_entities:
        if entity["type"] != entity_type:
            continue
        if entity.get("names") is None:
            fallback = fallback or entity
        elif wanted in {normalized_text(n) for n in entity["names"]}:
            return entity
    return fallback


def _value_matches(gold: dict, claim: dict) -> bool:
    values_si = _as_list(gold.get("values_si", gold.get("value_si")))
    if values_si:
        actual = claim.get("reviewed_value_si", claim.get("value_si"))
        if actual is None:
            return False
        return any(abs(actual - expected) <= REL_TOLERANCE * max(abs(expected), 1e-12)
                   for expected in values_si)
    actual = normalized_text(claim.get("reviewed_value_literal") or claim.get("value_literal")
                             or "")
    return actual in {normalized_text(v) for v in _as_list(gold.get("values", gold.get("value")))}


def _locator_matches(gold: dict, claim: dict) -> bool | None:
    """None si el gold no fija localizador; si lo fija, alguna evidencia debe contenerlo."""
    expected = _as_list(gold.get("locator"))
    if not expected:
        return None
    locators = [record.get("locator") or {} for record in claim.get("evidence", [])]
    return any(all(locator.get(key) == value for key, value in wanted.items())
               for wanted in expected for locator in locators)


class _Matcher:
    """Asigna afirmaciones a ítems del gold: primero los exigidos, luego los opcionales."""

    def __init__(self, items):
        self.items = sorted(items, key=lambda item: bool(item.get("optional")))
        self.matched = {}

    def assign(self, claim, predicate):
        candidates = [i for i, item in enumerate(self.items) if predicate(item)]
        free = [i for i in candidates if i not in self.matched]
        if free:
            self.matched[free[0]] = claim
            return "match", self.items[free[0]]
        if candidates:
            return "duplicate", self.items[candidates[0]]
        return "unmatched", None


def score_document(gold: dict, claims: list, questions: list = ()) -> dict:
    """Puntúa las afirmaciones (y preguntas) de una ejecución frente al gold del documento."""
    entities_gold = gold.get("entities", [])

    def ref_of(entity_type, name):
        entity = _resolve_entity(entities_gold, entity_type, name)
        return entity["ref"] if entity else None

    by_kind = {kind: [c for c in claims if c["kind"] == singular]
               for kind, singular in zip(KINDS, ("entity", "attribute", "relation"))}

    totals = {kind: _counts() for kind in KINDS}
    groups = {kind: defaultdict(_counts) for kind in KINDS}
    duplicates = {kind: 0 for kind in KINDS}
    evidence = {"checked": 0, "correct": 0}
    errors = []

    def record(kind, group, outcome, item=None, claim=None):
        if outcome == "match":
            if item.get("optional"):
                return
            totals[kind]["tp"] += 1
            groups[kind][group]["tp"] += 1
            located = _locator_matches(item, claim)
            if located is not None:
                evidence["checked"] += 1
                evidence["correct"] += int(located)
                if not located:
                    errors.append({"kind": "wrong_locator", "item": _label(kind, item),
                                   "locators": [r.get("locator") for r in claim["evidence"]]})
            return
        if outcome == "duplicate":
            duplicates[kind] += 1
        totals[kind]["fp"] += 1
        groups[kind][group]["fp"] += 1
        error = "duplicate" if outcome == "duplicate" else "false_positive"
        if error == "false_positive" and kind == "entities" and _name_variant(entities_gold, claim):
            error = "name_variant"  # «bajante BJ-1» por «BJ-1»: en el grafo sería otra entidad
        errors.append({"kind": error, "item": _claim_label(claim)})

    entity_matcher = _Matcher(entities_gold)
    for claim in by_kind["entities"]:
        outcome, item = entity_matcher.assign(
            claim, lambda e: e["type"] == claim["entity_type"]
            and _resolve_entity([e], claim["entity_type"], claim["name"]) is not None)
        record("entities", claim["entity_type"], outcome, item, claim)

    attribute_matcher = _Matcher(gold.get("attributes", []))
    for claim in by_kind["attributes"]:
        subject = ref_of(claim["entity_type"], claim.get("subject_name"))
        outcome, item = attribute_matcher.assign(
            claim, lambda a: a["name"] == claim["attribute"]
            and subject in _as_list(a["subject"]) and _value_matches(a, claim))
        if outcome == "unmatched" and any(
                a["name"] == claim["attribute"] and subject in _as_list(a["subject"])
                for a in gold.get("attributes", [])):
            errors.append({"kind": "wrong_value", "item": _claim_label(claim)})
        record("attributes", claim["attribute"], outcome, item, claim)

    relation_matcher = _Matcher(gold.get("relations", []))
    for claim in by_kind["relations"]:
        source = ref_of(claim.get("source_type"), claim.get("source_name"))
        target = ref_of(claim.get("target_type"), claim.get("target_name"))
        pairs = {(source, target)} | ({(target, source)} if claim.get("symmetric") else set())
        outcome, item = relation_matcher.assign(
            claim, lambda r: r["type"] == claim["relation_type"]
            and (r["source"], r["target"]) in pairs)
        record("relations", claim["relation_type"], outcome, item, claim)

    for kind, matcher in (("entities", entity_matcher), ("attributes", attribute_matcher),
                          ("relations", relation_matcher)):
        for index, item in enumerate(matcher.items):
            if item.get("optional") or index in matcher.matched:
                continue
            group = item["type"] if kind != "attributes" else item["name"]
            totals[kind]["fn"] += 1
            groups[kind][group]["fn"] += 1
            errors.append({"kind": "missed", "item": _label(kind, item)})

    forbidden = gold.get("forbidden", [])
    violations = [rule for rule in forbidden if any(
        _violates(rule, claim, ref_of) for claim in claims)]
    errors.extend({"kind": "forbidden", "item": rule} for rule in violations)

    expected_questions = gold.get("questions", [])
    found_questions = [q for q in expected_questions if any(
        question.get("kind") == q["kind"]
        and all(normalized_text(m) in normalized_text(question.get("question", ""))
                for m in q["mentions"]) for question in questions)]
    errors.extend({"kind": "missed_question", "item": q} for q in expected_questions
                  if q not in found_questions)

    invariants = {
        "accepted": sum(c.get("status") == ACCEPTED for c in claims),
        "calculation_inputs_not_in_review": sum(
            bool(c["kind"] == "attribute" and c.get("feeds_calculation")
                 and c.get("status") != NEEDS_REVIEW) for c in claims),
    }
    return {
        "counts": totals,
        "groups": {kind: dict(groups[kind]) for kind in KINDS},
        "duplicates": duplicates,
        "evidence": evidence,
        "forbidden": {"total": len(forbidden), "violations": len(violations)},
        "questions": {"expected": len(expected_questions), "found": len(found_questions)},
        "invariants": invariants,
        "errors": errors,
    }


def _name_variant(gold_entities: list, claim: dict) -> bool:
    name = normalized_text(claim["name"])
    return any(entity["type"] == claim["entity_type"] and any(
        normalized_text(known) in name or name in normalized_text(known)
        for known in entity.get("names") or ()) for entity in gold_entities)


def _label(kind: str, item: dict) -> str:
    if kind == "entities":
        return f"{item['type']} «{item['ref']}»"
    if kind == "attributes":
        expected = item.get("values_si", item.get("value_si", item.get("values", item.get("value"))))
        return f"{'/'.join(_as_list(item['subject']))}.{item['name']} = {expected}"
    return f"{item['source']} {item['type']} {item['target']}"


def _claim_label(claim: dict) -> str:
    if claim["kind"] == "entity":
        return f"{claim['entity_type']} «{claim['name']}»"
    if claim["kind"] == "attribute":
        return (f"{claim.get('subject_name')}.{claim['attribute']} = "
                f"{claim.get('value_literal')} {claim.get('unit_literal') or ''}".rstrip())
    return f"{claim.get('source_name')} {claim['relation_type']} {claim.get('target_name')}"


def _violates(rule: dict, claim: dict, ref_of) -> bool:
    if rule["kind"] == "attribute":
        return (claim["kind"] == "attribute" and claim["attribute"] == rule["name"]
                and ref_of(claim["entity_type"], claim.get("subject_name")) == rule["subject"])
    if claim["kind"] != "relation" or rule["type"] not in {"*", claim["relation_type"]}:
        return False
    pair = {ref_of(claim.get("source_type"), claim.get("source_name")),
            ref_of(claim.get("target_type"), claim.get("target_name"))}
    return pair == {rule["source"], rule["target"]}


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def prf(counts: dict) -> dict:
    """Precisión, recobrado y F1; None cuando no hay nada que medir."""
    precision = _ratio(counts["tp"], counts["tp"] + counts["fp"])
    recall = _ratio(counts["tp"], counts["tp"] + counts["fn"])
    f1 = (round(2 * precision * recall / (precision + recall), 4)
          if precision and recall else (0.0 if precision is not None and recall is not None
                                        else None))
    return {**counts, "precision": precision, "recall": recall, "f1": f1}


def aggregate(scores: list) -> dict:
    """Suma puntuaciones de documentos y calcula las métricas del informe."""
    totals = {kind: _counts() for kind in KINDS}
    groups = {kind: defaultdict(_counts) for kind in KINDS}
    summed = defaultdict(int)
    for score in scores:
        for kind in KINDS:
            for key in ("tp", "fp", "fn"):
                totals[kind][key] += score["counts"][kind][key]
            for group, counts in score["groups"][kind].items():
                for key in ("tp", "fp", "fn"):
                    groups[kind][group][key] += counts[key]
            summed[f"duplicates.{kind}"] += score["duplicates"][kind]
        for section in ("evidence", "forbidden", "questions", "invariants"):
            for key, value in score[section].items():
                summed[f"{section}.{key}"] += value
    overall = _counts()
    for kind in KINDS:
        for key in ("tp", "fp", "fn"):
            overall[key] += totals[kind][key]
    return {
        "overall": prf(overall),
        **{kind: prf(totals[kind]) for kind in KINDS},
        "by_group": {kind: {group: prf(counts) for group, counts in sorted(groups[kind].items())}
                     for kind in KINDS},
        "duplicates": sum(summed[f"duplicates.{kind}"] for kind in KINDS),
        "evidence_accuracy": _ratio(summed["evidence.correct"], summed["evidence.checked"]),
        "abstention": (None if not summed["forbidden.total"] else
                       round(1 - summed["forbidden.violations"] / summed["forbidden.total"], 4)),
        "question_recall": _ratio(summed["questions.found"], summed["questions.expected"]),
        "invariants": {key.split(".", 1)[1]: value for key, value in summed.items()
                       if key.startswith("invariants.")},
    }


def metric(report: dict, path: str):
    value = report
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def regressions(metrics: dict, thresholds: dict, baseline: dict | None = None) -> list:
    """Motivos por los que un informe no puede promoverse; lista vacía si cumple.

    `thresholds` admite `min` y `max` (valores absolutos) y `max_drop` (caída permitida
    frente a la línea base) por ruta de métrica, p. ej. `"attributes.f1"`.
    """
    failures = []
    for path, limit in thresholds.get("min", {}).items():
        value = metric(metrics, path)
        if value is None or value < limit:
            failures.append(f"{path} = {value} < mínimo {limit}")
    for path, limit in thresholds.get("max", {}).items():
        value = metric(metrics, path)
        if value is None or value > limit:
            failures.append(f"{path} = {value} > máximo {limit}")
    if baseline is not None:
        for path, drop in thresholds.get("max_drop", {}).items():
            before, after = metric(baseline, path), metric(metrics, path)
            if before is None:
                continue
            if after is None or after < before - drop:
                failures.append(f"{path} bajó de {before} a {after} (caída máxima {drop})")
    return failures
