"""Compile traceable OP-05 rules and reject unbuildable optimizer candidates.

This module intentionally contains no country-specific limits. A caller supplies a
curated, versioned profile; only applicable mandatory, constructability, or catalog
bounds become optimizer bounds. Guidance stays advisory.
"""

from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any

from src.domain.spat.grid_geometry import geometry_conflicts, grid_parts


_BOUND_CATEGORIES = {"mandatory", "constructability", "commercial"}
_RULE_CATEGORIES = _BOUND_CATEGORIES | {"guidance"}
_APPLICABILITY = {"applicable", "not_applicable", "unknown"}


class OptimizerGeometryRejected(ValueError):
    """Candidate geometry failed OP-05 checks before the electrical solver call."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        messages = [item["message"] for item in report["violations"]]
        super().__init__("optimizer candidate rejected: " + "; ".join(messages))


def compile_site_translation_bounds(
    geometry: dict[str, Any], requested_variables: list[str],
) -> dict[str, Any]:
    """Derive safe translation intervals from an explicit grid's site envelope.

    These are broad scalar bounds only. Polygon and obstacle feasibility remains an
    exact candidate check in ``geometry_conflicts``; arbitrary polygons are not
    approximated as rectangular limits.
    """
    if not isinstance(geometry, dict):
        raise ValueError("site_geometry must be an object")
    wanted = set(requested_variables) & {"translate_x_m", "translate_y_m"}
    if not wanted:
        return {"bounds": {}, "frozen_variables": {}, "provenance": {}}
    if not geometry.get("conductors"):
        return {"bounds": {}, "frozen_variables": {key: "translation_requires_explicit_conductors" for key in wanted},
                "provenance": {}}
    if "perimeter_extension_m" in requested_variables:
        return {"bounds": {}, "frozen_variables": {key: "translation_bound_coupled_to_perimeter_extension"
                                                       for key in wanted}, "provenance": {}}
    length, width = geometry.get("length_m"), geometry.get("width_m")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not isfinite(value) or value <= 0 for value in (length, width)):
        raise ValueError("site_geometry requires finite positive length_m and width_m")
    points = []
    for index, conductor in enumerate(geometry["conductors"]):
        for endpoint in ("start", "end"):
            point = conductor.get(endpoint) or {}
            x, y = point.get("x"), point.get("y")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
                   for value in (x, y)):
                raise ValueError(f"site_geometry.conductors[{index}].{endpoint} needs finite x and y")
            points.append((float(x), float(y)))
    for index, rod in enumerate(geometry.get("rods") or []):
        x, y = rod.get("x"), rod.get("y")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
               for value in (x, y)):
            raise ValueError(f"site_geometry.rods[{index}] needs finite x and y")
        points.append((float(x), float(y)))
    if not points:
        return {"bounds": {}, "frozen_variables": {key: "site_geometry_has_no_grid_points" for key in wanted},
                "provenance": {}}
    canonical = json.dumps(geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    site_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    bounds, provenance, frozen = {}, {}, {}
    axes = {"translate_x_m": (0, float(length)), "translate_y_m": (1, float(width))}
    for variable in sorted(wanted):
        axis, upper = axes[variable]
        coords = [point[axis] for point in points]
        low, high = -min(coords), upper - max(coords)
        if low > high:
            frozen[variable] = "baseline_grid_outside_site_envelope"
            continue
        bounds[variable] = {"min": low, "max": high}
        provenance[variable] = [{"source_type": "site_geometry_envelope", "site_geometry_sha256": site_hash,
                                 "unit": "m", "min": low, "max": high,
                                 "verification_method": "Exact envelope containment; polygon/obstacle checks remain candidate filters."}]
    return {"bounds": bounds, "frozen_variables": frozen, "provenance": provenance}


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _finite_bound(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _validate_source(source: Any, name: str) -> dict[str, Any]:
    if not isinstance(source, dict) or not source:
        raise ValueError(f"{name}.source must identify the origin of the constraint")
    return source


def resolve_optimizer_constraints(
    profile: dict[str, Any],
    requested_variables: list[str],
) -> dict[str, Any]:
    """Compile profile rules into finite OP-02 bounds and fail-closed diagnostics.

    Rule format is deliberately normalized and independent of any standard:
    ``{id, category, target, applicability, min, max, unit, criterion, source}``.
    Each requested variable is offered only when applicable, sourced finite bounds
    exist. Bounds from multiple applicable rules are intersected. Unknown applicability,
    guidance-only ranges, missing bounds, and inconsistent intersections freeze the
    variable. Mandatory criteria declared by the profile are checked separately so a
    missing electrical safety rule cannot be mistaken for compliance.
    """
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    profile_id = _nonempty_string(profile.get("profile_id"), "profile.profile_id")
    version = _nonempty_string(profile.get("version"), "profile.version")
    jurisdiction = _nonempty_string(profile.get("jurisdiction"), "profile.jurisdiction")
    installation_type = _nonempty_string(profile.get("installation_type"), "profile.installation_type")
    if "required_mandatory_criteria" not in profile:
        raise ValueError("profile.required_mandatory_criteria must explicitly declare profile coverage")
    required_criteria = profile["required_mandatory_criteria"]
    rules = profile.get("rules", [])
    if not isinstance(required_criteria, list) or any(not isinstance(item, str) or not item for item in required_criteria):
        raise ValueError("profile.required_mandatory_criteria must be a list of nonempty strings")
    if not isinstance(rules, list):
        raise ValueError("profile.rules must be a list")
    if not isinstance(requested_variables, list) or any(not isinstance(item, str) or not item for item in requested_variables):
        raise ValueError("requested_variables must be a list of parameter paths")
    if len(set(requested_variables)) != len(requested_variables):
        raise ValueError("requested_variables must not contain duplicates")

    normalized_rules = []
    ids = set()
    for index, rule in enumerate(rules):
        name = f"profile.rules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{name} must be an object")
        rule_id = _nonempty_string(rule.get("id"), f"{name}.id")
        if rule_id in ids:
            raise ValueError(f"duplicate rule id {rule_id!r}")
        ids.add(rule_id)
        category = _nonempty_string(rule.get("category"), f"{name}.category")
        if category not in _RULE_CATEGORIES:
            raise ValueError(f"{name}.category must be one of {sorted(_RULE_CATEGORIES)}")
        applicability = _nonempty_string(rule.get("applicability"), f"{name}.applicability")
        if applicability not in _APPLICABILITY:
            raise ValueError(f"{name}.applicability must be one of {sorted(_APPLICABILITY)}")
        target = _nonempty_string(rule.get("target"), f"{name}.target") if rule.get("target") is not None else None
        criterion = _nonempty_string(rule.get("criterion"), f"{name}.criterion") if rule.get("criterion") is not None else None
        verification_method = _nonempty_string(rule.get("verification_method"), f"{name}.verification_method")
        applicability_conditions = rule.get("applicability_conditions")
        if not isinstance(applicability_conditions, list) or not applicability_conditions \
                or any(not isinstance(condition, str) or not condition.strip() for condition in applicability_conditions):
            raise ValueError(f"{name}.applicability_conditions must contain nonempty explanations")
        source = _validate_source(rule.get("source"), name)
        item = {"id": rule_id, "category": category, "applicability": applicability,
                "target": target, "criterion": criterion, "source": source,
                "verification_method": verification_method,
                "applicability_conditions": [condition.strip() for condition in applicability_conditions]}
        if rule.get("expression") is not None:
            item["expression"] = _nonempty_string(rule["expression"], f"{name}.expression")
        if "min" in rule or "max" in rule:
            if "min" not in rule or "max" not in rule:
                raise ValueError(f"{name} must declare both min and max for optimizer bounds")
            low = _finite_bound(rule["min"], f"{name}.min")
            high = _finite_bound(rule["max"], f"{name}.max")
            if low > high:
                raise ValueError(f"{name}.min must not exceed max")
            unit = _nonempty_string(rule.get("unit"), f"{name}.unit")
            item.update({"min": low, "max": high, "unit": unit})
        normalized_rules.append(item)

    missing_mandatory = []
    for criterion in required_criteria:
        if not any(rule["category"] == "mandatory" and rule["criterion"] == criterion
                   and rule["applicability"] == "applicable" for rule in normalized_rules):
            missing_mandatory.append(criterion)

    bounds: dict[str, dict[str, float]] = {}
    frozen: dict[str, str] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    for target in requested_variables:
        matches = [rule for rule in normalized_rules if rule["target"] == target]
        uncertain = [rule for rule in matches if rule["applicability"] == "unknown"]
        restrictive = [rule for rule in matches if rule["applicability"] == "applicable"
                       and rule["category"] in _BOUND_CATEGORIES and "min" in rule]
        if uncertain:
            frozen[target] = "applicability_unknown"
        elif not restrictive:
            if any(rule["category"] == "guidance" and rule["applicability"] == "applicable" for rule in matches):
                frozen[target] = "guidance_is_advisory"
            else:
                frozen[target] = "no_applicable_sourced_bounds"
        else:
            units = {rule["unit"] for rule in restrictive}
            if len(units) != 1:
                frozen[target] = "incompatible_bound_units"
                continue
            low = max(rule["min"] for rule in restrictive)
            high = min(rule["max"] for rule in restrictive)
            if low > high:
                frozen[target] = "conflicting_bounds"
            else:
                bounds[target] = {"min": low, "max": high}
                provenance[target] = [
                    {"rule_id": rule["id"], "category": rule["category"], "unit": rule["unit"],
                     "min": rule["min"], "max": rule["max"], "expression": rule.get("expression"),
                     "verification_method": rule["verification_method"],
                     "applicability_conditions": rule["applicability_conditions"],
                     "source": rule["source"]}
                    for rule in restrictive
                ]

    status = "blocked" if missing_mandatory else "ready"
    if missing_mandatory:
        for target in bounds:
            frozen[target] = "mandatory_criteria_missing"

    return {
        "schema_version": "spat.optimizer-constraints/1.0",
        "profile": {"profile_id": profile_id, "version": version,
                    "jurisdiction": jurisdiction, "installation_type": installation_type},
        "status": status,
        "required_mandatory_criteria": list(required_criteria),
        "missing_mandatory_criteria": missing_mandatory,
        "rule_provenance": [dict(rule) for rule in normalized_rules],
        "variable_bounds": bounds,
        "optimizable_variables": sorted(bounds) if status == "ready" else [],
        "frozen_variables": frozen,
        "bound_provenance": provenance,
    }


def evaluate_optimizer_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Check site polygons, obstacles, rod contacts, and single-network connectivity."""
    conflicts = geometry_conflicts(geometry)
    violations = [{"kind": item.get("kind", "geometry"), "element": item.get("element"),
                   "index": item.get("index"), "message": item["message"]}
                  for item in conflicts]
    if not conflicts:
        try:
            parts = grid_parts(geometry)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            violations.append({"kind": "connectivity", "element": "geometry", "index": None,
                               "message": f"grid connectivity could not be evaluated: {exc}"})
        else:
            if parts != 1:
                violations.append({"kind": "connectivity", "element": "grid", "index": None,
                                   "message": f"grid has {parts} disconnected parts; connect them or evaluate each system separately"})
    return {"schema_version": "spat.optimizer-geometry-check/1.0",
            "status": "rejected" if violations else "valid", "violations": violations}


def require_optimizer_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return the successful geometry report or raise before solver evaluation."""
    report = evaluate_optimizer_geometry(geometry)
    if report["violations"]:
        raise OptimizerGeometryRejected(report)
    return report
