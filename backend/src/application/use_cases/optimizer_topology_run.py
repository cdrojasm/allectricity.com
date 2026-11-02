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
from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
from src.domain.spat.optimizer_topology_search import search_topology
from src.infrastructure.calculations import optimizer_evaluation, safety_criteria
from src.infrastructure.calculations.potential_engine_client import _file_sha256, as_soil, soil_record


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
    checkpoint_path: str | os.PathLike[str] | None = None,
    checkpoint_every: int = 1,
) -> dict[str, Any]:
    """Run the search. With `checkpoint_path`, every new solver verdict is saved and a later call with the same
    problem resumes from the file: nothing already evaluated is evaluated again."""
    starts = geometry_seeds.generate_seeds(domain, seed=seed, count=seed_count, initial=initial_geometry)
    problem = problem_fingerprint(
        domain=domain, rate_card=rate_card, soil=soil_record(as_soil(soil)), injection_a=injection_a, exposure=asdict(exposure),
        standards=standards, settings=settings, seed=seed, seeds=[s.graph_hash for s in starts], constraints=asdict(constraints),
        search=[neighbors_per_step, patience, uphill_moves, uphill_tolerance, max_steps_per_start, finalists, repair_share],
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

    result = search_topology(
        domain=domain, seeds=starts, evaluate_cost=evaluate_cost, evaluate_electrical=evaluate_electrical, seed=seed,
        max_solver_calls=max_solver_calls, constraints=constraints, neighbors_per_step=neighbors_per_step, patience=patience,
        uphill_moves=uphill_moves, uphill_tolerance=uphill_tolerance,
        **({"propose_operator": propose_operator} if propose_operator is not None else {}), max_steps_per_start=max_steps_per_start, finalists=finalists,
        evaluations=evaluations, on_checkpoint=on_checkpoint, problem_sha256=problem, repair_share=repair_share)
    if checkpoint_path:
        save_checkpoint(checkpoint_path, evaluations)
    result["seeds"] = [{"family": s.family, "candidate_sha256": s.graph_hash} for s in starts]
    result["cost_currency"] = rate_card["currency"]
    return result
