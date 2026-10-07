import pytest
from pydantic import ValidationError

from src.domain.spat.artifact_contract import validate_artifact, validate_document
from src.infrastructure.entrypoint.api.schemas import GroundingArtifactRequest


def test_artifact_snapshot_matches_published_schema():
    snapshot = GroundingArtifactRequest.model_validate({"name": "Malla piloto"}).model_dump(mode="json")
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
    valid = GroundingArtifactRequest.model_validate({"name": "Malla piloto"}).model_dump(mode="json")
    with pytest.raises(ValueError, match="Unsupported design artifact schema_version"):
        validate_artifact({**valid, "schema_version": "99.0"})
    with pytest.raises(ValueError, match="Invalid design artifact"):
        validate_artifact({**valid, "surprise": True})


def test_result_trace_and_diff_follow_their_versioned_contracts():
    assert validate_document("artifact_diff", [{"path": "name", "before": "A", "after": "B"}])
    with pytest.raises(ValueError, match="Invalid artifact_diff"):
        validate_document("artifact_diff", [{"path": "name", "before": "A", "after": "B", "extra": 1}])
    with pytest.raises(ValueError, match="Invalid calculation_result"):
        validate_document("calculation_result", {"schema_version": "1.0"})
    with pytest.raises(ValueError, match="Invalid calculation_trace"):
        validate_document("calculation_trace", {"schema_version": "1.0"})
