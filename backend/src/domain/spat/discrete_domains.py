"""Normalize traceable commercial options into OP-02 discrete domains.

This contract is intentionally catalog- and optimizer-independent. It accepts
curated domain records and explicit project facts; it never infers applicability
from missing facts or converts an option into a continuous interval.
"""

from __future__ import annotations

from math import isfinite
from typing import Any


_DOMAIN_STATUSES = {"draft", "active", "blocked"}
_OPTION_STATUSES = {"available", "withdrawn", "blocked"}
_SCHEMA_VERSION = "spat.optimizer-discrete-domain/1.0"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _source(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{name}.provenance must be a nonempty object")
    return value


def _filters(value: Any, name: str) -> dict[str, Any]:
    """Applicability is a conjunction of exact facts or allowed-value lists."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name}.applicability_filters must be an object")
    normalized = {}
    for key, expected in value.items():
        fact = _text(key, f"{name}.applicability_filters key")
        if isinstance(expected, list):
            if not expected or any(item is None or isinstance(item, (dict, list)) for item in expected):
                raise ValueError(f"{name}.applicability_filters[{fact!r}] must be a nonempty scalar list")
            normalized[fact] = expected
        elif expected is None or isinstance(expected, (dict, list)):
            raise ValueError(f"{name}.applicability_filters[{fact!r}] must be a scalar or scalar list")
        else:
            normalized[fact] = expected
    return normalized


def _matches(filters: dict[str, Any], facts: dict[str, Any]) -> str:
    unknown = False
    for key, expected in filters.items():
        if key not in facts or facts[key] is None:
            unknown = True
            continue
        allowed = expected if isinstance(expected, list) else [expected]
        if facts[key] not in allowed:
            return "not_applicable"
    return "unknown" if unknown else "applicable"


def resolve_discrete_domains(
    domains: list[dict[str, Any]], applicability_facts: dict[str, Any],
) -> dict[str, Any]:
    """Return candidate option records, preserving provenance and fail-closed status.

    An active domain with available, applicable options is emitted as ``ready``.
    Unknown project facts produce ``unknown`` option status and do not become
    candidates. Draft/blocked domains and withdrawn/blocked options are retained
    for traceability but never emitted to OP-02 as selectable candidates.
    """
    if not isinstance(domains, list):
        raise ValueError("domains must be a list")
    if not isinstance(applicability_facts, dict):
        raise ValueError("applicability_facts must be an object")

    seen_domains: set[str] = set()
    output = []
    for index, domain in enumerate(domains):
        name = f"domains[{index}]"
        if not isinstance(domain, dict):
            raise ValueError(f"{name} must be an object")
        domain_id = _text(domain.get("domain_id"), f"{name}.domain_id")
        if domain_id in seen_domains:
            raise ValueError(f"duplicate domain_id {domain_id!r}")
        seen_domains.add(domain_id)
        target = _text(domain.get("target"), f"{name}.target")
        unit = _text(domain.get("unit"), f"{name}.unit")
        status = _text(domain.get("status"), f"{name}.status")
        if status not in _DOMAIN_STATUSES:
            raise ValueError(f"{name}.status must be one of {sorted(_DOMAIN_STATUSES)}")
        domain_source = _source(domain.get("provenance"), name)
        raw_options = domain.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise ValueError(f"{name}.options must be a nonempty list")

        option_ids: set[str] = set()
        options = []
        for option_index, option in enumerate(raw_options):
            option_name = f"{name}.options[{option_index}]"
            if not isinstance(option, dict):
                raise ValueError(f"{option_name} must be an object")
            option_id = _text(option.get("option_id"), f"{option_name}.option_id")
            if option_id in option_ids:
                raise ValueError(f"duplicate option_id {option_id!r} in domain {domain_id!r}")
            option_ids.add(option_id)
            value = option.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{option_name}.value must be a finite number")
            option_status = _text(option.get("status", "available"), f"{option_name}.status")
            if option_status not in _OPTION_STATUSES:
                raise ValueError(f"{option_name}.status must be one of {sorted(_OPTION_STATUSES)}")
            filters = _filters(option.get("applicability_filters"), option_name)
            applicability = _matches(filters, applicability_facts)
            option_source = _source(option.get("provenance", domain_source), option_name)
            if status != "active":
                applicability = "unknown" if status == "draft" else "not_applicable"
            if option_status != "available":
                applicability = "not_applicable"
            options.append({
                "option_id": option_id,
                "value": float(value),
                "unit": unit,
                "status": option_status,
                "applicability": applicability,
                "applicability_filters": filters,
                "provenance": option_source,
            })

        eligible = [item for item in options if item["status"] == "available"
                    and item["applicability"] == "applicable"]
        output.append({
            "domain_id": domain_id,
            "target": target,
            "unit": unit,
            "status": "ready" if eligible else ("unknown" if any(
                item["applicability"] == "unknown" for item in options) else "blocked"),
            "provenance": domain_source,
            "options": options,
            "candidate_option_ids": [item["option_id"] for item in eligible],
            "candidate_values": [item["value"] for item in eligible],
        })
    return {"schema_version": _SCHEMA_VERSION, "domains": output}
