"""Fidelity controller and topological search, against a made-up electrical model (no solver)."""

import functools

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


@functools.lru_cache(maxsize=8)
def _seeds(seed, count):
    return tuple(seeds.generate_seeds(DOMAIN, seed=seed, count=count))


def run(model, seed=1, calls=80, **kwargs):
    return search_topology(domain=DOMAIN, seeds=list(_seeds(seed, 4)), evaluate_cost=model.cost,
                           evaluate_electrical=model.electrical, seed=seed, max_solver_calls=calls, **kwargs)


def test_search_improves_on_the_best_feasible_seed_and_never_claims_certification():
    model = Model()
    start = _seeds(1, 4)
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
    start = [s for s in _seeds(1, 4) if length(s.geometry) < 120][:1]
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


# ---- exploring through costlier states ------------------------------------------------------------------

from src.domain.spat import geometry_operators as ops   # noqa: E402


def _rods(geometry):
    return len(geometry.get("rods") or [])


class Ridge:
    """Cost depends on the rod count only: a local minimum, three costlier steps, then a much cheaper design."""
    TABLE = {0: 1000.0, 1: 1100.0, 2: 1200.0, 3: 1300.0, 4: 700.0}

    def __init__(self):
        self.calls = []                                   # (level, cost) of every solver call

    def cost(self, geometry):
        return self.TABLE.get(_rods(geometry), 5000.0)

    def electrical(self, level, geometry):
        self.calls.append((level, self.cost(geometry)))
        return {"status": "UNKNOWN", "ratio": 0.5}


def add_next_rod(graph, rng):
    free = [n for n in sorted(graph.nodes()) if n not in graph.rod_nodes()]
    return ops.AddRod(free[0], 2.4)


@functools.lru_cache(maxsize=1)
def _rodless_seed():
    start = [s for s in _seeds(1, 4) if _rods(s.geometry) == 0][:1]
    assert start
    return tuple(start)


def ridge_run(model, **kwargs):
    start = list(_rodless_seed())
    return search_topology(domain=DOMAIN, seeds=start, evaluate_cost=model.cost, evaluate_electrical=model.electrical, seed=3,
                           max_solver_calls=40, propose_operator=add_next_rod, neighbors_per_step=2, patience=1, finalists=1, **kwargs)


def test_the_search_can_cross_a_costlier_ridge_to_a_cheaper_design_without_spending_the_solver_on_it():
    model = Ridge()
    result = ridge_run(model, uphill_moves=3)
    assert result["best"]["cost"] == 700.0
    assert result["counts"]["uphill_moves_taken"] == 3 and result["counts"]["incumbents_found_after_uphill_moves"] >= 1
    # The three intermediate designs (1100, 1200, 1300) were never sent to the solver: they cannot beat the incumbent.
    assert {cost for _, cost in model.calls} <= {1000.0, 700.0}
    assert result["counts"]["skipped_cost_dominated"] >= 3          # the ridge states, and the dearer neighbours of the end state


def test_without_uphill_moves_the_search_stops_at_the_local_minimum():
    flat = ridge_run(Ridge(), uphill_moves=0)
    assert flat["best"]["cost"] == 1000.0 and flat["counts"].get("uphill_moves_taken", 0) == 0
    short = ridge_run(Ridge(), uphill_moves=2)                 # two steps are not enough for a three-step ridge
    assert short["best"]["cost"] == 1000.0 and short["counts"]["uphill_moves_taken"] == 2


def test_the_cost_tolerance_limits_how_much_costlier_an_intermediate_state_may_be():
    assert ridge_run(Ridge(), uphill_moves=3, uphill_tolerance=0.05)["best"]["cost"] == 1000.0     # +10% per step is too much
    assert ridge_run(Ridge(), uphill_moves=3, uphill_tolerance=0.12)["best"]["cost"] == 700.0


def test_exploration_keeps_the_search_deterministic():
    assert ridge_run(Ridge(), uphill_moves=3) == ridge_run(Ridge(), uphill_moves=3)
