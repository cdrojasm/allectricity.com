"""Singularity regression suite for the potential engine (SV-03, SV-04).

Every case is a few explicit segments whose pair interactions are known situations (self, shared end,
T-junction, crossing, near, separated, near a soil interface). The engine is compared with an
independent Galerkin reference (`galerkin_reference`) on the group resistance and the segment
currents.

Two thresholds per case:

- ``GATE``: the accuracy the engine has today, with margin. Failing it is a regression.
- ``TARGET``: the accuracy SV-05 (adaptive near-field quadrature) must reach. Cases above it are
  listed in ``ABOVE_TARGET``; the test is a ratchet in both directions, so improving the engine makes
  it fail until the case is removed from the set and its gate tightened.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from src.infrastructure.calculations.interaction_classifier import Interaction, classify, classify_all
from src.infrastructure.calculations.potential_engine_client import (
    ElectrodeSegment,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    TwoLayerSoil,
)

from tests.infrastructure import galerkin_reference as reference
from tests.infrastructure.singularity_cases import Case, all_cases, homogeneous_cases

TARGET = 1.0e-5  # relative error in R, and absolute error of a segment current per ampere injected

# Accuracy of the current engine (relative error in R, absolute error in segment currents per A),
# set at about three times the measurement of 2026-10-16. Cases not listed use DEFAULT_GATE.
DEFAULT_GATE = (1.0e-6, 1.0e-6)
GATE = {
    "collinear_touching": (8.0e-4, 5.0e-4),
    "perpendicular_corner": (7.0e-6, 5.0e-6),
    "horizontal_rod_t_junction": (3.0e-4, 2.0e-4),
    "crossing_same_depth": (9.0e-4, 1.0e-6),
    "crossing_5cm_apart": (3.0e-4, 1.0e-6),
    "parallel_3cm": (2.0e-4, 1.0e-6),
    "parallel_6_radii": (2.0e-4, 1.0e-6),
    "short_next_to_long": (5.0e-4, 2.0e-5),
    "minimum_length_stub": (5.0e-4, 2.0e-6),
    "buried_near_surface_2cm": (6.0e-5, 1.0e-6),
}
NEAR_INTERFACE_GATE = (1.2e-4, 1.0e-6)  # a wire 3 % of the layer thickness from the interface

# Cases whose current error is above TARGET (ratchet, see module docstring).
ABOVE_TARGET: set[str] = set()

CASES = all_cases()
IDS = [case.name for case in CASES]


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def engine_soil(case: Case, n_layer: bool = False):
    kind, *values = case.engine_soil
    if kind == "homogeneous":
        return HomogeneousSoil(values[0])
    rho1, rho2, h = values
    return LayerStackSoil(((rho1, h), (rho2, None))) if n_layer else TwoLayerSoil(rho1, rho2, h)


def solve_engine(client, case: Case, n_layer: bool = False) -> tuple[float, np.ndarray]:
    segments = [ElectrodeSegment(f"s{i}", "g", "grid", s.a, s.b, s.radius) for i, s in enumerate(case.segments)]
    result = client.calculate(segments=segments, injections_a={"g": 1.0}, points=[], soil=engine_soil(case, n_layer))
    ordered = [result["segment_currents_a"][s["id"]] for s in result["trace"]["segments"]]
    return result["groups"]["g"]["potential_v"], np.array(ordered)


_reference_cache: dict[str, reference.Solution] = {}


def solve_reference(case: Case) -> reference.Solution:
    if case.name not in _reference_cache:
        _reference_cache[case.name] = reference.solve_group(list(case.segments), case.ref_soil)
    return _reference_cache[case.name]


def gate(case: Case) -> tuple[float, float]:
    if "3pct" in case.name:
        return NEAR_INTERFACE_GATE
    return GATE.get(case.name, DEFAULT_GATE)


def errors(client, case: Case, n_layer: bool = False) -> tuple[float, float]:
    truth = solve_reference(case)
    resistance, currents = solve_engine(client, case, n_layer)
    assert len(currents) == len(truth.currents_a), "the case must not need splitting at an interface"
    return abs(resistance / truth.resistance_ohm - 1.0), float(np.max(np.abs(currents - truth.currents_a)))


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_engine_stays_within_its_current_accuracy(client, case):
    error_r, error_i = errors(client, case)
    gate_r, gate_i = gate(case)
    assert error_r <= gate_r, f"R error {error_r:.2e} above the gate {gate_r:.1e}"
    assert error_i <= gate_i, f"current error {error_i:.2e} above the gate {gate_i:.1e}"


@pytest.mark.parametrize("case", [c for c in CASES if c.engine_soil[0] == "two-layer"],
                         ids=lambda c: c.name)
def test_n_layer_kernel_agrees_with_the_two_layer_reference(client, case):
    error_r, error_i = errors(client, case, n_layer=True)
    gate_r, gate_i = gate(case)
    assert error_r <= max(gate_r, 1.0e-6) and error_i <= max(gate_i, 1.0e-6)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_target_accuracy_ratchet(client, case):
    error_r, error_i = errors(client, case)
    meets = error_r <= TARGET and error_i <= TARGET
    if case.name in ABOVE_TARGET:
        assert not meets, f"{case.name} now meets the target; remove it from ABOVE_TARGET and tighten its gate"
    else:
        assert meets, f"{case.name} no longer meets the target (R {error_r:.2e}, I {error_i:.2e})"


def test_quadrature_tolerance_is_configurable_and_diagnostics_are_reported():
    case = next(c for c in CASES if c.name == "crossing_same_depth")
    results = []
    for tolerance in (1.0e-6, 1.0e-9, 1.0e-11):
        engine = PotentialEngineClient(quadrature_tolerance=tolerance)
        resistance, _ = solve_engine(engine, case)
        results.append((resistance, engine))
        diagnostics = engine.calculate(
            segments=[ElectrodeSegment(f"s{i}", "g", "grid", s.a, s.b, s.radius)
                      for i, s in enumerate(case.segments)],
            injections_a={"g": 1.0}, points=[], soil=engine_soil(case),
        )["diagnostics"]
        assert diagnostics["quadrature_tolerance"] == pytest.approx(tolerance)
        assert diagnostics["quadrature_converged"] == 1
        assert diagnostics["quadrature_evaluations"] > 0
        assert diagnostics["quadrature_interactions"] > 0
        assert diagnostics["quadrature_max_evaluations_per_interaction"] > 0
        assert diagnostics["quadrature_max_depth"] <= 16
    assert results[2][0] == pytest.approx(results[1][0], rel=1e-8)


@pytest.mark.parametrize("tolerance", [0.0, 1.0e-13, 1.0e-3, float("nan")])
def test_quadrature_tolerance_rejects_values_outside_supported_range(tolerance):
    with pytest.raises(ValueError, match="quadrature_tolerance"):
        PotentialEngineClient(quadrature_tolerance=tolerance)


def test_collinear_halves_reproduce_the_single_segment_without_any_reference(client):
    """Equal currents on two collinear halves are the same charge distribution as one segment, so R
    must match exactly. This check needs no reference solver."""
    cases = {c.name: c for c in homogeneous_cases()}
    whole = solve_engine(client, cases["single_segment"])[0]
    halves, currents = solve_engine(client, cases["collinear_touching"])
    assert currents == pytest.approx([0.5, 0.5], abs=gate(cases["collinear_touching"])[1])
    assert abs(halves / whole - 1.0) <= gate(cases["collinear_touching"])[0]


def test_reference_inner_closed_form_matches_numerical_quadrature():
    """The only analytic piece of the reference (line integral of the reduced kernel) against QUADPACK."""
    from scipy.integrate import quad

    a, b, p, radius = np.array([0.0, 0.0, -1.0]), np.array([3.0, 1.0, -2.0]), np.array([1.2, 0.4, -1.3]), 0.01
    d = b - a
    numeric, _ = quad(lambda v: 1.0 / np.sqrt(np.sum((p - (a + d * v)) ** 2) + radius**2) * np.linalg.norm(d),
                      0.0, 1.0, epsabs=0.0, epsrel=1e-13, points=[0.4])
    assert reference.line_integral(p, a, b, radius) == pytest.approx(numeric, rel=1e-11)


# ---- SV-03: classification ------------------------------------------------------------------

def pair(case: Case, interfaces=()):
    segs = [(s.a, s.b, s.radius) for s in case.segments]
    return classify(segs[0], segs[-1], same=len(segs) == 1, interfaces=interfaces)


@pytest.mark.parametrize("case", homogeneous_cases(), ids=lambda c: c.name)
def test_each_case_is_classified_in_the_category_it_was_built_for(case):
    assert pair(case).kind.value == case.category


def test_suite_covers_every_interaction_category():
    seen = {pair(case).kind for case in homogeneous_cases()}
    assert seen == set(Interaction) - {Interaction.DEGENERATE}
    assert classify(((0, 0, -1), (0.0001, 0, -1), 0.005), ((1, 0, -1), (2, 0, -1), 0.005)).kind is Interaction.DEGENERATE
    assert classify(((0, 0, -1), (float("nan"), 0, -1), 0.005), ((1, 0, -1), (2, 0, -1), 0.005)).kind \
        is Interaction.DEGENERATE


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_engine_interaction_diagnostics_match_python_classifier(client, case):
    segments = [ElectrodeSegment(f"s{i}", "g", "grid", s.a, s.b, s.radius) for i, s in enumerate(case.segments)]
    soil = engine_soil(case)
    result = client.calculate(segments=segments, injections_a={"g": 1.0}, points=[], soil=soil)
    interfaces = (soil.upper_thickness_m,) if isinstance(soil, TwoLayerSoil) else ()
    expected = classify_all([(s.a, s.b, s.radius) for s in case.segments], interfaces)
    for kind in Interaction:
        assert result["diagnostics"][f"interaction_{kind.value}_pairs"] == expected[kind.value], case.name
    assert result["diagnostics"]["interaction_near_interface_pairs"] == expected["near_interface"], case.name


def test_wires_close_to_an_interface_are_flagged_and_mid_layer_wires_are_not():
    for case in CASES:
        if case.engine_soil[0] != "two-layer":
            continue
        interface = case.engine_soil[3]
        flagged = classify_all([(s.a, s.b, s.radius) for s in case.segments], [interface])["near_interface"] > 0
        assert flagged == ("3pct" in case.name or "rod_across" in case.name), case.name


def test_classification_is_symmetric_and_invariant_to_rigid_motion_and_scale():
    segs = [(s.a, s.b, s.radius) for case in homogeneous_cases() for s in case.segments]
    angle, shift, scale = 0.7, np.array([13.0, -4.0, 0.0]), 3.0
    rot = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])

    def move(s):
        a, b, r = s
        return (tuple(scale * (rot @ np.array(a) + shift)), tuple(scale * (rot @ np.array(b) + shift)), r * scale)

    for i, first in enumerate(segs):
        for second in segs[i:]:
            same = first is second
            kind = classify(first, second, same=same).kind
            assert classify(second, first, same=same).kind is kind
            assert classify(move(first), move(second), same=same).kind is kind
