"""End-to-end design evaluation for the grounding-grid optimizer (OP-04).

This adapter composes the deterministic geometry generator, stateless solver API and
the explicit safety-criteria API. It deliberately has no persistence or search logic.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite
from threading import Lock
from typing import Any, Callable

from src.domain.spat.optimizer_foundations import generate_rectangular_grid
from src.domain.spat.optimizer_constraints import require_optimizer_geometry
from src.domain.spat.parametric_geometry import generate_traced_grid
from src.infrastructure.calculations import safety_criteria, solver_evaluation
from src.infrastructure.calculations.optimizer_safety import utilization_from_exposure
from src.infrastructure.calculations.potential_engine_client import (
    PotentialEngineClient,
    PotentialPoint,
    SoilModel,
)


class EvaluationBudgetExceeded(RuntimeError):
    """Raised when an optimizer tries to exceed its configured solver-call budget."""


@dataclass
class EvaluationContext:
    """Thread-safe count/budget shared by all candidates in one optimization run.

    The count records solver evaluations started, including calls which later fail
    numerically. Invalid geometry rejected before the solver call is not counted.
    """

    max_evaluations: int | None = None
    _count: int = field(default=0, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def reserve(self) -> int:
        with self._lock:
            if self.max_evaluations is not None and self._count >= self.max_evaluations:
                raise EvaluationBudgetExceeded(
                    f"evaluation budget exhausted ({self.max_evaluations})"
                )
            self._count += 1
            return self._count

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._count


GeometryGenerator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _generate_geometry(base_geometry: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Select the current OP-02 generator for regular or explicitly drawn layouts."""
    if base_geometry.get("conductors"):
        return generate_traced_grid(base_geometry, parameters)
    return generate_rectangular_grid(base_geometry, parameters)


def _numeric_parameter_value(parameters: dict[str, Any], path: str) -> float:
    """Read a dotted/indexed OP-02 numeric path such as rod_lengths_m[0]."""
    current: Any = parameters
    token = ""
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            if token:
                if not isinstance(current, dict) or token not in current:
                    raise ValueError(f"optimized variable {path!r} is absent from the candidate")
                current, token = current[token], ""
            index += 1
        elif char == "[":
            if token:
                if not isinstance(current, dict) or token not in current:
                    raise ValueError(f"optimized variable {path!r} is absent from the candidate")
                current, token = current[token], ""
            close = path.find("]", index + 1)
            if close < 0 or not path[index + 1:close].isdigit():
                raise ValueError(f"invalid optimized variable path {path!r}")
            item_index = int(path[index + 1:close])
            if not isinstance(current, list) or item_index >= len(current):
                raise ValueError(f"optimized variable {path!r} is absent from the candidate")
            current = current[item_index]
            index = close + 1
        else:
            token += char
            index += 1
    if token:
        if not isinstance(current, dict) or token not in current:
            raise ValueError(f"optimized variable {path!r} is absent from the candidate")
        current = current[token]
    if isinstance(current, bool) or not isinstance(current, (int, float)) or not isfinite(current):
        raise ValueError(f"optimized variable {path!r} must be a finite number")
    return float(current)


