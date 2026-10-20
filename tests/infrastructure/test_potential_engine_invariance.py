"""Mathematical invariances of the potential engine (SV-02).

None of these needs a reference solver: each states that two different inputs describe the same
physical problem (or one a scaled copy of the other), so the results must agree to numerical noise.
They run on a small graded grid with rods, in homogeneous, two-layer and n-layer soil, so the
rods cross interfaces and the segments are split.

Complements `test_n_layer_engine.py`, which already covers equal layers, nearly equal layers, a deep
top layer and a thin layer.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from src.infrastructure.calculations.potential_engine_client import (
    ElectrodeSegment,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialPoint,
    TwoLayerSoil,
    rectangular_grid_segments,
)


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def grid(interface_depth_m: float | None = 2.0, interface_depths_m=None, radius_m: float = 0.006):
    return rectangular_grid_segments(
        length_m=12, width_m=8, conductor_spacing_m=4, burial_depth_m=0.5, conductor_radius_m=radius_m,
        rods_count=4, rod_length_m=4.0, interface_depth_m=interface_depth_m, interface_depths_m=interface_depths_m,
        segmentation="graded", discretization_m=1.0)


POINTS = [PotentialPoint(f"p{i}", (-3.0 + 2.5 * i, 1.7 + 0.4 * i, 0.0)) for i in range(8)]
CURRENT = 500.0

SOILS = {
    "homogeneous": HomogeneousSoil(120.0),
    "two-layer": TwoLayerSoil(300.0, 60.0, 2.0),
    "n-layer": LayerStackSoil(((250.0, 1.0), (40.0, 1.5), (800.0, None))),
}


def run(client, soil, segments, points=POINTS):
    result = client.calculate(soil=soil, segments=segments, injections_a={"grid": CURRENT}, points=points)
    potentials = np.array([result["potentials_v"][p.id] for p in points])
    currents = np.array([result["segment_currents_a"][s["id"]] for s in result["trace"]["segments"]])
    return result["groups"]["grid"]["potential_v"], potentials, currents


def baseline(client, name):
    soil = SOILS[name]
    interface = {"homogeneous": None, "two-layer": 2.0, "n-layer": 1.0}[name]
    return soil, grid(interface), run(client, soil, grid(interface))


def transformed(segments, fn):
    return [ElectrodeSegment(s.id, s.group, s.kind, fn(s.start_m), fn(s.end_m), s.radius_m) for s in segments]


@pytest.mark.parametrize("name", SOILS)
def test_resistivity_scaling_scales_potentials_and_keeps_currents(client, name):
    soil, segments, (r0, v0, i0) = baseline(client, name)
    factor = 3.7
    if isinstance(soil, HomogeneousSoil):
        scaled = HomogeneousSoil(soil.resistivity_ohm_m * factor)
    elif isinstance(soil, TwoLayerSoil):
        scaled = TwoLayerSoil(soil.upper_resistivity_ohm_m * factor, soil.lower_resistivity_ohm_m * factor,
                              soil.upper_thickness_m)
    else:
        scaled = LayerStackSoil(tuple((rho * factor, t) for rho, t in soil.layers))
    r1, v1, i1 = run(client, scaled, segments)
    # The n-layer kernel refits its images for each stack; 1e-7 is its fit noise, not a physical effect.
    assert r1 == pytest.approx(factor * r0, rel=1e-7)
    assert v1 == pytest.approx(factor * v0, rel=1e-7)
    assert i1 == pytest.approx(i0, rel=1e-7)


@pytest.mark.parametrize("name", SOILS)
@pytest.mark.parametrize("scale", [0.5, 2.0])
def test_geometric_scaling_scales_resistance_inversely(client, name, scale):
    """All lengths, radii, thicknesses and point coordinates times s: potentials divide by s."""
    soil, segments, (r0, v0, i0) = baseline(client, name)
    if isinstance(soil, TwoLayerSoil):
        scaled_soil = TwoLayerSoil(soil.upper_resistivity_ohm_m, soil.lower_resistivity_ohm_m,
                                   soil.upper_thickness_m * scale)
    elif isinstance(soil, LayerStackSoil):
        scaled_soil = LayerStackSoil(tuple((rho, None if t is None else t * scale) for rho, t in soil.layers))
    else:
        scaled_soil = soil
    scaled_segments = [ElectrodeSegment(s.id, s.group, s.kind, tuple(c * scale for c in s.start_m),
                                        tuple(c * scale for c in s.end_m), s.radius_m * scale) for s in segments]
    points = [PotentialPoint(p.id, tuple(c * scale for c in p.xyz_m)) for p in POINTS]
    r1, v1, i1 = run(client, scaled_soil, scaled_segments, points)
    assert r1 == pytest.approx(r0 / scale, rel=1e-6)
    assert v1 == pytest.approx(v0 / scale, rel=1e-6)
    assert i1 == pytest.approx(i0, rel=1e-6, abs=1e-9)


@pytest.mark.parametrize("name", SOILS)
def test_translation_and_rotation_about_the_vertical_axis_change_nothing(client, name):
    soil, segments, (r0, v0, i0) = baseline(client, name)
    angle, shift = math.radians(33.0), (41.0, -17.5)
    c, s = math.cos(angle), math.sin(angle)

    def move(p):
        return (c * p[0] - s * p[1] + shift[0], s * p[0] + c * p[1] + shift[1], p[2])

    points = [PotentialPoint(p.id, move(p.xyz_m)) for p in POINTS]
    r1, v1, i1 = run(client, soil, transformed(segments, move), points)
    # Homogeneous soil shows 6e-6: its near-field quadrature is the least isotropic (SV-05 target 1e-6).
    r_tolerance, v_tolerance = (2e-5, 1e-4) if name == "homogeneous" else (1e-6, 1e-6)
    assert r1 == pytest.approx(r0, rel=r_tolerance)
    assert v1 == pytest.approx(v0, rel=v_tolerance)
    assert i1 == pytest.approx(i0, rel=1e-3 if name == "homogeneous" else 1e-5, abs=1e-6)  # homogeneous: 2e-4


@pytest.mark.parametrize("name", SOILS)
def test_mirror_image_geometry_gives_the_same_resistance(client, name):
    soil, segments, (r0, v0, _) = baseline(client, name)

    def flip(p):
        return (-p[0], p[1], p[2])

    points = [PotentialPoint(p.id, flip(p.xyz_m)) for p in POINTS]
    r1, v1, _ = run(client, soil, transformed(segments, flip), points)
    assert r1 == pytest.approx(r0, rel=1e-6)
    assert v1 == pytest.approx(v0, rel=1e-6)


@pytest.mark.parametrize("name", SOILS)
def test_segment_direction_and_order_do_not_matter(client, name):
    soil, segments, (r0, v0, _) = baseline(client, name)
    reordered = [ElectrodeSegment(s.id, s.group, s.kind, s.end_m, s.start_m, s.radius_m) if i % 2 else s
                 for i, s in enumerate(reversed(segments))]
    r1, v1, _ = run(client, soil, reordered)
    # Reversing a segment changes which end the graded quadrature starts from: 2e-8 in R and 1.4e-6 in
    # the surface potentials in homogeneous soil, nothing visible in layered soil.
    assert r1 == pytest.approx(r0, rel=1e-7)
    assert v1 == pytest.approx(v0, rel=5e-6 if name == "homogeneous" else 1e-7)


def test_adjacent_identical_layers_merge_into_one(client):
    """Splitting a layer in two (same resistivity) must not change anything, wherever the cut falls,
    including through the rods and just under the grid plane."""
    segments = grid(None)
    merged = LayerStackSoil(((250.0, 3.0), (40.0, 1.5), (800.0, None)))
    base = run(client, merged, segments)
    for first in (0.51, 0.9, 2.2):
        split = LayerStackSoil(((250.0, first), (250.0, 3.0 - first), (40.0, 1.5), (800.0, None)))
        result = run(client, split, segments)
        assert result[0] == pytest.approx(base[0], rel=1e-9)
        assert result[1] == pytest.approx(base[1], rel=1e-9)


def test_a_vanishing_layer_disappears_monotonically(client):
    """A layer of thickness t inserted below 3 m converges to the stack without it as t -> 0.
    The thinnest layer the engine accepts is 0.01 m, so the rods use a 1.9 mm radius (5 radii)."""
    radius = 0.0019
    without = run(client, LayerStackSoil(((250.0, 3.0), (800.0, None))), grid(None, [3.0], radius))[0]
    errors = []
    for thickness in (0.5, 0.1, 0.03, 0.01):
        stack = LayerStackSoil(((250.0, 3.0), (20.0, thickness), (800.0, None)))
        segments = grid(None, [3.0, 3.0 + thickness], radius)
        errors.append(abs(run(client, stack, segments)[0] / without - 1.0))
    assert errors == sorted(errors, reverse=True), errors
    assert errors[-1] < 0.1 * errors[0]


@pytest.mark.parametrize("depth", [100.0, 400.0, 1000.0])
def test_a_very_deep_interface_recovers_the_half_space(client, depth):
    segments = grid(None)
    homogeneous = run(client, HomogeneousSoil(250.0), segments)[0]
    layered = run(client, LayerStackSoil(((250.0, depth), (30.0, None))), segments)[0]
    # The first reflection is about K*L/(2h); the bound tightens as the interface recedes.
    assert abs(layered / homogeneous - 1.0) < 3.0 * 12.0 / (2.0 * depth) * 0.9
