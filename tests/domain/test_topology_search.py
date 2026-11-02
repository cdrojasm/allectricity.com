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


# ---- trust, diversity, repair and resumption ---------------------------------------------------------------

import copy  # noqa: E402
import json  # noqa: E402


class Recorder(Model):
    """Model that also remembers every verdict it gave, by design hash."""

    def __init__(self, strictness=None):
        super().__init__(strictness)
        self.seen = {}                                        # hash -> (ratio, cost)
        self.keys = []                                        # "hash:level" of every real call

    def electrical(self, level, geometry):
        outcome = super().electrical(level, geometry)
        digest = gg.canonical_hash(gg.from_geometry(geometry))
        self.keys.append(f"{digest}:{level}")
        self.seen[digest] = (outcome["ratio"], self.cost(geometry))
        return outcome


def test_an_L1_pass_alone_never_confirms_a_design_and_unevaluated_ones_are_never_promoted():
    log = {}
    result = run(Model({"L1": 1.0, "L2+": 9.0, "L3": 9.0}), evaluations=log)      # L1 always passes, L2+ always rejects
    assert result["confirmed"] == [] and result["best"] is None and result["finalists"] == []
    assert result["certified"] is False and result["counts"].get("confirmed", 0) == 0


def test_every_confirmed_design_has_both_verdicts_and_every_finalist_has_the_finest_one():
    log = {}
    result = run(Model(), evaluations=log, calls=60)
    assert result["confirmed"] and result["finalists"]
    for record in result["confirmed"]:
        assert f"{record['candidate_sha256']}:L1" in log and f"{record['candidate_sha256']}:L2+" in log
        assert log[f"{record['candidate_sha256']}:L2+"]["status"] == "UNKNOWN"
    for record in result["finalists"]:
        assert f"{record['candidate_sha256']}:L3" in log
    assert result["best"] is None or result["best"]["candidate_sha256"] in {f["candidate_sha256"] for f in result["finalists"] if f["status"] == "finalist"}
    # nothing that was skipped for cost or never screened can appear as a confirmed design
    assert all(r["status"] == "confirmed" for r in result["confirmed"])


def test_repairable_violations_are_kept_in_a_pool_and_never_reported_as_feasible():
    model = Recorder()
    result = run(model, calls=60)
    pool = result["repair_pool"]
    assert pool and all(r["excess"] > 0 and r["status"] != "confirmed" for r in pool)
    assert all(r["excess"] <= 1.0 for r in pool)
    confirmed = {r["candidate_sha256"] for r in result["confirmed"]}
    assert not confirmed & {r["candidate_sha256"] for r in pool}
    # the closest-to-compliant violator that was cheaper than the answer is still in the pool
    cheaper = [(ratio - 1.0, digest) for digest, (ratio, cost) in model.seen.items() if ratio > 1.0 and cost < result["best"]["cost"]]
    if cheaper:
        assert min(cheaper)[1] in {r["candidate_sha256"] for r in pool}


def test_spare_budget_starts_repair_descents_from_the_pool():
    result = run(Model(), calls=60, repair_share=0.3, max_steps_per_start=6)
    assert result["counts"]["repair_starts"] > 0
    assert result["solver_calls_total"] <= 100


def test_finalists_are_chosen_for_diversity_and_not_only_for_cost():
    crowded = run(Model(), calls=60, min_elite_distance=0.0, max_steps_per_start=8)
    spread = run(Model(), calls=60, min_elite_distance=0.5, max_steps_per_start=8)
    assert crowded["counts"].get("finalists_skipped_similar", 0) == 0
    assert spread["counts"]["finalists_skipped_similar"] > 0


class Interrupted(Exception):
    pass


def _interrupt_after(count, model, **kwargs):
    log, saved = {}, {}

    def checkpoint(current):
        saved["log"] = json.loads(json.dumps(current))             # what a file would hold: plain data
        if len([k for k in current if k != "__problem__"]) >= count:
            raise Interrupted
    with pytest.raises(Interrupted):
        run(model, evaluations=log, on_checkpoint=checkpoint, problem_sha256="p", **kwargs)
    return saved["log"]


STABLE = ("best", "finalists", "confirmed", "solver_calls", "counts", "operator_rejections", "repair_pool", "l1_candidates")


@functools.lru_cache(maxsize=1)
def _reference():
    return run(Model(), calls=60, evaluations={}, problem_sha256="p")


