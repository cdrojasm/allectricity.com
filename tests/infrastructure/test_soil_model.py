import math
import random

import pytest
from src.infrastructure.calculations.soil_model import (
    SCHLUMBERGER,
    WENNER,
    ResistivityMeasurement,
    TwoLayerSoil,
    apparent_resistivity,
    fit_two_layer,
    to_soil_layers,
)

SPACINGS = [1, 1.5, 2, 3, 4.5, 6, 8, 10, 15, 20, 30, 45, 60]
# Two-layer soil models used by IEEE Std 80-2013 Annex H (Grids 3-6).
ANNEX_H_HIGH_ON_LOW = TwoLayerSoil(300.0, 100.0, 6.096)
ANNEX_H_LOW_ON_HIGH = TwoLayerSoil(100.0, 300.0, 6.096)


def sounding(soil, array=WENNER, noise=0.0, seed=7):
    rnd = random.Random(seed)
    readings = []
    for a in SPACINGS:
        mn = a / 5 if array == SCHLUMBERGER else None
        value = apparent_resistivity(soil, array, a, mn) * (1 + rnd.uniform(-noise, noise))
        readings.append(ResistivityMeasurement(a, value, mn))
    return readings


def brute_force_wenner(soil, a, terms=2_000_000):
    """Tagg's Wenner series summed term by term, as an independent check of the forward model."""
    total, power = 0.0, 1.0
    for n in range(1, terms):
        power *= soil.k
        if abs(power) < 1e-300:
            break
        x = 2 * n * soil.h_m / a
        total += power * (1 / math.sqrt(1 + x * x) - 1 / math.sqrt(4 + x * x))
    return soil.rho1_ohm_m * (1 + 4 * total)


@pytest.mark.parametrize(("soil", "a"), [
    (ANNEX_H_HIGH_ON_LOW, 10), (TwoLayerSoil(1, 999, 0.1), 60), (TwoLayerSoil(999, 1, 0.1), 60),
    (TwoLayerSoil(1000, 10, 0.05), 20),
])
def test_forward_model_matches_term_by_term_series(soil, a):
    assert math.isclose(apparent_resistivity(soil, WENNER, a), brute_force_wenner(soil, a), rel_tol=1e-6)


def test_forward_model_limits():
    for a in (0.5, 5, 50):
        assert math.isclose(apparent_resistivity(TwoLayerSoil(200, 200, 3), WENNER, a), 200, rel_tol=1e-12)
        assert math.isclose(apparent_resistivity(TwoLayerSoil(300, 100, 1e4), WENNER, a), 300, rel_tol=1e-6)
        assert math.isclose(apparent_resistivity(TwoLayerSoil(300, 100, 1e-4), WENNER, a), 100, rel_tol=1e-3)
        assert math.isclose(apparent_resistivity(TwoLayerSoil(300, 100, 1e4), SCHLUMBERGER, a, a / 5), 300, rel_tol=1e-6)


@pytest.mark.parametrize("array", [WENNER, SCHLUMBERGER])
@pytest.mark.parametrize("truth", [ANNEX_H_HIGH_ON_LOW, ANNEX_H_LOW_ON_HIGH, TwoLayerSoil(50, 800, 0.8)])
def test_inversion_recovers_exact_soundings(truth, array):
    fit = fit_two_layer(sounding(truth, array), array)
    assert math.isclose(fit.model.rho1_ohm_m, truth.rho1_ohm_m, rel_tol=1e-4)
    assert math.isclose(fit.model.rho2_ohm_m, truth.rho2_ohm_m, rel_tol=1e-4)
    assert math.isclose(fit.model.h_m, truth.h_m, rel_tol=1e-4)
    assert fit.rms_error_percent < 1e-6 and not fit.excluded


def test_inversion_with_two_percent_noise_reports_error_and_uncertainty():
    fit = fit_two_layer(sounding(ANNEX_H_HIGH_ON_LOW, noise=0.02))
    assert abs(fit.model.rho1_ohm_m / 300 - 1) < 0.02
    assert abs(fit.model.rho2_ohm_m / 100 - 1) < 0.02
    assert abs(fit.model.h_m / 6.096 - 1) < 0.03
    assert 0.3 < fit.rms_error_percent < 2.0
    assert all(0 < fit.relative_uncertainty_percent[name] < 5 for name in ("rho1", "rho2", "h"))
    assert fit.uniform_rms_error_percent > 10 * fit.rms_error_percent
    assert not fit.warnings


def test_outlier_is_excluded_and_reported():
    readings = sounding(ANNEX_H_HIGH_ON_LOW, noise=0.02)
    readings[5] = ResistivityMeasurement(readings[5].spacing_m, readings[5].apparent_resistivity_ohm_m * 1.6)
    fit = fit_two_layer(readings)
    assert fit.excluded == [5]
    assert fit.residuals_percent[5] < -15
    assert abs(fit.model.h_m / 6.096 - 1) < 0.03
    assert any("excluidas" in warning for warning in fit.warnings)


def test_uniform_soil_is_recognised():
    fit = fit_two_layer([ResistivityMeasurement(a, 150.0) for a in SPACINGS])
    assert math.isclose(fit.uniform_resistivity_ohm_m, 150.0)
    assert abs(fit.model.k) < 0.02
    assert len(fit.warnings) == 1 and "homogéneo" in fit.warnings[0]


def test_layers_feed_the_artifact_format():
    layers = to_soil_layers(ANNEX_H_HIGH_ON_LOW)
    assert layers == [{"resistivity_ohm_m": 300.0, "depth_m": 6.096}, {"resistivity_ohm_m": 100.0, "depth_m": None}]


@pytest.mark.parametrize(("readings", "array", "message"), [
    ([ResistivityMeasurement(a, 100) for a in (1, 2, 3)], WENNER, "at least"),
    ([ResistivityMeasurement(a, 100) for a in (1, 3, 2, 4)], WENNER, "increasing"),
    ([ResistivityMeasurement(a, 100) for a in (1, 1, 2, 4)], WENNER, "increasing"),
    ([ResistivityMeasurement(a, -5 if a == 2 else 100) for a in (1, 2, 3, 4)], WENNER, "positive"),
    ([ResistivityMeasurement(a, math.nan if a == 2 else 100) for a in (1, 2, 3, 4)], WENNER, "positive"),
    ([ResistivityMeasurement(a, 100) for a in (1, 2, 3, 4)], SCHLUMBERGER, "MN spacing"),
    ([ResistivityMeasurement(a, 100, 2 * a) for a in (1, 2, 3, 4)], SCHLUMBERGER, "smaller than AB"),
    ([ResistivityMeasurement(a, 100) for a in (1, 2, 3, 4)], "dipole", "array"),
])
def test_invalid_soundings_are_rejected(readings, array, message):
    with pytest.raises(ValueError, match=message):
        fit_two_layer(readings, array)


def test_wide_schlumberger_potential_spacing_is_flagged():
    readings = [ResistivityMeasurement(a, 100.0, a / 2) for a in SPACINGS]
    assert any("AB/5" in warning for warning in fit_two_layer(readings, SCHLUMBERGER).warnings)
