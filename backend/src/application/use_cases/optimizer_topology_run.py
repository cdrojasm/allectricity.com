"""Run the topological optimizer on a site: seeds, operators, geometry cost and the electrical solver.

The cost is the geometry takeoff priced with an explicit rate card (no solver). The electrical side is
`evaluate_design` at the level the controller asks for, with the utilization ratio read from its safety
evaluations so the search can repair a violating seed before making it cheaper.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from src.domain.spat import geometry_seeds
from src.domain.spat import geometry_graph as gg
from src.domain.spat.feasibility import admits
from src.domain.spat.geometry_cost import evaluate_geometry_cost
from src.domain.spat.geometry_operators import OperatorConstraints
from src.domain.spat.operator_selection import AdaptiveOperatorSelector
from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
from src.domain.spat.optimizer_topology_search import search_topology
from src.infrastructure.calculations import optimizer_evaluation, safety_criteria, solver_evaluation
from src.infrastructure.calculations.potential_engine_client import _file_sha256, as_soil, soil_record


STRATEGIES = ("descent", "uphill", "opportunistic", "adaptive", "alns", "alns_refined", "alns_opportunistic", "alns_checkpoint")
DEFAULT_STRATEGY = "alns"     # the official policy: pure ALNS, no parametric refinement
# alns_refined, alns_opportunistic and alns_checkpoint are experimental (OPT-014/014B): kept for reproducible benchmarks,
# not recommended and not part of the product flow. See docs/EXPERIMENTO_OPT014_REFINAMIENTO.md.
EXPERIMENTAL_STRATEGIES = ("alns_refined", "alns_opportunistic", "alns_checkpoint")
REFINE_SHARE = 0.25     # of the budget left after the finalists' reserve; what the refined strategy holds back for the parametric step


def _seed_constraints(constraints: OperatorConstraints) -> geometry_seeds.SeedConstraints:
    """Seeds follow the operators' limits: horizontal and vertical runs only when asked, and rods within the allowed length."""
    low, high = constraints.rod_length_range_m
    defaults = geometry_seeds.SeedConstraints()
    lengths = tuple(length for length in defaults.rod_length_choices_m if low <= length <= high) or (round((low + high) / 2, 3),)
    return replace(defaults, orthogonal=constraints.orthogonal, redundant=constraints.redundant,
                   stub_max_m=constraints.stub_max_m, rod_length_choices_m=lengths)


