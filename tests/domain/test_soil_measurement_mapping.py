from src.domain.knowledge_graph.artifact_mapping import map_soil_measurements


def claim(attribute, subject, value, claim_id, page):
    return {
        "kind": "attribute", "entity_type": "ResistivityReading", "entity_key": subject,
        "subject_name": subject, "attribute": attribute, "value_si": value,
        "value_literal": str(value), "status": "needs_review", "claim_id": claim_id,
        "evidence": [{"quote": str(value), "locator": {"page": page}}],
    }


def test_groups_readings_in_si_and_preserves_locator():
    claims = [{"kind": "attribute", "entity_type": "SoilSurvey", "attribute": "array_type",
               "value_literal": "Wenner", "status": "needs_review", "claim_id": "array"}]
    for index, spacing in enumerate((1, 2, 4, 8), start=1):
        claims += [claim("probe_spacing", f"r{index}", spacing, f"s{index}", index),
                   claim("apparent_resistivity", f"r{index}", 100 + index,
                         f"rho{index}", index)]

    result = map_soil_measurements(claims)
    assert result["valid"] is True and result["array"] == "wenner"
    assert [item["spacing_m"] for item in result["measurements"]] == [1, 2, 4, 8]
    assert result["measurements"][0]["locator"] == "page=1"


def test_incomplete_reading_is_pending_and_conflicting_array_is_not_selected():
    result = map_soil_measurements([
        claim("probe_spacing", "r1", 1, "s1", 1),
        {"kind": "attribute", "entity_type": "SoilSurvey", "attribute": "array_type",
         "value_literal": "wenner", "status": "needs_review", "claim_id": "a"},
        {"kind": "attribute", "entity_type": "SoilSurvey", "attribute": "array_type",
         "value_literal": "schlumberger", "status": "needs_review", "claim_id": "b"},
    ])

    assert result["state"] == "incompleto" and result["array"] is None
    assert result["pending"][0]["missing"] == ["apparent_resistivity"]
