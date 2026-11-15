"""BL-15 / EG-21: deterministic coherence rules on the calculation inputs. No solver is involved."""

import math

import pytest
from src.domain.spat.input_coherence import (
    coherence_diagnostics, coherence_errors, coherence_warnings, resistance_plausibility, sverak_resistance_ohm,
)

SOUND = {
    "geometry": {"length_m": 70, "width_m": 70, "burial_depth_m": 0.5, "conductor_spacing_m": 14, "rods_count": 0, "rod_length_m": 7.5},
    "soil_layers": [{"resistivity_ohm_m": 140}],
    "fault": {"current_a": 744.8, "clearing_time_s": 0.5, "surface_resistivity_ohm_m": 3000, "surface_thickness_m": 0.1},
    "conductor": {"thermal_duration_s": 1.0},
}


def _with(**sections):
    return {**SOUND, **{key: {**SOUND.get(key, {}), **value} if isinstance(value, dict) else value for key, value in sections.items()}}


def _paths(diagnostics):
    return [(d["path"], d["severity"]) for d in diagnostics]


def test_a_sound_artifact_has_no_diagnostics_and_missing_data_is_not_a_coherence_problem():
    assert coherence_diagnostics(SOUND) == []
    assert coherence_diagnostics({}) == [] and coherence_diagnostics(None) == []
    assert coherence_diagnostics({"fault": {"current_a": None, "clearing_time_s": "0.5"}}) == []   # types are the schema's job


@pytest.mark.parametrize("fault, expected", [
    ({"current_a": 400_000}, [("fault.current_a", "error")]),
    ({"current_a": 50}, [("fault.current_a", "warning")]),
    ({"current_a": 150_000}, [("fault.current_a", "warning")]),
    ({"clearing_time_s": 0.01}, [("fault.clearing_time_s", "error")]),                  # less than one cycle: ms or cycles typed as s
    ({"clearing_time_s": 12}, [("fault.clearing_time_s", "error"), ("conductor.thermal_duration_s", "error")]),
    ({"clearing_time_s": 5}, [("fault.clearing_time_s", "warning"), ("conductor.thermal_duration_s", "error")]),  # outside Dalziel's 0.03-3 s
    ({"clearing_time_s": 0.02}, [("fault.clearing_time_s", "warning")]),
    ({"surface_thickness_m": 10}, [("fault.surface_thickness_m", "error")]),            # centimetres typed as metres
    ({"surface_thickness_m": 0.02}, [("fault.surface_thickness_m", "warning")]),
    ({"surface_resistivity_ohm_m": 1e8}, [("fault.surface_resistivity_ohm_m", "warning")]),
    ({"surface_resistivity_ohm_m": 100}, [("fault.surface_resistivity_ohm_m", "warning")]),  # less resistive than the soil
])
def test_fault_and_surface_layer_rules(fault, expected):
    diagnostics = coherence_diagnostics(_with(fault=fault))
    assert _paths(diagnostics) == expected
    diagnostic = diagnostics[0]
    assert all(d["source"] and d["expected"] and d["message"] for d in diagnostics)
    assert diagnostic["value"] == fault[diagnostic["path"].split(".")[-1]]


def test_a_declared_absence_of_surface_layer_is_not_flagged_for_being_less_resistive():
    declared = _with(fault={"surface_resistivity_ohm_m": 140, "surface_layer_present": False})
    assert coherence_diagnostics(declared) == []
    assert _paths(coherence_diagnostics(_with(fault={"surface_resistivity_ohm_m": 100, "surface_layer_present": True}))) == [
        ("fault.surface_resistivity_ohm_m", "warning")]


def test_the_conductor_must_withstand_at_least_the_clearing_time():
    [error] = coherence_diagnostics(_with(conductor={"thermal_duration_s": 0.4}))
    assert error["path"] == "conductor.thermal_duration_s" and error["severity"] == "error"
    assert error["related"] == ["fault.clearing_time_s"] and "t_c" in error["message"] and "t_s" in error["message"]
    assert coherence_diagnostics(_with(conductor={"thermal_duration_s": 0.5})) == []      # equal is fine
    assert coherence_diagnostics({**SOUND, "conductor": {}}) == []                        # legacy artifact without conductor


