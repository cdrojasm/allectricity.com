from pathlib import Path
import math

import pytest

from src.domain.spat.grid_geometry import missing_for_calculation
from src.infrastructure.calculations import artifact_potential, solver_evaluation
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient


def test_v2_calculates_each_entity_and_groups_results_by_building(monkeypatch):
    calls = []

    def fake_evaluate(*, geometry, soil, injection_a, points, client, settings):
        calls.append((geometry, injection_a, settings))
        token = geometry["token"]
        return {
            "schema_version": solver_evaluation.EVALUATION_SCHEMA,
            "protocol_version": "SPAT-POTENTIAL-3",
            "solver_version": "3.4.0",
            "input_sha256": token * 64,
            "status": "approximate",
            "quantities": {"Rg_ohm": 1.0, "GPR_v": 100.0, "Vs_v": 2.0, "Vt_v": 3.0},
            "locations": {"Vs": {"from_m": [0.0, 0.0], "to_m": [1.0, 0.0]},
                          "Vt": {"x_m": 0.0, "y_m": 0.0}},
            "point_potentials_v": {}, "diagnostics": {}, "warnings": [],
        }

    monkeypatch.setattr(solver_evaluation, "evaluate", fake_evaluate)
    snapshot = {
        "schema_version": "2.0",
        "soil_layers": [{"resistivity_ohm_m": 100.0}],
        "fault": {"current_a": 100.0, "clearing_time_s": 0.5},
        "networks": [{"id": "n1", "name": "Subestación", "geometry": {"token": "a"}}],
        "electrodes": [{"id": "e1", "name": "Anillo", "geometry": {"token": "b"}}],
        "buildings": [{"id": "b1", "name": "Edificio", "network_ids": ["n1"], "electrode_ids": ["e1"]}],
    }

    computed = artifact_potential.calculate(snapshot, {"surface_spacing_m": 0.5}, object())
    result = computed["result"]

    assert len(calls) == 2
    assert all(current == 100.0 for _, current, _ in calls)
    assert set(result["buildings"]["b1"]["networks"]) == {"n1"}
    assert set(result["buildings"]["b1"]["electrodes"]) == {"e1"}
    assert result["networks"]["n1"]["evaluation"]["quantities"]["Rg_ohm"] == 1.0
    assert computed["trace"]["input_sha256"] != computed["trace"]["evaluations"][0]["input_sha256"]


def test_v2_missing_calculation_inputs_are_reported_per_entity():
    snapshot = {
        "schema_version": "2.0", "networks": [{"id": "n1", "geometry": {}}], "electrodes": [],
        "soil_layers": [], "fault": {"current_a": None, "clearing_time_s": None},
    }
    assert missing_for_calculation(snapshot) == [
        "geometry.n1", "soil_layers", "fault.current_a", "fault.clearing_time_s",
    ]


def test_v2_adapter_runs_against_the_real_solver_and_groups_results():
    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        pytest.skip("potential engine binary is not available")
    snapshot = {
        "schema_version": "2.0",
        "soil_layers": [{"resistivity_ohm_m": 100.0}],
        "fault": {"current_a": 100.0, "clearing_time_s": 0.5},
        "networks": [{"id": "n1", "name": "Red", "geometry": {
            "length_m": 2.0, "width_m": 2.0, "burial_depth_m": 0.5,
            "conductor_spacing_m": 2.0, "rods_count": 0,
        }}],
        "electrodes": [],
        "buildings": [{"id": "b1", "name": "Edificio", "network_ids": ["n1"], "electrode_ids": []}],
    }

    result = artifact_potential.calculate(
        snapshot, {"discretization_m": 2.0, "surface_spacing_m": 1.0}, client,
    )["result"]

    evaluation = result["buildings"]["b1"]["networks"]["n1"]["evaluation"]
    assert evaluation["status"] == "approximate"
    assert evaluation["quantities"]["Rg_ohm"] > 0
    assert evaluation["quantities"]["GPR_v"] == pytest.approx(100.0 * evaluation["quantities"]["Rg_ohm"])
    assert evaluation["locations"]["Vs"]["from_m"] is not None
    assert result["networks"]["n1"]["evaluation"]["input_sha256"] == evaluation["input_sha256"]


