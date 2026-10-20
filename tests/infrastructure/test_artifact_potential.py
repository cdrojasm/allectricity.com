import math
from pathlib import Path

import pytest
from src.infrastructure.calculations.artifact_potential import (
    UnsupportedModelError,
    calculate,
    run_potential_calculation,
    soil_model,
)
from src.infrastructure.calculations.n_layer_soil import NLayerSoil, SoilLayer, apparent_resistivity_n_layer
from src.infrastructure.calculations.potential_engine_client import LayerStackSoil, PotentialEngineClient, TwoLayerSoil
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
    # Graded by default: 452 segments instead of 840 uniform 1 m pieces.
    assert result["segmentation"] == "graded" and result["segment_count"] == 452
    assert math.isclose(result["grid_resistance_ohm"], 1.0002, rel_tol=1e-3)
    assert math.isclose(result["gpr_v"], 744.8 * result["grid_resistance_ohm"], rel_tol=1e-9)
    # Annex H T3 worst touch 202.7-209.0 V; the converged engine value is 203.4 V.
    assert 202.7 <= result["max_touch_v"]["value"] <= 209.0
    # The worst 1 m step is at least the converged diagonal corner step S1 (91.24 V).
    assert 91.0 <= result["max_step_v"]["value"] <= 95.0
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


def test_two_layer_artifact_is_calculated(engine):
    # Annex H Grid 3 as an artifact: Grid 2 geometry (rods at the 20 perimeter nodes) in 300/100 soil.
    snapshot = {**ANNEX_H_GRID1, "geometry": {**ANNEX_H_GRID1["geometry"], "rods_count": 20},
                "soil_layers": [{"resistivity_ohm_m": 300, "depth_m": 6.096}, {"resistivity_ohm_m": 100}]}
    result = calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0}, engine)["result"]
    assert result["soil"] == {"model": "two-layer", "upper_resistivity_ohm_m": 300.0,
                              "lower_resistivity_ohm_m": 100.0, "upper_thickness_m": 6.096}
    # Annex H range 0.97-0.972 ohm with 7.95 mm rods; the artifact uses the conductor radius for rods.
    assert math.isclose(result["grid_resistance_ohm"], 0.971, rel_tol=0.01)
    # IEEE 80 Cs uses the soil directly beneath the surface layer: the upper layer (300 ohm-m).
    cs = result["safety"][0]["parameters"]["surface_layer_factor_cs"]
    assert math.isclose(cs, 1 - 0.09 * (1 - 300 / 3000) / (2 * 0.1 + 0.09), rel_tol=1e-9)


def test_three_soil_layers_are_calculated_with_the_n_layer_kernel(engine):
    # Grid 1 geometry with 7.5 m rods through both interfaces (2 m and 6 m).
    snapshot = {**ANNEX_H_GRID1, "geometry": {**ANNEX_H_GRID1["geometry"], "rods_count": 4},
                "soil_layers": [{"resistivity_ohm_m": 300, "depth_m": 2},
                                {"resistivity_ohm_m": 100, "depth_m": 4}, {"resistivity_ohm_m": 50}]}
    outcome = calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0}, engine)
    result, trace = outcome["result"], outcome["trace"]
    assert result["soil"] == {"model": "n-layer", "kernel_density": 10, "layers": [
        {"resistivity_ohm_m": 300.0, "thickness_m": 2.0}, {"resistivity_ohm_m": 100.0, "thickness_m": 4.0},
        {"resistivity_ohm_m": 50.0, "thickness_m": None}]}
    assert result["diagnostics"]["kernel_error_bound"] < 1e-5
    assert trace["soil_model"] == "n-layer" and "n-layer-generalized-reflection-recursion" in trace["method"]
    rods = [s["id"] for s in trace["segments"] if s["kind"] == "rod"]
    assert any(".L2" in r or "p1" in r for r in rods) and any("p2" in r for r in rods)
    # Between the homogeneous grids of the bottom (50) and top (300 ohm-m) resistivities.
    homogeneous = {rho: calculate({**snapshot, "soil_layers": [{"resistivity_ohm_m": rho}]},
                                  {**PARAMETERS, "surface_spacing_m": 1.0}, engine)["result"]["grid_resistance_ohm"]
                   for rho in (50, 300)}
    assert homogeneous[50] < result["grid_resistance_ohm"] < homogeneous[300]
    # IEEE 80 Cs uses the soil directly beneath the surface layer: the top layer (300 ohm-m).
    cs = result["safety"][0]["parameters"]["surface_layer_factor_cs"]
    assert math.isclose(cs, 1 - 0.09 * (1 - 300 / 3000) / (2 * 0.1 + 0.09), rel_tol=1e-9)


