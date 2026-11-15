"""Fidelity controller and topological search, against a made-up electrical model (no solver)."""

import functools
import threading
import time

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


def test_parallel_finalist_checks_overlap_but_keep_the_sequential_result_and_budget():
    class ConcurrentModel(Model):
        def __init__(self):
            super().__init__()
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def electrical(self, level, geometry):
            if level == "L3":
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.02)
                try:
                    return super().electrical(level, geometry)
                finally:
                    with self.lock:
                        self.active -= 1
            return super().electrical(level, geometry)

    sequential = run(Model(), calls=60, parallel_workers=1)
    concurrent_model = ConcurrentModel()
    parallel = run(concurrent_model, calls=60, parallel_workers=3)
    for key in STABLE:
        assert parallel[key] == sequential[key], key
    assert concurrent_model.max_active > 1
    assert parallel["solver_calls_total"] <= 60


def test_parallel_finalist_mode_rejects_invalid_worker_counts():
    with pytest.raises(ValueError, match="parallel_workers"):
        run(Model(), parallel_workers=0)


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
        assert result["reserved_for_finalists"] == 4        # finalists + 2, so a demoted design can be replaced
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


# ---- the finest check can demote designs, and the search must have calls left to replace them ---------------

class DemoteSome(Model):
    """Passes L1 and L2+ like Model, but the finest level rejects a chosen set of designs."""

    def __init__(self, hashes):
        super().__init__()
        self.hashes = set(hashes)

    def electrical(self, level, geometry):
        outcome = super().electrical(level, geometry)
        if level == "L3" and gg.canonical_hash(gg.from_geometry(geometry)) in self.hashes:
            return {"status": "VIOLATED", "ratio": 1.5}
        return outcome


def test_when_the_finest_check_demotes_the_cheapest_designs_the_next_confirmed_one_is_examined():
    reference = run(Model(), calls=60, finalists=2, min_elite_distance=0.0)
    cheapest = [r["candidate_sha256"] for r in reference["confirmed"]]
    assert len(cheapest) >= 4
    doomed = cheapest[:3]
    result = run(DemoteSome(doomed), calls=60, finalists=2, min_elite_distance=0.0)
    assert result["counts"]["demoted_at_finalist_level"] == 3
    assert result["best"] is not None and result["best"]["candidate_sha256"] == cheapest[3]
    assert result["solver_calls"].get("L3", 0) == 4 and result["solver_calls_total"] <= 60


def test_a_reserve_of_exactly_the_finalists_cannot_replace_a_demoted_design():
    reference = run(Model(), calls=60, finalists=2, finalist_reserve=2, min_elite_distance=0.0)
    doomed = [r["candidate_sha256"] for r in reference["confirmed"]][:2]
    stuck = run(DemoteSome(doomed), calls=60, finalists=2, finalist_reserve=2, min_elite_distance=0.0)
    assert stuck["best"] is None                                     # the old behaviour: two calls, two demotions, nothing left
    assert run(Model(), calls=60, finalists=2)["reserved_for_finalists"] == 4          # default: finalists + 2


# ---- OPT-005: one reading of feasibility for the parametric and the topological search -----------------------

from src.application.use_cases.optimizer_topology_run import electrical_verdict  # noqa: E402
from src.domain.spat.feasibility import admits  # noqa: E402
from src.domain.spat.optimizer_search import search_discrete_local  # noqa: E402

# (level, FeasibilityStatus, Feasible) -> may it pass the gate?
GATE = {("L1", "UNKNOWN", None): True, ("L1", "VIOLATED", False): False,
        ("L2+", "UNKNOWN", True): True, ("L2+", "UNKNOWN", None): False, ("L2+", "VIOLATED", False): False,
        ("L3", "UNKNOWN", True): True, ("L3", "UNKNOWN", None): False, ("L3", "VIOLATED", False): False,
        ("L2", "UNKNOWN", True): True, ("L2", "UNKNOWN", None): False}


