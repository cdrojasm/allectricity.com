import math
from pathlib import Path

import pytest
from src.infrastructure.calculations.artifact_potential import (
    UnsupportedModelError,
    calculate,
    run_potential_calculation,
)
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient
from src.infrastructure.entrypoint.worker import tasks

from tests.infrastructure.test_identity import env, headers  # noqa: F401

PARAMETERS = {"conductor_radius_m": 0.00525, "discretization_m": 1.0, "surface_spacing_m": 0.5}
# IEEE 80 Annex H Grid 1 expressed as an artifact.
ANNEX_H_GRID1 = {
    "name": "Annex H Grid 1",
    "geometry": {"length_m": 70, "width_m": 70, "burial_depth_m": 0.5, "conductor_spacing_m": 14,
                 "rods_count": 0, "rod_length_m": 7.5},
    "soil_layers": [{"resistivity_ohm_m": 140}],
    "fault": {"current_a": 744.8, "clearing_time_s": 0.5},
}


@pytest.fixture(scope="module")
def engine():
    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        pytest.skip(f"potential engine not built at {client.executable}; run `make potential-engine`")
    return client


def test_annex_h_grid1_artifact_matches_reference(engine):
    outcome = calculate(ANNEX_H_GRID1, PARAMETERS, engine)
    result = outcome["result"]
    assert result["segment_count"] == 840
    assert math.isclose(result["grid_resistance_ohm"], 1.0002, rel_tol=1e-3)
    assert math.isclose(result["gpr_v"], 744.8 * result["grid_resistance_ohm"], rel_tol=1e-9)
    # Annex H T3 worst touch 202.7-209.0 V; the converged engine value is 203.4 V.
    assert 202.7 <= result["max_touch_v"]["value"] <= 209.0
    # The worst 1 m step is at least the diagonal corner step S1 (91.0 V at 1 m segments).
    assert 90.9 <= result["max_step_v"]["value"] <= 95.0
    assert math.isclose(math.dist(result["max_step_v"]["from_m"], result["max_step_v"]["to_m"]), 1.0, rel_tol=1e-9)
    assert result["diagnostics"]["backward_error"] < 1e-12
    assert outcome["trace"]["parameters"] == PARAMETERS
    assert outcome["trace"]["injections"][0]["origin"] == "artifact:fault.current_a"
    assert len(outcome["trace"]["request_sha256_batches"]) >= 2
    # Default safety evaluation: IEEE 80-2013, 50 kg, 3000 ohm-m x 0.1 m surface layer, t_s 0.5 s.
    [ieee] = result["safety"]
    cs = 1 - 0.09 * (1 - 140 / 3000) / (2 * 0.1 + 0.09)
    touch, step = ieee["criteria"]
    assert ieee["standard"] == "IEEE 80-2013" and ieee["status"] == "cumple"
    assert math.isclose(touch["tolerable_v"], (1000 + 1.5 * cs * 3000) * 0.116 / math.sqrt(0.5))
    assert touch["actual_v"] == result["max_touch_v"]["value"] and step["actual_v"] == result["max_step_v"]["value"]


def test_user_split_factor_scales_injection_without_extra_solve(engine):
    parameters = {**PARAMETERS, "surface_spacing_m": 1.0, "x_over_r": 10,
                  "fault_split": {"split_factor": 0.6, "split_factor_origin": "estudio de reparto 2026"}}
    outcome = calculate(ANNEX_H_GRID1, parameters, engine)
    result, trace = outcome["result"], outcome["trace"]
    expected = 744.8 * 0.6 * 1.026
    assert result["injected_current_a"] == pytest.approx(expected, rel=1e-3)
    assert result["gpr_v"] == pytest.approx(result["injected_current_a"] * result["grid_resistance_ohm"], rel=1e-9)
    assert trace["injections"][0]["origin"] == "artifact:fault.current_a:df:sf-user"
    assert trace["fault_current"]["split_origin"] == "user: estudio de reparto 2026"
    assert not any("sin factor de división" in w for w in result["model_warnings"])


def test_return_paths_split_current_using_engine_resistance(engine):
    parameters = {**PARAMETERS, "surface_spacing_m": 1.0,
                  "fault_split": {"return_paths": [{"name": "ohgw-1", "kind": "shield_wire",
                                                    "resistance_ohm": 1.0, "reactance_ohm": 1.0}]}}
    result = calculate(ANNEX_H_GRID1, parameters, engine)["result"]
    rg = result["grid_resistance_ohm"]
    sf = abs((1 + 1j) / ((1 + 1j) + rg))
    assert result["fault_current"]["split_factor"] == pytest.approx(sf, rel=1e-6)
    assert result["injected_current_a"] == pytest.approx(744.8 * sf, rel=1e-6)
    path = result["fault_current"]["paths"][0]
    assert path["current_a"] == pytest.approx(744.8 * rg / abs((1 + 1j) + rg), rel=1e-6)


def test_layered_soil_is_rejected(engine):
    snapshot = {**ANNEX_H_GRID1, "soil_layers": [{"resistivity_ohm_m": 300, "depth_m": 6.1}, {"resistivity_ohm_m": 100}]}
    with pytest.raises(UnsupportedModelError, match="homogéneo"):
        calculate(snapshot, PARAMETERS, engine)


