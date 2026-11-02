"""Run the topological optimizer on a site: seeds, operators, geometry cost and the electrical solver.

The cost is the geometry takeoff priced with an explicit rate card (no solver). The electrical side is
`evaluate_design` at the level the controller asks for, with the utilization ratio read from its safety
evaluations so the search can repair a violating seed before making it cheaper.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.domain.spat import geometry_seeds
from src.domain.spat.geometry_cost import evaluate_geometry_cost
from src.domain.spat.geometry_operators import OperatorConstraints
from src.domain.spat.operator_selection import AdaptiveOperatorSelector
from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
from src.domain.spat.optimizer_topology_search import search_topology
from src.infrastructure.calculations import optimizer_evaluation, safety_criteria, solver_evaluation
from src.infrastructure.calculations.potential_engine_client import _file_sha256, as_soil, soil_record


STRATEGIES = ("descent", "uphill", "opportunistic", "adaptive", "alns")


def strategy_options(strategy: str, domain: dict[str, Any], constraints: OperatorConstraints) -> dict[str, Any]:
    """Search options for each strategy, so they can be compared on the same budget.

    descent        strict descent: only improving moves, no repair pool descents
    uphill         adds moves through costlier or unevaluated states
    opportunistic  adds the repair pool, on budget the descents leave unused, with additive moves while violating
    adaptive       opportunistic, but moves are drawn by adaptive weights over the atomic operators
    alns           adaptive weights over the atomic operators and the destroy-and-repair large-neighbourhood moves
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    if strategy == "descent":
        return {"uphill_moves": 0, "propose_repair": None, "max_repair_starts": 0}
    if strategy == "uphill":
        return {"propose_repair": None, "max_repair_starts": 0}
    if strategy == "opportunistic":
        return {}
    return {"operator_selector": AdaptiveOperatorSelector(domain, constraints, use_lns=(strategy == "alns"))}


def utilization_ratio(result: dict[str, Any]) -> float | None:
    """Largest actual/tolerable voltage over the evaluable criteria; above 1 is a violation."""
    ratios = [c["actual_v"] / c["tolerable_v"]
              for standard in result.get("SafetyEvaluations") or []
              for c in standard.get("criteria", [])
              if c.get("status") != "no_evaluable" and c.get("tolerable_v")]
    return max(ratios) if ratios else None


def problem_fingerprint(**parts: Any) -> str:
    """Hash of everything that decides what a verdict means: a checkpoint is only valid for the same problem."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def load_checkpoint(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    return json.loads(target.read_text()) if target.is_file() else {}


def save_checkpoint(path: str | os.PathLike[str], log: dict[str, Any]) -> None:
    """Atomic write of plain verdicts only; json.dumps refuses anything that is not data (an engine session, say)."""
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(log, sort_keys=True))
    os.replace(temporary, target)


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
    repair_share: float = 0.0,
    strategy: str = "opportunistic",
    max_repair_starts: int | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    checkpoint_every: int = 1,
) -> dict[str, Any]:
    """Run the search. With `checkpoint_path`, every new solver verdict is saved and a later call with the same
    problem resumes from the file: nothing already evaluated is evaluated again."""
    # A seed can pass the geometry rules and still be refused by the solver (a piece shorter than five radii once it
    # is discretised). Ask for a few extra and keep the first `seed_count` the solver accepts, so every strategy
    # starts from the same valid seeds.
    candidates = geometry_seeds.generate_seeds(domain, seed=seed, count=seed_count + 3, initial=initial_geometry)
    starts = [s for s in candidates if not solver_evaluation.discretization_violations(s.geometry, soil, settings)][:seed_count]
    problem = problem_fingerprint(
        domain=domain, rate_card=rate_card, soil=soil_record(as_soil(soil)), injection_a=injection_a, exposure=asdict(exposure),
        standards=standards, settings=settings, seed=seed, seeds=[s.graph_hash for s in starts], constraints=asdict(constraints),
        search=[neighbors_per_step, patience, uphill_moves, uphill_tolerance, max_steps_per_start, finalists, repair_share, strategy, max_repair_starts],
        engine=[getattr(client, "quadrature_tolerance", None), _file_sha256(getattr(client, "executable", "")) if getattr(client, "executable", None) else None])
    evaluations = load_checkpoint(checkpoint_path) if checkpoint_path else {}
    pending = {"n": 0}

    def on_checkpoint(log: dict[str, Any]) -> None:
        pending["n"] += 1
        if checkpoint_path and pending["n"] % max(1, checkpoint_every) == 0:
            save_checkpoint(checkpoint_path, log)

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

    options = {"uphill_moves": uphill_moves, **strategy_options(strategy, domain, constraints)}   # the strategy decides
    if propose_operator is not None:
        options["propose_operator"] = propose_operator
    if max_repair_starts is not None:
        options["max_repair_starts"] = max_repair_starts
    result = search_topology(
        domain=domain, seeds=starts, evaluate_cost=evaluate_cost, evaluate_electrical=evaluate_electrical, seed=seed,
        max_solver_calls=max_solver_calls, constraints=constraints, neighbors_per_step=neighbors_per_step, patience=patience,
        uphill_tolerance=uphill_tolerance, max_steps_per_start=max_steps_per_start, finalists=finalists,
        evaluations=evaluations, on_checkpoint=on_checkpoint, problem_sha256=problem, repair_share=repair_share, **options)
    if checkpoint_path:
        save_checkpoint(checkpoint_path, evaluations)
    result["seeds"] = [{"family": s.family, "candidate_sha256": s.graph_hash} for s in starts]
    result["seeds_dropped_by_solver_check"] = len(candidates) - len(starts) if len(candidates) > seed_count else 0
    result["cost_currency"] = rate_card["currency"]
    return result