@pytest.mark.parametrize("case,expected", GATE.items())
def test_both_searches_read_every_feasibility_state_the_same_way(case, expected):
    level, status, feasible = case
    assert admits(level=level, status=status, feasible=feasible) is expected
    # topological reading of an evaluate_design-shaped result
    verdict = electrical_verdict(level, {"FeasibilityStatus": status, "Feasible": feasible, "SafetyEvaluations": []})
    assert (verdict["status"] not in ("VIOLATED", "REJECTED")) is expected
    assert (verdict["status"] == "VIOLATED") is (status == "VIOLATED")
    # parametric reading of the same result: it searches at L2
    if level == "L2":
        found = search_discrete_local(
            base_parameters={"x": 1}, domains={"x": [1, 2]}, build_candidate=lambda p: {"ok": True},
            evaluate_safety=lambda b, p: {"FeasibilityStatus": status, "Feasible": feasible},
            evaluate_cost=lambda b, s, p: 1.0, seed=1, max_evaluations=4, restarts=1)
        assert (found["best"] is not None) is expected


def test_an_unassessed_design_is_rejected_at_the_confirming_level_not_promoted():
    verdict = electrical_verdict("L2+", {"FeasibilityStatus": "UNKNOWN", "Feasible": None, "SafetyEvaluations": []})
    assert verdict["status"] == "REJECTED" and verdict["reason"] == "not_assessable"
    assert electrical_verdict("L1", {"FeasibilityStatus": "UNKNOWN", "Feasible": None, "SafetyEvaluations": []})["status"] == "UNKNOWN"


# ---- fast mode: a time budget with an L3 reserve ---------------------------------------------------------------

class Clocked(Model):
    """Model whose calls take time on a fake clock: L1 1 s, L2+ 6.5 s, L3 6.9 s."""
    SECONDS = {"L1": 1.0, "L2+": 6.5, "L3": 6.9}

    def __init__(self):
        super().__init__()
        self.now = 0.0

    def clock(self):
        return self.now

    def electrical(self, level, geometry):
        outcome = super().electrical(level, geometry)
        self.now += self.SECONDS[level]
        return outcome


def test_the_fast_mode_stops_on_time_and_keeps_the_finalists_their_l3_reserve():
    model = Clocked()
    result = run(model, calls=None, time_budget_s=120.0, clock=model.clock)
    assert result["budget"]["mode"] == "time" and result["max_solver_calls"] is None
    assert model.now <= 120.0 + Clocked.SECONDS["L3"]                    # a started call is not interrupted
    assert result["solver_calls"].get("L3", 0) >= 1 and result["best"] is not None   # the search left room for the finest check
    assert result["budget"]["finalists_hold_at_start_of_search"] >= 0.2 * 120.0
    searching_end = max(i for i, (level, _) in enumerate(model.calls) if level != "L3")
    assert all(level == "L3" for level, _ in model.calls[searching_end + 1:])
    model2 = Clocked()
    assert run(model2, calls=None, time_budget_s=120.0, clock=model2.clock)["best"] == result["best"]    # the fake clock is deterministic


def test_the_time_reserve_follows_the_observed_l3_cost():
    model = Clocked()
    model.SECONDS = {"L1": 1.0, "L2+": 6.5, "L3": 30.0}                   # L3 turns out far dearer than the weights say
    result = run(model, calls=None, time_budget_s=200.0, clock=model.clock, finalists=2)
    assert result["solver_calls"].get("L3", 0) >= 1


def test_exactly_one_budget_is_accepted_and_the_call_mode_is_unchanged():
    model = Model()
    for kwargs in ({"calls": None}, {"calls": 10, "time_budget_s": 5.0}, {"calls": None, "time_budget_s": 0}):
        with pytest.raises(ValueError):
            run(model, **kwargs)
    reference = run(Model(), calls=80)
    assert reference["budget"] == {**reference["budget"], "mode": "calls", "total": 80} and reference["refinements"] == []


# ---- OPT-014: the parametric search tunes the rods of the elite topologies ---------------------------------------

from src.domain.spat import parametric_refinement  # noqa: E402
from src.domain.spat.geometry_operators import OperatorConstraints as _Constraints  # noqa: E402


def _graph_with_rods(lengths):
    base = gg.from_geometry(_seeds(1, 4)[0].geometry)
    nodes = sorted(base.nodes())[:len(lengths)]
    return gg.GeometryGraph(base.site, base.segments, frozenset((n, float(length), "unspecified") for n, length in zip(nodes, lengths)))


