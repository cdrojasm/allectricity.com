from pathlib import Path

import pytest
from src.application.use_cases.optimizer_topology_run import run_topology_optimizer, utilization_ratio
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient

DOMAIN = {
    "length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
    "areas": [{"type": "intervenible", "label": "lote", "polygon": [
        {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
    "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}],
}
RATES = {"currency": "COP", "assumptions": {"trench_width_m": 0.4},
         "rates": {"material.conductor.unspecified": "18000", "material.rod.unspecified": "25000", "excavation.trench": "60000",
                   "installation.conductor": "7000", "installation.rod": "40000", "installation.connection": "15000"}}


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def run(client, seed=7, calls=90):
    return run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0, exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=client, seed=seed, max_solver_calls=calls, seed_count=4)


def test_topology_search_with_the_real_solver_is_bounded_deterministic_and_uncertified(client):
    result = run(client)
    assert result["solver_calls_total"] <= 90 and result["certified"] is False
    assert result["solver_time_units"] < result["baseline_time_units_if_every_candidate_used_L2plus"]
    assert result["best"] is not None and result["best"]["status"] == "finalist" and result["best"]["ratio"] <= 1.0
    assert {s["family"] for s in result["seeds"]} >= {"perimeter", "inscribed"}
    assert result["best"]["candidate_sha256"] == run(client)["best"]["candidate_sha256"]


def test_the_best_design_costs_no_more_than_the_best_feasible_seed(client):
    from src.domain.spat.geometry_cost import evaluate_geometry_cost
    from src.domain.spat.geometry_seeds import generate_seeds
    result = run(client)
    seed_costs = {s.graph_hash: float(evaluate_geometry_cost(s.geometry, RATES)["total"]) for s in generate_seeds(DOMAIN, seed=7, count=4)}
    confirmed_seeds = [c["cost"] for c in result["confirmed"] if c["candidate_sha256"] in seed_costs]
    assert result["best"]["cost"] <= min(confirmed_seeds)


def test_utilization_ratio_reads_the_worst_evaluable_criterion():
    result = {"SafetyEvaluations": [{"criteria": [{"status": "cumple", "actual_v": 300.0, "tolerable_v": 900.0},
                                                  {"status": "no_cumple", "actual_v": 400.0, "tolerable_v": 200.0},
                                                  {"status": "no_evaluable", "actual_v": 1.0, "tolerable_v": 0}]}]}
    assert utilization_ratio(result) == 2.0 and utilization_ratio({"SafetyEvaluations": []}) is None


# ---- interruption and resumption with the real solver ------------------------------------------------------

import json  # noqa: E402

from src.application.use_cases import optimizer_topology_run as topology_run  # noqa: E402
from src.infrastructure.calculations.potential_engine_client import PotentialSession  # noqa: E402


def test_an_interrupted_run_resumes_from_its_file_without_repeating_a_solver_call(client, tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.json"
    reference = run(client, calls=60)

    class Interrupted(Exception):
        pass
    real_save, saves = topology_run.save_checkpoint, {"n": 0}

    def flaky_save(target, log):
        real_save(target, log)
        saves["n"] += 1
        if saves["n"] == 12:
            raise Interrupted
    monkeypatch.setattr(topology_run, "save_checkpoint", flaky_save)
    with pytest.raises(Interrupted):
        run_topology_optimizer(domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0,
                               exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100), standards=[safety_criteria.IEEE80_2013],
                               client=client, seed=7, max_solver_calls=60, seed_count=4, checkpoint_path=path)
    monkeypatch.setattr(topology_run, "save_checkpoint", real_save)
    saved = json.loads(path.read_text())                           # plain verdicts: no session, no process handle
    verdicts = len([k for k in saved if k != "__problem__"])
    assert verdicts >= 12 and PotentialSession.open_sessions() == 0

    resumed = run_topology_optimizer(domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0,
                                     exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100), standards=[safety_criteria.IEEE80_2013],
                                     client=client, seed=7, max_solver_calls=60, seed_count=4, checkpoint_path=path)
    assert resumed["best"]["candidate_sha256"] == reference["best"]["candidate_sha256"]
    assert resumed["solver_calls"] == reference["solver_calls"]
    assert resumed["evaluations_replayed"] >= verdicts
    assert resumed["solver_calls_spent_this_run"] == reference["solver_calls_total"] - verdicts
    assert PotentialSession.open_sessions() == 0


def test_a_checkpoint_is_not_reused_for_another_problem_or_another_current(client, tmp_path):
    path = tmp_path / "checkpoint.json"
    common = dict(domain=DOMAIN, rate_card=RATES, soil=100.0, exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
                  standards=[safety_criteria.IEEE80_2013], client=client, seed=7, max_solver_calls=20, seed_count=2, checkpoint_path=path)
    run_topology_optimizer(injection_a=1000.0, **common)
    with pytest.raises(ValueError, match="different problem"):
        run_topology_optimizer(injection_a=1500.0, **common)
