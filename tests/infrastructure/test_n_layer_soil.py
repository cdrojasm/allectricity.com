"""Wenner/Schlumberger forward model and fit for 2-8 soil layers (`n_layer_soil`)."""

import pytest
from src.infrastructure.calculations import soil_model
from src.infrastructure.calculations.n_layer_soil import (
    MAX_CONTRAST,
    NLayerSoil,
    SoilLayer,
    apparent_resistivity_n_layer,
    fit_n_layer,
    soil_layers_record,
)
from src.infrastructure.calculations.potential_engine_client import LayerStackSoil
from src.infrastructure.calculations.soil_model import ResistivityMeasurement

from tests.infrastructure import layered_green_reference as reference

# Published sounding curves of three and four layers. Both were computed with Ghosh's (1971)
# linear filter on a TI-59 calculator; Haines & Campbell themselves warn that this short filter is
# "somewhat in error" on steeply falling curves, so the tolerance is the filter's accuracy, not
# ours (our model agrees with direct quadrature to 1e-4, see the test below). Assumptions:
# horizontal isotropic layers, point electrodes on the surface, ideal (MN -> 0) Schlumberger.
PUBLISHED = {
    "usgs_ofr_80_190_wenner": {
        "citation": "D. N. Haines and D. L. Campbell, 'Texas Instruments Model 59 hand calculator program to calculate "
                    "theoretical Wenner and Schlumberger vertical electrode soundings of a structure of up to 10 "
                    "horizontal layers', U.S. Geological Survey Open-File Report 80-190, 1980, example p. 11-12",
        "method": "Ghosh (1971) linear filter, 3 points per decade",
        "model": ((10.0, 10.0), (4.0, 50.0), (25.0, None)), "array": "wenner", "tolerance_rel": 0.01,
        "values": {1.0: 9.999734309, 2.15443469: 9.985672905, 4.641588834: 9.77223771, 10.0: 8.539385065,
                   21.5443469: 5.992546854, 46.41588834: 5.221504638, 100.0: 7.742246853,
                   215.443469: 12.59139515, 464.16: 18.00, 1000.0: 22.09, 2154.43: 24.10},
    },
    "usgs_ofr_80_190_schlumberger": {
        "citation": "Haines and Campbell, USGS Open-File Report 80-190, 1980, printer tape p. 14",
        "method": "Ghosh (1971) linear filter, 3 points per decade",
        "model": ((10.0, 10.0), (4.0, 50.0), (25.0, None)), "array": "schlumberger", "tolerance_rel": 0.01,
        "values": {1.0: 9.979896606, 2.15443469: 9.977938627, 4.641588834: 9.907182152, 10.0: 9.319470423,
                   21.5443469: 7.047480762, 46.41588834: 5.094844712, 100.0: 6.350793289,
                   215.443469: 10.50266499, 464.16: 15.96, 1000.0: 20.81, 2154.43: 23.60},
    },
    "usgs_ofr_81_160_schlumberger": {
        "citation": "A. S. M. El Kahwagy, 'A TI-59 calculator program for computation of Schlumberger resistivity "
                    "sounding curve for models with as many as 25 horizontal layers', U.S. Geological Survey "
                    "Open-File Report 81-160, 1981, example p. 2-3",
        "method": "Ghosh (1971) linear filter, 6 points per decade",
        "model": ((259.0, 1.0), (94.0, 46.0), (27.0, 150.0), (150.0, None)), "array": "schlumberger",
        "tolerance_rel": 0.045,
        "values": dict(zip([10 ** (k / 6) for k in range(25)], [
            241.1431472, 217.0136337, 179.1268944, 139.846785, 113.1147091, 100.9726029, 96.86244975,
            95.1592856, 93.71288423, 91.59566606, 86.95311787, 76.90352711, 61.51721231, 46.82094031,
            40.00588464, 43.1819453, 53.71142519, 68.20108221, 84.45314038, 100.9135405, 116.0076031,
            128.363842, 137.3269032, 143.100719, 146.4431868])),
    },
}


def soil(layers) -> NLayerSoil:
    return NLayerSoil(tuple(SoilLayer(rho, h) for rho, h in layers))


def model_value(model: NLayerSoil, array: str, spacing: float) -> float:
    # MN = AB/2 / 1000 reproduces the ideal Schlumberger array within 1e-6.
    return apparent_resistivity_n_layer(model, array, spacing, spacing * 1e-3 if array == "schlumberger" else None)


@pytest.mark.parametrize("case_id", PUBLISHED)
def test_published_three_and_four_layer_soundings(case_id):
    case = PUBLISHED[case_id]
    assert case["citation"] and case["method"]
    model = soil(case["model"])
    deviations = {a: model_value(model, case["array"], a) / v - 1 for a, v in case["values"].items()}
    assert max(map(abs, deviations.values())) <= case["tolerance_rel"], deviations


def test_forward_model_matches_direct_quadrature():
    # Independent check of the image fit: direct Hankel quadrature of the transform (tests only).
    for layers, spacings in ((((259.0, 1.0), (94.0, 46.0), (27.0, 150.0), (150.0, None)), (1.0, 3.16, 10.0, 31.6)),
                             (((10.0, 10.0), (4.0, 50.0), (25.0, None)), (1.0, 10.0, 46.4))):
        model = soil(layers)
        rhos, thicknesses = [rho for rho, _ in layers], [h for _, h in layers[:-1]]
        for s in spacings:
            expected = reference.ideal_schlumberger(rhos, thicknesses, s)
            assert model_value(model, "schlumberger", s) == pytest.approx(expected, rel=1e-4), s