class RodScreen:
    """A confirmed design needs 8 m of rod in total; the cost is per metre of rod. Counts what it is asked."""

    def __init__(self):
        self.asked = []

    def __call__(self, graph):
        total = sum(length for _, length, _ in graph.rods)
        self.asked.append(total)
        ok = total >= 8.0
        return {"candidate_sha256": gg.canonical_hash(graph), "status": "confirmed" if ok else "rejected",
                "reason": None if ok else "violated_at_L2+", "cost": total * 1000.0}


def test_rod_refinement_walks_a_feasible_design_down_to_the_cheapest_rods_that_still_pass():
    graph = _graph_with_rods([6.0, 6.0, 6.0])
    screen = RodScreen()
    outcome = parametric_refinement.refine_rods(graph, screen=screen, constraints=_Constraints(), domain=DOMAIN, max_evaluations=60)
    assert outcome["improved"] is True
    refined = sum(length for _, length, _ in outcome["refined_graph"].rods)
    assert 8.0 <= refined < 18.0 and outcome["best"]["cost"] == pytest.approx(refined * 1000.0)
    assert min(screen.asked) < 8.0                                 # it did probe the violating side
    rodless = gg.GeometryGraph(graph.site, graph.segments, frozenset())
    assert parametric_refinement.refine_rods(rodless, screen=screen, domain=DOMAIN)["reason"] == "no_rods"


def test_refinement_reuses_the_op06_search_and_its_gate():
    graph = _graph_with_rods([3.0, 3.0])
    outcome = parametric_refinement.refine_rods(graph, screen=lambda g: {"status": "rejected", "reason": "violated_at_L1", "cost": 1.0},
                                                constraints=_Constraints(), domain=DOMAIN, max_evaluations=10)
    assert outcome["best"] is None and outcome["improved"] is False       # nothing confirmed, so nothing is claimed


def test_the_refining_search_stays_inside_the_same_budget_and_reports_what_it_did():
    plain = run(Model(), calls=80)
    refined = run(Model(), calls=80, refine_share=0.25)
    assert refined["solver_calls_total"] <= 80 and plain["solver_calls_total"] <= 80
    assert refined["certified"] is False and refined["reserved_for_finalists"] == plain["reserved_for_finalists"]
    assert refined["budget"]["refine_hold"] == int(0.25 * (80 - refined["reserved_for_finalists"]))
    assert plain["refinements"] == [] and "refinement_starts" not in plain["counts"]


# ---- OPT-014B: refinement policies that compete with exploration for the same budget ---------------------------------

def test_the_opportunistic_policy_holds_nothing_back_and_never_refines_on_an_exhausted_budget():
    tight = run(Model(), calls=40, refine_leftover=True)
    assert tight["budget"]["refine_hold"] == 0 and tight["solver_calls_total"] <= 40
    if tight["budget_exhausted"]:
        assert tight["refinements"] == []                                  # the search used its budget: refinement gets none of it
    assert run(Model(), calls=40, refine_leftover=True) == tight           # deterministic


def test_the_checkpoint_rule_reads_only_what_has_happened_and_either_explores_or_refines():
    results = [run(Model(), calls=calls, checkpoint_fraction=0.8) for calls in (40, 80, 150)]
    for result in results:
        decided = result["counts"].get("checkpoint_explored", 0) + result["counts"].get("checkpoint_refined", 0)
        assert decided == 1 and result["solver_calls_total"] <= result["max_solver_calls"] and result["certified"] is False
        assert result["budget"]["refine_hold"] > 0
    assert run(Model(), calls=80, checkpoint_fraction=0.8) == results[1]
    with pytest.raises(ValueError):
        run(Model(), checkpoint_fraction=0.8, refine_share=0.2)
    with pytest.raises(ValueError):
        run(Model(), checkpoint_fraction=1.0)


def test_every_policy_keeps_the_finest_check_and_the_same_total_budget():
    from src.application.use_cases.optimizer_topology_run import strategy_options
    from src.domain.spat.geometry_operators import OperatorConstraints
    assert strategy_options("alns_opportunistic", DOMAIN, OperatorConstraints())["refine_leftover"] is True
    assert strategy_options("alns_checkpoint", DOMAIN, OperatorConstraints())["checkpoint_fraction"] == 0.8
    for extra in ({"refine_share": 0.25}, {"refine_leftover": True}, {"checkpoint_fraction": 0.8}):
        result = run(Model(), calls=80, **extra)
        assert result["solver_calls_total"] <= 80 and all(f["level"] == "L3" for f in result["finalists"])