@pytest.mark.parametrize("layers, expected", [
    ([{"resistivity_ohm_m": 1_400_000, "depth_m": 2}, {"resistivity_ohm_m": 100}],
     [("fault.surface_resistivity_ohm_m", "warning"), ("soil_layers[0].resistivity_ohm_m", "error")]),            # ohm-cm typed as ohm-m
    ([{"resistivity_ohm_m": 14000, "depth_m": 2}, {"resistivity_ohm_m": 100}],
     [("fault.surface_resistivity_ohm_m", "warning"), ("soil_layers[0].resistivity_ohm_m", "warning")]),          # above IEEE 80 Table 2
    ([{"resistivity_ohm_m": 2}], [("soil_layers[0].resistivity_ohm_m", "warning")]),
    ([{"resistivity_ohm_m": 5000}], [("fault.surface_resistivity_ohm_m", "warning")]),                                # the 3000 ohm-m layer stops protecting
    ([{"resistivity_ohm_m": 100, "depth_m": 0.05}, {"resistivity_ohm_m": 300}], [("soil_layers[0].depth_m", "warning")]),
    ([{"resistivity_ohm_m": 100, "depth_m": 0.05}], []),                                   # the last layer's depth is not a thickness
    ([{"material": "arcilla", "depth_m": 2}, {"resistivity_ohm_m": 100}], []),            # resistivity still unknown: not incoherent
])
def test_soil_layer_rules(layers, expected):
    assert _paths(coherence_diagnostics(_with(soil_layers=layers))) == expected


def test_errors_and_warnings_are_separated_and_every_rule_can_fire_at_once():
    absurd = _with(fault={"current_a": 400_000, "clearing_time_s": 5, "surface_thickness_m": 10},
                   conductor={"thermal_duration_s": 1}, soil_layers=[{"resistivity_ohm_m": 2}])
    assert _paths(coherence_errors(absurd)) == [("fault.current_a", "error"), ("conductor.thermal_duration_s", "error"),
                                                ("fault.surface_thickness_m", "error")]
    assert _paths(coherence_warnings(absurd)) == [("fault.clearing_time_s", "warning"), ("soil_layers[0].resistivity_ohm_m", "warning")]
    assert len(coherence_diagnostics(absurd)) == 5


def test_sverak_matches_the_ieee_80_annex_b_hand_calculation():
    # IEEE 80-2013 Annex B.1: rho 400 ohm-m, A 70 x 70 m, L_T 1540 m, h 0.5 m -> R_g = 2.78 ohm.
    assert sverak_resistance_ohm(400, 4900, 1540, 0.5) == pytest.approx(2.78, abs=0.01)
    with pytest.raises(ValueError):
        sverak_resistance_ohm(400, 0, 1540, 0.5)


def test_resistance_plausibility_brackets_the_engine_against_sverak():
    geometry, soil = SOUND["geometry"], SOUND["soil_layers"]
    estimate = sverak_resistance_ohm(140, 4900, 840, 0.5)                              # 12 lines of 70 m, no rods
    assert resistance_plausibility(geometry, soil, estimate) is None
    assert resistance_plausibility(geometry, soil, estimate * 4) is None               # within the wide bracket
    high = resistance_plausibility(geometry, soil, estimate * 8)
    assert high and high["severity"] == "warning" and high["kind"] == "plausibility" and "Sverak" in high["message"]
    assert resistance_plausibility(geometry, soil, estimate / 10)["path"] == "result.grid_resistance_ohm"
    assert resistance_plausibility(geometry, soil, math.nan) is None
    assert resistance_plausibility({}, soil, 1.0) is None                              # nothing to estimate from: no verdict
    drawn = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "rods": [{"x": 0, "y": 0, "length_m": 3}],
             "conductors": [{"start": {"x": 0, "y": 0}, "end": {"x": 20, "y": 0}}]}
    assert resistance_plausibility(drawn, soil, sverak_resistance_ohm(140, 20, 23, 0.5)) is None
