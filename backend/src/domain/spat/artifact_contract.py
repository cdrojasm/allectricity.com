"""Versioned JSON contracts for design snapshots and calculation records."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.domain.spat.thermal_profile import DEFAULT_THERMAL_PROFILE, DEFAULT_VOLTAGE_LEVEL, RETIE_PROFILE_ID

SCHEMA_DIR = Path(__file__).with_name("schemas")
SUPPORTED_ARTIFACT_SCHEMAS = {
    "1.0": SCHEMA_DIR / "design-artifact-1.0.json",
    "2.0": SCHEMA_DIR / "design-artifact-2.0.json",
}
DOCUMENT_SCHEMAS = {
    "calculation_result": SCHEMA_DIR / "calculation-result-1.0.json",
    "calculation_trace": SCHEMA_DIR / "calculation-trace-1.0.json",
    "calculation_result_v2": SCHEMA_DIR / "calculation-result-2.0.json",
    "calculation_trace_v2": SCHEMA_DIR / "calculation-trace-2.0.json",
    "artifact_diff": SCHEMA_DIR / "artifact-diff-1.0.json",
}


# Fields the frozen 1.0 contract does not know; a request dumped for a 1.0 snapshot must not carry them.
V1_UNSUPPORTED_FIELDS = ("buildings", "networks", "electrodes", "connections")


def snapshot_fields(data: dict) -> dict:
    """Trim a dumped artifact request to the fields its schema version stores (the one place that knows).

    The conductor's `thermal_profile` and `voltage_level` are stored only when they differ from the default, so
    artifacts that do not use them stay identical to what was saved before they existed (no phantom diff).
    """
    if data.get("schema_version") == "1.0":
        for key in V1_UNSUPPORTED_FIELDS:
            data.pop(key, None)
    else:
        data.pop("geometry", None)
    conductor = data.get("conductor")
    if isinstance(conductor, dict):
        if conductor.get("thermal_profile") == DEFAULT_THERMAL_PROFILE:
            conductor.pop("thermal_profile")
        if conductor.get("thermal_profile") != RETIE_PROFILE_ID or conductor.get("voltage_level") == DEFAULT_VOLTAGE_LEVEL:
            conductor.pop("voltage_level", None)
    return data


def _load(path: Path) -> dict:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def validate_artifact(snapshot: dict) -> dict:
    """Validate and return a snapshot using the JSON Schema named by its version marker."""
    if not isinstance(snapshot, dict):
        raise ValueError("Design artifact snapshot must be an object")
    version = snapshot.get("schema_version")
    path = SUPPORTED_ARTIFACT_SCHEMAS.get(version)
    if path is None:
        raise ValueError(f"Unsupported design artifact schema_version: {version!r}")
    errors = sorted(Draft202012Validator(_load(path)).iter_errors(snapshot), key=lambda e: list(e.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(f"Invalid design artifact at {location}: {error.message}")
    if version == "2.0":
        for field in ("buildings", "networks", "electrodes"):
            identifiers = [item["id"] for item in snapshot.get(field, [])]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"Invalid design artifact: {field} ids must be unique")
        network_ids = {item["id"] for item in snapshot.get("networks", [])}
        electrode_ids = {item["id"] for item in snapshot.get("electrodes", [])}
        if len(network_ids | electrode_ids) != len(network_ids) + len(electrode_ids):
            raise ValueError("Invalid design artifact: network and electrode ids must be globally unique")
        for building in snapshot.get("buildings", []):
            if not set(building.get("network_ids", [])) <= network_ids:
                raise ValueError(f"Invalid design artifact: building {building['id']!r} references an unknown network")
            if not set(building.get("electrode_ids", [])) <= electrode_ids:
                raise ValueError(f"Invalid design artifact: building {building['id']!r} references an unknown electrode")
        entity_ids = network_ids | electrode_ids
        connection_ids = [item["id"] for item in snapshot.get("connections", [])]
        if len(connection_ids) != len(set(connection_ids)):
            raise ValueError("Invalid design artifact: electrical connection ids must be unique")
        for connection in snapshot.get("connections", []):
            if connection["group_a"] == connection["group_b"]:
                raise ValueError(f"Invalid design artifact: connection {connection['id']!r} must join distinct entities")
            if connection["group_a"] not in entity_ids or connection["group_b"] not in entity_ids:
                raise ValueError(f"Invalid design artifact: connection {connection['id']!r} references an unknown entity")
    return snapshot


def group_results_by_building(snapshot: dict, network_results: dict, electrode_results: dict) -> dict:
    """Group independently calculated network/electrode records through artifact associations.

    Result payloads remain owned by the calculation layer; this function only applies v2 links.
    """
    if snapshot.get("schema_version") != "2.0":
        raise ValueError("Building result grouping requires design artifact schema_version 2.0")
    return {
        building["id"]: {
            "building": building,
            "networks": {key: network_results[key] for key in building.get("network_ids", []) if key in network_results},
            "electrodes": {key: electrode_results[key] for key in building.get("electrode_ids", []) if key in electrode_results},
        }
        for building in snapshot.get("buildings", [])
    }


def validate_document(kind: str, document):
    """Validate a result, trace, or diff against its published 1.0 contract."""
    path = DOCUMENT_SCHEMAS.get(kind)
    if path is None:
        raise ValueError(f"Unknown artifact contract: {kind}")
    errors = list(Draft202012Validator(_load(path)).iter_errors(document))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(f"Invalid {kind} at {location}: {error.message}")
    return document
