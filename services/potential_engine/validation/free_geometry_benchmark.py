"""Benchmark of the L1, L2 and L2+ evaluation levels on seeded free-form geometries.

Usage: make free-geometry-benchmark [BENCH_OUT=/tmp/free-geometry-benchmark.json]
                                    [ARGS='--seeds 2026,2027 --per-family 100 --fine-sample 120']

For every geometry it evaluates L0 (geometry and discretization check), L1, L2 and L2+, and for a
sample also a fine-raster L2 reference. Nothing here is ground truth: the best known value of a
design is the largest value any level found, since each is attained at a real surface point.
Reported: Vt/Vs underestimation, apparent false compliance, top-k ranking, time and errors by
family. Timings are only comparable between levels of one run; use --workers 1 for clean numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

import free_geometry_generator as generator  # noqa: E402

LEVELS = ("L1", "L2", "L2+", "L3")
FINE_SPACING_M = 0.125
SOILS = {"homog": 100.0, "2layer": (100.0, 300.0, 2.0)}
EXPOSURES = {"gravel 3000 ohm-m": 3000.0, "no surface layer": 100.0}
VIOLATING_FRACTIONS = (0.2, 0.5, 0.8)


def build_suite(seeds: list[int], per_family: int) -> list[dict]:
    """Deterministic list of {seed, index, family, soil, geometry}; the same seeds give the same list."""
    suite = []
    for seed in seeds:
        rng = random.Random(seed)
        for index in range(per_family * len(generator.FAMILIES)):
            family = generator.FAMILIES[index % len(generator.FAMILIES)]
            produced = generator.valid_geometry(rng, family)
            soil = "homog" if rng.random() < 0.5 else "2layer"
            if produced:
                suite.append({"seed": seed, "index": index, "family": family, "soil": soil,
                              "geometry": produced[0], "meta": produced[1]})
    return suite


def suite_sha256(suite: list[dict]) -> str:
    payload = json.dumps([(d["seed"], d["index"], d["soil"], d["geometry"]) for d in suite],
                         sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _soil(name: str):
    from src.infrastructure.calculations.potential_engine_client import TwoLayerSoil
    spec = SOILS[name]
    return spec if isinstance(spec, float) else TwoLayerSoil(*spec)


def evaluate_design_levels(job: dict) -> dict:
    """Worker: L0 then every level on one design, recording values, times and refusals."""
    from src.infrastructure.calculations import solver_evaluation
    from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
    client, soil = PotentialEngineClient(), _soil(job["soil"])
    row = {"key": job["key"], "family": job["family"], "soil": job["soil"]}
    started = time.perf_counter()
    violations = solver_evaluation.discretization_violations(job["geometry"], soil)
    row["t_L0"] = time.perf_counter() - started
    if violations:
        row["l0_rejected"] = [v["kind"] for v in violations]
        return row
    try:
        for level in LEVELS:
            started = time.perf_counter()
            result = solver_evaluation.evaluate(geometry=job["geometry"], soil=soil, injection_a=1000.0,
                                                points=[], client=client, level=level)
            row["t_" + level] = time.perf_counter() - started
            row[level] = {"Vt": result["quantities"]["Vt_v"], "Vs": result["quantities"]["Vs_v"]}
            if result.get("refinement"):
                row["refinement"] = result["refinement"]
    except Exception as exc:  # noqa: BLE001 - a refusal L0 missed is itself a result
        row["solver_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return row


def fine_reference(job: dict) -> dict:
    from src.infrastructure.calculations import solver_evaluation
    from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
    try:
        result = solver_evaluation.evaluate(geometry=job["geometry"], soil=_soil(job["soil"]), injection_a=1000.0, points=[],
                                            client=PotentialEngineClient(), level="L2",
                                            settings={"surface_spacing_m": FINE_SPACING_M})
        return {"key": job["key"], "Vt": result["quantities"]["Vt_v"], "Vs": result["quantities"]["Vs_v"]}
    except Exception as exc:  # noqa: BLE001
        return {"key": job["key"], "error": str(exc)[:120]}


def _pct(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _spearman(a: list[float], b: list[float]) -> float:
    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        out = [0.0] * len(values)
        for rank, index in enumerate(order):
            out[index] = rank
        return out
    ra, rb, mean = ranks(a), ranks(b), (len(a) - 1) / 2
    den = (sum((x - mean) ** 2 for x in ra) * sum((y - mean) ** 2 for y in rb)) ** 0.5
    return sum((x - mean) * (y - mean) for x, y in zip(ra, rb)) / den if den else 0.0


def _limits(surface_resistivity: float) -> dict[str, float]:
    from src.infrastructure.calculations import safety_criteria
    exposure = safety_criteria.FaultExposure(0.5, 70, surface_resistivity, 0.1, 100)
    result = safety_criteria.evaluate({"step_v": 1.0, "touch_v": 1.0, "gpr_v": 1.0}, exposure, [safety_criteria.IEEE80_2013])
    return {c["criterion"]: c["tolerable_v"] for c in result[0]["criteria"]}


def report(rows: list[dict], fine: dict[str, dict]) -> dict:
    evaluated = [r for r in rows if all(level in r for level in LEVELS)]
    best = {}
    for r in evaluated:
        values = [r[level] for level in LEVELS] + ([fine[r["key"]]] if r["key"] in fine else [])
        best[r["key"]] = {q: max(v[q] for v in values) for q in ("Vt", "Vs")}
    out = {"designs": len(rows), "evaluated": len(evaluated), "fine_references": len(fine), "families": {}}

    out["errors_by_family"] = {}
    for family in generator.FAMILIES:
        group = [r for r in rows if r["family"] == family]
        out["errors_by_family"][family] = {
            "designs": len(group),
            "l0_rejected": sum("l0_rejected" in r for r in group),
            "solver_errors_missed_by_l0": sum("solver_error" in r for r in group),
        }

    below = [r["key"] for r in evaluated for q in ("Vt", "Vs")
             if r["L2+"][q] < max(r["L1"][q], r["L2"][q]) * (1 - 1e-9)]
    out["l2plus_below_l1_or_l2"] = len(set(below))
    out["l3_below_l2plus"] = len({r["key"] for r in evaluated for q in ("Vt", "Vs") if r["L3"][q] < r["L2+"][q] * (1 - 1e-9)})

    # OPT-004: precision against the fine-raster reference, cost against L2+, and how the search stopped.
    sampled = [r for r in evaluated if r["key"] in fine]
    out["against_fine_reference"] = {}
    for level in LEVELS:
        out["against_fine_reference"][level] = {}
        for q in ("Vt", "Vs"):
            errors = [r[level][q] / fine[r["key"]][q] - 1 for r in sampled]
            if errors:
                out["against_fine_reference"][level][q] = {
                    "n": len(errors), "median": statistics.median(errors), "p5": _pct(errors, 0.05), "worst": min(errors),
                    "short_over_1pct": sum(e < -0.01 for e in errors), "above_reference_over_half_pct": sum(e > 0.005 for e in errors)}
    refined = [r for r in evaluated if "refinement" in r]
    stops: dict[str, int] = {}
    for r in refined:
        for reason, count in r["refinement"]["stops"].items():
            stops[reason] = stops.get(reason, 0) + count
    short_after_convergence = [r["key"] for r in sampled if r.get("refinement", {}).get("locally_converged")
                               and any(r["L3"][q] / fine[r["key"]][q] - 1 < -0.01 for q in ("Vt", "Vs"))]
    out["adaptive_refinement"] = {
        "designs": len(refined), "stops": stops,
        "locally_converged": sum(r["refinement"]["locally_converged"] for r in refined),
        "points_evaluated_median": statistics.median(r["refinement"]["points_evaluated"] for r in refined) if refined else None,
        "points_evaluated_max": max((r["refinement"]["points_evaluated"] for r in refined), default=None),
        "gain_vs_l2plus_Vs_max": max((r["L3"]["Vs"] / r["L2+"]["Vs"] - 1 for r in evaluated), default=None),
        "gain_vs_l2plus_Vt_max": max((r["L3"]["Vt"] / r["L2+"]["Vt"] - 1 for r in evaluated), default=None),
        # Local convergence is not a certificate: these converged and still fall short of the fine reference.
        "converged_but_short_of_fine_reference": len(short_after_convergence),
        "certifies_global_maximum": False}

    out["underestimation"] = {}   # level -> quantity -> family or "all" -> stats (relative to best known)
    for level in LEVELS:
        out["underestimation"][level] = {}
        for q in ("Vt", "Vs"):
            by = {}
            for family in ("all", *generator.FAMILIES):
                errors = [r[level][q] / best[r["key"]][q] - 1 for r in evaluated if family in ("all", r["family"])]
                if errors:
                    by[family] = {"n": len(errors), "median": statistics.median(errors), "p5": _pct(errors, 0.05),
                                  "worst": min(errors), "short_over_2pct": sum(e < -0.02 for e in errors),
                                  "short_over_5pct": sum(e < -0.05 for e in errors)}
            out["underestimation"][level][q] = by

    out["false_compliance"] = {}
    ratio = lambda values, scale, lim: max(values["Vt"] * scale / lim["touch"], values["Vs"] * scale / lim["step"])  # noqa: E731
    for name, surface in EXPOSURES.items():
        lim, entry = _limits(surface), {}
        base = [ratio(best[r["key"]], 1.0, lim) for r in evaluated]
        for fraction in VIOLATING_FRACTIONS:
            scale = 1.0 / _pct(base, 1 - fraction)
            counts = {}
            for level in LEVELS:
                bad = [(ratio(best[r["key"]], scale, lim)) for r in evaluated
                       if ratio(best[r["key"]], scale, lim) > 1 and ratio(r[level], scale, lim) <= 1]
                counts[level] = {"false_compliance": len(bad), "worst_true_ratio": max(bad) if bad else None}
            entry[f"{int(fraction * 100)}% violating"] = {"injection_ka": scale, "levels": counts}
        out["false_compliance"][name] = entry

    lim = _limits(3000.0)
    truth = [ratio(best[r["key"]], 1.0, lim) for r in evaluated]
    top_k = max(1, len(evaluated) // 10)
    best_set = set(sorted(range(len(evaluated)), key=truth.__getitem__)[:top_k])
    out["ranking"] = {}
    for level in LEVELS:
        scores = [ratio(r[level], 1.0, lim) for r in evaluated]
        order = sorted(range(len(evaluated)), key=scores.__getitem__)
        out["ranking"][level] = {
            "spearman_vs_best_known": _spearman(scores, truth),
            f"top_{top_k}_found_in_level_top_{top_k}": len(best_set & set(order[:top_k])) / top_k,
            f"top_{top_k}_found_in_level_top_{2 * top_k}": len(best_set & set(order[:2 * top_k])) / top_k}

    out["time_s"] = {"L0": {"total": sum(r["t_L0"] for r in rows)}}
    for level in LEVELS:
        times = [r["t_" + level] for r in evaluated]
        out["time_s"][level] = {"total": sum(times), "median": statistics.median(times)}
    out["time_s"]["median_ratio_L2_over_L1"] = statistics.median(r["t_L2"] / r["t_L1"] for r in evaluated)
    out["time_s"]["median_ratio_L2plus_over_L2"] = statistics.median(r["t_L2+"] / r["t_L2"] for r in evaluated)
    out["time_s"]["median_ratio_L3_over_L2plus"] = statistics.median(r["t_L3"] / r["t_L2+"] for r in evaluated)
    return out


def markdown(result: dict, meta: dict) -> str:
    lines = ["# Free-geometry fidelity benchmark", "",
             f"Seeds {meta['seeds']}, {result['designs']} designs ({result['evaluated']} evaluated, "
             f"{result['fine_references']} with a fine reference). Geometry set `{meta['geometry_set_sha256'][:16]}`.", "",
             f"L2+ below L1 or L2: **{result['l2plus_below_l1_or_l2']}** | L3 below L2+: **{result['l3_below_l2plus']}**", "",
             "## Errors by family", "", "| family | designs | L0 rejected | solver refusals missed by L0 |", "|---|---|---|---|"]
    for family, e in result["errors_by_family"].items():
        lines.append(f"| {family} | {e['designs']} | {e['l0_rejected']} | {e['solver_errors_missed_by_l0']} |")
    lines += ["", "## Underestimation against the best known value (negative = falls short)", "",
              "| level | quantity | median | p5 | worst | short >2% | short >5% |", "|---|---|---|---|---|---|---|"]
    for level, quantities in result["underestimation"].items():
        for q, groups in quantities.items():
            a = groups["all"]
            lines.append(f"| {level} | {q} | {a['median']:+.4f} | {a['p5']:+.4f} | {a['worst']:+.4f} | "
                         f"{a['short_over_2pct']} | {a['short_over_5pct']} |")
    lines += ["", "## Apparent false compliance (best known value violates, level says it complies)", "",
              "| exposure | share violating | " + " | ".join(LEVELS) + " |", "|---|---|" + "---|" * len(LEVELS)]
    for exposure, entry in result["false_compliance"].items():
        for share, data in entry.items():
            cells = " | ".join(str(data["levels"][level]["false_compliance"]) for level in LEVELS)
            lines.append(f"| {exposure} | {share} | {cells} |")
    lines += ["", "## Against the fine-raster reference (negative = falls short)", "",
              "| level | quantity | n | median | p5 | worst | short >1% | above reference >0.5% |", "|---|---|---|---|---|---|---|---|"]
    for level, quantities in result["against_fine_reference"].items():
        for q, a in quantities.items():
            lines.append(f"| {level} | {q} | {a['n']} | {a['median']:+.4f} | {a['p5']:+.4f} | {a['worst']:+.4f} | "
                         f"{a['short_over_1pct']} | {a['above_reference_over_half_pct']} |")
    lines += ["", "## Adaptive refinement (L3)", "", "Local convergence is not certification: the searches stop improving from their own seeds only.",
              "", "```json", json.dumps(result["adaptive_refinement"], indent=1), "```"]
    lines += ["", "## Ranking", "", "```json", json.dumps(result["ranking"], indent=1), "```", "",
              "## Time (s)", "", "```json", json.dumps(result["time_s"], indent=1), "```"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", default="2026")
    parser.add_argument("--per-family", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fine-sample", type=int, default=0, help="designs given a fine-raster reference (half worst-disagreement, half random)")
    parser.add_argument("--json", default="/tmp/free-geometry-benchmark.json")
    parser.add_argument("--markdown", default=None)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    suite = build_suite(seeds, args.per_family)
    jobs = [{"key": f"{d['seed']}:{d['index']}", **{k: d[k] for k in ("family", "soil", "geometry")}} for d in suite]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(evaluate_design_levels, jobs, chunksize=2))
        fine = {}
        if args.fine_sample:
            ready = [r for r in rows if all(level in r for level in LEVELS)]
            disagreement = sorted(ready, key=lambda r: -(abs(r["L1"]["Vt"] / r["L2"]["Vt"] - 1) + abs(r["L1"]["Vs"] / r["L2"]["Vs"] - 1)))
            chosen = [r["key"] for r in disagreement[: args.fine_sample // 2]]
            rest = [r["key"] for r in ready if r["key"] not in set(chosen)]
            chosen += random.Random(seeds[0]).sample(rest, min(len(rest), args.fine_sample - len(chosen)))
            by_key = {j["key"]: j for j in jobs}
            fine = {f["key"]: f for f in pool.map(fine_reference, [by_key[k] for k in chosen]) if "error" not in f}
    result = report(rows, fine)
    meta = {"seeds": seeds, "per_family": args.per_family, "workers": args.workers, "geometry_set_sha256": suite_sha256(suite),
            "created_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform()}
    Path(args.json).write_text(json.dumps({"meta": meta, "result": result}, indent=1))
    text = markdown(result, meta)
    if args.markdown:
        Path(args.markdown).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