def test_soil_layer_stacks_are_merged_or_rejected():
    assert soil_model([{"resistivity_ohm_m": 300, "depth_m": 2}, {"resistivity_ohm_m": 300, "depth_m": 4},
                       {"resistivity_ohm_m": 100}]) == TwoLayerSoil(300.0, 100.0, 6.0)
    assert soil_model([{"resistivity_ohm_m": 300, "depth_m": 2}, {"resistivity_ohm_m": 100, "depth_m": 4},
                       {"resistivity_ohm_m": 100}]) == TwoLayerSoil(300.0, 100.0, 2.0)
    stack = soil_model([{"resistivity_ohm_m": r, "depth_m": 1.0} for r in (10, 20, 30, 40, 50, 60, 70)] +
                       [{"resistivity_ohm_m": 80}])
    assert isinstance(stack, LayerStackSoil) and len(stack.layers) == 8
    with pytest.raises(UnsupportedModelError, match="semiespacio"):
        soil_model([{"resistivity_ohm_m": 300, "depth_m": 2}, {"resistivity_ohm_m": 100, "depth_m": 4},
                    {"resistivity_ohm_m": 50, "depth_m": 3}])
    with pytest.raises(UnsupportedModelError, match="capa 2"):
        soil_model([{"resistivity_ohm_m": 300, "depth_m": 2}, {"resistivity_ohm_m": 100}, {"resistivity_ohm_m": 50}])
    with pytest.raises(UnsupportedModelError, match="entre 1 y 8"):
        soil_model([{"resistivity_ohm_m": 10 + r, "depth_m": 1.0} for r in range(8)] + [{"resistivity_ohm_m": 5}])
    with pytest.raises(UnsupportedModelError, match="fuera del rango"):
        soil_model([{"resistivity_ohm_m": 1, "depth_m": 2}, {"resistivity_ohm_m": 20000, "depth_m": 4},
                    {"resistivity_ohm_m": 50}])


def test_two_layers_need_upper_thickness(engine):
    snapshot = {**ANNEX_H_GRID1, "soil_layers": [{"resistivity_ohm_m": 300}, {"resistivity_ohm_m": 100}]}
    with pytest.raises(UnsupportedModelError, match="espesor"):
        calculate(snapshot, PARAMETERS, engine)


def test_identical_layers_count_as_homogeneous(engine):
    snapshot = {**ANNEX_H_GRID1, "soil_layers": [{"resistivity_ohm_m": 140, "depth_m": 3}, {"resistivity_ohm_m": 140}]}
    assert calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0}, engine)["result"]["soil"] == {
        "model": "homogeneous", "resistivity_ohm_m": 140.0}


def test_grid_over_segment_limit_is_rejected(engine):
    with pytest.raises(UnsupportedModelError, match="segmentos"):
        calculate(ANNEX_H_GRID1, {**PARAMETERS, "discretization_m": 0.2, "segmentation": "uniform"}, engine)


def test_uniform_segmentation_is_still_available(engine):
    result = calculate(ANNEX_H_GRID1, {**PARAMETERS, "surface_spacing_m": 1.0, "segmentation": "uniform"}, engine)["result"]
    assert result["segmentation"] == "uniform" and result["segment_count"] == 840


def test_numerical_uncertainty_brackets_the_converged_values(engine):
    parameters = {**PARAMETERS, "surface_spacing_m": 1.0, "estimate_uncertainty": True}
    outcome = calculate(ANNEX_H_GRID1, parameters, engine)
    uncertainty = outcome["result"]["numerical_uncertainty"]
    assert uncertainty["status"] == "estimado" and uncertainty["discretizations_m"] == [4.0, 2.0, 1.0]
    assert outcome["trace"]["numerical_uncertainty"] == uncertainty
    assert len(outcome["trace"]["request_sha256_batches"]) >= 6
    converged_resistance = 1.00011
    for entry in uncertainty["quantities"].values():
        assert entry["method"] in {"richardson-gci", "diferencia-entre-refinamientos", "sin-cambio-entre-refinamientos"}
        assert entry["value"] == entry["levels"][-1] and entry["error_estimate"] >= 0
    # The estimated error band contains the converged resistance (Richardson on uniform 1/0.5/0.25 m).
    r = uncertainty["quantities"]["grid_resistance_ohm"]
    assert r["method"] == "richardson-gci"
    assert abs(r["value"] - converged_resistance) <= r["error_estimate"]
    # The reported values are those of the requested (finest) run.
    assert r["value"] == outcome["result"]["grid_resistance_ohm"]
    assert uncertainty["quantities"]["max_step_v"]["value"] == outcome["result"]["max_step_v"]["value"]


