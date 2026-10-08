from src.domain.knowledge_graph.interrogation import build_interrogation, interrogation_text


def claim(attribute, value, claim_id, filename="memoria.pdf"):
    return {"kind": "attribute", "attribute": attribute, "status": "needs_review",
            "claim_id": claim_id, "value_si": value, "value_literal": str(value),
            "unit_literal": "SI", "filename": filename}


def test_interrogation_counts_found_conflicts_missing_and_confirmable():
    summary = build_interrogation([
        claim("fault_current", 12000, "if"),
        claim("shock_duration", 0.5, "ts"),
        claim("grid_length", 40, "gl"),
        claim("grid_length", 50, "gl2"),
    ], [{"kind": "conflict", "claim_ids": ["gl", "gl2"]}])

    assert summary["found_count"] == 2
    assert summary["conflict_count"] == 1
    assert summary["missing_count"] == 5
    assert set(summary["confirmable_claim_ids"]) == {"if", "ts"}
    assert "Encontré 2 de 8" in interrogation_text(summary, "memoria.pdf")
