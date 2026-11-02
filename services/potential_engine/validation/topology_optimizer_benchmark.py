"""Benchmark of the topology optimizer's strategies over several scenarios and seeds, on equal budgets.

Usage: make optimizer-benchmark [OPT_BENCH_OUT=/tmp/optimizer-benchmark.json]
                                [ARGS='--seeds 8 --budget 150 --workers 8']

Strategies (see `optimizer_topology_run.strategy_options`): descent, uphill, opportunistic, adaptive, alns, alns_refined.
alns_refined is alns with part of the same budget spent tuning the rod lengths of the elite topologies (OPT-014); it is
also compared directly with alns, paired by scenario and seed.
Every strategy gets the same scenario, the same starting seeds and the same cap on solver calls, so a
difference in cost is a difference in search. Reported per scenario and overall:
  feasibility and best cost, regret against the best design any strategy found for that (scenario, seed),
  paired comparison against plain descent (better / equal / worse, mean change with a bootstrap interval and an
  exact sign test), average rank, solver calls and time units used, finalists demoted by the finest check,
  and what each kind of move earned (atomic versus large-neighbourhood).
Nothing here certifies a design. A cost is for a design that survived sampled checks and the finest level.
"""

from __future__ import annotations

import argparse
import json
import os
import math
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

STRATEGIES = ("descent", "uphill", "opportunistic", "adaptive", "alns", "alns_refined")
RATES = {"currency": "COP", "assumptions": {"trench_width_m": 0.4},
         "rates": {"material.conductor.unspecified": "18000", "material.rod.unspecified": "25000", "excavation.trench": "60000",
                   "installation.conductor": "7000", "installation.rod": "40000", "installation.connection": "15000"}}
