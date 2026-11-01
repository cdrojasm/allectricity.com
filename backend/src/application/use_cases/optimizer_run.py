"""Application orchestration for one discrete grounding optimizer run.

The use case connects an already resolved OP-05 context to OP-06 candidate search,
OP-04 electrical evaluation, and explicit catalog pricing. It owns no persistence:
callers must provide the exact geometry, solver inputs, and quantity policy used for
this run.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from src.domain.spat.optimizer_constraints import require_optimizer_geometry
from src.domain.spat.optimizer_search import search_discrete_local
from src.infrastructure.calculations import optimizer_evaluation, safety_criteria
from src.infrastructure.calculations.potential_engine_client import (
    PotentialEngineClient,
    PotentialPoint,
    SoilModel,
)
from src.infrastructure.services.optimizer_material_options import evaluate_material_cost


QuantityProvider = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]],
                            dict[str, dict[str, Any]]]


def run_discrete_optimizer(
    *,
    base_parameters: dict[str, Any],
    base_geometry: dict[str, Any],
    constraint_context: dict[str, Any],
    optimized_variables: list[str],
    soil: SoilModel | float,
    injection_a: float,
    points: list[PotentialPoint],
    client: PotentialEngineClient,
    exposure: safety_criteria.FaultExposure,
    standards: list[str],
    explicit_quantities: dict[str, dict[str, Any]] | None = None,
    quantity_provider: QuantityProvider | None = None,
    cost_currency: str,
    seed: int,
    max_evaluations: int,
    restarts: int = 5,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic search using a ready context and explicit cost quantities.

    Quantities can be a fixed mapping or a callback so callers can supply quantities
    derived by their reviewed takeoff rules. The use case never infers quantities,
    invents currency conversions, or downgrades an unknown safety result to feasible.
    """
    if not isinstance(constraint_context, dict) or constraint_context.get("status") != "ready":
        raise ValueError("a ready OP-05 constraint context is required")
    if not isinstance(optimized_variables, list) or not optimized_variables:
        raise ValueError("at least one optimized variable is required")
    if quantity_provider is not None and explicit_quantities is not None:
        raise ValueError("provide either explicit_quantities or quantity_provider, not both")
    if explicit_quantities is None and quantity_provider is None:
        raise ValueError("an explicit material quantity map or reviewed quantity provider is required")
    if not isinstance(cost_currency, str) or len(cost_currency) != 3 or not cost_currency.isalpha() or cost_currency.upper() != cost_currency:
        raise ValueError("cost_currency must be an uppercase three-letter code")

    resolved_domains = (constraint_context.get("discrete_domains") or {}).get("domains", [])
    domains: dict[str, dict[str, Any]] = {}
    for item in resolved_domains:
        if (not isinstance(item, dict) or item.get("status") != "ready"
                or not item.get("candidate_values")):
            continue
        combined = domains.setdefault(item["target"], {
            "status": "ready", "candidate_values": [], "candidate_option_ids": [], "options": [],
        })
        combined["candidate_values"].extend(item["candidate_values"])
        combined["candidate_option_ids"].extend(item.get("candidate_option_ids") or [])
        combined["options"].extend(item.get("options") or [])
    requested_discrete = set(constraint_context.get("discrete_optimizable_variables") or [])
    search_domains = {path: domains[path] for path in optimized_variables if path in domains}
    if set(search_domains) != set(optimized_variables):
        missing = sorted(set(optimized_variables) - set(search_domains))
        raise ValueError("OP-06 currently requires ready discrete domains for every optimized variable: "
                         + ", ".join(missing))
    if not set(search_domains).issubset(requested_discrete):
        raise ValueError("optimized variables must be declared discrete_optimizable_variables in OP-05")

    bounds = {
        path: constraint_context["variable_bounds"][path]
        for path in optimized_variables
        if path in (constraint_context.get("variable_bounds") or {})
    }
    catalog_options: dict[str, dict[str, Any]] = {}
    for domain in search_domains.values():
        candidate_ids = set(domain.get("candidate_option_ids") or [])
        for option in domain.get("options") or []:
            option_id = option.get("option_id")
            if option_id in candidate_ids:
                catalog_options[option_id] = option

    evaluation_context = optimizer_evaluation.EvaluationContext(max_evaluations=max_evaluations)

    def build_candidate(parameters: dict[str, Any]) -> dict[str, Any]:
        # OP-04 owns the active OP-02 geometry generator. Validate construction before
        # launching the electrical solver, then pass this exact geometry to OP-04.
        geometry_parameters = deepcopy(parameters)
        geometry_parameters.pop("selected_discrete_options", None)
        geometry = optimizer_evaluation._generate_geometry(deepcopy(base_geometry), geometry_parameters)
        require_optimizer_geometry(geometry)
        return {"geometry": geometry}

    def evaluate_candidate_safety(built: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return optimizer_evaluation.evaluate_design(
            design_parameters=parameters,
            base_geometry=deepcopy(base_geometry),
            soil=soil,
            injection_a=injection_a,
            points=points,
            client=client,
            exposure=exposure,
            standards=standards,
            settings=settings,
            context=evaluation_context,
            constraint_context=constraint_context,
            optimized_variables=optimized_variables,
            geometry_generator=lambda _base, _params: deepcopy(built["geometry"]),
        )

    def evaluate_candidate_cost(
        _built: dict[str, Any], safety: dict[str, Any], parameters: dict[str, Any]
    ) -> dict[str, Any]:
        selected_map = safety.get("SelectedDiscreteOptions") or {}
        selected: list[dict[str, Any]] = []
        for path, option_id in sorted(selected_map.items()):
            option = catalog_options.get(option_id)
            if option is None:
                raise ValueError(f"selected catalog option {option_id!r} is absent from the OP-05 snapshot")
            selected.append({"option_id": option_id, "provenance": deepcopy(option.get("provenance"))})
        quantities = (quantity_provider(deepcopy(parameters), deepcopy(_built), deepcopy(safety))
                      if quantity_provider is not None else deepcopy(explicit_quantities))
        if not selected:
            raise ValueError("candidate has no priced selected catalog options")
        selected_ids = {item["option_id"] for item in selected}
        selected_quantities = {option_id: quantity for option_id, quantity in (quantities or {}).items()
                               if option_id in selected_ids}
        cost = evaluate_material_cost(selected, selected_quantities)
        currencies = {item["currency"] for item in cost.get("currency_totals", [])}
        if currencies and currencies != {cost_currency}:
            raise ValueError("candidate price currency does not match the requested objective currency")
        return cost

    result = search_discrete_local(
        base_parameters=base_parameters,
        domains=search_domains,
        build_candidate=build_candidate,
        evaluate_safety=evaluate_candidate_safety,
        evaluate_cost=evaluate_candidate_cost,
        seed=seed,
        max_evaluations=max_evaluations,
        restarts=restarts,
        bounds=bounds,
    )
    result["solver_evaluations"] = evaluation_context.evaluation_count
    result["constraint_context_schema_version"] = constraint_context.get("schema_version")
    result["site_geometry_sha256"] = constraint_context.get("site_geometry_sha256")
    result["selected_profile"] = deepcopy(constraint_context.get("profile"))
    result["cost_policy"] = "explicit_quantities_requested_currency_no_conversion"
    result["cost_currency"] = cost_currency
    return result
