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


def run(client, seed=7, calls=60):
    return run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0, exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=client, seed=seed, max_solver_calls=calls, seed_count=4)


def test_topology_search_with_the_real_solver_is_bounded_deterministic_and_uncertified(client):
    result = run(client)
    assert result["solver_calls_total"] <= 60 and result["certified"] is False
    assert result["solver_time_units"] < result["baseline_time_units_if_every_candidate_used_L2plus"]
    assert result["best"] is not None and result["best"]["status"] == "finalist" and result["best"]["ratio"] <= 1.0
    assert {s["family"] for s in result["seeds"]} >= {"perimeter", "inscribed"}
    assert result["best"]["candidate_sha256"] == run(client)["best"]["candidate_sha256"]
    parallel = run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0,
        exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=client, seed=7, max_solver_calls=60,
        seed_count=4, parallel_workers=2)
    assert parallel["solver_calls_total"] <= 60 and parallel["certified"] is False
    assert parallel["best"]["candidate_sha256"] == result["best"]["candidate_sha256"]


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
    reference = run(client, calls=45)

    class Interrupted(Exception):
        pass
    real_save, saves = topology_run.save_checkpoint, {"n": 0}

    def flaky_save(target, log):
        real_save(target, log)
        saves["n"] += 1
        if saves["n"] == 8:
            raise Interrupted
    monkeypatch.setattr(topology_run, "save_checkpoint", flaky_save)
    with pytest.raises(Interrupted):
        run_topology_optimizer(domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0,
                               exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100), standards=[safety_criteria.IEEE80_2013],
                               client=client, seed=7, max_solver_calls=45, seed_count=4, checkpoint_path=path)
    monkeypatch.setattr(topology_run, "save_checkpoint", real_save)
    saved = json.loads(path.read_text())                           # plain verdicts: no session, no process handle
    verdicts = len([k for k in saved if k != "__problem__"])
    assert verdicts >= 8 and PotentialSession.open_sessions() == 0

    resumed = run_topology_optimizer(domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0,
                                     exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100), standards=[safety_criteria.IEEE80_2013],
                                     client=client, seed=7, max_solver_calls=45, seed_count=4, checkpoint_path=path)
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


def test_elite_archive_is_context_bound_hashed_and_only_stores_l3_admitted_designs(tmp_path):
    from src.domain.spat.geometry_graph import canonical_hash, from_geometry
    from src.application.use_cases.optimizer_topology_run import load_elite_archive, save_elite_archive

    path = tmp_path / "elite.json"
    geometry = {"length_m": 10, "width_m": 10, "burial_depth_m": 0.5,
                "conductors": [{"start": {"x": 1, "y": 1}, "end": {"x": 9, "y": 1}}], "rods": []}
    digest = canonical_hash(from_geometry(geometry))
    result = {"finalists": [
        {"candidate_sha256": digest, "status": "finalist", "level": "L3", "geometry": geometry},
        {"candidate_sha256": "bad", "status": "demoted", "level": "L3", "geometry": geometry},
        {"candidate_sha256": "unknown", "status": "finalist", "level": "L2+", "geometry": geometry},
    ]}
    save_elite_archive(path, "context-a", result, "run-a")
    loaded = load_elite_archive(path, "context-a")
    assert len(loaded) == 1 and loaded[0].graph_hash == digest
    with pytest.raises(ValueError, match="incompatible"):
        load_elite_archive(path, "context-b")
    payload = json.loads(path.read_text())
    payload["candidates"][0]["geometry"]["width_m"] = 12
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_elite_archive(path, "context-a")


def test_topology_run_uses_context_matched_elite_seeds(monkeypatch, tmp_path):
    from dataclasses import asdict
    from types import SimpleNamespace

    from src.domain.spat import geometry_seeds
    from src.domain.spat.geometry_graph import canonical_hash, from_geometry

    exposure = safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100)
    generated = geometry_seeds.generate_seeds(DOMAIN, seed=7, count=5)
    archived = next(seed for seed in geometry_seeds.generate_seeds(DOMAIN, seed=8, count=5)
                    if seed.graph_hash not in {item.graph_hash for item in generated})
    soil_record = topology_run.soil_record(topology_run.as_soil(100.0))
    context = topology_run.problem_fingerprint(
        domain=DOMAIN, rate_card=RATES, soil=soil_record, injection_a=1000.0,
        exposure=asdict(exposure), standards=[safety_criteria.IEEE80_2013], settings=None,
        engine=[None, None])
    archive_path = tmp_path / "elite.json"
    topology_run.save_elite_archive(archive_path, context, {"finalists": [{
        "candidate_sha256": archived.graph_hash, "status": "finalist", "level": "L3",
        "geometry": archived.geometry}]}, "prior-run")

    monkeypatch.setattr(geometry_seeds, "generate_seeds", lambda *_args, **_kwargs: generated)
    monkeypatch.setattr(topology_run.solver_evaluation, "discretization_violations", lambda *_args: [])
    observed = {}

    def capture_search(**kwargs):
        observed["seeds"] = kwargs["seeds"]
        return {"finalists": [], "solver_calls_total": 0}

    monkeypatch.setattr(topology_run, "search_topology", capture_search)
    result = run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0, exposure=exposure,
        standards=[safety_criteria.IEEE80_2013], client=SimpleNamespace(quadrature_tolerance=None, executable=None),
        seed=7, max_solver_calls=20, seed_count=2, elite_archive_path=archive_path)

    assert canonical_hash(from_geometry(observed["seeds"][0].geometry)) == archived.graph_hash
    assert result["seeds"][0]["candidate_sha256"] == archived.graph_hash
    assert result["elite_archive"]["loaded"] == 1


# ---- fast mode and parametric refinement with the real solver ------------------------------------------------

def test_the_fast_mode_runs_on_a_time_budget_and_still_finishes_with_a_finest_level_check(client):
    import time
    started = time.perf_counter()
    result = run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0, exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=client, seed=7, time_budget_s=20.0, seed_count=4)
    assert result["budget"]["mode"] == "time" and result["max_solver_calls"] is None
    assert result["solver_calls"].get("L3", 0) >= 1                      # the L3 reserve was honoured
    assert time.perf_counter() - started < 20.0 + 15.0                   # a started call is not interrupted; allow for the slowest one
    assert result["certified"] is False and (result["best"] is None or result["best"]["level"] == "L3")


def test_the_refined_strategy_stays_inside_the_call_budget_with_the_real_solver(client):
    result = run_topology_optimizer(
        domain=DOMAIN, rate_card=RATES, soil=100.0, injection_a=1000.0, exposure=safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100),
        standards=[safety_criteria.IEEE80_2013], client=client, seed=7, max_solver_calls=60, seed_count=4, strategy="alns_refined")
    assert result["solver_calls_total"] <= 60 and result["budget"]["refine_hold"] > 0
    assert result["counts"].get("refinement_starts", 0) >= 0 and result["certified"] is False
    assert result["best"] is None or result["best"]["status"] == "finalist"