_LOT = {"length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
        "areas": [{"type": "intervenible", "label": "lote", "polygon": [
            {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
        "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}]}
_SQUARE = {"length_m": 30, "width_m": 30, "burial_depth_m": 0.6, "areas": [],
           "structures": [{"x": 15, "y": 15, "width": 6, "height": 6, "label": "edificio"}]}
_TRAPEZOID = {"length_m": 40, "width_m": 20, "burial_depth_m": 0.8, "structures": [],
              "areas": [{"type": "intervenible", "label": "terreno", "polygon": [
                  {"x": 2, "y": 2}, {"x": 38, "y": 2}, {"x": 30, "y": 18}, {"x": 10, "y": 18}]}]}
# name: (domain, soil, injection A, surface resistivity ohm-m). Currents leave a mix of compliant and violating seeds.
SCENARIOS = {
    "L-homogeneous": (_LOT, 100.0, 1000.0, 3000.0),
    "L-two-layer": (_LOT, ("two", 100.0, 300.0, 2.0), 1000.0, 3000.0),
    "square-building": (_SQUARE, 100.0, 900.0, 3000.0),
    "trapezoid": (_TRAPEZOID, 150.0, 800.0, 3000.0),
}


def run_one(job: dict) -> dict:
    from src.application.use_cases.optimizer_topology_run import run_topology_optimizer
    from src.infrastructure.calculations import safety_criteria
    from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient, TwoLayerSoil
    domain, soil, current, rho = SCENARIOS[job["scenario"]]
    soil = TwoLayerSoil(*soil[1:]) if isinstance(soil, tuple) else soil
    started = time.perf_counter()
    result = run_topology_optimizer(
        domain=domain, rate_card=RATES, soil=soil, injection_a=current, exposure=safety_criteria.FaultExposure(0.5, 70, rho, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=PotentialEngineClient(), seed=job["seed"], max_solver_calls=job["budget"],
        seed_count=4, strategy=job["strategy"])
    stats = result.get("operator_stats") or {}
    lns, atomic = {"incumbent": 0, "improving": 0, "novel": 0, "used": 0}, {"incumbent": 0, "improving": 0, "novel": 0, "used": 0}
    for context in (stats.get("outcomes") or {}).values():
        for arm, outcomes in context.items():
            bucket = lns if arm.startswith("lns:") else atomic
            for outcome, count in outcomes.items():
                bucket["used"] += count
                if outcome in bucket:
                    bucket[outcome] += count
    return {**{k: job[k] for k in ("scenario", "seed", "strategy", "budget")},
            "best_cost": result["best"]["cost"] if result["best"] else None, "solver_calls": result["solver_calls_total"],
            "time_units": result["solver_time_units"], "considered": result["counts"]["considered"],
            "confirmed": result["counts"].get("confirmed", 0), "demoted": result["counts"].get("demoted_at_finalist_level", 0),
            "uphill_moves": result["counts"].get("uphill_moves_taken", 0), "repair_starts": result["counts"].get("repair_starts", 0),
            "refinement_starts": result["counts"].get("refinement_starts", 0), "refined_confirmed": result["counts"].get("confirmed_from_refinement", 0),
            "refinement_won": result["counts"].get("incumbent_improved_by_refinement", 0),
            "planning_failures": result["operator_rejections"].get("planning", 0), "lns": lns, "atomic": atomic,
            "seconds": round(time.perf_counter() - started, 2), "budget_exhausted": result["budget_exhausted"]}


def _sign_test(better: int, worse: int) -> float:
    """Exact two-sided sign test, ties dropped."""
    n = better + worse
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(better, worse) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _bootstrap(values: list[float], draws: int = 2000) -> tuple[float, float]:
    rng = random.Random(0)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def analyse(rows: list[dict], strategies: tuple[str, ...]) -> dict:
    out: dict = {"runs": len(rows), "scenarios": {}, "overall": {}}
    keys = sorted({(r["scenario"], r["seed"]) for r in rows})
    best_known = {}
    for key in keys:
        costs = [r["best_cost"] for r in rows if (r["scenario"], r["seed"]) == key and r["best_cost"] is not None]
        best_known[key] = min(costs) if costs else None
    by = {(r["scenario"], r["seed"], r["strategy"]): r for r in rows}

    def paired(subset_keys: list[tuple], base: str, strategy: str) -> dict:
        """`strategy` against `base` on the same scenario and seed: better / equal / worse and the mean cost change."""
        diffs, better, worse, equal = [], 0, 0, 0
        for k in subset_keys:
            a, b = by.get((*k, base)), by.get((*k, strategy))
            if not a or not b:
                continue
            if a["best_cost"] is None and b["best_cost"] is None:
                equal += 1
            elif a["best_cost"] is None:
                better += 1                              # found a feasible design where the base found none
            elif b["best_cost"] is None:
                worse += 1
            else:
                change = (b["best_cost"] - a["best_cost"]) / a["best_cost"]
                diffs.append(change)
                better, worse, equal = better + (change < -1e-6), worse + (change > 1e-6), equal + (abs(change) <= 1e-6)
        return {"better": better, "equal": equal, "worse": worse, "sign_test_p": round(_sign_test(better, worse), 4),
                "mean_cost_change": statistics.mean(diffs) if diffs else None,
                "bootstrap95": _bootstrap(diffs) if len(diffs) > 1 else None}

    def summarise(subset_keys: list[tuple]) -> dict:
        table = {}
        for strategy in strategies:
            runs = [by[(*k, strategy)] for k in subset_keys if (*k, strategy) in by]
            feasible = [r for r in runs if r["best_cost"] is not None]
            regrets = [(r["best_cost"] - best_known[(r["scenario"], r["seed"])]) / best_known[(r["scenario"], r["seed"])] for r in feasible]
            entry = {"runs": len(runs), "feasible": len(feasible),
                     "mean_cost": statistics.mean(r["best_cost"] for r in feasible) if feasible else None,
                     "mean_regret": statistics.mean(regrets) if regrets else None,
                     "found_best": sum(1 for g in regrets if g <= 1e-9),
                     "mean_solver_calls": statistics.mean(r["solver_calls"] for r in runs) if runs else None,
                     "mean_time_units": statistics.mean(r["time_units"] for r in runs) if runs else None,
                     "demoted_finalists": sum(r["demoted"] for r in runs),
                     "uphill_moves": sum(r["uphill_moves"] for r in runs), "repair_starts": sum(r["repair_starts"] for r in runs)}
            if strategy != "descent":
                entry["versus_descent"] = paired(subset_keys, "descent", strategy)
            if strategy == "alns_refined" and "alns" in strategies:
                entry["versus_alns"] = paired(subset_keys, "alns", strategy)
            table[strategy] = entry
        ranks = {s: [] for s in strategies}
        for k in subset_keys:
            costs = {s: (by[(*k, s)]["best_cost"] if (*k, s) in by else None) for s in strategies}
            ordered = sorted(strategies, key=lambda s: (costs[s] is None, costs[s] or 0.0))
            for s in strategies:
                ranks[s].append(1 + sum(1 for o in strategies if (costs[o] is not None and (costs[s] is None or costs[o] < costs[s] - 1e-9))))
        for s in strategies:
            table[s]["mean_rank"] = statistics.mean(ranks[s]) if ranks[s] else None
        return table

    for scenario in sorted({k[0] for k in keys}):
        out["scenarios"][scenario] = summarise([k for k in keys if k[0] == scenario])
    out["overall"] = summarise(keys)
    moves = {s: {"lns": {"used": 0, "incumbent": 0, "improving": 0, "novel": 0}, "atomic": {"used": 0, "incumbent": 0, "improving": 0, "novel": 0}, "planning_failures": 0}
             for s in ("adaptive", "alns", "alns_refined")}
    for r in rows:
        if r["strategy"] in moves:
            for kind in ("lns", "atomic"):
                for name, count in r[kind].items():
                    moves[r["strategy"]][kind][name] += count
            moves[r["strategy"]]["planning_failures"] += r["planning_failures"]
    out["moves"] = moves
    return out


def markdown(result: dict, meta: dict) -> str:
    def fmt(value, scale=1.0, digits=3):
        return "—" if value is None else f"{value / scale:.{digits}f}"
    lines = ["# Topology optimizer benchmark", "",
             f"{result['runs']} runs: {meta['scenarios']} scenarios x {meta['seeds']} seeds x {len(meta['strategies'])} strategies, "
             f"a cap of {meta['budget']} solver calls each. Same scenario, same starting seeds and same cap for every strategy.", ""]

    def table(title, data):
        lines.extend([f"## {title}", "", "| strategy | feasible | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for strategy, e in data.items():
            def describe(v):
                versus = "—" if not v else f"{v['better']}/{v['equal']}/{v['worse']}, p={v['sign_test_p']}"
                change = "—" if not v or v["mean_cost_change"] is None else (
                    f"{100 * v['mean_cost_change']:+.1f}%" + ("" if not v["bootstrap95"] else f" [{100 * v['bootstrap95'][0]:+.1f}, {100 * v['bootstrap95'][1]:+.1f}]"))
                return versus, change
            versus, change = describe(e.get("versus_descent"))
            versus_alns, change_alns = describe(e.get("versus_alns"))
            lines.append(f"| {strategy} | {e['feasible']}/{e['runs']} | {fmt(e['mean_cost'], 1e6)} | {fmt(e['mean_regret'] and 100 * e['mean_regret'], 1, 1)}% | "
                         f"{e['found_best']} | {fmt(e['mean_rank'], 1, 2)} | {fmt(e['mean_solver_calls'], 1, 0)} | {fmt(e['mean_time_units'], 1, 0)} | {versus} | {change} | {versus_alns} | {change_alns} |")
        lines.append("")
    table("Overall", result["overall"])
    for scenario, data in result["scenarios"].items():
        table(scenario, data)
    lines.extend(["## What each kind of move earned", "", "```json", json.dumps(result["moves"], indent=1), "```"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--first-seed", type=int, default=2026)
    parser.add_argument("--budget", type=int, default=150)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="worker processes (default: every core but one)")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    parser.add_argument("--json", default="/tmp/optimizer-benchmark.json")
    parser.add_argument("--markdown", default=None)
    args = parser.parse_args()
    scenarios, strategies = args.scenarios.split(","), tuple(args.strategies.split(","))
    jobs = [{"scenario": sc, "seed": args.first_seed + i, "strategy": st, "budget": args.budget}
            for sc in scenarios for i in range(args.seeds) for st in strategies]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run_one, jobs, chunksize=1))
    meta = {"scenarios": len(scenarios), "seeds": args.seeds, "strategies": list(strategies), "budget": args.budget, "first_seed": args.first_seed}
    result = analyse(rows, strategies)
    Path(args.json).write_text(json.dumps({"meta": meta, "result": result, "rows": rows}, indent=1))
    text = markdown(result, meta)
    if args.markdown:
        Path(args.markdown).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