def _artifact(client, tokens, snapshot):
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    artifact = client.post(base, json=snapshot, headers=headers(tokens)).json()
    return base, artifact


# A grid in the back yard (x 22-27 m) of a 27 x 10 m site whose building fills x 2-22 m.
YARD_SITE = {"length_m": 27, "width_m": 10, "burial_depth_m": 0.5,
             "structures": [{"x": 12, "y": 5, "width": 20, "height": 10, "label": "Edificio existente"}],
             "areas": [{"type": "intervenible", "label": "Patio", "x_min": 22, "x_max": 27, "y_min": 0, "y_max": 10}],
             "conductors": [{"start": {"x": 22, "y": y}, "end": {"x": 27, "y": y}} for y in (0, 5, 10)]
             + [{"start": {"x": x, "y": 0}, "end": {"x": x, "y": 10}} for x in (22, 27)]}


def test_touch_is_searched_over_the_grid_and_step_outside_structures(engine):
    snapshot = {"name": "Patio", "geometry": YARD_SITE, "soil_layers": [{"resistivity_ohm_m": 100}],
                "fault": {"current_a": 1000, "clearing_time_s": 0.5}}
    result = calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0}, engine)["result"]
    surface, touch = result["surface_potential"], result["max_touch_v"]
    # Plan x 22-27 is -13.5..13.5 centred: the yard is 8.5..13.5; the raster starts 3 m before the site.
    assert (surface["grid_x_m"], surface["grid_width_m"], surface["grid_height_m"]) == (25, 5, 10)
    assert 8.5 - 1e-9 <= touch["x_m"] <= 13.5 + 1e-9 and -5 - 1e-9 <= touch["y_m"] <= 5 + 1e-9
    # The maximum location may move on the 0.25 m refinement lattice, finer than the 1 m raster.
    assert math.isclose(touch["x_m"] * 4, round(touch["x_m"] * 4), abs_tol=1e-9)
    assert math.isclose(touch["y_m"] * 4, round(touch["y_m"] * 4), abs_tol=1e-9)
    for x, y in (result["max_step_v"]["from_m"], result["max_step_v"]["to_m"]):
        assert not (-11.5 < x < 8.5 and -5 < y < 5)  # never inside the building
    assert math.isclose(math.dist(result["max_step_v"]["from_m"], result["max_step_v"]["to_m"]), 1.0, rel_tol=1e-9)
    reach = calculate(snapshot, {**PARAMETERS, "surface_spacing_m": 1.0, "touch_reach_m": 1.0}, engine)["result"]
    assert reach["surface_potential"]["grid_width_m"] == 7 and reach["max_touch_v"]["value"] >= touch["value"]


