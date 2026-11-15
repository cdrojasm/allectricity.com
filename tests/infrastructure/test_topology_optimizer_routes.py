"""The topological optimizer in the product: queued run, worker execution, cancel, comparison and apply."""

from pathlib import Path

import pytest

from src.application.use_cases import optimizer_topology_job as job
from src.application.use_cases.optimizer_topology_run import run_topology_optimizer
from src.infrastructure.calculations.optimizer_topology_inputs import build_inputs, evaluate_base
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
from src.infrastructure.entrypoint.api import optimizer_routes
from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository
from tests.infrastructure.test_identity import env, headers  # noqa: F401

LOT = {"length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
       "areas": [{"type": "intervenible", "label": "lote", "polygon": [
           {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
       "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}],
       "conductors": [{"start": {"x": 4, "y": 4}, "end": {"x": 32, "y": 4}}, {"start": {"x": 32, "y": 4}, "end": {"x": 32, "y": 12}},
                      {"start": {"x": 32, "y": 12}, "end": {"x": 4, "y": 12}}, {"start": {"x": 4, "y": 12}, "end": {"x": 4, "y": 4}},
                      {"start": {"x": 18, "y": 4}, "end": {"x": 18, "y": 12}}],
       "rods": [{"x": 4, "y": 4, "length_m": 2.4}, {"x": 32, "y": 12, "length_m": 2.4}]}
SOURCE = {"document": "Perfil de prueba", "edition": "2026", "clause": "1"}
PROFILE = {
    "title": "Prueba subestación", "jurisdiction": "global", "installation_type": "substation_ac",
    "required_mandatory_criteria": ["touch", "step"],
    "rules": [
        {"id": "touch", "category": "mandatory", "criterion": "touch", "applicability": "applicable",
         "applicability_conditions": ["toda la malla"], "verification_method": "IEEE 80", "source": SOURCE},
        {"id": "step", "category": "mandatory", "criterion": "step", "applicability": "applicable",
         "applicability_conditions": ["toda la malla"], "verification_method": "IEEE 80", "source": SOURCE},
        {"id": "rod", "category": "constructability", "target": "rod_length_m", "applicability": "applicable",
         "applicability_conditions": ["varillas comerciales"], "verification_method": "catálogo",
         "min": 1.5, "max": 3.0, "unit": "m", "source": {"reference": "catálogo de prueba"}},
    ],
}
RATES = {key: {"amount": amount, "source": "cotización de prueba"} for key, amount in {
    "material.conductor.unspecified": 18000, "material.rod.unspecified": 25000, "excavation.trench": 60000,
    "installation.conductor": 7000, "installation.rod": 40000, "installation.connection": 15000}.items()}


def request_body(artifact, **overrides):
    body = {"artifact_id": artifact["artifact_id"], "artifact_version": artifact["version"],
            "soil": {"model": "homogeneous", "resistivity_ohm_m": 100},
            "injection_a": 1000, "standards": ["IEEE 80-2013"],
            "exposure": {"clearing_time_s": 0.5, "body_weight_kg": 70, "surface_resistivity_ohm_m": 3000,
                         "surface_thickness_m": 0.1, "surface_layer_present": True},
            "cost_currency": "COP", "rates": RATES, "trench_width_m": 0.4, "trench_width_source": "práctica de obra local",
            "seed": 7, "max_solver_calls": 40, "seed_count": 3}
    body.update(overrides)
    return body


@pytest.fixture
def site(env, monkeypatch, tmp_path):  # noqa: F811
    _, services, client, _, tokens, _ = env
    monkeypatch.setenv("OPTIMIZER_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
    queued = []
    monkeypatch.setattr(optimizer_routes, "dispatch_topology_run", queued.append)
    h = headers(tokens)
    assert client.post("/api/v1/constraint-profiles", json={"profile_id": "prueba-se", "definition": PROFILE}, headers=h).status_code == 201
    assert client.post("/api/v1/constraint-profiles/prueba-se/versions/1/review", headers=h).status_code == 200
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=h).json()
    assert client.put(f"/api/v1/projects/{project['id']}/constraint-profiles",
                      json={"profiles": [{"profile_id": "prueba-se", "version": 1}]}, headers=h).status_code == 200
    artifact = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras",
                           json={"name": "Malla", "geometry": LOT, "soil_layers": [{"resistivity_ohm_m": 100}],
                                 "fault": {"current_a": 1000, "clearing_time_s": 0.5}}, headers=h)
    assert artifact.status_code == 201, artifact.text
    root = f"/api/v1/projects/{project['id']}/optimizer-runs"
    return services, client, h, project, artifact.json(), root, queued


def deps(services, run_optimizer, client_factory=lambda: None, base=None):
    return job.TopologyJobDeps(store=services.store, repository=OptimizerRunRepository, client_factory=client_factory,
                               run_optimizer=run_optimizer, build_inputs=build_inputs, evaluate_base=base, cancel_poll_s=0)


def fake_result(geometries):
    finalists = [{"candidate_sha256": f"{i:064x}", "cost": cost, "status": "finalist", "level": "L3", "ratio": ratio,
                  "metrics": {"Rg_ohm": 2.0 + i, "Vs_v": 100.0, "Vt_v": 300.0 * ratio}, "geometry": LOT,
                  "cost_breakdown": {"by_group": {"materials": str(cost)}}}
                 for i, (cost, ratio) in enumerate(geometries)]
    return {"finalists": finalists + [{"candidate_sha256": "f" * 64, "cost": 1.0, "status": "demoted", "level": "L3", "ratio": 1.4}],
            "best": finalists[0] if finalists else None, "budget_exhausted": True, "certified": False,
            "cost_currency": "COP", "problem_sha256": "p" * 64}


def test_a_queued_run_is_executed_by_the_worker_with_the_real_solver_and_applied_as_a_new_version(site):
    services, client, h, project, artifact, root, queued = site
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip("potential engine not built; run `make potential-engine`")
    created = client.post(f"{root}/topology", json=request_body(artifact, max_solver_calls=60), headers=h)
    assert created.status_code == 202, created.text
    run = created.json()["run"]
    assert run["status"] == "queued" and queued == [run["id"]]
    snapshot = run["request_snapshot"]
    assert snapshot["algorithm"] == "topology_alns" and snapshot["strategy"] == "alns"
    assert snapshot["operator_constraints"]["rod_length_range_m"]["min"] == 1.5
    assert snapshot["operator_constraints"]["rod_length_range_m"]["max"] == 3.0
    assert snapshot["rate_provenance"]["installation.rod"]["source"] == "cotización de prueba"
    assert snapshot["base"]["cost_status"] == "complete" and snapshot["base"]["cost"] > 0

    assert job.execute_topology_run(deps(services, run_topology_optimizer, PotentialEngineClient, evaluate_base), run["id"]) == "completed"
    detail = client.get(f"{root}/{run['id']}", headers=h).json()
    assert detail["run"]["status"] == "completed"
    summary = detail["run"]["result_summary"]
    assert summary["certified"] is False and summary["solver_calls_total"] <= 60
    alternatives = detail["alternatives"]
    assert alternatives, "the lot admits a compliant design at this current"
    for alternative in alternatives:
        evaluation = alternative["evaluation_snapshot"]
        assert evaluation["validated_at_level"] == "L3" and evaluation["certified"] is False
        assert evaluation["utilization_ratio"] <= 1.0 and evaluation["metrics"]["Rg_ohm"] > 0
        rods = evaluation["geometry"].get("rods") or []
        assert all(1.5 - 1e-9 <= rod["length_m"] <= 3.0 + 1e-9 for rod in rods if rod not in LOT["rods"])

    comparison = client.get(f"{root}/{run['id']}/comparison", headers=h).json()
    assert comparison["base"]["cost"] == snapshot["base"]["cost"]
    base_check = comparison["base"]["electrical"]
    assert base_check["level"] == "L3" and base_check["status"] in {"VIOLATED", "UNKNOWN", "REJECTED"}
    if comparison["saving_vs_base"]:
        assert comparison["saving_vs_base"]["kind"] == ("saving" if base_check["feasible"] is True else "difference")
    assert any(row["pareto"] for row in comparison["alternatives"])
    assert comparison["alternatives"][0]["recommended"] is True
    assert any("certificada" in warning for warning in comparison["warnings"])

    applied = client.post(f"{root}/{run['id']}/alternatives/{alternatives[0]['id']}/apply", headers=h)
    assert applied.status_code == 201, applied.text
    row = applied.json()
    assert row["version"] == artifact["version"] + 1
    assert row["origin"]["optimizer"]["run_id"] == run["id"] and row["origin"]["optimizer"]["certified"] is False
    assert row["snapshot"]["geometry"]["conductors"] == alternatives[0]["evaluation_snapshot"]["geometry"]["conductors"]
    assert row["snapshot"]["soil_layers"] == artifact["snapshot"]["soil_layers"]      # only the geometry changes


def test_rates_must_cover_every_line_and_carry_their_source(site):
    _, client, h, _, artifact, root, queued = site
    missing = {k: v for k, v in RATES.items() if k != "installation.connection"}
    response = client.post(f"{root}/topology", json=request_body(artifact, rates=missing), headers=h)
    assert response.status_code == 422 and "installation.connection" in response.json()["detail"]
    unsourced = {**RATES, "excavation.trench": {"amount": 60000}}
    assert client.post(f"{root}/topology", json=request_body(artifact, rates=unsourced), headers=h).status_code == 422
    catalog = {**RATES, "material.rod.unspecified": {"catalog_item_id": "0" * 36}}
    response = client.post(f"{root}/topology", json=request_body(artifact, rates=catalog), headers=h)
    assert response.status_code == 422 and "not approved" in response.json()["detail"]
    assert queued == []


def test_without_a_reviewed_profile_the_run_is_refused(site):
    _, client, h, project, artifact, root, _ = site
    client.put(f"/api/v1/projects/{project['id']}/constraint-profiles", json={"profiles": []}, headers=h)
    response = client.post(f"{root}/topology", json=request_body(artifact), headers=h)
    assert response.status_code == 422 and "normative_profile_not_selected" in response.json()["detail"]


def test_cancel_stops_a_running_search_and_a_late_finish_does_not_overwrite_it(site):
    services, client, h, _, artifact, root, _ = site
    run = client.post(f"{root}/topology", json=request_body(artifact), headers=h).json()["run"]

    def cancelled_midway(**kwargs):
        kwargs["on_progress"]({"verdicts": 1})
        assert client.post(f"{root}/{run['id']}/cancel", headers=h).status_code == 200
        kwargs["on_progress"]({"verdicts": 2})
        raise AssertionError("the progress hook must stop the search")

    assert job.execute_topology_run(deps(services, cancelled_midway), run["id"]) == "cancelled"
    assert client.get(f"{root}/{run['id']}", headers=h).json()["run"]["status"] == "cancelled"
    assert client.post(f"{root}/{run['id']}/cancel", headers=h).status_code == 409
    # A redelivered task finds the run terminal and does nothing.
    assert job.execute_topology_run(deps(services, cancelled_midway), run["id"]) == "cancelled"

    queued = client.post(f"{root}/topology", json=request_body(artifact), headers=h).json()["run"]
    assert client.post(f"{root}/{queued['id']}/cancel", headers=h).json()["run"]["status"] == "cancelled"


def test_an_interrupted_run_resumes_with_its_checkpoint_and_failures_are_recorded(site):
    services, client, h, _, artifact, root, _ = site
    run = client.post(f"{root}/topology", json=request_body(artifact), headers=h).json()["run"]
    seen = []

    def crashes(**kwargs):
        seen.append(kwargs["checkpoint_path"])
        raise RuntimeError("worker lost the engine")

    with pytest.raises(RuntimeError):
        job.execute_topology_run(deps(services, crashes), run["id"])
    failed = client.get(f"{root}/{run['id']}", headers=h).json()["run"]
    assert failed["status"] == "failed" and "worker lost the engine" in failed["error"]

    again = client.post(f"{root}/topology", json=request_body(artifact), headers=h).json()["run"]
    with services.store.transaction(write=True) as db:      # a worker died while it was running
        OptimizerRunRepository(db.connection).transition(again["project_id"], again["id"], ("queued",), {"status": "running"})

    def finishes(**kwargs):
        seen.append(kwargs["checkpoint_path"])
        assert kwargs["constraint_context"]["status"] == "ready" and kwargs["strategy"] == "alns"
        return fake_result([(900.0, 0.95), (1000.0, 0.7), (1100.0, 0.8)])

    violating_base = lambda inputs, client: {"status": "VIOLATED", "feasible": False, "ratio": 1.6, "level": "L3"}  # noqa: E731
    assert job.execute_topology_run(deps(services, finishes, base=violating_base), again["id"]) == "completed"
    assert seen[-1].name == f"{again['id']}.json"
    comparison = client.get(f"{root}/{again['id']}/comparison", headers=h).json()
    rows = comparison["alternatives"]
    assert [row["cost"] for row in rows] == [900.0, 1000.0, 1100.0]      # demoted finalists are never offered
    assert [row["pareto"] for row in rows] == [True, True, False]        # 1100 @ 0.8 is dominated by 1000 @ 0.7
    assert rows[1]["margin"] == pytest.approx(0.3)
    assert comparison["saving_vs_base"]["amount"] == pytest.approx(comparison["base"]["cost"] - 900.0)
    # The base violates, so the cost difference is the price of complying, never reported as a saving.
    assert comparison["saving_vs_base"]["kind"] == "difference" and comparison["saving_vs_base"]["base_status"] == "violates"
    assert any("no cumple" in warning and "160%" in warning for warning in comparison["warnings"])


def test_catalog_rates_need_the_run_currency_and_the_takeoff_unit():
    row = {"id": "c" * 36, "status": "approved", "version": 2, "price_per_unit": "25000", "price_currency": "COP",
           "quantity_unit": "m", "expires_at": None, "name": "Varilla 5/8"}
    built = job.build_rate_card({"material.rod.unspecified": {"catalog_item_id": row["id"]}}, currency="COP",
                                trench_width_m=None, trench_width_source=None, catalog_rows=[row], now_epoch_s=10)
    assert built["rate_card"]["rates"] == {"material.rod.unspecified": "25000"}
    assert built["provenance"]["material.rod.unspecified"]["catalog_version"] == 2
    for bad, message in (({**row, "price_currency": "USD"}, "no conversion"), ({**row, "quantity_unit": "und"}, "measures m"),
                         ({**row, "expires_at": 5}, "expired")):
        with pytest.raises(job.RateCardError, match=message):
            job.build_rate_card({"material.rod.unspecified": {"catalog_item_id": row["id"]}}, currency="COP",
                                trench_width_m=None, trench_width_source=None, catalog_rows=[bad], now_epoch_s=10)
    with pytest.raises(job.RateCardError, match="material suffix"):
        job.build_rate_card({"material.rod": {"amount": 1, "source": "x"}}, currency="COP", trench_width_m=None,
                            trench_width_source=None, catalog_rows=[], now_epoch_s=10)
