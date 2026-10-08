import json
from pathlib import Path

import pytest

from src.domain.knowledge_graph.claims import (
    ACCEPTED, NEEDS_REVIEW, PROPOSED, REJECTED, ReviewError, claim_id, content_key,
    review_decision,
)
from src.domain.knowledge_graph.consolidation import compact_tag, consolidate
from src.domain.knowledge_graph.contract import structural_errors
from src.domain.knowledge_graph.source import Segment, SourceDocument
from src.domain.knowledge_graph.taxonomy import parse_number, parse_quantity
from src.domain.knowledge_graph.validation import merge_claims, validate_extraction

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "extraction_contract"
PAGE_4 = ("Memoria de cálculo.\nEl transformador T1, 13,8 kV, alimenta el tablero TD-2.\n"
          "Escenario: falla monofásica en barra de 115 kV: If = 12,5 kA, tiempo de despeje 0,5 s.")


def source_from_pages(pages: dict) -> SourceDocument:
    text, segments = "", []
    for number, page in pages.items():
        if text:
            text += "\n"
        start = len(text)
        text += page
        segments.append(Segment(f"p{number}", start, len(text), {"page": number}))
    return SourceDocument(text, segments, "application/pdf", "test")


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def validate(payload, pages=None, method="llm"):
    source = source_from_pages(pages or {3: "Portada del proyecto", 4: PAGE_4})
    return validate_extraction(payload, source, project_id="project-1", method=method)


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("valid_*.json")))
def test_valid_examples_pass_schema_and_source_checks(name):
    result = validate(example(name))
    assert result["errors"] == [] and result["rejected"] == []
    assert result["claims"]


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("invalid_*.json")))
def test_invalid_examples_are_rejected_by_the_schema(name):
    assert structural_errors(example(name))
    result = validate(example(name))
    assert result["claims"] == []
    # Raíz inválida anula la extracción; un ítem inválido se descarta con código «schema».
    assert result["errors"] or any(item["code"] == "schema" for item in result["rejected"])


def test_one_malformed_finding_does_not_discard_the_others():
    payload = example("valid_fault_scenario.json")
    payload["attributes"][1].pop("value")
    result = validate(payload)
    assert [(i["finding_id"], i["code"]) for i in result["rejected"]] == [("a2", "schema")]
    assert {c["kind"] for c in result["claims"]} == {"entity", "attribute"}
    # Sin unidad, «12,5» no es una corriente: el atributo cae por dimensión, no por esquema.
    payload = example("valid_fault_scenario.json")
    payload["attributes"][0].pop("unit")
    codes = [i["code"] for i in validate(payload)["rejected"]]
    assert codes == ["incompatible_unit"]


def test_backlog_example_yields_entity_attribute_and_relation_claims():
    claims = validate(example("valid_transformer_supplies_panel.json"))["claims"]
    by_kind = {claim["kind"]: claim for claim in claims}
    attribute = by_kind["attribute"]
    assert attribute["value_si"] == pytest.approx(13800)
    assert attribute["unit"] == "V" and attribute["value_literal"] == "13,8"
    evidence = attribute["evidence"][0]
    assert evidence["locator"]["page"] == 4
    assert PAGE_4[evidence["locator"]["start"] - len("Portada del proyecto\n"):].startswith(
        "El transformador T1")
    relation = by_kind["relation"]
    assert relation["relation_type"] == "SUPPLIES"
    assert relation["source_key"] == next(c["entity_key"] for c in claims
                                          if c.get("name") == "T1")


def test_quote_must_exist_in_the_located_page():
    payload = example("valid_transformer_supplies_panel.json")
    payload["evidence"][0]["locator"] = {"page": 3}
    result = validate(payload)
    assert result["claims"] == []
    codes = {item["finding_id"]: item["code"] for item in result["rejected"]}
    # Sin entidades válidas, el atributo y la relación caen con ellas (no quedan huérfanos).
    assert codes == {"e1": "missing_evidence", "e3": "missing_evidence",
                     "a1": "unresolved_subject", "r1": "unresolved_endpoint"}
    assert "no aparece" in result["rejected"][0]["message"]


