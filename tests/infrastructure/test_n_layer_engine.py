"""N-layer soil kernel of the C++ potential engine against an independent reference.

The reference (`layered_green_reference`) solves the full boundary-condition system per wavenumber
and integrates the Hankel transform numerically; it shares no code with the engine's generalized
reflection recursion or its exponential-image fit.
"""

import math
from pathlib import Path
import subprocess

import pytest
from src.infrastructure.calculations.potential_engine_client import (
    MAX_POINT_IMAGE_WORK,
    PROTOCOL,
    ElectrodeSegment,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialPoint,
    TwoLayerSoil,
    image_work,
    interface_depths,
    kernel_terms,
    point_batch_size,
    rectangular_grid_segments,
    split_at_interface,
    validate_request,
)
from src.infrastructure.calculations.potential_engine_validation import case_soil, evaluate_case, load_cases

from tests.infrastructure import layered_green_reference as reference

CASES = load_cases(Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation" / "reference_cases.json")

# Contrasts of both signs at every interface; thin layers in the 8-layer (maximum) stack.
SOILS = {
    "3-layer high-low-high": LayerStackSoil(((300.0, 1.0), (60.0, 2.0), (1000.0, None))),
    "3-layer low-high-low": LayerStackSoil(((50.0, 0.8), (800.0, 1.5), (100.0, None))),
    "4-layer": LayerStackSoil(((500.0, 0.6), (80.0, 1.2), (1500.0, 2.5), (40.0, None))),
    "8-layer": LayerStackSoil(((200.0, 0.4), (500.0, 0.6), (50.0, 0.5), (800.0, 0.5), (120.0, 1.0),
                               (2000.0, 1.0), (60.0, 4.0), (400.0, None))),
}


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def stack(soil: LayerStackSoil) -> tuple[list[float], list[float]]:
    return [rho for rho, _ in soil.layers], [h for _, h in soil.layers[:-1]]


def mid_depths(soil: LayerStackSoil) -> list[float]:
    tops = [0.0, *interface_depths(soil)]
    return [(top + bottom) / 2 for top, bottom in zip(tops, tops[1:])] + [tops[-1] + 1.5]


def wire(segment_id: str, depth: float, x: float = 0.0, length: float = 0.1, group: str | None = None):
    return ElectrodeSegment(segment_id, group or segment_id, "probe", (x, 0.0, -depth), (x + length, 0.0, -depth), 0.002)


@pytest.mark.parametrize("name", SOILS)
def test_surface_potential_matches_reference_for_a_source_in_every_layer(client, name):
    soil = SOILS[name]
    rhos, thicknesses = stack(soil)
    for layer, depth in enumerate(mid_depths(soil)):
        source = wire("s", depth)
        points = [PotentialPoint("near", (0.05, 2.0, 0.0)), PotentialPoint("far", (6.0, 3.0, 0.0))]
        result = client.calculate(soil=soil, segments=[source], injections_a={"s": 1.0}, points=points)
        assert result["diagnostics"]["kernel_error_bound"] < 1e-5
        for point in points:
            expected = reference.segment_to_point(rhos, thicknesses, source.start_m, source.end_m, point.xyz_m)
            assert result["potentials_v"][point.id] == pytest.approx(expected, rel=2e-5), (name, layer, point.id)


@pytest.mark.parametrize("name", ["3-layer high-low-high", "4-layer", "8-layer"])
def test_coupling_between_layers_matches_reference_and_is_reciprocal(client, name):
    soil = SOILS[name]
    rhos, thicknesses = stack(soil)
    depths = mid_depths(soil)
    pairs = [(0, len(depths) - 1), (1, len(depths) - 2), (1, 1)]
    for a_layer, b_layer in pairs:
        a, b = wire("a", depths[a_layer]), wire("b", depths[b_layer], x=2.5)
        forward = client.calculate(soil=soil, segments=[a, b], injections_a={"a": 1.0}, points=[])
        backward = client.calculate(soil=soil, segments=[a, b], injections_a={"b": 1.0}, points=[])
        transfer_ab = forward["groups"]["b"]["potential_v"]
        transfer_ba = backward["groups"]["a"]["potential_v"]
        assert transfer_ab == pytest.approx(transfer_ba, rel=1e-7), (a_layer, b_layer)
        expected = reference.segment_to_segment(rhos, thicknesses, (a.start_m, a.end_m), (b.start_m, b.end_m))
        assert transfer_ab == pytest.approx(expected, rel=2e-5), (a_layer, b_layer)


@pytest.mark.parametrize("name", ["3-layer low-high-low", "8-layer"])
def test_potential_is_continuous_across_every_interface(client, name):
    # By reciprocity, the surface potential of a source moved across an interface equals the
    # potential at the interface of a surface source: it must not jump where the kernel switches
    # between the formulas of the two layers.
    soil = SOILS[name]
    point = PotentialPoint("p", (1.5, 2.0, 0.0))
    for depth in interface_depths(soil):
        values = {}
        gaps = (1e-3, 1e-4, 1e-5)
        for gap in gaps:
            for side, offset in (("above", -gap), ("below", gap)):
                source = wire("s", depth + offset)
                result = client.calculate(soil=soil, segments=[source], injections_a={"s": 1.0}, points=[point])
                values[(gap, side)] = result["potentials_v"]["p"]
        jump = {gap: abs(values[(gap, "below")] - values[(gap, "above")]) / values[(gap, "above")] for gap in gaps}
        # A jump that shrinks in proportion to the gap is the finite slope of a continuous potential;
        # a discontinuity would leave a constant jump as the gap closes.
        assert jump[1e-4] < 0.15 * jump[1e-3] + 2e-7 and jump[1e-5] < 0.15 * jump[1e-4] + 2e-7, (depth, jump)
        assert jump[1e-5] < 5e-5, (depth, jump)


def test_two_layer_stack_matches_the_image_series_engine(client):
    # Same geometry, two routes: the exact two-layer image series and the n-layer kernel.
    segments = rectangular_grid_segments(length_m=20, width_m=16, conductor_spacing_m=4, burial_depth_m=0.5,
                                         conductor_radius_m=0.006, rods_count=8, rod_length_m=4.0,
                                         interface_depth_m=2.0, segmentation="graded", discretization_m=1.0)
    points = [PotentialPoint(f"p{i}", (-14 + 2.0 * i, 3.0, 0.0)) for i in range(15)]
    for upper, lower in ((300.0, 100.0), (100.0, 900.0)):
        series = client.calculate(soil=TwoLayerSoil(upper, lower, 2.0), segments=segments, injections_a={"grid": 1000.0},
                                  points=points)
        kernel = client.calculate(soil=LayerStackSoil(((upper, 2.0), (lower, None))), segments=segments,
                                  injections_a={"grid": 1000.0}, points=points)
        assert kernel["trace"]["soil_model"] == "n-layer" and series["trace"]["soil_model"] == "two-layer"
        assert kernel["groups"]["grid"]["potential_v"] == pytest.approx(series["groups"]["grid"]["potential_v"], rel=1e-6)
        for point in points:
            assert kernel["potentials_v"][point.id] == pytest.approx(series["potentials_v"][point.id], rel=1e-5)


@pytest.mark.parametrize("case_id", ["ieee80_annex_h_grid3", "ieee80_annex_h_grid6", "ieee80_annex_b_exhibit1"])
def test_two_layer_reference_cases_through_the_n_layer_kernel(client, case_id):
    # Regression against the published two-layer cases: the n-layer route must reproduce the values
    # the validated image-series route computes for every check.
    case = next(case for case in CASES["cases"] if case["id"] == case_id)
    series = case_soil(case)
    stacked = LayerStackSoil(((series.upper_resistivity_ohm_m, series.upper_thickness_m), (series.lower_resistivity_ohm_m, None)))
    expected = evaluate_case(client, case)["values"]
    values = evaluate_case(client, case, soil=stacked)["values"]
    for value, check, reference_value in zip(values, case["checks"], expected):
        assert value == pytest.approx(reference_value, rel=2e-5), check.get("label", check["quantity"])


def test_homogeneous_limits(client):
    # Electrodes inside the top metre, so every soil below sees the same segments (no interface cuts).
    rods = [ElectrodeSegment("r", "g", "rod", (0, 0, -0.3), (0, 0, -0.9), 0.008),
            ElectrodeSegment("w", "g", "grid", (0, 0, -0.3), (5, 0, -0.3), 0.006)]
    points = [PotentialPoint("p", (3.0, 2.0, 0.0))]
    homogeneous = client.calculate(soil=HomogeneousSoil(150.0), segments=rods, injections_a={"g": 10.0}, points=points)
    # One layer, or equal layers, are merged into exactly the homogeneous solution.
    for soil in (LayerStackSoil(((150.0, None),)), LayerStackSoil(((150.0, 1.0), (150.0, 2.0), (150.0, None)))):
        result = client.calculate(soil=soil, segments=rods, injections_a={"g": 10.0}, points=points)
        assert result["groups"] == homogeneous["groups"] and result["potentials_v"] == homogeneous["potentials_v"]
        assert result["trace"]["soil_model"] == "n-layer"
    merged = client.calculate(soil=LayerStackSoil(((150.0, 1.0), (150.0, 2.0), (150.0, None))), segments=rods,
                              injections_a={"g": 10.0}, points=points)
    assert [w["code"] for w in merged["warnings"]] == ["equal-layers"]
    # Almost equal resistivities go through the kernel and converge to the homogeneous result.
    nearly = client.calculate(soil=LayerStackSoil(((150.0, 1.0), (150.001, 2.0), (149.999, None))), segments=rods,
                              injections_a={"g": 10.0}, points=points)
    assert nearly["diagnostics"]["kernel_terms"] > 0
    assert nearly["groups"]["g"]["potential_v"] == pytest.approx(homogeneous["groups"]["g"]["potential_v"], rel=1e-5)
    assert nearly["potentials_v"]["p"] == pytest.approx(homogeneous["potentials_v"]["p"], rel=1e-5)
    # A deep stack under a thick top layer behaves as the top layer; under a thin one, as the second.
    deep = client.calculate(soil=LayerStackSoil(((150.0, 400.0), (30.0, 100.0), (900.0, None))), segments=rods,
                            injections_a={"g": 10.0}, points=points)
    assert deep["groups"]["g"]["potential_v"] == pytest.approx(homogeneous["groups"]["g"]["potential_v"], rel=1e-3)
    rods_low = [ElectrodeSegment(s.id, s.group, s.kind, *(tuple(c - (0, 0, 2.0)[k] for k, c in enumerate(e))
                                                          for e in (s.start_m, s.end_m)), s.radius_m) for s in rods]
    thin = client.calculate(soil=LayerStackSoil(((900.0, 0.01), (150.0, 400.0), (40.0, None))), segments=rods_low,
                            injections_a={"g": 10.0}, points=[])
    alone = client.calculate(soil=HomogeneousSoil(150.0), segments=rods_low, injections_a={"g": 10.0}, points=[])
    assert thin["groups"]["g"]["potential_v"] == pytest.approx(alone["groups"]["g"]["potential_v"], rel=5e-3)


def test_refining_the_kernel_converges(client):
    soil_layers = ((300.0, 1.0), (60.0, 2.0), (1000.0, None))
    segments = rectangular_grid_segments(length_m=12, width_m=12, conductor_spacing_m=4, burial_depth_m=0.5,
                                         conductor_radius_m=0.006, rods_count=4, rod_length_m=5.0,
                                         interface_depths_m=(1.0, 3.0), discretization_m=1.0)
    points = [PotentialPoint("corner", (6.5, 6.5, 0.0)), PotentialPoint("out", (12.0, 0.0, 0.0))]
    runs = {}
    for density in range(7, 13):
        result = client.calculate(soil=LayerStackSoil(soil_layers, kernel_density=density), segments=segments,
                                  injections_a={"grid": 1.0}, points=points)
        runs[density] = ((result["groups"]["grid"]["potential_v"], result["potentials_v"]["corner"],
                          result["potentials_v"]["out"]), result["diagnostics"]["kernel_error_bound"])
    bounds = [runs[d][1] for d in range(7, 11)]
    # The a-posteriori bound falls with every refinement until the fit reaches its noise floor ...
    assert bounds == sorted(bounds, reverse=True) and bounds[0] > 10 * bounds[-1] and bounds[-1] < 1e-6, bounds
    # ... and every level agrees with the finest one within the sum of both bounds.
    finest, finest_bound = runs[12]
    for density, (values, bound) in runs.items():
        change = max(abs(a / b - 1) for a, b in zip(values, finest))
        assert change <= bound + finest_bound and change < 2e-7, (density, change, bound)
    # The coarsest density cannot meet the error-bound acceptance limit for this stack.
    with pytest.raises(Exception, match="did not converge"):
        client.calculate(soil=LayerStackSoil(soil_layers, kernel_density=6), segments=segments,
                         injections_a={"grid": 1.0}, points=points)


def test_rods_crossing_several_interfaces_in_both_orientations(client):
    soil = SOILS["4-layer"]  # interfaces at 0.6, 1.8 and 4.3 m
    down = ElectrodeSegment("rod", "g", "rod", (0, 0, -0.3), (0, 0, -5.3), 0.008)
    up = ElectrodeSegment("rod", "g", "rod", (0, 0, -5.3), (0, 0, -0.3), 0.008)
    within = ElectrodeSegment("w", "g", "grid", (0.5, 0, -0.7), (3.0, 0, -0.7), 0.006)
    one = ElectrodeSegment("one", "g", "rod", (3.0, 0, -1.0), (3.0, 0, -2.5), 0.008)
    parts_down = split_at_interface([down, within, one], soil)
    parts_up = split_at_interface([up, within, one], soil)
    assert [p.id for p in parts_down] == ["rod.L1", "rod.L2", "rod.L3", "rod.L4", "w", "one.L2", "one.L3"]
    assert [p.id for p in parts_up] == ["rod.L4", "rod.L3", "rod.L2", "rod.L1", "w", "one.L2", "one.L3"]
    assert [round(p.start_m[2], 9) for p in parts_up[:4]] == [-5.3, -4.3, -1.8, -0.6]
    assert all(p.group == "g" and p.radius_m == 0.008 and p.kind == "rod" for p in parts_down[:4])
    points = [PotentialPoint("p", (1.0, 1.0, 0.0))]
    a = client.calculate(soil=soil, segments=[down, within, one], injections_a={"g": 100.0}, points=points)
    b = client.calculate(soil=soil, segments=[up, within, one], injections_a={"g": 100.0}, points=points)
    assert a["groups"]["g"]["potential_v"] == pytest.approx(b["groups"]["g"]["potential_v"], rel=1e-9)
    assert a["potentials_v"]["p"] == pytest.approx(b["potentials_v"]["p"], rel=1e-9)
    assert a["segment_currents_a"]["rod.L3"] == pytest.approx(b["segment_currents_a"]["rod.L3"], rel=1e-9)
    assert [s["id"] for s in a["trace"]["segments"]][:4] == ["rod.L1", "rod.L2", "rod.L3", "rod.L4"]
    assert sum(a["segment_currents_a"].values()) == pytest.approx(100.0, rel=1e-9)


def test_split_rejects_short_parts_and_duplicate_ids():
    soil = SOILS["4-layer"]
    with pytest.raises(ValueError, match="shorter than 5 radii"):
        split_at_interface([ElectrodeSegment("r", "g", "rod", (0, 0, -0.3), (0, 0, -1.82), 0.008)], soil)
    with pytest.raises(ValueError, match="already used"):
        split_at_interface([ElectrodeSegment("r", "g", "rod", (0, 0, -0.3), (0, 0, -1.0), 0.008),
                            ElectrodeSegment("r.L1", "g", "rod", (2, 0, -0.3), (2, 0, -0.5), 0.008)], soil)
    with pytest.raises(ValueError, match="within 5 radii"):
        rectangular_grid_segments(length_m=10, width_m=10, conductor_spacing_m=5, burial_depth_m=0.5,
                                  conductor_radius_m=0.008, rods_count=4, rod_length_m=1.31,
                                  interface_depths_m=interface_depths(soil))
    # Grid rods are cut at every interface with distinct ids before discretisation.
    rods = [s for s in rectangular_grid_segments(length_m=10, width_m=10, conductor_spacing_m=5, burial_depth_m=0.5,
                                                 conductor_radius_m=0.008, rods_count=1, rod_length_m=5.0,
                                                 interface_depths_m=interface_depths(soil)) if s.kind == "rod"]
    assert sorted({round(-s.end_m[2], 6) for s in rods}) == [0.6, 1.8, 4.3, 5.5]
    assert len({s.id for s in rods}) == len(rods)


@pytest.mark.parametrize("layers, message", [
    (((100.0, 1.0), (50.0, 3.0)), "half-space"),
    (((100.0, None), (50.0, None)), "thickness"),
    (((100.0, 0.001), (50.0, None)), "thickness"),
    (((100.0, 2000.0), (50.0, None)), "thickness"),
    (((0.0, 1.0), (50.0, None)), "resistivity"),
    (((-5.0, 1.0), (50.0, None)), "resistivity"),
    (((100.0, 1.0), (2e6, None)), "resistivity"),
    (((100.0, 1.0), (math.nan, None)), "resistivity"),
    (tuple((100.0 + i, 1.0) for i in range(8)) + ((50.0, None),), "between 1 and 8"),
    ((), "between 1 and 8"),
    (((1.0, 1.0), (20000.0, None)), "contrast"),
])
def test_invalid_layer_stacks_are_rejected(layers, message):
    with pytest.raises(ValueError, match=message):
        LayerStackSoil(layers)


@pytest.mark.parametrize("soil_line, message", [
    ("n-layer 2 100 1 50 3 10 1", "half-space"),
    ("n-layer 2 100 inf 50 inf 10 1", "only the bottom"),
    ("n-layer 2 100 0.001 50 inf 10 1", "thickness must be between"),
    ("n-layer 2 100 1 0 inf 10 1", "resistivity must be in"),
    ("n-layer 9 1 1 2 1 1 1 2 1 1 1 2 1 1 1 2 1 1 inf 10 1", "maximum 8"),
    ("n-layer 0 10 1", "layer count"),
    ("n-layer 3 100 1 50 inf 10 1", "n-layer soil line must be"),
    ("n-layer 2 1 1 20000 inf 10 1", "contrast"),
    ("n-layer 2 100 1 50 inf 5 1", "kernel density"),
    ("n-layer 3 300 1 60 2 1000 inf 6 1", "did not converge"),
    ("n-layer 8 10 0.01 1000 1000 20 1000 30 1000 40 1000 50 1000 60 1000 100000 inf 12 1", "images per coefficient"),
])
def test_engine_rejects_invalid_n_layer_requests(client, soil_line, message):
    payload = f"{PROTOCOL}\n{soil_line}\na g rod 0 0 -0.5 4 0 -0.5 0.008\n1\ng 1 user\n1\np 30 0 0\nEND\n"
    done = subprocess.run([client.executable], input=payload, capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and message in done.stdout, done.stdout


@pytest.mark.parametrize("rows, points, message", [
    (["a g rod 0 0 -0.5 0 0 -2.5 0.008"], ["p 3 0 0"], "crosses the soil interface at 1 m"),
    (["a g grid 0 0 -0.5 4 0 -0.5 0.008"], ["p 3 0 0.5"], "must lie on the surface"),
])
def test_engine_rejects_unsplit_segments_and_buried_points(client, rows, points, message):
    payload = (f"{PROTOCOL}\nn-layer 3 300 1 60 2 1000 inf 10 {len(rows)}\n" + "\n".join(rows) +
               f"\n1\ng 1 user\n{len(points)}\n" + "\n".join(points) + "\nEND\n")
    done = subprocess.run([client.executable], input=payload, capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and message in done.stdout, done.stdout


def test_client_mirrors_kernel_cost_and_limits(client):
    soil = SOILS["8-layer"]
    segments = split_at_interface(rectangular_grid_segments(
        length_m=10, width_m=10, conductor_spacing_m=5, burial_depth_m=0.5, conductor_radius_m=0.006,
        rods_count=4, rod_length_m=8.0, interface_depths_m=interface_depths(soil)), soil)
    points = [PotentialPoint(f"p{i}", (i * 0.5, 1.0, 0.0)) for i in range(40)]
    result = client.calculate(soil=soil, segments=segments, injections_a={"grid": 1.0}, points=points)
    matrix_work, point_work = image_work(soil, segments, points)
    assert result["diagnostics"]["matrix_image_work"] == matrix_work
    assert result["diagnostics"]["point_image_work"] == point_work
    assert result["diagnostics"]["kernel_terms"] == kernel_terms(soil)
    trace = result["trace"]
    assert trace["soil"]["model"] == "n-layer" and len(trace["soil"]["layers"]) == 8
    assert trace["soil_layer_count"] == "8" and trace["soil_layers_resistivity_ohm_m_thickness_m"].endswith("400:inf")
    assert "n-layer-generalized-reflection-recursion" in trace["method"] and trace["solver_version"] == "3.6.0"
    assert "max_error_bound=1e-4" in trace["kernel_limits"]
    # Surface points are batched so that every request respects the point image-work limit.
    many = [PotentialPoint(f"q{i}", (float(i % 100), float(i // 100), 0.0)) for i in range(20000)]
    big = segments * 1  # same geometry
    batch = point_batch_size(soil, big, many)
    assert image_work(soil, big, many[:batch])[1] <= MAX_POINT_IMAGE_WORK
    with pytest.raises(ValueError, match="images per coefficient"):
        validate_request(LayerStackSoil(((10.0, 0.01), *((1000.0, 1000.0),) * 6, (100000.0, None)), kernel_density=12),
                         [ElectrodeSegment("a", "g", "grid", (0, 0, -0.005), (1, 0, -0.005), 0.001)], {"g": 1.0}, [])
    with pytest.raises(ValueError, match="must lie on the surface"):
        validate_request(soil, segments, {"grid": 1.0}, [PotentialPoint("air", (0.0, 0.0, 1.0))])