def test_identical_layers_count_as_homogeneous(engine):
    snapshot = {**ANNEX_H_GRID1, "soil_layers": [{"resistivity_ohm_m": 140, "depth_m": 3}, {"resistivity_ohm_m": 140}]}
    assert calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0}, engine)["result"]["soil_resistivity_ohm_m"] == 140


def test_grid_over_segment_limit_is_rejected(engine):
    with pytest.raises(UnsupportedModelError, match="segmentos"):
        calculate(ANNEX_H_GRID1, {**PARAMETERS, "discretization_m": 0.2}, engine)


def _artifact(client, tokens, snapshot):
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    artifact = client.post(base, json=snapshot, headers=headers(tokens)).json()
    return base, artifact


def test_calculation_lifecycle_through_api(env, engine, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    queued = []
    monkeypatch.setattr(tasks.calculate_artifact_potential, "apply_async",
                        lambda args, task_id: queued.append((args, task_id)))
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    url = f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial"

    response = client.post(url, json={"surface_spacing_m": 1.0, "safety_standards": ["IEEE 80-2013", "RETIE 2013"]},
                           headers=headers(tokens))
    assert response.status_code == 202
    calculation = response.json()
    assert calculation["status"] == "pending" and queued == [([calculation["id"]], calculation["id"])]
    assert calculation["parameters"] == {**PARAMETERS, "surface_spacing_m": 1.0,
                                         "safety_standards": ["IEEE 80-2013", "RETIE 2013"], "fault_split": None,
                                         "x_over_r": None, "system_frequency_hz": 60.0}

    run_potential_calculation(services.store, calculation["id"], engine)
    run_potential_calculation(services.store, calculation["id"], engine)  # redelivery is a no-op
    detail = client.get(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}", headers=headers(tokens)).json()
    assert detail["status"] == "completed" and detail["error"] is None
    assert math.isclose(detail["result"]["grid_resistance_ohm"], 1.0002, rel_tol=1e-3)
    assert detail["trace"]["solver_version"] and len(detail["trace"]["request_sha256"]) == 64
    assert detail["trace"]["segments"][0]["radius_m"] == 0.00525
    assert [(entry["standard"], entry["status"]) for entry in detail["result"]["safety"]] == [
        ("IEEE 80-2013", "cumple"), ("RETIE 2013", "no_evaluable")]

    listed = client.get(url, headers=headers(tokens)).json()
    assert [row["id"] for row in listed] == [calculation["id"]]
    cancel = client.post(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}/cancelar",
                         headers=headers(tokens))
    assert cancel.status_code == 409


def test_layered_artifact_calculation_is_rejected(env, engine, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    monkeypatch.setattr(tasks.calculate_artifact_potential, "apply_async", lambda args, task_id: None)
    layered = {**ANNEX_H_GRID1, "soil_layers": [{"resistivity_ohm_m": 300, "depth_m": 6.1}, {"resistivity_ohm_m": 100}]}
    base, artifact = _artifact(client, tokens, layered)
    calculation = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial", json={},
                              headers=headers(tokens)).json()
    run_potential_calculation(services.store, calculation["id"], engine)
    detail = client.get(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}", headers=headers(tokens)).json()
    assert detail["status"] == "rejected" and "homogéneo" in detail["error"] and detail["result"] is None


def test_cancelled_calculation_is_not_run(env, engine, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    monkeypatch.setattr(tasks.calculate_artifact_potential, "apply_async", lambda args, task_id: None)
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    calculation = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial", json={},
                              headers=headers(tokens)).json()
    cancel = client.post(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}/cancelar",
                         headers=headers(tokens))
    assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"
    run_potential_calculation(services.store, calculation["id"], engine)
    detail = client.get(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}", headers=headers(tokens)).json()
    assert detail["status"] == "cancelled" and detail["result"] is None


def test_missing_artifact_version_is_not_queued(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    monkeypatch.setattr(tasks.calculate_artifact_potential, "apply_async", lambda args, task_id: pytest.fail("queued"))
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    response = client.post(f"{base}/{artifact['artifact_id']}/versions/9/calculos-potencial", json={}, headers=headers(tokens))
    assert response.status_code == 404


@pytest.mark.parametrize("payload", [
    {"fault_split": {"split_factor": 0.5}},
    {"fault_split": {}},
    {"fault_split": {"return_paths": [{"name": "p", "resistance_ohm": 0}]}},
    {"system_frequency_hz": 55},
])
def test_invalid_fault_split_is_rejected(env, payload):  # noqa: F811
    _, _, client, _, tokens, _ = env
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    response = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial",
                           json=payload, headers=headers(tokens))
    assert response.status_code == 422


def test_invalid_surface_spacing_is_rejected(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    response = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial",
                           json={"surface_spacing_m": 0.3}, headers=headers(tokens))
    assert response.status_code == 422


def test_unsupported_safety_standard_is_rejected(env, monkeypatch):  # noqa: F811
    _, _, client, _, tokens, _ = env
    base, artifact = _artifact(client, tokens, ANNEX_H_GRID1)
    response = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial",
                           json={"safety_standards": ["IEEE 80-2000"]}, headers=headers(tokens))
    assert response.status_code == 422
