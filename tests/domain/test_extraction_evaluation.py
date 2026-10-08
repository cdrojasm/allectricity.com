import json
from pathlib import Path

import pytest

from src.domain.knowledge_graph.evaluation import aggregate, regressions, score_document
from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, ENTITY_TYPES, RELATION_RULES

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evaluation" / "extraction" / "v1"
MANIFEST = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
GOLD = [(name, json.loads((DATASET / name).read_text(encoding="utf-8")))
        for case in MANIFEST["cases"] for name in case["documents"]]


def _as_list(value):
    return value if isinstance(value, list) else [value]


@pytest.mark.parametrize("name, gold", GOLD, ids=[name for name, _ in GOLD])
def test_gold_documents_respect_the_taxonomy(name, gold):
    assert (ROOT / gold["file"]).is_file()
    refs = {}
    for entity in gold["entities"]:
        assert entity["type"] in ENTITY_TYPES and ENTITY_TYPES[entity["type"]].llm_extractable
        assert entity["ref"] not in refs, f"ref repetida {entity['ref']}"
        refs[entity["ref"]] = entity["type"]
    for attribute in gold["attributes"]:
        spec = ATTRIBUTES[attribute["name"]]
        for subject in _as_list(attribute["subject"]):
            assert refs[subject] in spec.subjects, f"{subject}.{attribute['name']}"
        assert spec.is_quantity == ("value_si" in attribute or "values_si" in attribute)
    for relation in gold["relations"]:
        rule = RELATION_RULES[relation["type"]]
        assert rule.allows(refs[relation["source"]], refs[relation["target"]]), relation
    for rule in gold["forbidden"]:
        for key in ("subject", "source", "target"):
            if key in rule:
                assert rule[key] in refs


def entity(entity_type, name, page=1, status="proposed"):
    return {"kind": "entity", "entity_type": entity_type, "name": name, "status": status,
            "evidence": [{"locator": {"page": page}}]}


def attribute(subject_type, subject, name, value_si, literal, page=1, **extra):
    return {"kind": "attribute", "entity_type": subject_type, "subject_name": subject,
            "attribute": name, "value_si": value_si, "value_literal": literal,
            "status": "needs_review", "evidence": [{"locator": {"page": page}}], **extra}


def relation(kind, source, target, symmetric=False, page=1):
    return {"kind": "relation", "relation_type": kind, "symmetric": symmetric,
            "source_type": source[0], "source_name": source[1], "target_type": target[0],
            "target_name": target[1], "status": "needs_review",
            "evidence": [{"locator": {"page": page}}]}


GOLD_DOC = {
    "entities": [
        {"ref": "T1", "type": "Transformer", "names": ["T1"], "locator": {"page": 1}},
        {"ref": "TD-2", "type": "ElectricalPanel", "names": ["TD-2"]},
        {"ref": "malla", "type": "GroundingGrid", "names": ["malla principal"], "optional": True},
    ],
    "attributes": [
        {"subject": "T1", "name": "rated_voltage", "value_si": 13800, "locator": {"page": 1}},
        {"subject": "T1", "name": "frequency", "value_si": 60},
    ],
    "relations": [{"type": "SUPPLIES", "source": "T1", "target": "TD-2"}],
    "forbidden": [{"kind": "relation", "type": "*", "source": "TD-2", "target": "malla"}],
    "questions": [{"kind": "alias", "mentions": ["T-01", "T1"]}],
}


def test_scoring_counts_hits_errors_and_ignores_optional_items():
    claims = [
        entity("Transformer", "t1"), entity("ElectricalPanel", "TD-2"),
        entity("GroundingGrid", "malla principal"), entity("Breaker", "52-T1"),
        attribute("Transformer", "T1", "rated_voltage", 13800.0, "13,8", page=2),
        attribute("Transformer", "T1", "frequency", 50.0, "50"),
        relation("SUPPLIES", ("Transformer", "T1"), ("ElectricalPanel", "TD-2")),
    ]
    score = score_document(GOLD_DOC, claims, [{"kind": "alias",
                                               "question": "¿«T-01» y «T1» son el mismo?"}])
    assert score["counts"]["entities"] == {"tp": 2, "fp": 1, "fn": 0}
    assert score["counts"]["attributes"] == {"tp": 1, "fp": 1, "fn": 1}
    assert score["counts"]["relations"] == {"tp": 1, "fp": 0, "fn": 0}
    assert score["evidence"] == {"checked": 2, "correct": 1}  # T1 en p1; tensión en p2
    assert score["questions"] == {"expected": 1, "found": 1}
    assert {e["kind"] for e in score["errors"]} >= {"wrong_value", "wrong_locator",
                                                     "false_positive", "missed"}
    metrics = aggregate([score])
    assert metrics["entities"]["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["abstention"] == 1.0


def test_duplicates_forbidden_relations_and_state_invariants_are_reported():
    claims = [
        entity("Transformer", "T1"), entity("Transformer", "T1", status="accepted"),
        entity("ElectricalPanel", "TD-2"), entity("GroundingGrid", "malla principal"),
        relation("BONDED_TO", ("GroundingGrid", "malla principal"),
                 ("ElectricalPanel", "TD-2"), symmetric=True),
        attribute("Transformer", "T1", "rated_voltage", 13800.0, "13,8",
                  feeds_calculation=True, status="proposed"),
    ]
    score = score_document(GOLD_DOC, claims)
    assert score["duplicates"]["entities"] == 1
    assert score["forbidden"] == {"total": 1, "violations": 1}
    assert score["invariants"] == {"accepted": 1, "calculation_inputs_not_in_review": 1}
    assert score["questions"] == {"expected": 1, "found": 0}
    assert aggregate([score])["abstention"] == 0.0


def test_text_values_and_alternative_subjects_and_values():
    gold = {"entities": [{"ref": "F3", "type": "FaultScenario", "names": ["F3"]},
                         {"ref": "SPT", "type": "GroundingSystem", "names": None}],
            "attributes": [
                {"subject": "F3", "name": "fault_current", "values_si": [1.25, 1250]},
                {"subject": ["F3", "SPT"], "name": "standard_edition", "value": "IEEE 80-2013"}],
            "relations": []}
    claims = [entity("FaultScenario", "F3"), entity("GroundingSystem", "cualquier nombre"),
              attribute("FaultScenario", "F3", "fault_current", 1250.0, "1250"),
              attribute("GroundingSystem", "cualquier nombre", "standard_edition", None,
                        "ieee 80-2013")]
    assert score_document(gold, claims)["counts"]["attributes"] == {"tp": 2, "fp": 0, "fn": 0}


def test_regressions_block_drops_against_the_baseline_and_absolute_limits():
    thresholds = {"max": {"invariants.accepted": 0}, "min": {"abstention": 1.0},
                  "max_drop": {"overall.f1": 0.02, "relations.recall": 0.05}}
    baseline = {"overall": {"f1": 0.80}, "relations": {"recall": None}}
    good = {"overall": {"f1": 0.79}, "relations": {"recall": 0.1}, "abstention": 1.0,
            "invariants": {"accepted": 0}}
    assert regressions(good, thresholds, baseline) == []
    bad = {"overall": {"f1": 0.70}, "relations": {"recall": 0.1}, "abstention": 0.5,
           "invariants": {"accepted": 2}}
    failures = regressions(bad, thresholds, baseline)
    assert len(failures) == 3 and any("overall.f1" in failure for failure in failures)
