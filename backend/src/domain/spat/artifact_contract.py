"""Versioned JSON contracts for design snapshots and calculation records."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).with_name("schemas")
SUPPORTED_ARTIFACT_SCHEMAS = {"1.0": SCHEMA_DIR / "design-artifact-1.0.json"}
DOCUMENT_SCHEMAS = {
    "calculation_result": SCHEMA_DIR / "calculation-result-1.0.json",
    "calculation_trace": SCHEMA_DIR / "calculation-trace-1.0.json",
    "artifact_diff": SCHEMA_DIR / "artifact-diff-1.0.json",
}


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
    return snapshot


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