def _scenario_snapshot():
    def wire(y):
        return {
            "length_m": 4.0, "width_m": 4.0, "burial_depth_m": 0.5,
            "conductors": [{"start": {"x": 0.0, "y": y}, "end": {"x": 4.0, "y": y}}],
            "rods_count": 0,
        }

    return {
        "schema_version": "2.0",
        "soil_layers": [{"resistivity_ohm_m": 100.0}],
        "fault": {"current_a": 1.0, "clearing_time_s": 0.5},
        "networks": [{"id": "north", "name": "North", "geometry": wire(1.0)}],
        "electrodes": [{"id": "south", "name": "South", "geometry": wire(3.0)}],
        "buildings": [],
        "connections": [{"id": "bond-resistor", "kind": "resistor", "group_a": "north",
                         "group_b": "south", "resistance_ohm": 2.0}],
    }


def test_v2_scenarios_obey_superposition_kcl_and_transfer_polarity():
    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        pytest.skip("potential engine binary is not available")
    snapshot = _scenario_snapshot()
    scenarios = [
        {"id": "north-only", "injections_a": {"north": 1.0}},
        {"id": "south-only", "injections_a": {"south": -0.4}},
        {"id": "combined", "injections_a": {"north": 1.0, "south": -0.4}},
        {"id": "reversed", "injections_a": {"north": -1.0, "south": 0.4}},
    ]
    result = artifact_potential.calculate(
        snapshot,
        {"scenarios": scenarios, "discretization_m": 2.0, "surface_spacing_m": 1.0},
        client,
    )["result"]["scenario_results"]

    for entity_id in ("north", "south"):
        combined = result["combined"]["entities"][entity_id]["potential_v"]
        individual = (result["north-only"]["entities"][entity_id]["potential_v"]
                      + result["south-only"]["entities"][entity_id]["potential_v"])
        assert combined == pytest.approx(individual, rel=1e-9, abs=1e-10)
        assert result["reversed"]["entities"][entity_id]["potential_v"] == pytest.approx(-combined, rel=1e-9)

    for scenario in result.values():
        assert scenario["potential_reference"] == "remote-earth"
        assert scenario["diagnostics"]["max_relative_balance_error"] < 1e-9
        transfer = scenario["transferred_potentials_v"][0]
        delta = (scenario["entities"][transfer["from_entity_id"]]["potential_v"]
                 - scenario["entities"][transfer["to_entity_id"]]["potential_v"])
        assert transfer["signed_potential_v"] == pytest.approx(delta)
        assert transfer["absolute_potential_v"] == pytest.approx(abs(delta))
        assert scenario["connection_currents_a"]["bond-resistor"] == pytest.approx(
            (scenario["entities"]["north"]["potential_v"]
             - scenario["entities"]["south"]["potential_v"]) / 2.0,
            rel=1e-8,
        )
        assert math.isfinite(scenario["max_touch_v"]["value_v"])
        assert math.isfinite(scenario["max_step_v"]["value_v"])


def test_v2_accessible_voltage_maxima_stabilize_under_raster_refinement():
    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        pytest.skip("potential engine binary is not available")
    snapshot = _scenario_snapshot()
    snapshot["electrodes"] = []
    snapshot["connections"] = []
    snapshot["networks"] = [snapshot["networks"][0]]
    scenario = [{"id": "unit", "injections_a": {"north": 1.0}}]
    observed = {}
    for spacing in (1.0, 0.5, 0.25):
        values = artifact_potential.calculate(
            snapshot,
            {"scenarios": scenario, "discretization_m": 2.0, "surface_spacing_m": spacing},
            client,
        )["result"]["scenario_results"]["unit"]
        observed[spacing] = (values["max_touch_v"]["value_v"], values["max_step_v"]["value_v"])
        assert values["touch_by_entity"]
        assert all(math.isfinite(value) for value in observed[spacing])
        assert values["surface_grid"]["spacing_m"] == spacing

    # The 0.25 m search should not move materially from the 0.5 m estimate on this small wire case.
    # This is a raster-convergence guard, not an independent physical validation of the maximum.
    for coarse, fine in zip(observed[0.5], observed[0.25]):
        assert abs(fine - coarse) <= 0.1 * max(abs(fine), abs(coarse), 1e-9)
