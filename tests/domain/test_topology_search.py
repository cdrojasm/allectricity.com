"""Fidelity controller and topological search, against a made-up electrical model (no solver)."""

import pytest
from src.domain.spat import geometry_graph as gg, geometry_seeds as seeds
from src.domain.spat.optimizer_topology_search import search_topology

DOMAIN = {
    "length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
    "areas": [{"type": "intervenible", "label": "lote", "polygon": [
        {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
    "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}],
}


def length(geometry):
    return gg.from_geometry(geometry).total_length_m()


class Model:
    """Utilization falls as conductor length grows; each level is a little stricter than the one before."""

    def __init__(self, strictness=None):
        self.calls = []                       # (level, canonical hash of the geometry)
        self.strictness = strictness or {"L1": 1.0, "L2+": 1.0, "L3": 1.0}

    def cost(self, geometry):
        return length(geometry) * 1000.0

    def electrical(self, level, geometry):
        total = length(geometry)
        self.calls.append((level, gg.canonical_hash(gg.from_geometry(geometry))))
        ratio = 120.0 / total * self.strictness[level]
        return {"status": "VIOLATED" if ratio > 1 else "UNKNOWN", "ratio": ratio}


def run(model, seed=1, calls=80, **kwargs):
    return search_topology(domain=DOMAIN, seeds=seeds.generate_seeds(DOMAIN, seed=seed, count=4), evaluate_cost=model.cost,
                           evaluate_electrical=model.electrical, seed=seed, max_solver_calls=calls, **kwargs)


def test_search_improves_on_the_best_feasible_seed_and_never_claims_certification():
    model = Model()
    start = seeds.generate_seeds(DOMAIN, seed=1, count=4)
    feasible_seeds = [length(s.geometry) * 1000 for s in start if length(s.geometry) >= 120]
    result = run(model)
    assert result["best"] is not None and result["certified"] is False
    assert result["best"]["cost"] <= min(feasible_seeds)
    assert result["best"]["ratio"] <= 1.0 + 1e-9
    assert result == run(Model())                 # deterministic for a seed


def test_the_fidelity_controller_escalates_only_what_passes_and_skips_what_cannot_win():
    model = Model()
    result = run(model)
    first_level = {}
    for level, size in model.calls:
        first_level.setdefault(size, []).append(level)
    for size, levels in first_level.items():
        assert levels[0] == "L1"                                           # nothing reaches the solver above L1 directly
        assert levels.count("L1") == 1 and levels.count("L2+") <= 1
    assert result["counts"]["skipped_cost_dominated"] > 0                  # priced out before any solver call
    assert result["counts"]["pruned_at_L1"] > 0
    assert result["solver_time_units"] < result["baseline_time_units_if_every_candidate_used_L2plus"]
    assert result["solver_calls_total"] == len(model.calls) <= 80


def test_screened_and_confirmed_archives_are_kept_apart():
    result = run(Model({"L1": 1.0, "L2+": 1.4, "L3": 1.4}))     # L2+ is stricter, so some L1 passes are rejected there
    confirmed = {r["candidate_sha256"] for r in result["confirmed"]}
    screened = {r["candidate_sha256"] for r in result["l1_candidates"]}
    assert confirmed <= screened and screened - confirmed         # L1 passes that L2+ did not confirm stay out of `confirmed`
    assert all(r["status"] == "confirmed" for r in result["confirmed"])
    assert all(r["status"] != "confirmed" for r in result["l1_candidates"] if r["candidate_sha256"] not in confirmed)


def test_finalists_that_fail_the_finest_check_are_demoted():
    result = run(Model({"L1": 1.0, "L2+": 1.0, "L3": 1.25}), calls=100, finalists=3)
    assert result["counts"].get("demoted_at_finalist_level", 0) >= 1
    assert result["best"] is None or result["best"]["ratio"] <= 1.0 + 1e-9
    assert all(f["status"] == "finalist" for f in result["finalists"] if f["candidate_sha256"] == (result["best"] or {}).get("candidate_sha256"))


def test_a_violating_seed_is_repaired_before_it_is_made_cheaper():
    start = [s for s in seeds.generate_seeds(DOMAIN, seed=1, count=6) if length(s.geometry) < 120][:1]
    assert start
    model = Model()
    result = search_topology(domain=DOMAIN, seeds=start, evaluate_cost=model.cost, evaluate_electrical=model.electrical,
                             seed=2, max_solver_calls=150)
    assert result["best"] is not None and result["best"]["ratio"] <= 1.0 + 1e-9


def test_the_solver_budget_is_never_exceeded_and_finalists_keep_a_reserve():
    for budget in (6, 15, 40):
        model = Model()
        result = run(model, calls=budget, finalists=2)
        assert len(model.calls) <= budget and result["solver_calls_total"] <= budget
        assert result["reserved_for_finalists"] == 2
    tiny = run(Model(), calls=3, finalists=2)
    assert tiny["solver_calls_total"] <= 3 and tiny["certified"] is False


def test_invalid_arguments_are_refused():
    model = Model()
    with pytest.raises(ValueError):
        search_topology(domain=DOMAIN, seeds=[], evaluate_cost=model.cost, evaluate_electrical=model.electrical, seed=True, max_solver_calls=5)
    with pytest.raises(ValueError):
        search_topology(domain=DOMAIN, seeds=[], evaluate_cost=model.cost, evaluate_electrical=model.electrical, seed=1, max_solver_calls=0)
