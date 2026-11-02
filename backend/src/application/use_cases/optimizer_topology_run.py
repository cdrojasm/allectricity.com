"""Run the topological optimizer on a site: seeds, operators, geometry cost and the electrical solver.

The cost is the geometry takeoff priced with an explicit rate card (no solver). The electrical side is
`evaluate_design` at the level the controller asks for, with the utilization ratio read from its safety
evaluations so the search can repair a violating seed before making it cheaper.
"""

from __future__ import annotations

from typing import Any

from src.domain.spat import geometry_seeds
from src.domain.spat.geometry_cost import evaluate_geometry_cost
from src.domain.spat.geometry_operators import OperatorConstraints
from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
from src.domain.spat.optimizer_topology_search import search_topology
from src.infrastructure.calculations import optimizer_evaluation, safety_criteria


def utilization_ratio(result: dict[str, Any]) -> float | None:
    """Largest actual/tolerable voltage over the evaluable criteria; above 1 is a violation."""
    ratios = [c["actual_v"] / c["tolerable_v"]
              for standard in result.get("SafetyEvaluations") or []
              for c in standard.get("criteria", [])
              if c.get("status") != "no_evaluable" and c.get("tolerable_v")]
    return max(ratios) if ratios else None


def run_topology_optimizer(
    *,
    domain: dict[str, Any],
    rate_card: dict[str, Any],
    soil: Any,
    injection_a: float,
    exposure: safety_criteria.FaultExposure,
    standards: list[str],
    client: Any,
    seed: int,
    max_solver_calls: int,
    initial_geometry: dict[str, Any] | None = None,
    seed_count: int = 4,
    settings: dict[str, Any] | None = None,
    constraints: OperatorConstraints = OperatorConstraints(),
    neighbors_per_step: int = 6,
    patience: int = 4,
    uphill_moves: int = 2,
    uphill_tolerance: float = 0.15,
    propose_operator: Any = None,
    max_steps_per_start: int = 30,
    finalists: int = 3,
) -> dict[str, Any]:
    starts = geometry_seeds.generate_seeds(domain, seed=seed, count=seed_count, initial=initial_geometry)
    context = optimizer_evaluation.EvaluationContext(max_evaluations=max_solver_calls)

    def evaluate_cost(geometry: dict[str, Any]) -> dict[str, Any]:
        return evaluate_geometry_cost(geometry, rate_card)

    def evaluate_electrical(level: str, geometry: dict[str, Any]) -> dict[str, Any]:
        try:
            result = optimizer_evaluation.evaluate_design(
                design_parameters=None, base_geometry=geometry, soil=soil, injection_a=injection_a, points=[],
                client=client, exposure=exposure, standards=standards, settings=settings, context=context, level=level)
        except OptimizerGeometryRejected as rejected:
            return {"status": "REJECTED", "reason": "geometry_rejected", "detail": str(rejected), "charged": False}
        return {"status": result["FeasibilityStatus"], "ratio": utilization_ratio(result), "feasible": result["Feasible"]}

    result = search_topology(
        domain=domain, seeds=starts, evaluate_cost=evaluate_cost, evaluate_electrical=evaluate_electrical, seed=seed,
        max_solver_calls=max_solver_calls, constraints=constraints, neighbors_per_step=neighbors_per_step, patience=patience,
        uphill_moves=uphill_moves, uphill_tolerance=uphill_tolerance,
        **({"propose_operator": propose_operator} if propose_operator is not None else {}), max_steps_per_start=max_steps_per_start, finalists=finalists)
    result["seeds"] = [{"family": s.family, "candidate_sha256": s.graph_hash} for s in starts]
    result["cost_currency"] = rate_card["currency"]
    return result
