from src.domain.knowledge_graph.artifact_mapping import map_claims_to_artifact


def claim(attribute, entity_type, value_si, literal=None, status="needs_review", claim_id=None):
    return {
        "kind": "attribute", "attribute": attribute, "entity_type": entity_type,
        "subject_name": "obj", "value_si": value_si,
        "value_literal": literal or str(value_si), "unit": "SI", "status": status,
        "claim_id": claim_id or attribute,
        "evidence": [{"quote": literal or str(value_si), "locator": {"page": 2}}],
    }


def test_maps_scalar_claims_to_artifact_paths_and_converts_area():
    mapped = map_claims_to_artifact([
        claim("fault_current", "FaultScenario", 12500, "12.5 kA"),
        claim("shock_duration", "FaultScenario", 0.5, "0.5 s"),
        claim("thermal_duration", "FaultScenario", 1.0, "1 s"),
        claim("grid_length", "GroundingGrid", 40, "40 m"),
        claim("grid_width", "GroundingGrid", 20, "20 m"),
        claim("conductor_cross_section", "GridConductor", 0.0001, "100 mm²"),
    ])

    assert mapped["fault.current_a"]["value"] == 12500
    assert mapped["fault.clearing_time_s"]["value"] == 0.5
    assert mapped["conductor.thermal_duration_s"]["value"] == 1.0
    assert mapped["geometry.length_m"]["value"] == 40
    assert mapped["geometry.width_m"]["value"] == 20
    assert mapped["conductor.cross_section_mm2"]["value"] == 100
    assert mapped["fault.current_a"]["claim"]["claim_id"] == "fault_current"


def test_reports_conflict_and_missing_without_picking_a_value():
    mapped = map_claims_to_artifact([
        claim("fault_current", "FaultScenario", 10000, "10 kA", claim_id="a"),
        claim("fault_current", "FaultScenario", 12500, "12.5 kA", claim_id="b"),
    ])

    assert mapped["fault.current_a"]["state"] == "conflicto"
    assert mapped["fault.current_a"]["value"] is None
    assert {candidate["claim_id"] for candidate in mapped["fault.current_a"]["candidates"]} == {"a", "b"}
    assert mapped["fault.clearing_time_s"]["state"] == "falta"


def test_same_value_duplicates_are_found_and_rejected_claims_are_ignored():
    mapped = map_claims_to_artifact([
        claim("grid_length", "GroundingGrid", 40, claim_id="a"),
        claim("grid_length", "GroundingGrid", 40.00000001, claim_id="b"),
        claim("grid_width", "GroundingGrid", 20, status="rejected"),
    ])

    assert mapped["geometry.length_m"]["state"] == "encontrado"
    assert len(mapped["geometry.length_m"]["candidates"]) == 2
    assert mapped["geometry.width_m"]["state"] == "falta"
