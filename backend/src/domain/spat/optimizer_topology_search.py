"""Topological local search with a fidelity controller (OPT-010).

Moves are the reversible operators of `geometry_operators`; starting points are the seeds of
`geometry_seeds`. Cost is evaluated first, for every valid candidate and without the solver, and it
decides whether the solver is worth calling:

  L0  cost only. A candidate that costs at least as much as the best confirmed design cannot improve
      it, so the solver is never called for it ("cost_dominated").
  L1  cheap electrical screen. A violation here is conclusive and the candidate is rejected; a pass
      proves nothing, so the candidate goes to the L1 archive and is escalated.
  L2+ confirmation. A violation rejects; otherwise the candidate joins the confirmed archive and may
      become the incumbent.
  L3  finalists only: the cheapest confirmed designs are re-examined with the adaptive search, and a
      violation there demotes them.

The two archives are kept apart on purpose: `l1_candidates` are only screened, `confirmed` passed
L2+. Nothing here is certified. A pass means no violation was found by sampled searches, so results
carry `certified: False`. Search ordering is lexicographic on (violation excess, cost), which lets the
search repair an infeasible seed before it tries to make it cheaper.
"""

from __future__ import annotations

import random
from collections import Counter
from math import isfinite
from typing import Any, Callable

from src.domain.spat import geometry_graph as gg
from src.domain.spat.geometry_operators import OperatorConstraints, OperatorRejected, apply_operator, random_operator

# Relative cost of one solver call per level, from the benchmark medians (L1 = 1): L2+ about 6.5, L3 about 6.9.
LEVEL_WEIGHTS = {"L1": 1.0, "L2+": 6.5, "L3": 6.9}
EvaluateCost = Callable[[dict[str, Any]], "float | dict[str, Any]"]
# (level, geometry) -> {"status": "VIOLATED"|"UNKNOWN"|"REJECTED", "ratio": float|None, "charged": bool, ...}
EvaluateElectrical = Callable[[str, dict[str, Any]], dict[str, Any]]


def _cost_value(result: Any) -> float:
    if isinstance(result, dict):
        if result.get("status") == "incomplete":
            raise ValueError("cost result is incomplete")
        totals = result.get("currency_totals")
        if totals is not None:
            if len(totals) != 1:
                raise ValueError("cost comparison requires exactly one currency")
            result = totals[0]["amount"]
        else:
            result = result.get("total")
    value = float(result)
    if not isfinite(value):
        raise ValueError("cost must be finite")
    return value


