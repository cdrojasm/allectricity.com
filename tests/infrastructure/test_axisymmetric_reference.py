"""Sanity checks for the independent finite-radius axisymmetric reference."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

MODULE = Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation" / "axisymmetric_fv.py"
SPEC = importlib.util.spec_from_file_location("axisymmetric_fv_reference", MODULE)
REFERENCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REFERENCE
SPEC.loader.exec_module(REFERENCE)


def test_axisymmetric_rod_solution_is_positive_and_finite():
    result = REFERENCE.solve_rod(REFERENCE.RodCase(cell_size_m=0.2))
    assert result["current_a_at_1v"] > 0
    assert result["resistance_ohm"] == pytest.approx(1 / result["current_a_at_1v"])


def test_axisymmetric_rod_resistance_scales_linearly_with_resistivity():
    case = REFERENCE.RodCase(cell_size_m=0.2)
    baseline = REFERENCE.solve_rod(case)["resistance_ohm"]
    doubled = REFERENCE.solve_rod(replace(case, resistivity_ohm_m=200.0))["resistance_ohm"]
    assert doubled == pytest.approx(2 * baseline, rel=1e-9)


def test_axisymmetric_rod_mesh_refinement_is_stable():
    coarse = REFERENCE.solve_rod(REFERENCE.RodCase(cell_size_m=0.1))["resistance_ohm"]
    fine = REFERENCE.solve_rod(REFERENCE.RodCase(cell_size_m=0.05))["resistance_ohm"]
    assert abs(fine / coarse - 1) < 0.01

