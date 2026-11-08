import pytest

from src.domain.spat.optimizer_sensitivity import finite_difference_sensitivities


def test_central_differences_recover_linear_cost_and_voltage_slopes():
    result = finite_difference_sensitivities(
        parameters={"x": 2.0}, variables={"x": {"min": 0.0, "max": 4.0, "step": 0.1}},
        evaluate=lambda p: {"cost": 3 * p["x"], "Vs": 2 * p["x"] + 1, "Vt": 5 - p["x"]})
    metrics = result["variables"]["x"]["metrics"]
    assert metrics["cost"]["derivative"] == pytest.approx(3.0)
    assert metrics["Vs"]["derivative"] == pytest.approx(2.0)
    assert metrics["Vt"]["derivative"] == pytest.approx(-1.0)
    assert not result["variables"]["x"]["nonsmooth"]


def test_bound_uses_one_sided_difference_and_flags_a_kink():
    result = finite_difference_sensitivities(
        parameters={"x": 0.1}, variables={"x": {"min": 0.0, "max": 2.0, "step": 0.1}},
        evaluate=lambda p: {"cost": p["x"] ** 2, "Vs": abs(p["x"] - 0.05), "Vt": None})
    variable = result["variables"]["x"]
    assert variable["metrics"]["cost"]["one_sided"] is False
    assert variable["metrics"]["Vt"]["status"] == "unavailable"
    assert variable["nonsmooth"] is True


def test_invalid_bounds_and_evaluation_failures_are_reported_without_imputation():
    result = finite_difference_sensitivities(
        parameters={"x": 1.0}, variables={"x": {"min": 2.0, "max": 3.0}, "y": {"min": 0, "max": 2}},
        evaluate=lambda p: {"cost": 1.0, "Vs": 2.0, "Vt": 3.0})
    assert result["variables"]["x"]["status"] == "unavailable"
    assert result["variables"]["y"]["status"] == "unavailable"


def test_baseline_solver_failure_is_reported_for_all_variables():
    def fail(_parameters):
        raise RuntimeError("solver unavailable")

    result = finite_difference_sensitivities(
        parameters={"x": 1.0}, variables={"x": {"min": 0.0, "max": 2.0}}, evaluate=fail)
    assert result["status"] == "unavailable"
    assert result["variables"]["x"]["status"] == "unavailable"
    assert "solver unavailable" in result["reason"]