def test_quote_matching_tolerates_whitespace_and_case():
    payload = example("valid_transformer_supplies_panel.json")
    payload["evidence"][0]["quote"] = "el  TRANSFORMADOR T1,\n13,8 kV, alimenta el tablero TD-2"
    result = validate(payload)
    assert result["rejected"] == []
    assert result["claims"][0]["evidence"][0]["quote"].startswith("El transformador")


def test_incompatible_relation_endpoints_are_rejected():
    payload = example("valid_transformer_supplies_panel.json")
    payload["relations"][0]["type"] = "PROTECTED_BY"  # el destino debe ser un Breaker
    result = validate(payload)
    assert [item["code"] for item in result["rejected"]] == ["incompatible_endpoints"]
    assert {claim["kind"] for claim in result["claims"]} == {"entity", "attribute"}


def test_out_of_range_and_wrong_dimension_values_are_rejected():
    payload = example("valid_transformer_supplies_panel.json")
    payload["attributes"][0]["unit"] = "kA"
    assert [i["code"] for i in validate(payload)["rejected"]] == ["incompatible_unit"]

    payload = example("valid_fault_scenario.json")
    payload["attributes"][1]["value"] = "500"
    payload["attributes"][1]["unit"] = "s"
    payload["evidence"][0]["quote"] = payload["evidence"][0]["quote"].replace("0,5 s", "500 s")
    rejected = validate(payload, {4: PAGE_4.replace("0,5 s", "500 s")})["rejected"]
    assert [item["code"] for item in rejected] == ["out_of_range"]


def test_value_must_be_quoted_and_unknown_subjects_are_rejected():
    payload = example("valid_transformer_supplies_panel.json")
    payload["attributes"][0]["value"] = "13,2"
    payload["attributes"].append({"id": "a2", "subject_id": "e9", "name": "rated_power",
                                  "value": "1", "unit": "MVA",
                                  "confidence": {"level": "low", "reason": "x"}})
    payload["evidence"][0]["finding_ids"].append("a2")
    codes = {item["finding_id"]: item["code"] for item in validate(payload)["rejected"]}
    assert codes == {"a1": "value_not_in_quote", "a2": "unresolved_subject"}


def test_llm_and_calculation_inputs_always_need_review_rules_stay_proposed():
    llm = validate(example("valid_fault_scenario.json"))["claims"]
    assert all(claim["status"] == NEEDS_REVIEW for claim in merge_claims(llm))
    rules = validate(example("valid_fault_scenario.json"), method="rules")["claims"]
    statuses = {c["kind"] + ":" + str(c.get("attribute")): c["status"] for c in merge_claims(rules)}
    assert statuses["entity:None"] == PROPOSED
    assert statuses["attribute:fault_current"] == NEEDS_REVIEW
    assert ACCEPTED not in statuses.values()


def test_merge_combines_rules_and_llm_evidence_for_the_same_fact():
    rules = validate(example("valid_transformer_supplies_panel.json"), method="rules")["claims"]
    llm = validate(example("valid_transformer_supplies_panel.json"))["claims"]
    merged = merge_claims(rules, llm)
    assert len(merged) == len(rules)
    assert all(set(claim["methods"]) == {"rules", "llm"} for claim in merged)


def test_number_parsing_flags_ambiguous_thousands_separator():
    assert parse_number("13,8") == (13.8, ())
    assert parse_number("1.234,5")[0] == 1234.5
    value, notes = parse_number("1,200")
    assert value == 1.2 and notes
    with pytest.raises(ValueError):
        parse_quantity("10", "furlong")


@pytest.mark.parametrize("unit, value_si", [
    ("mV", 1e-3), ("MV", 1e6), ("kV", 1e3), ("KV", 1e3), ("mA", 1e-3), ("mW", 1e-3),
    ("MW", 1e6), ("Mw", 1e6), ("MVA", 1e6), ("Mva", 1e6), ("mΩ", 1e-3), ("MΩ", 1e6),
    ("mm", 1e-3), ("MM", 1e-3), ("m", 1.0), ("Ω·m", 1.0),
])
def test_unit_prefix_case_distinguishes_milli_from_mega(unit, value_si):
    assert parse_quantity("1", unit).value_si == pytest.approx(value_si)