@pytest.mark.parametrize("count", [2, 20])
def test_an_interrupted_search_resumes_to_the_same_result_without_repeating_any_evaluation(count):
    reference = _reference()
    saved = _interrupt_after(count, Model(), calls=60)
    assert json.dumps(saved)                                       # a checkpoint is plain data: no engine session in it
    spy = Recorder()
    resumed = run(spy, calls=60, evaluations=copy.deepcopy(saved), problem_sha256="p")
    for key in STABLE:
        assert resumed[key] == reference[key], key
    assert not set(spy.keys) & set(saved), "an evaluation already in the checkpoint was evaluated again"
    verdicts = len([k for k in saved if k != "__problem__"])
    assert resumed["evaluations_replayed"] >= verdicts and resumed["solver_calls_spent_this_run"] == reference["solver_calls_spent_this_run"] - verdicts


def test_a_checkpoint_from_a_different_problem_is_refused():
    saved = _interrupt_after(5, Model(), calls=60)
    with pytest.raises(ValueError, match="different problem"):
        run(Model(), calls=60, evaluations=saved, problem_sha256="another problem")


def test_a_failed_evaluation_is_not_checkpointed_so_a_resume_retries_it():
    class Flaky(Model):
        def __init__(self):
            super().__init__()
            self.failed = False

        def electrical(self, level, geometry):
            if not self.failed:
                self.failed = True
                raise RuntimeError("engine crashed")
            return super().electrical(level, geometry)
    log = {}
    run(Flaky(), calls=40, evaluations=log, problem_sha256="p")
    assert all(v.get("reason") != "evaluation_error" for k, v in log.items() if k != "__problem__")


# ---- adaptive selection inside the search ---------------------------------------------------------------

def selector_run(model, **kwargs):
    selector = AdaptiveOperatorSelector(DOMAIN)
    return run(model, operator_selector=selector, **kwargs)


def test_the_adaptive_search_reports_what_each_operator_earned_and_stays_within_budget():
    result = selector_run(Model(), calls=60)
    stats = result["operator_stats"]
    assert result["solver_calls_total"] <= 60 and result["certified"] is False
    assert set(stats) == {"weights", "outcomes"} and stats["outcomes"]
    used = {arm for arms in stats["outcomes"].values() for arm in arms}
    assert any(a.startswith("lns:") for a in used) and any(a.startswith("atomic:") for a in used)
    assert run(Model(), calls=60)["operator_stats"] is None             # not asked for, not reported


def test_the_adaptive_search_is_deterministic_and_resumes_to_the_same_result():
    reference = selector_run(Model(), calls=60, evaluations={}, problem_sha256="a")
    assert reference == selector_run(Model(), calls=60, evaluations={}, problem_sha256="a") | {}
    saved = _interrupt_after_with(AdaptiveOperatorSelector(DOMAIN), 8)
    spy = Recorder()
    resumed = run(spy, calls=60, evaluations=copy.deepcopy(saved), problem_sha256="a", operator_selector=AdaptiveOperatorSelector(DOMAIN))
    for key in STABLE + ("operator_stats",):
        assert resumed[key] == reference[key], key
    assert not set(spy.keys) & set(saved)


def _interrupt_after_with(selector, count):
    saved = {}

    def checkpoint(current):
        saved["log"] = json.loads(json.dumps(current))
        if len([k for k in current if k != "__problem__"]) >= count:
            raise Interrupted
    with pytest.raises(Interrupted):
        run(Model(), calls=60, evaluations={}, on_checkpoint=checkpoint, problem_sha256="a", operator_selector=selector)
    return saved["log"]


from src.application.use_cases.optimizer_topology_run import STRATEGIES, strategy_options  # noqa: E402
from src.domain.spat.geometry_operators import OperatorConstraints  # noqa: E402
from src.domain.spat.operator_selection import AdaptiveOperatorSelector  # noqa: E402


def test_each_strategy_maps_to_the_options_that_define_it():
    opts = {s: strategy_options(s, DOMAIN, OperatorConstraints()) for s in STRATEGIES}
    assert opts["descent"] == {"uphill_moves": 0, "propose_repair": None, "max_repair_starts": 0}
    assert opts["uphill"] == {"propose_repair": None, "max_repair_starts": 0} and opts["opportunistic"] == {}
    assert opts["adaptive"]["operator_selector"].arms == tuple(a for a in ARMS_ALL if not a.startswith("lns:"))
    assert any(a.startswith("lns:") for a in opts["alns"]["operator_selector"].arms)
    with pytest.raises(ValueError):
        strategy_options("annealing", DOMAIN, OperatorConstraints())


from src.domain.spat.operator_selection import ARMS as ARMS_ALL  # noqa: E402