def _ready_discrete_domains(constraint_context: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not constraint_context or constraint_context.get("status") != "ready":
        return result
    domains = (constraint_context.get("discrete_domains") or {}).get("domains", [])
    for domain in domains:
        if domain.get("status") != "ready" or not domain.get("candidate_values"):
            continue
        target = domain["target"]
        combined = result.setdefault(target, {"candidate_values": [], "options": [], "candidate_option_ids": []})
        combined["candidate_values"].extend(domain["candidate_values"])
        combined["options"].extend(domain.get("options", []))
        combined["candidate_option_ids"].extend(domain.get("candidate_option_ids", []))
    return result


def evaluate_design(
    *,
    design_parameters: dict[str, Any] | None,
    base_geometry: dict[str, Any],
    soil: SoilModel | float,
    injection_a: float,
    points: list[PotentialPoint],
    client: PotentialEngineClient,
    exposure: safety_criteria.FaultExposure,
    standards: list[str],
    settings: dict[str, Any] | None = None,
    context: EvaluationContext | None = None,
    geometry_generator: GeometryGenerator = _generate_geometry,
    constraint_context: dict[str, Any] | None = None,
    optimized_variables: list[str] | None = None,
    level: str = "L2",
) -> dict[str, Any]:
    """Evaluate one design and report solver quantities, safety constraints and status.

    `level` selects the fidelity. L0 only builds the geometry and checks it (invalid geometry
    raises `OptimizerGeometryRejected`, as at every level); it never calls the solver and does not
    count against the evaluation budget. L1 runs the solver on a coarse raster without
    refinements, so `Vs` and `Vt` are lower bounds: a violation is conclusive, a pass is not and
    reports `Feasible=None`. L2 is the full evaluation.

    `design_parameters=None` evaluates a copy of `base_geometry`. Otherwise the selected
    generator maps parameters onto the baseline geometry; the default is the current OP-02
    regular-grid generator. A custom generator can be supplied while OP-02 adds other layout
    families. The solver's `Vs` and `Vt` extrema are compared to limits computed from the
    explicit exposure and standards; no standard or edition is inferred.
    """
    if level not in ("L0", "L1", "L2"):
        raise ValueError("level must be 'L0', 'L1' or 'L2'")
    run = context if context is not None else EvaluationContext()
    selected_discrete_options: dict[str, str] = {}
    if isinstance(design_parameters, dict):
        raw_selected = design_parameters.get("selected_discrete_options", {})
        if not isinstance(raw_selected, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                      for key, value in raw_selected.items()):
            raise ValueError("selected_discrete_options must map parameter paths to option ids")
        selected_discrete_options = dict(raw_selected)
    if optimized_variables is not None:
        if design_parameters is None:
            raise ValueError("design_parameters are required when optimizing variables")
        if constraint_context is None:
            raise ValueError("optimized_variables require a resolved OP-05 constraint_context")
        if constraint_context.get("status") != "ready":
            raise ValueError("optimizer constraint profile is blocked by missing mandatory criteria")
        expected_site_hash = constraint_context.get("site_geometry_sha256")
        if expected_site_hash:
            actual_site_hash = hashlib.sha256(json.dumps(
                base_geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")).hexdigest()
            if actual_site_hash != expected_site_hash:
                raise ValueError("base_geometry differs from the site geometry used to resolve OP-05 bounds")
        discrete_domains = _ready_discrete_domains(constraint_context)
        unexpected_option_paths = sorted(set(selected_discrete_options) - set(optimized_variables))
        if unexpected_option_paths:
            raise ValueError("selected_discrete_options reference unoptimized variables: "
                             + ", ".join(unexpected_option_paths))
        available = (set(constraint_context.get("optimizable_variables") or [])
                     | set(constraint_context.get("discrete_optimizable_variables") or [])
                     | set(discrete_domains))
        unavailable = sorted(set(optimized_variables) - available)
        if unavailable:
            raise ValueError("variables lack applicable sourced bounds and are frozen: " + ", ".join(unavailable))

    parameters = deepcopy(design_parameters)
    if parameters is not None:
        parameters.pop("selected_discrete_options", None)
    if selected_discrete_options and optimized_variables is None:
        raise ValueError("selected_discrete_options require an OP-05 optimization context")
    if parameters is not None and optimized_variables is not None:
        compiled = constraint_context.get("variable_bounds") or {}
        discrete_domains = _ready_discrete_domains(constraint_context)
        supplied = parameters.get("variable_bounds") or {}
        merged = deepcopy(supplied)
        for path in optimized_variables:
            allowed = compiled.get(path)
            domain = discrete_domains.get(path)
            if not allowed and not domain:
                raise ValueError(f"optimized variable {path!r} has neither a resolved bound nor an applicable discrete domain")
            if path in selected_discrete_options and not domain:
                raise ValueError(f"selected catalog option for {path!r} has no applicable discrete domain")
            if domain:
                value = _numeric_parameter_value(parameters, path)
                candidate_ids = set(domain["candidate_option_ids"])
                options = {item["option_id"]: item for item in domain["options"]
                           if item.get("option_id") in candidate_ids}
                requested_id = selected_discrete_options.get(path)
                matching = [item for item in options.values() if item.get("value") == value]
                if requested_id:
                    chosen = options.get(requested_id)
                    if not chosen or chosen.get("value") != value:
                        raise ValueError(f"selected option for {path!r} is not applicable or does not match the candidate value")
                elif len(matching) == 1:
                    selected_discrete_options[path] = matching[0]["option_id"]
                else:
                    raise ValueError(f"candidate for discrete variable {path!r} must select one unambiguous catalog option id")
            if not allowed:
                continue
            proposed = merged.get(path, allowed)
            if not isinstance(proposed, dict) or set(proposed) != {"min", "max"}:
                raise ValueError(f"variable_bounds[{path!r}] must contain exactly min and max")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
                   for value in proposed.values()):
                raise ValueError(f"variable_bounds[{path!r}] limits must be finite numbers")
            if proposed["min"] > proposed["max"]:
                raise ValueError(f"variable_bounds[{path!r}] min must not exceed max")
            low, high = max(allowed["min"], proposed["min"]), min(allowed["max"], proposed["max"])
            if low > high:
                raise ValueError(f"variable_bounds[{path!r}] conflict with the resolved OP-05 bounds")
            merged[path] = {"min": low, "max": high}
        parameters["variable_bounds"] = merged

    geometry = (
        deepcopy(base_geometry)
        if parameters is None
        else geometry_generator(deepcopy(base_geometry), parameters)
    )
    geometry_check = require_optimizer_geometry(geometry)
    if level == "L0":
        return {
            "schema_version": "spat.optimizer-evaluation/1.0",
            "Fidelity": {"level": "L0", "values_are": "none"},
            "geometry": geometry,
            "Rg": None, "Vs": None, "Vt": None,
            "Feasible": None,
            "ComplianceStatus": "not_evaluated",
            "OptimizerGeometryCheck": geometry_check,
            "SelectedDiscreteOptions": selected_discrete_options,
            "EvaluationCount": run.evaluation_count,
        }

    # Count immediately before entering the stateless solver call. A failed call still uses
    # computational budget and therefore remains in the count.
    run.reserve()
    solved = solver_evaluation.evaluate(
        geometry=geometry,
        soil=soil,
        injection_a=injection_a,
        points=points,
        client=client,
        settings=settings,
        level=level,
    )
    quantities = solved["quantities"]
    field = {
        "step_v": quantities["Vs_v"],
        "touch_v": quantities["Vt_v"],
        "gpr_v": quantities["GPR_v"],
    }
    evaluations = safety_criteria.evaluate(field, exposure, standards)

    violations: list[dict[str, Any]] = []
    utilization_results: dict[str, Any] = {}
    evaluable = bool(evaluations)
    for standard_result in evaluations:
        standard = standard_result["standard"]
        if standard_result["status"] == "no_evaluable":
            evaluable = False
            violations.append({
                "standard": standard,
                "criterion": None,
                "status": "no_evaluable",
                "reason": standard_result["reason"],
            })
        for criterion in standard_result["criteria"]:
            if criterion.get("status") == "no_evaluable":
                continue
            if criterion["status"] != "cumple":
                violations.append({
                    "standard": standard,
                    "criterion": criterion["criterion"],
                    "actual_v": criterion["actual_v"],
                    "limit_v": criterion["tolerable_v"],
                    "excess_v": max(0.0, criterion["actual_v"] - criterion["tolerable_v"]),
                    "status": criterion["status"],
                })
        if standard_result["status"] == "no_evaluable":
            continue
        utilization_results[standard] = utilization_from_exposure(
            touch_v=field["touch_v"],
            step_v=field["step_v"],
            exposure=exposure,
            standard=standard,
        )

    feasible: bool | None = (
        all(result["status"] == "cumple" for result in evaluations)
        if evaluable
        else None
    )
    context = constraint_context or {}
    required_criteria = set(context.get("required_mandatory_criteria", []))
    evaluated_criteria = {
        criterion.get("criterion")
        for standard_result in evaluations
        for criterion in standard_result.get("criteria", [])
        if criterion.get("status") != "no_evaluable"
    }
    unassessed_criteria = sorted(required_criteria - evaluated_criteria)
    missing_mandatory = sorted(set(context.get("missing_mandatory_criteria", [])) | set(unassessed_criteria))
    if missing_mandatory:
        feasible = None
    if level == "L1" and feasible:
        feasible = None  # lower bounds cannot certify compliance; only a violation is conclusive
    compliance_status = (
        "blocked_missing_mandatory_criteria" if missing_mandatory
        else "evaluable" if evaluable
        else "no_evaluable"
    )
    numerical_status = {
        "solver": solved["status"],
        "safety": "evaluable" if evaluable else "no_evaluable",
        "overall": "approximate" if solved["status"] == "approximate" else solved["status"],
        "warnings": list(solved.get("warnings", [])),
    }
    return {
        "schema_version": "spat.optimizer-evaluation/1.0",
        "Fidelity": solved["fidelity"],
        "geometry": geometry,
        "Rg": quantities["Rg_ohm"],
        "Vs": quantities["Vs_v"],
        "Vt": quantities["Vt_v"],
        "Feasible": feasible,
        "ComplianceStatus": compliance_status,
        "MissingMandatoryCriteria": list(missing_mandatory),
        "OptimizerGeometryCheck": geometry_check,
        "ConstraintContext": deepcopy(constraint_context),
        "SelectedDiscreteOptions": selected_discrete_options,
        "ConstraintViolations": violations,
        "NumericalStatus": numerical_status,
        "EvaluationCount": run.evaluation_count,
        "SolverInputSha256": solved["input_sha256"],
        "SolverQuantities": quantities,
        "SafetyEvaluations": evaluations,
        "SafetyUtilization": utilization_results,
        "SolverLocations": solved["locations"],
    }
