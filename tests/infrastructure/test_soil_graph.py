import pytest

from src.infrastructure.processing.soil_graph import fit_graph_soil_measurements


def soil_claim(attribute, subject, value, claim_id):
    return {"kind": "attribute", "entity_type": "ResistivityReading", "entity_key": subject,
            "subject_name": subject, "attribute": attribute, "value_si": value,
            "value_literal": str(value), "status": "needs_review", "claim_id": claim_id,
            "evidence": [{"locator": {"page": 1}}]}


def test_fit_graph_soil_measurements_reuses_sounding_fit():
    claims = [{"kind": "attribute", "entity_type": "SoilSurvey", "attribute": "array_type",
               "value_literal": "wenner", "status": "needs_review", "claim_id": "array"}]
    for index, spacing in enumerate((1, 2, 4, 8), start=1):
        claims += [soil_claim("probe_spacing", f"r{index}", spacing, f"s{index}"),
                   soil_claim("apparent_resistivity", f"r{index}", 100, f"rho{index}")]

    result = fit_graph_soil_measurements(claims)
    assert result["soil_measurements"]["array"] == "wenner"
    assert result["fit"]["soil_layers"]


def test_fit_graph_soil_measurements_explains_missing_inputs():
    with pytest.raises(ValueError, match="al menos 4 lecturas"):
        fit_graph_soil_measurements([])
