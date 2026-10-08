from src.domain.knowledge_graph.conflict_resolution import resolve_conflicts


def claim(value, claim_id, *, status="needs_review", document_type=None, document_date=None):
    return {
        "kind": "attribute", "entity_key": "fault-1", "entity_type": "FaultScenario",
        "subject_name": "F1", "attribute": "fault_current", "value_si": value,
        "value_literal": str(value), "status": status, "claim_id": claim_id,
        "document_type": document_type, "document_date": document_date,
    }


def test_preferred_document_and_newer_date_resolve_without_mutating_claims():
    old = claim(10000, "old", document_type="report", document_date="2025-01-01")
    preferred = claim(12500, "preferred", document_type="calculation", document_date="2024-01-01")
    result = resolve_conflicts([old, preferred])

    entry = result["entries"][0]
    assert entry["state"] == "encontrado"
    assert entry["selected"]["claim_id"] == "preferred"
    assert old["status"] == "needs_review" and preferred["status"] == "needs_review"
    assert result["questions"] == []


def test_same_priority_produces_question():
    result = resolve_conflicts([claim(10000, "a", document_date="2025-01-01"),
                                claim(12500, "b", document_date="2025-01-01")])

    assert result["entries"][0]["state"] == "conflicto"
    assert result["entries"][0]["selected"] is None
    assert result["questions"][0]["claim_ids"] == ["a", "b"]


def test_accepted_claim_wins_over_document_priority():
    result = resolve_conflicts([
        claim(10000, "accepted", status="accepted", document_type="report", document_date="2024-01-01"),
        claim(12500, "new", document_type="calculation", document_date="2026-01-01"),
    ])

    assert result["entries"][0]["selected"]["claim_id"] == "accepted"