def test_pure_alns_is_the_default_and_no_experimental_policy_changes_another_one():
    import inspect
    from src.application.use_cases import optimizer_topology_run as topology_run
    assert inspect.signature(topology_run.run_topology_optimizer).parameters["strategy"].default == "alns"
    assert topology_run.DEFAULT_STRATEGY == "alns" and set(topology_run.EXPERIMENTAL_STRATEGIES) <= set(topology_run.STRATEGIES)
    off = topology_run.strategy_options("alns", DOMAIN, OperatorConstraints())
    assert not {"refine_share", "refine_leftover", "checkpoint_fraction"} & set(off)
    # With every refinement switch off the search is the one it always was, whatever the other policies do in between.
    reference = run(Model(), calls=80)
    run(Model(), calls=80, refine_share=0.25)
    run(Model(), calls=80, refine_leftover=True)
    run(Model(), calls=80, checkpoint_fraction=0.8)
    assert run(Model(), calls=80) == reference
    assert run(Model(), calls=80, refine_share=0.0, refine_leftover=False, checkpoint_fraction=None) == reference
    assert reference["refinements"] == [] and reference["budget"]["refine_hold"] == 0


def test_the_experimental_policies_account_for_every_call_in_the_one_budget():
    for extra in ({"refine_share": 0.25}, {"refine_leftover": True}, {"checkpoint_fraction": 0.8}):
        model = Model()
        result = run(model, calls=60, **extra)
        assert len(model.calls) == result["solver_calls_total"] <= 60


def _diagonals(geometry):
    return [s for s in gg.from_geometry(geometry).segments if gg.is_diagonal(s[0], s[1])] if hasattr(gg, "is_diagonal") else [
        s for s in gg.from_geometry(geometry).segments if abs(s[0][0] - s[1][0]) > 1e-6 and abs(s[0][1] - s[1][1]) > 1e-6]


class Recording(Model):
    def electrical(self, level, geometry):
        self.seen = getattr(self, "seen", []) + [geometry]
        return super().electrical(level, geometry)


@pytest.mark.parametrize("adaptive", [False, True])
def test_an_orthogonal_search_never_builds_a_diagonal(adaptive):
    from src.domain.spat.geometry_operators import OperatorConstraints
    from src.domain.spat.operator_selection import AdaptiveOperatorSelector

    constraints = OperatorConstraints(orthogonal=True)
    start = seeds.generate_seeds(DOMAIN, seed=3, count=4, constraints=seeds.SeedConstraints(orthogonal=True))
    assert start and not any(_diagonals(s.geometry) for s in start)
    model = Recording()
    options = {"operator_selector": AdaptiveOperatorSelector(DOMAIN, constraints)} if adaptive else {}
    result = search_topology(domain=DOMAIN, seeds=start, evaluate_cost=model.cost, evaluate_electrical=model.electrical,
                             seed=3, max_solver_calls=80, constraints=constraints, **options)
    assert result["best"] is not None and len(model.seen) > 10
    assert not any(_diagonals(geometry) for geometry in model.seen)


def test_a_diagonal_of_the_base_design_is_kept_and_no_other_is_added():
    from src.domain.spat.geometry_operators import OperatorConstraints, OperatorRejected, check, diagonals_of

    base = {**DOMAIN, "conductors": [{"start": {"x": 4, "y": 4}, "end": {"x": 20, "y": 4}},
                                      {"start": {"x": 20, "y": 4}, "end": {"x": 24, "y": 8}}]}
    inherited = diagonals_of(base)
    assert len(inherited) == 1
    graph = gg.from_geometry(base)
    check(graph, OperatorConstraints(orthogonal=True, inherited_diagonals=inherited), DOMAIN)
    with pytest.raises(OperatorRejected, match="diagonal"):
        check(graph, OperatorConstraints(orthogonal=True), DOMAIN)
    check(graph, OperatorConstraints(), DOMAIN)                         # unconstrained search is unchanged
