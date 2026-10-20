import pytest
from pydantic import ValidationError

from src.domain.spat.artifact_contract import group_results_by_building, validate_artifact, validate_document
from src.infrastructure.entrypoint.api.schemas import GroundingArtifactRequest, PotentialCalculationRequest


def test_artifact_snapshot_matches_published_schema():
    snapshot = GroundingArtifactRequest.model_validate({"name": "Malla piloto"}).model_dump(
        mode="json", exclude={"buildings", "networks", "electrodes", "connections"})
    assert snapshot["schema_version"] == "1.0"
    assert validate_artifact(snapshot) is snapshot


@pytest.mark.parametrize("payload", [
    {"name": "Malla piloto", "unexpected": True},
    {"name": "Malla piloto", "geometry": {"length_m": 20, "width_m": 20,
                                               "conductor_spacing_m": 2, "mystery": 1}},
    {"name": "Malla piloto", "fault": {"current_a": 1000, "clearing_time_s": 0.5, "mystery": 1}},
])
def test_artifact_request_rejects_unknown_fields(payload):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GroundingArtifactRequest.model_validate(payload)


def test_artifact_validator_rejects_unknown_and_unsupported_versions():
    valid = GroundingArtifactRequest.model_validate({"name": "Malla piloto"}).model_dump(
        mode="json", exclude={"buildings", "networks", "electrodes", "connections"})
    with pytest.raises(ValueError, match="Unsupported design artifact schema_version"):
        validate_artifact({**valid, "schema_version": "99.0"})
    with pytest.raises(ValueError, match="Invalid design artifact"):
        validate_artifact({**valid, "surprise": True})


def test_artifact_v2_decouples_buildings_networks_and_electrodes_and_groups_results():
    geometry = {"length_m": 20, "width_m": 20, "conductor_spacing_m": 2}
    snapshot = GroundingArtifactRequest.model_validate({
        "schema_version": "2.0", "name": "Campus",
        "buildings": [
            {"id": "b1", "name": "Edificio A", "network_ids": ["n1"], "electrode_ids": ["e1", "e2"]},
            {"id": "b2", "name": "Edificio B", "network_ids": ["n1"], "electrode_ids": ["e2"]},
        ],
        "networks": [{"id": "n1", "name": "Malla compartida", "geometry": geometry}],
        "electrodes": [
            {"id": "e1", "name": "Varillas A", "geometry": geometry},
            {"id": "e2", "name": "Anillo común", "geometry": geometry},
        ],
    }).model_dump(mode="json", exclude={"geometry"})
    assert validate_artifact(snapshot) is snapshot
    grouped = group_results_by_building(snapshot, {"n1": {"rg": 1.2}},
                                        {"e1": {"rg": 2.0}, "e2": {"rg": 3.0}})
    assert set(grouped["b1"]["networks"]) == {"n1"}
    assert set(grouped["b2"]["networks"]) == {"n1"}
    assert set(grouped["b1"]["electrodes"]) == {"e1", "e2"}
    assert set(grouped["b2"]["electrodes"]) == {"e2"}


@pytest.mark.parametrize("payload", [
    {"schema_version": "2.0", "name": "A", "buildings": [{"id": "b", "name": "B", "network_ids": ["missing"]}],
     "networks": [], "electrodes": []},
    {"schema_version": "2.0", "name": "A", "buildings": [], "networks": [], "electrodes": [],
     "geometry": {"length_m": 1, "width_m": 1, "conductor_spacing_m": 1}},
])
def test_artifact_v2_rejects_invalid_links_and_mixed_legacy_geometry(payload):
    with pytest.raises(ValidationError):
        GroundingArtifactRequest.model_validate(payload)


def test_artifact_v2_persistence_validator_rejects_dangling_building_links():
    snapshot = GroundingArtifactRequest.model_validate({
        "schema_version": "2.0", "name": "Campus",
        "buildings": [{"id": "b1", "name": "A"}],
        "networks": [], "electrodes": [],
    }).model_dump(mode="json", exclude={"geometry"})
    snapshot["buildings"][0]["network_ids"] = ["missing"]
    with pytest.raises(ValueError, match="references an unknown network"):
        validate_artifact(snapshot)


def test_calculation_request_accepts_signed_scenarios_and_rejects_double_current_adjustments():
    request = PotentialCalculationRequest.model_validate({
        "scenarios": [{"id": "fault-A", "injections_a": {"network-1": 100.0, "rod-1": -25.0}}],
    })
    assert request.scenarios[0].injections_a == {"network-1": 100.0, "rod-1": -25.0}

    with pytest.raises(ValidationError, match="already include current division"):
        PotentialCalculationRequest.model_validate({
            "scenarios": [{"id": "fault-A", "injections_a": {"network-1": 100.0}}],
            "fault_split": {"split_factor": 0.5, "split_factor_origin": "study"},
        })


def test_result_trace_and_diff_follow_their_versioned_contracts():
    assert validate_document("artifact_diff", [{"path": "name", "before": "A", "after": "B"}])
    with pytest.raises(ValueError, match="Invalid artifact_diff"):
        validate_document("artifact_diff", [{"path": "name", "before": "A", "after": "B", "extra": 1}])
    with pytest.raises(ValueError, match="Invalid calculation_result"):
        validate_document("calculation_result", {"schema_version": "1.0"})
    with pytest.raises(ValueError, match="Invalid calculation_trace"):
        validate_document("calculation_trace", {"schema_version": "1.0"})
