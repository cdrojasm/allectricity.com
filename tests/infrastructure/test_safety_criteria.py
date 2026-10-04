import math

import pytest
from src.infrastructure.calculations.safety_criteria import (
    EN50522_2010,
    IEEE80_2013,
    RETIE_2013,
    FaultExposure,
    StandardNotLoadedError,
    evaluate,
    surface_layer_factor,
    tolerable_limits,
)

# IEEE Std 80-2013 Annex B, Example 1: rho 400 ohm-m, crushed rock 2500 ohm-m, h_s 0.102 m,
# t_s 0.5 s, 70 kg body. The example rounds Cs to 0.74 and reports E_step70 = 2686.6 V and
# E_touch70 = 838.2 V (check against a licensed copy of the standard).
ANNEX_B = FaultExposure(clearing_time_s=0.5, body_weight_kg=70, surface_resistivity_ohm_m=2500,
                        surface_thickness_m=0.102, soil_resistivity_ohm_m=400)


def test_surface_layer_factor_matches_annex_b_example():
    assert round(surface_layer_factor(400, 2500, 0.102), 2) == 0.74


def test_surface_layer_factor_is_one_without_contrast():
    assert surface_layer_factor(300, 300, 0.1) == 1.0


def test_annex_b_tolerable_limits_with_published_rounding():
    limits = tolerable_limits(IEEE80_2013, ANNEX_B)
    body_current = limits["parameters"]["body_current_a"]
    assert math.isclose(body_current, 0.157 / math.sqrt(0.5))
    # With the example's rounded Cs = 0.74 the formulas reproduce the published values.
    assert math.isclose((1000 + 6 * 0.74 * 2500) * body_current, 2686.6, abs_tol=0.05)
    assert math.isclose((1000 + 1.5 * 0.74 * 2500) * body_current, 838.2, abs_tol=0.05)
    # Unrounded Cs = 0.7429 gives slightly higher limits.
    assert math.isclose(limits["step_v"], 2686.6, rel_tol=0.005)
    assert math.isclose(limits["touch_v"], 838.2, rel_tol=0.005)
    assert limits["parameters"]["body_weight_kg_used"] == 70


def test_fifty_kg_limits_and_conservative_intermediate_weight():
    exposure = FaultExposure(0.5, 60, 3000, 0.1, 140)
    limits = tolerable_limits(IEEE80_2013, exposure)
    cs = 1 - 0.09 * (1 - 140 / 3000) / (2 * 0.1 + 0.09)
    assert limits["parameters"]["body_weight_kg_used"] == 50
    assert math.isclose(limits["touch_v"], (1000 + 1.5 * cs * 3000) * 0.116 / math.sqrt(0.5))
    assert math.isclose(limits["step_v"], (1000 + 6 * cs * 3000) * 0.116 / math.sqrt(0.5))


@pytest.mark.parametrize("standard", [EN50522_2010, RETIE_2013])
def test_table_based_standards_are_not_invented(standard):
    with pytest.raises(StandardNotLoadedError, match="pendiente"):
        tolerable_limits(standard, ANNEX_B)


def test_evaluate_reports_status_margins_and_unevaluable_standards():
    field = {"touch_v": 900.0, "step_v": 450.0, "gpr_v": 5000.0}
    ieee, retie, unknown = evaluate(field, ANNEX_B, [IEEE80_2013, RETIE_2013, "NFPA 70"])
    touch, step = ieee["criteria"]
    assert ieee["status"] == "no_cumple" and ieee["gpr_below_tolerable_touch"] is False
    assert touch["status"] == "no_cumple" and touch["margin_v"] < 0 and "eq. 33" in touch["formula"]
    assert step["status"] == "cumple" and math.isclose(step["margin_v"], step["tolerable_v"] - 450.0)
    assert retie["status"] == "no_evaluable" and "pendiente" in retie["reason"]
    assert unknown["status"] == "no_evaluable" and "no soportada" in unknown["reason"]


def test_clearing_time_outside_ieee80_range_is_not_evaluable():
    exposure = FaultExposure(5.0, 50, 3000, 0.1, 140)
    [result] = evaluate({"touch_v": 1.0, "step_v": 1.0, "gpr_v": 1.0}, exposure, [IEEE80_2013])
    assert result["status"] == "no_evaluable" and "0.03" in result["reason"]