@pytest.mark.parametrize("rho1, rho2, h", [(300, 100, 6.096), (100, 300, 6.096), (1000, 10, 0.5), (10, 10000, 1.0)])
def test_two_layer_limit_matches_the_exact_image_series(rho1, rho2, h):
    model = soil(((rho1, h), (rho2, None)))
    for array, mn in (("wenner", None), ("schlumberger", 0.2)):
        for a in (0.5, 1, 2, 5, 10, 20, 50, 100):
            exact = soil_model.apparent_resistivity(soil_model.TwoLayerSoil(rho1, rho2, h), array, a, mn and a * mn)
            assert apparent_resistivity_n_layer(model, array, a, mn and a * mn) == pytest.approx(exact, rel=2e-5)
    # A middle layer equal to its neighbour does not change the sounding.
    split = soil(((rho1, h / 2), (rho1, h / 2), (rho2, None)))
    expected = apparent_resistivity_n_layer(model, "wenner", 3.0)
    assert apparent_resistivity_n_layer(split, "wenner", 3.0) == pytest.approx(expected, rel=1e-9)


def published_readings(case_id):
    return [ResistivityMeasurement(a, v) for a, v in PUBLISHED[case_id]["values"].items()]


def test_fit_recovers_the_published_three_layer_model():
    fit = fit_n_layer(published_readings("usgs_ofr_80_190_wenner"), 3, "wenner")
    expected = PUBLISHED["usgs_ofr_80_190_wenner"]["model"]
    for layer, (rho, h) in zip(fit.model.layers, expected):
        assert layer.resistivity_ohm_m == pytest.approx(rho, rel=0.03)
        assert (layer.thickness_m is None) == (h is None)
        if h is not None:
            assert layer.thickness_m == pytest.approx(h, rel=0.03)
    assert fit.rms_error_percent < 0.5 and fit.excluded == []
    assert all(u["resistivity_ohm_m"] is not None and u["resistivity_ohm_m"] < 5 for u in fit.relative_uncertainty_percent)
    assert fit.relative_uncertainty_percent[-1]["thickness_m"] is None
    assert fit.uniform_rms_error_percent > 10 * fit.rms_error_percent
    assert "koefoed-transform" in fit.forward_model


@pytest.mark.parametrize("index", [2, 5, 8])
def test_fit_excludes_an_atypical_reading(index):
    readings = published_readings("usgs_ofr_80_190_wenner")
    readings[index] = ResistivityMeasurement(readings[index].spacing_m, readings[index].apparent_resistivity_ohm_m * 1.4)
    fit = fit_n_layer(readings, 3, "wenner")
    assert fit.excluded == [index]
    assert fit.residuals_percent[index] == pytest.approx(100 * (1 / 1.4 - 1), abs=2.0)
    assert fit.model.layers[1].resistivity_ohm_m == pytest.approx(4.0, rel=0.03)
    assert any("excluidas" in warning for warning in fit.warnings)


def test_fit_schlumberger_four_layers_and_store_in_engine_format():
    # Synthetic self-consistency (not an independent validation): the 4-layer OFR 81-160 model
    # sampled by our own forward model with a finite MN and refitted.
    model = soil(PUBLISHED["usgs_ofr_81_160_schlumberger"]["model"])
    readings = [ResistivityMeasurement(s, apparent_resistivity_n_layer(model, "schlumberger", s, s / 5), s / 5)
                for s in [10 ** (k / 4) for k in range(1, 15)]]
    fit = fit_n_layer(readings, 4, "schlumberger")
    assert fit.rms_error_percent < 0.1
    records = soil_layers_record(fit.model)
    assert records[-1]["depth_m"] is None and len(records) == 4
    stack = LayerStackSoil(tuple((r["resistivity_ohm_m"], r["depth_m"]) for r in records))
    assert len(stack.layers) == 4


def test_fit_keeps_the_engine_limits():
    # A sounding that would need a contrast above 1e4 is fitted inside the engine's range.
    contrasted = soil(((1.0, 2.0), (5000.0, 5.0), (1.0, None)))
    readings = [ResistivityMeasurement(a, apparent_resistivity_n_layer(contrasted, "wenner", a))
                for a in (0.5, 1, 2, 4, 8, 16, 32, 64)]
    readings = [ResistivityMeasurement(r.spacing_m, r.apparent_resistivity_ohm_m * (30.0 if i > 2 else 1.0))
                for i, r in enumerate(readings)]
    fit = fit_n_layer(readings, 3, "wenner", outlier_threshold=0.99)
    rhos = [layer.resistivity_ohm_m for layer in fit.model.layers]
    assert max(rhos) / min(rhos) <= MAX_CONTRAST * (1 + 1e-9)
    assert all(0.01 <= layer.thickness_m <= 1000 for layer in fit.model.layers[:-1])
    LayerStackSoil(tuple((layer.resistivity_ohm_m, layer.thickness_m) for layer in fit.model.layers))


@pytest.mark.parametrize("readings, layers, message", [
    ([ResistivityMeasurement(a, 100.0) for a in (1, 2, 3, 4, 5)], 3, "at least 6 readings"),
    ([ResistivityMeasurement(a, 100.0) for a in (1, 2, 3, 3, 5, 6)], 3, "strictly increasing"),
    ([ResistivityMeasurement(a, 100.0) for a in range(1, 20)], 9, "between 2 and 8"),
    ([ResistivityMeasurement(a, -1.0) for a in range(1, 8)], 3, "positive"),
])
def test_invalid_soundings_are_rejected(readings, layers, message):
    with pytest.raises(ValueError, match=message):
        fit_n_layer(readings, layers, "wenner")


def test_fit_respects_its_time_budget():
    fit = fit_n_layer(published_readings("usgs_ofr_80_190_wenner"), 3, "wenner", time_budget_s=0.0)
    assert any("presupuesto" in warning for warning in fit.warnings)
    assert len(fit.model.layers) == 3