def test_geometry_check_and_area_grid_endpoints(env):
    _, _, client, _, tokens, _ = env
    project = client.post("/api/v1/projects", json={"name": "Casa"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/geometria"
    site = {**YARD_SITE, "areas": [{"type": "intervenible", "label": "Antejardín", "x_min": 0, "x_max": 2,
                                    "y_min": 0, "y_max": 10}, *YARD_SITE["areas"]]}
    across = {**site, "conductors": [{"start": {"x": 0, "y": 5}, "end": {"x": 27, "y": 5}}]}
    checked = client.post(f"{base}/validar", json={"geometry": across}, headers=headers(tokens)).json()
    assert {(c["element"], c["index"], c["kind"]) for c in checked["conflicts"]} == {
        ("conductor", 0, "crosses_obstacle"), ("conductor", 0, "outside_areas")}
    grid = client.post(f"{base}/malla-en-areas", json={"geometry": site, "areas": ["Patio"], "spacing_x_m": 5,
                                                       "spacing_y_m": 5}, headers=headers(tokens)).json()
    assert len(grid["conductors"]) == 5 and grid["conflicts"] == [] and grid["warnings"] == []
    missing = client.post(f"{base}/malla-en-areas", json={"geometry": site, "spacing_x_m": 5, "spacing_y_m": 5},
                          headers=headers(tokens))
    assert missing.status_code == 422 and "say which one" in missing.json()["detail"]
    malformed = client.post(f"{base}/validar", json={"geometry": {"length_m": 10, "width_m": 10, "conductors": "x"}},
                            headers=headers(tokens))
    assert malformed.status_code == 422


def test_artifact_api_rejects_unknown_fields(env):
    _, _, client, _, tokens, _ = env
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    response = client.post(base, json={**ANNEX_H_GRID1, "unexpected": True}, headers=headers(tokens))
    assert response.status_code == 422


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
    assert calculation["parameters"] == {**PARAMETERS, "justification": "Configuración predeterminada validada por el motor.", "surface_spacing_m": 1.0,
                                         "safety_standards": ["IEEE 80-2013", "RETIE 2013"], "fault_split": None,
                                         "x_over_r": None, "system_frequency_hz": 60.0,
                                         "segmentation": "graded", "estimate_uncertainty": False,
                                             "touch_reach_m": 0.0}

    run_potential_calculation(services.store, calculation["id"], engine)
    run_potential_calculation(services.store, calculation["id"], engine)  # redelivery is a no-op
    detail = client.get(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}", headers=headers(tokens)).json()
    assert detail["status"] == "completed" and detail["error"] is None
    assert math.isclose(detail["result"]["grid_resistance_ohm"], 1.0002, rel_tol=1e-3)
    assert detail["trace"]["solver_version"] and len(detail["trace"]["request_sha256"]) == 64
    assert math.isclose(detail["trace"]["segments"][0]["radius_m"], 0.00525, rel_tol=1e-6)
    assert [(entry["standard"], entry["status"]) for entry in detail["result"]["safety"]] == [
        ("IEEE 80-2013", "cumple"), ("RETIE 2013", "no_evaluable")]

    listed = client.get(url, headers=headers(tokens)).json()
    assert [row["id"] for row in listed] == [calculation["id"]]
    cancel = client.post(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}/cancelar",
                         headers=headers(tokens))
    assert cancel.status_code == 409


def test_fitted_three_layer_soil_is_stored_and_calculated_through_api(env, engine, monkeypatch):  # noqa: F811
    _, services, client, _, tokens, _ = env
    monkeypatch.setattr(tasks.calculate_artifact_potential, "apply_async", lambda args, task_id: None)
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    sounding = NLayerSoil((SoilLayer(300.0, 2.0), SoilLayer(80.0, 5.0), SoilLayer(600.0)))
    readings = [{"spacing_m": a, "apparent_resistivity_ohm_m": apparent_resistivity_n_layer(sounding, "wenner", a)}
                for a in (0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32)]
    fitted = client.post(f"{base}/mediciones-suelo/ajustar", json={"array": "wenner", "layer_count": 3,
                                                                   "measurements": readings}, headers=headers(tokens))
    assert fitted.status_code == 200, fitted.text
    fit = fitted.json()
    assert fit["layer_count"] == 3 and fit["model"]["model"] == "n-layer" and fit["excluded"] == []
    assert fit["soil_layers"][-1]["depth_m"] is None and fit["rms_error_percent"] < 0.5
    assert len(fit["relative_uncertainty_percent"]) == 3 and "koefoed-transform" in fit["forward_model"]
    snapshot = {**ANNEX_H_GRID1, "soil_layers": fit["soil_layers"],
                "soil_measurements": {"array": "wenner", "layer_count": 3, "measurements": readings}}
    artifact = client.post(base, json=snapshot, headers=headers(tokens)).json()
    calculation = client.post(f"{base}/{artifact['artifact_id']}/versions/1/calculos-potencial",
                              json={"surface_spacing_m": 1.0}, headers=headers(tokens)).json()
    run_potential_calculation(services.store, calculation["id"], engine)
    detail = client.get(f"{base}/{artifact['artifact_id']}/calculos-potencial/{calculation['id']}",
                        headers=headers(tokens)).json()
    assert detail["status"] == "completed", detail["error"]
    assert detail["result"]["soil"]["model"] == "n-layer" and len(detail["result"]["soil"]["layers"]) == 3
    assert detail["trace"]["soil_model"] == "n-layer"


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