def test_milli_volt_ampere_is_not_read_as_mega():
    with pytest.raises(ValueError):
        parse_quantity("1", "mva")


def _attribute(claim_suffix, value_si, literal, status=NEEDS_REVIEW, entity="ent-t1"):
    claim = {"kind": "attribute", "entity_key": entity, "attribute": "rated_voltage",
             "value_si": value_si, "value_literal": literal, "unit_literal": "kV", "unit": "V",
             "qualifier": "", "subject_name": "T1", "status": status, "review_reasons": []}
    claim["content_key"] = content_key(claim)
    claim["claim_id"] = claim_id(claim_suffix, claim)
    return claim


def test_consolidation_flags_contradictions_without_overwriting():
    accepted = dict(_attribute("old-run", 13200, "13,2", status=ACCEPTED), filename="a.pdf")
    candidate = _attribute("new-run", 13800, "13,8", status="proposed")
    duplicate = _attribute("new-run-2", 13200, "13.2", status="proposed")
    result = consolidate("project-1", [candidate, duplicate], [accepted])
    assert candidate["status"] == NEEDS_REVIEW
    assert accepted["claim_id"] in candidate["contradicts"]
    assert duplicate["duplicate_of"] == [accepted["claim_id"]]
    assert duplicate["contradicts"] == [candidate["claim_id"]]
    conflict = [q for q in result["questions"] if q["kind"] == "conflict"]
    # 13,2 y 13.2 son el mismo valor: el conflicto con 13,8 es una sola pregunta.
    assert len(conflict) == 1
    assert {candidate["claim_id"], accepted["claim_id"]} <= set(conflict[0]["claim_ids"])
    assert accepted["status"] == ACCEPTED and accepted["value_literal"] == "13,2"


def test_previously_rejected_fact_is_sent_back_to_review():
    rejected = _attribute("old", 13800, "13,8", status=REJECTED)
    candidate = _attribute("new", 13800, "13,8", status=PROPOSED)
    consolidate("project-1", [candidate], [rejected])
    assert candidate["status"] == NEEDS_REVIEW
    assert candidate["duplicate_of"] == [rejected["claim_id"]]


def test_possible_aliases_raise_a_question_and_are_not_merged():
    def entity(run, name):
        claim = {"kind": "entity", "entity_type": "Transformer", "name": name, "aliases": [],
                 "entity_key": f"key-{name}", "status": PROPOSED, "review_reasons": []}
        claim["content_key"] = content_key(claim)
        claim["claim_id"] = claim_id(run, claim)
        return claim

    first, second = entity("r1", "T-01"), entity("r2", "T1")
    questions = consolidate("project-1", [first], [second])["questions"]
    assert compact_tag("T-01") == compact_tag("t 1") == "T1"
    assert first["status"] == NEEDS_REVIEW and first["entity_key"] != second["entity_key"]
    assert questions[0]["kind"] == "alias"


def test_review_decisions_preserve_the_proposed_value():
    claim = _attribute("run", 13800, "13,8")
    claim["attribute"] = "rated_voltage"
    changes = review_decision(claim, "correct", "Placa del equipo", "13,2", "kV")
    assert changes["status"] == ACCEPTED and changes["reviewed_value_si"] == pytest.approx(13200)
    assert "value_literal" not in changes
    with pytest.raises(ReviewError):
        review_decision(claim, "accept", "  ")
    with pytest.raises(ReviewError):
        review_decision(claim, "correct", "ok", "13,2", "kA")
    with pytest.raises(ReviewError):
        review_decision(dict(claim, status="superseded"), "accept", "ok")
    with pytest.raises(ReviewError):
        review_decision({"kind": "relation", "status": PROPOSED}, "correct", "ok", "x")