def search_topology(
    *,
    domain: dict[str, Any],
    seeds: list[Any],
    evaluate_cost: EvaluateCost,
    evaluate_electrical: EvaluateElectrical,
    seed: int,
    max_solver_calls: int,
    constraints: OperatorConstraints = OperatorConstraints(),
    neighbors_per_step: int = 6,
    patience: int = 4,
    max_steps_per_start: int = 30,
    finalists: int = 3,
    finalist_level: str = "L3",
) -> dict[str, Any]:
    """Descend from each seed.

    A step samples `neighbors_per_step` distinct new neighbours and moves to the best improving one. When
    none improves it samples another batch, up to `patience` batches, before calling the start a local
    optimum: in a sparse design few random moves help. Operator attempts are cheap (they never reach the
    solver), so up to 12 are drawn per neighbour wanted.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(max_solver_calls, bool) or not isinstance(max_solver_calls, int) or max_solver_calls < 1:
        raise ValueError("max_solver_calls must be a positive integer")
    rng = random.Random(seed)
    cache: dict[str, dict[str, Any]] = {}
    graphs: dict[str, gg.GeometryGraph] = {}
    calls: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    operator_rejections: Counter[str] = Counter()
    incumbent: dict[str, Any] | None = None
    exhausted = False

    searching = True      # while searching, the finalists' calls stay reserved
    start_cap: int | None = None   # absolute call count a single start may not pass

    def remaining() -> int:
        left = max_solver_calls - (finalists if searching else 0) - sum(calls.values())
        return left if start_cap is None else min(left, start_cap - sum(calls.values()))

    def electrical(level: str, geometry: dict[str, Any]) -> dict[str, Any] | None:
        """One charged solver call, or None when the budget cannot cover it."""
        nonlocal exhausted
        if remaining() < 1:
            if start_cap is None or max_solver_calls - (finalists if searching else 0) - sum(calls.values()) < 1:
                exhausted = True
            return None
        try:
            outcome = evaluate_electrical(level, geometry)
        except Exception as exc:  # callback boundary: keep the failure as a trace record
            calls[level] += 1
            return {"status": "REJECTED", "reason": "evaluation_error", "detail": str(exc), "ratio": None}
        if outcome.get("charged", True):
            calls[level] += 1
        return outcome

    def screen(graph: gg.GeometryGraph) -> dict[str, Any]:
        nonlocal incumbent
        digest = gg.canonical_hash(graph)
        if digest in cache:
            return cache[digest]
        graphs[digest] = graph
        geometry = gg.to_geometry(graph, domain)
        record: dict[str, Any] = {"candidate_sha256": digest, "level": "L0", "status": "rejected", "score": None}
        cache[digest] = record
        counts["considered"] += 1
        try:
            record["cost"] = _cost_value(evaluate_cost(geometry))
        except Exception as exc:
            record.update(reason="cost_error", detail=str(exc))
            return record
        if incumbent is not None and record["cost"] >= incumbent["cost"]:
            record.update(status="skipped", reason="cost_dominated")
            counts["skipped_cost_dominated"] += 1
            return record
        first = electrical("L1", geometry)
        if first is None:
            cache.pop(digest, None)        # not evaluated for lack of budget: a later start may still try it
            counts["considered"] -= 1
            return {**record, "status": "unscreened", "reason": "budget", "score": None}
        record["level"] = "L1"
        if first["status"] == "REJECTED":
            record.update(reason=first.get("reason", "geometry_rejected"), detail=first.get("detail"))
            return record
        if first["status"] == "VIOLATED":
            record.update(reason="violated_at_L1", ratio=first.get("ratio"), score=(max(0.0, (first.get("ratio") or 1.0) - 1.0), record["cost"]))
            counts["pruned_at_L1"] += 1
            return record
        record["l1"] = first
        second = electrical("L2+", geometry)
        if second is None:
            cache.pop(digest, None)
            counts["considered"] -= 1
            return {**record, "status": "screened", "reason": "budget", "score": (0.0, record["cost"]), "ratio": first.get("ratio")}
        record["level"] = "L2+"
        if second["status"] == "REJECTED":
            record.update(reason=second.get("reason", "evaluation_error"), detail=second.get("detail"))
            return record
        if second["status"] == "VIOLATED":
            record.update(reason="violated_at_L2+", ratio=second.get("ratio"),
                          score=(max(0.0, (second.get("ratio") or 1.0) - 1.0), record["cost"]))
            counts["rejected_at_L2plus"] += 1
            return record
        record.update(status="confirmed", ratio=second.get("ratio"), score=(0.0, record["cost"]), reason=None)
        counts["confirmed"] += 1
        if incumbent is None or record["cost"] < incumbent["cost"]:
            incumbent = record
        return record

    def descend(current: dict[str, Any]) -> None:
        for _ in range(max_steps_per_start):
            if exhausted or current["score"] is None:
                return
            best = None
            tried = attempts = widened = 0
            limit = neighbors_per_step
            while attempts < 12 * limit and not exhausted:
                if tried >= limit:
                    if best is not None or widened + 1 >= patience:
                        break
                    widened += 1
                    limit += neighbors_per_step     # nothing improved yet: look at another batch of neighbours
                attempts += 1
                try:
                    applied = apply_operator(graphs[current["candidate_sha256"]], random_operator(graphs[current["candidate_sha256"]], rng),
                                             constraints, domain)
                except OperatorRejected as rejected:
                    operator_rejections[rejected.kind] += 1
                    continue
                if gg.canonical_hash(applied.graph) not in cache:
                    tried += 1                      # only distinct, new neighbours use up the step's allowance
                neighbor = screen(applied.graph)
                if neighbor["score"] is not None and neighbor["score"] < current["score"] \
                        and (best is None or neighbor["score"] < best["score"]):
                    best = neighbor
            if best is None:
                return
            current = best

    # Phase 1: evaluate every seed once, so the incumbent and the feasible starting points are known.
    starts = []
    for start in seeds:
        graph = gg.from_geometry(start.geometry)
        record = screen(graph)
        if record["score"] is not None and record["candidate_sha256"] in graphs:
            starts.append(record)
    # Phase 2: descend from feasible seeds first (cheapest first), then repair the violating ones. Each start gets
    # an equal share of what is left, and a share it does not use passes on to the next.
    starts.sort(key=lambda r: (r["score"][0] > 0, r["score"], r["candidate_sha256"]))
    for index, record in enumerate(starts):
        if exhausted:
            break
        left = max_solver_calls - finalists - sum(calls.values())
        start_cap = sum(calls.values()) + max(1, -(-left // (len(starts) - index)))
        descend(record)
        start_cap = None

    # Finalists: the cheapest confirmed designs are re-examined; a violation demotes them.
    search_exhausted = exhausted
    searching = False
    exhausted = False
    finalist_records: list[dict[str, Any]] = []
    for record in sorted((r for r in cache.values() if r["status"] == "confirmed"), key=lambda r: (r["cost"], r["candidate_sha256"])):
        if len([f for f in finalist_records if f["status"] == "finalist"]) >= finalists:
            break
        outcome = electrical(finalist_level, gg.to_geometry(graphs[record["candidate_sha256"]], domain))
        if outcome is None:
            break
        verdict = "demoted" if outcome["status"] in ("VIOLATED", "REJECTED") else "finalist"
        finalist_records.append({"candidate_sha256": record["candidate_sha256"], "cost": record["cost"], "status": verdict,
                                 "level": finalist_level, "ratio": outcome.get("ratio")})
        if verdict == "demoted":
            counts["demoted_at_finalist_level"] += 1

    survivors = [f for f in finalist_records if f["status"] == "finalist"]
    best = min(survivors, key=lambda f: (f["cost"], f["candidate_sha256"]), default=None)
    public = lambda r: {k: v for k, v in r.items() if k != "score"}   # noqa: E731
    return {
        "schema_version": "spat.optimizer-topology-search/1.0",
        "algorithm": "operator_local_search_with_fidelity_controller",
        "seed": seed, "starts": len(seeds),
        "max_solver_calls": max_solver_calls, "reserved_for_finalists": finalists, "solver_calls": dict(calls), "solver_calls_total": sum(calls.values()),
        "baseline_solver_calls_if_every_candidate_used_L2plus": counts["considered"],
        # Same comparison in time units (one L1 call = 1), since the levels do not cost the same.
        "solver_time_units": round(sum(LEVEL_WEIGHTS.get(level, 1.0) * n for level, n in calls.items()), 1),
        "baseline_time_units_if_every_candidate_used_L2plus": round(LEVEL_WEIGHTS["L2+"] * counts["considered"], 1),
        "budget_exhausted": search_exhausted,
        "counts": dict(counts), "operator_rejections": dict(operator_rejections),
        "best": best, "best_geometry": gg.to_geometry(graphs[best["candidate_sha256"]], domain) if best else None,
        "finalists": finalist_records,
        "confirmed": sorted((public(r) for r in cache.values() if r["status"] == "confirmed"), key=lambda r: (r["cost"], r["candidate_sha256"])),
        "l1_candidates": sorted((public(r) for r in cache.values() if r.get("l1") is not None), key=lambda r: (r["cost"], r["candidate_sha256"])),
        "certified": False,
        "feasibility_note": "no violation was found by sampled searches; nothing here is certified",
    }
