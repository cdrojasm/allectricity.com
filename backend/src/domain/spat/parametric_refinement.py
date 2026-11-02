"""Parametric refinement of an elite topology: the OP-06 local search, run on a fixed network (OPT-014).

The topological search decides where conductors and rods go; this step keeps that network and tunes what
is left to tune, the length of each rod, with `search_discrete_local` (the same best-improvement search
over finite domains that OP-06 runs on commercial options). Reusing it means the same candidate cache,
the same strict-improvement rule and the same reading of feasibility (`feasibility.admits`).

Candidates are not evaluated here. `screen` is the topological search's own pipeline, so every refined
design goes through the same fidelity controller: priced first, dropped without a solver call when it
cannot beat the best known cost, screened at L1, confirmed at L2+, and charged to the same budget. A
refined design that is confirmed lands in the same archive as any other and competes for a finalist seat.
"""

from __future__ import annotations

from typing import Any, Callable

from src.domain.spat import geometry_graph as gg
from src.domain.spat.geometry_operators import OperatorConstraints, OperatorRejected, check
from src.domain.spat.optimizer_search import search_discrete_local

# Rod lengths worth trying besides the one the design already has (metres, filtered by the constraints).
ROD_LENGTHS_M = (1.5, 2.4, 3.0, 4.5, 6.0, 9.0)
Screen = Callable[[gg.GeometryGraph], dict[str, Any]]


def rod_variables(graph: gg.GeometryGraph, constraints: OperatorConstraints,
                  lengths_m: tuple[float, ...] = ROD_LENGTHS_M) -> tuple[list[gg.Rod], dict[str, list[float]]]:
    """The rods in a fixed order and, per rod, the lengths it may take (its own length is always allowed)."""
    rods = sorted(graph.rods)
    low, high = constraints.rod_length_range_m
    domains = {f"rod_lengths_m[{i}]": sorted({length, *(v for v in lengths_m if low <= v <= high)})
               for i, (_, length, _) in enumerate(rods)}
    return rods, domains


def with_rod_lengths(graph: gg.GeometryGraph, rods: list[gg.Rod], lengths: list[float]) -> gg.GeometryGraph:
    return gg.GeometryGraph(graph.site, graph.segments,
                            frozenset((node, round(float(length), gg.DECIMALS), material) for (node, _, material), length in zip(rods, lengths)))


def refine_rods(
    graph: gg.GeometryGraph,
    *,
    screen: Screen,
    constraints: OperatorConstraints = OperatorConstraints(),
    domain: dict[str, Any] | None = None,
    seed: int = 0,
    max_evaluations: int = 24,
    lengths_m: tuple[float, ...] = ROD_LENGTHS_M,
) -> dict[str, Any]:
    """Tune the rod lengths of one topology. Returns the OP-06 search record plus the refined graph, if any improved.

    A candidate is eligible when `screen` confirmed it (no violation at L1 or L2+). The search is bounded by
    `max_evaluations` unique candidates and, much more tightly in practice, by the solver budget behind `screen`.
    """
    rods, domains = rod_variables(graph, constraints, lengths_m)
    if not rods:
        return {"evaluations": 0, "best": None, "refined_graph": None, "reason": "no_rods"}
    base = {"rod_lengths_m": [length for _, length, _ in rods]}

    def build(parameters: dict[str, Any]) -> dict[str, Any]:
        candidate = with_rod_lengths(graph, rods, parameters["rod_lengths_m"])
        try:
            check(candidate, constraints, domain)
        except OperatorRejected as rejected:
            raise ValueError(str(rejected)) from rejected
        return {"graph": candidate}

    def safety(built: dict[str, Any], _parameters: dict[str, Any]) -> dict[str, Any]:
        record = screen(built["graph"])
        confirmed = record.get("status") == "confirmed"
        violated = str(record.get("reason") or "").startswith("violated")
        return {"Feasible": True if confirmed else None if record.get("status") in ("screened", "unscreened") else False,
                "FeasibilityStatus": "VIOLATED" if violated else "UNKNOWN", "record": record}

    result = search_discrete_local(
        base_parameters=base, domains=domains, build_candidate=build, evaluate_safety=safety,
        evaluate_cost=lambda _built, evaluation, _parameters: evaluation["record"]["cost"],
        seed=seed, max_evaluations=max_evaluations, restarts=1,
        start={f"rod_lengths_m[{i}]": length for i, (_, length, _) in enumerate(rods)})
    best = result["best"]
    refined = None
    if best is not None:
        refined = with_rod_lengths(graph, rods, best["parameters"]["rod_lengths_m"])
    return {"evaluations": result["unique_evaluations"], "best": best, "refined_graph": refined,
            "improved": best is not None and gg.canonical_hash(refined) != gg.canonical_hash(graph)}