def strategy_options(strategy: str, domain: dict[str, Any], constraints: OperatorConstraints,
                     selector_scores: dict[str, float] | None = None) -> dict[str, Any]:
    """Search options for each strategy, so they can be compared on the same budget.

    descent        strict descent: only improving moves, no repair pool descents
    uphill         adds moves through costlier or unevaluated states
    opportunistic  adds the repair pool, on budget the descents leave unused, with additive moves while violating
    adaptive       opportunistic, but moves are drawn by adaptive weights over the atomic operators
    alns           adaptive weights over the atomic operators and the destroy-and-repair large-neighbourhood moves
    alns_opportunistic  alns, then rod tuning of the elites only on budget the search leaves unused (OPT-014B, policy C)
    alns_checkpoint     alns until 80% of the budget, then a fixed rule picks more exploration or rod tuning (policy D)
    alns_refined   alns, with a quarter of the budget held back to tune the rod lengths of the elite topologies (OPT-014);
                   it spends the same total budget as alns, so the two compare on equal footing
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    if strategy == "descent":
        return {"uphill_moves": 0, "propose_repair": None, "max_repair_starts": 0}
    if strategy == "uphill":
        return {"propose_repair": None, "max_repair_starts": 0}
    if strategy == "opportunistic":
        return {}
    options = {"operator_selector": AdaptiveOperatorSelector(domain, constraints, use_lns=strategy.startswith("alns"), scores=selector_scores)}
    extra = {"alns_refined": {"refine_share": REFINE_SHARE}, "alns_opportunistic": {"refine_leftover": True},
             "alns_checkpoint": {"checkpoint_fraction": 0.8}}.get(strategy, {})
    return {**options, **extra}


def utilization_ratio(result: dict[str, Any]) -> float | None:
    """Largest actual/tolerable voltage over the evaluable criteria; above 1 is a violation."""
    ratios = [c["actual_v"] / c["tolerable_v"]
              for standard in result.get("SafetyEvaluations") or []
              for c in standard.get("criteria", [])
              if c.get("status") != "no_evaluable" and c.get("tolerable_v")]
    return max(ratios) if ratios else None


def electrical_verdict(level: str, result: dict[str, Any]) -> dict[str, Any]:
    """The topological search's reading of one `evaluate_design` result, through the gate the parametric search uses.

    A violation stays a violation. A design with no violation found passes only where `feasibility.admits` lets it:
    at L1 to be escalated, at finer levels when `Feasible` is True. Otherwise it could not be assessed (a standard
    with no evaluable criterion, a mandatory criterion missing) and is rejected, never promoted on silence.
    """
    verdict = {"status": result["FeasibilityStatus"], "ratio": utilization_ratio(result), "feasible": result["Feasible"],
               # what the comparison and the report show; plain numbers so the verdict stays checkpointable
               "metrics": {"Rg_ohm": result.get("Rg"), "Vs_v": result.get("Vs"), "Vt_v": result.get("Vt"),
                           "missing_mandatory_criteria": list(result.get("MissingMandatoryCriteria") or [])}}
    if verdict["status"] != "VIOLATED" and not admits(level=level, status=verdict["status"], feasible=verdict["feasible"]):
        return {**verdict, "status": "REJECTED", "reason": "not_assessable", "detail": "no criterion could be assessed"}
    return verdict


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


@dataclass(frozen=True)
class _EliteSeed:
    family: str
    geometry: dict[str, Any]
    graph_hash: str
    metadata: dict[str, Any]


def load_elite_archive(path: str | os.PathLike[str], context_sha256: str) -> list[_EliteSeed]:
    """Load portable candidate geometries only when their design/evaluation context matches."""
    target = Path(path)
    if not target.is_file():
        return []
    payload = json.loads(target.read_text())
    if payload.get("schema_version") != "spat.optimizer-elite-archive/1.0":
        raise ValueError("unsupported elite archive schema")
    if payload.get("context_sha256") != context_sha256:
        raise ValueError("elite archive belongs to an incompatible optimization context")
    result = []
    for item in payload.get("candidates", []):
        geometry = item["geometry"]
        digest = gg.canonical_hash(gg.from_geometry(geometry))
        if digest != item.get("candidate_sha256"):
            raise ValueError("elite archive candidate hash mismatch")
        result.append(_EliteSeed("archive", geometry, digest, {"source_run_id": item.get("source_run_id")}))
    return result


def save_elite_archive(path: str | os.PathLike[str], context_sha256: str, result: dict[str, Any], run_id: str) -> None:
    """Atomically retain distinct L3-admitted geometries; archive data is only a source of starts, never proof."""
    target = Path(path)
    previous = load_elite_archive(target, context_sha256) if target.is_file() else []
    by_hash = {seed.graph_hash: {"candidate_sha256": seed.graph_hash, "geometry": seed.geometry,
                                "source_run_id": seed.metadata.get("source_run_id")} for seed in previous}
    for item in result.get("finalists", []):
        if item.get("status") != "finalist" or item.get("level") != "L3" or not item.get("geometry"):
            continue
        digest = gg.canonical_hash(gg.from_geometry(item["geometry"]))
        by_hash[digest] = {"candidate_sha256": digest, "geometry": item["geometry"], "source_run_id": run_id}
    ranked = sorted(by_hash.values(), key=lambda item: item["candidate_sha256"])[:20]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps({"schema_version": "spat.optimizer-elite-archive/1.0", "context_sha256": context_sha256,
                                     "candidates": ranked}, sort_keys=True, indent=2))
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
    max_solver_calls: int | None = None,
    time_budget_s: float | None = None,
    finalist_time_share: float = 0.2,
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
    strategy: str = DEFAULT_STRATEGY,
    max_repair_starts: int | None = None,
    selector_scores: dict[str, float] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    checkpoint_every: int = 1,
    elite_archive_path: str | os.PathLike[str] | None = None,
    parallel_workers: int = 1,
    constraint_context: dict[str, Any] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the search on a budget of solver calls (`max_solver_calls`, repeatable) or of seconds (`time_budget_s`,
    the fast mode: part of it is held for the L3 check of the finalists, see `search_topology`). With `checkpoint_path`, every new solver verdict is saved and a later call with the same
    problem resumes from the file: nothing already evaluated is evaluated again.

    `constraint_context` is a resolved OP-05 context: its mandatory criteria must be assessed for a design to pass, as in the
    parametric search. `on_progress({"verdicts": n})` runs after each new verdict is logged, outside the evaluation boundary,
    so an exception it raises (a cancellation, say) stops the search; with `checkpoint_every=1` the file already holds that verdict."""
    # A seed can pass the geometry rules and still be refused by the solver (a piece shorter than five radii once it
    # is discretised). Ask for a few extra and keep the first `seed_count` the solver accepts, so every strategy
    # starts from the same valid seeds.
    candidates = geometry_seeds.generate_seeds(domain, seed=seed, count=seed_count + 3, initial=initial_geometry,
                                               constraints=_seed_constraints(constraints))
    elite_context = problem_fingerprint(domain=domain, rate_card=rate_card, soil=soil_record(as_soil(soil)),
                                       injection_a=injection_a, exposure=asdict(exposure), standards=standards, settings=settings,
                                       engine=[getattr(client, "quadrature_tolerance", None),
                                               _file_sha256(getattr(client, "executable", "")) if getattr(client, "executable", None) else None])
    archived = load_elite_archive(elite_archive_path, elite_context) if elite_archive_path else []
    known = {s.graph_hash for s in candidates}
    candidates.extend(s for s in archived if s.graph_hash not in known)
    valid_archive = [s for s in archived if not solver_evaluation.discretization_violations(s.geometry, soil, settings)]
    valid_generated = [s for s in candidates if s.graph_hash not in {a.graph_hash for a in valid_archive}
                       and not solver_evaluation.discretization_violations(s.geometry, soil, settings)]
    starts = (valid_archive[:seed_count] + valid_generated[:max(0, seed_count - len(valid_archive[:seed_count]))])
    # Only a given context enters the fingerprint, so runs without one keep their earlier checkpoints valid.
    context_part = {} if constraint_context is None else {"constraint_context": constraint_context}
    problem = problem_fingerprint(
        **context_part,
        domain=domain, rate_card=rate_card, soil=soil_record(as_soil(soil)), injection_a=injection_a, exposure=asdict(exposure),
        standards=standards, settings=settings, seed=seed, seeds=[s.graph_hash for s in starts], constraints=asdict(constraints),
        search=[neighbors_per_step, patience, uphill_moves, uphill_tolerance, max_steps_per_start, finalists, repair_share, strategy, max_repair_starts, selector_scores, parallel_workers]
        + ([time_budget_s, finalist_time_share] if time_budget_s is not None else []),
        engine=[getattr(client, "quadrature_tolerance", None), _file_sha256(getattr(client, "executable", "")) if getattr(client, "executable", None) else None])
    evaluations = load_checkpoint(checkpoint_path) if checkpoint_path else {}
    pending = {"n": 0}

    def on_checkpoint(log: dict[str, Any]) -> None:
        pending["n"] += 1
        if checkpoint_path and pending["n"] % max(1, checkpoint_every) == 0:
            save_checkpoint(checkpoint_path, log)
        if on_progress is not None:
            on_progress({"verdicts": len(log)})

    context = optimizer_evaluation.EvaluationContext(max_evaluations=max_solver_calls)     # None (time mode): the search keeps the time

    def evaluate_cost(geometry: dict[str, Any]) -> dict[str, Any]:
        return evaluate_geometry_cost(geometry, rate_card)

    def evaluate_electrical(level: str, geometry: dict[str, Any]) -> dict[str, Any]:
        try:
            result = optimizer_evaluation.evaluate_design(
                design_parameters=None, base_geometry=geometry, soil=soil, injection_a=injection_a, points=[],
                client=client, exposure=exposure, standards=standards, settings=settings, context=context, level=level,
                constraint_context=constraint_context)
        except OptimizerGeometryRejected as rejected:
            return {"status": "REJECTED", "reason": "geometry_rejected", "detail": str(rejected), "charged": False}
        return electrical_verdict(level, result)

    options = {"uphill_moves": uphill_moves, **strategy_options(strategy, domain, constraints, selector_scores)}   # the strategy decides
    if propose_operator is not None:
        options["propose_operator"] = propose_operator
    if max_repair_starts is not None:
        options["max_repair_starts"] = max_repair_starts
    result = search_topology(
        domain=domain, seeds=starts, evaluate_cost=evaluate_cost, evaluate_electrical=evaluate_electrical, seed=seed,
        max_solver_calls=max_solver_calls, time_budget_s=time_budget_s, finalist_time_share=finalist_time_share, constraints=constraints, neighbors_per_step=neighbors_per_step, patience=patience,
        uphill_tolerance=uphill_tolerance, max_steps_per_start=max_steps_per_start, finalists=finalists,
        evaluations=evaluations, on_checkpoint=on_checkpoint, problem_sha256=problem, repair_share=repair_share,
        parallel_workers=parallel_workers, **options)
    if checkpoint_path:
        save_checkpoint(checkpoint_path, evaluations)
    result["seeds"] = [{"family": s.family, "candidate_sha256": s.graph_hash} for s in starts]
    result["seeds_dropped_by_solver_check"] = len(candidates) - len(starts) if len(candidates) > seed_count else 0
    result["cost_currency"] = rate_card["currency"]
    if elite_archive_path:
        archive_run_id = str(uuid.uuid4())
        save_elite_archive(elite_archive_path, elite_context, result, archive_run_id)
        result["elite_archive"] = {"path": str(elite_archive_path), "loaded": len(archived),
                                   "saved": len(load_elite_archive(elite_archive_path, elite_context)),
                                   "context_sha256": elite_context}
    return result
