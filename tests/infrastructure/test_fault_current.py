import math

import pytest
from src.infrastructure.calculations.fault_current import (
    ReturnPath,
    decrement_factor,
    grid_current,
    split_from_paths,
)


@pytest.mark.parametrize(("x_over_r", "duration_s", "expected"), [
    # IEEE Std 80-2013 Table 10 (60 Hz): typical decrement factors.
    (10, 0.5, 1.026), (40, 0.5, 1.101), (10, 0.1, 1.125), (20, 0.1, 1.232), (10, 0.05, 1.232),
])
def test_decrement_factor_matches_ieee80_table(x_over_r, duration_s, expected):
    assert decrement_factor(x_over_r, duration_s) == pytest.approx(expected, abs=5e-4)


def test_decrement_factor_limits():
    assert decrement_factor(0, 0.5) == 1.0
    assert decrement_factor(10, 100.0) == pytest.approx(1.0, abs=2e-4)
    assert decrement_factor(10, 0.5, 50) > decrement_factor(10, 0.5, 60)
    with pytest.raises(ValueError):
        decrement_factor(-1, 0.5)
    with pytest.raises(ValueError):
        decrement_factor(10, 0)


def test_split_limits_and_current_conservation():
    assert split_from_paths(1.0, [ReturnPath("open", "other", 1e12)])["split_factor"] == pytest.approx(1.0)
    assert split_from_paths(1.0, [ReturnPath("short", "other", 1e-9)])["split_factor"] == pytest.approx(0.0, abs=1e-8)
    assert split_from_paths(1.0, [ReturnPath("equal", "other", 1.0)])["split_factor"] == pytest.approx(0.5)
    split = split_from_paths(0.8, [ReturnPath("ohgw", "shield_wire", 0.6 + 0.9j), ReturnPath("n", "neutral", 2 + 1j)])
    total = complex(split["grid_share"]["real"], split["grid_share"]["imag"]) + sum(
        complex(p["share"]["real"], p["share"]["imag"]) for p in split["paths"])
    assert total == pytest.approx(1.0 + 0j, abs=1e-12)


def test_grid_current_combines_decrement_and_split():
    result = grid_current(10_000, 0.5, x_over_r=10, split_factor=0.6, split_factor_origin="estudio 2026")
    assert result["grid_current_a"] == pytest.approx(10_000 * 0.6 * decrement_factor(10, 0.5))
    assert result["split_origin"] == "user: estudio 2026"
    paths = grid_current(1000, 0.5, grid_resistance_ohm=1.0, return_paths=[ReturnPath("a", "other", 1.0)])
    assert paths["grid_current_a"] == pytest.approx(500)
    assert paths["paths"][0]["current_a"] == pytest.approx(500)
    assert paths["decrement_factor"] == 1.0
    assert grid_current(1000, 0.5)["grid_current_a"] == 1000


@pytest.mark.parametrize("kwargs", [
    {"split_factor": 0.5, "return_paths": [ReturnPath("a", "other", 1.0)], "split_factor_origin": "x",
     "grid_resistance_ohm": 1.0},
    {"split_factor": 0.5},
    {"split_factor": 1.5, "split_factor_origin": "x"},
    {"return_paths": [ReturnPath("a", "other", 1.0)]},
])
def test_grid_current_rejects_inconsistent_inputs(kwargs):
    with pytest.raises(ValueError):
        grid_current(1000, 0.5, **kwargs)


def test_zero_impedance_path_is_rejected():
    with pytest.raises(ValueError):
        split_from_paths(1.0, [ReturnPath("bad", "other", 0j)])
    assert math.isfinite(split_from_paths(1.0, [ReturnPath("r", "other", 0.5j)])["split_factor"])
