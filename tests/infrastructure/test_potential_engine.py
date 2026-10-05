import math
from pathlib import Path
import subprocess

import pytest
from src.infrastructure.calculations.potential_engine_client import (
    PROTOCOL,
    ElectrodeSegment,
    HomogeneousSoil,
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    Segmentation,
    TwoLayerSoil,
    discretize,
    graded_lengths,
    split_at_interface,
    validate_request,
)
from src.infrastructure.calculations.potential_engine_validation import (
    case_segments,
    case_soil,
    convergence,
    evaluate_case,
    load_cases,
    validate,
)

CASES_PATH = Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation" / "reference_cases.json"
CASES = load_cases(CASES_PATH)
CASE_IDS = [case["id"] for case in CASES["cases"]]


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


def rod(group="rod", x=0.0, segment_id=None, radius=0.008):
    return ElectrodeSegment(segment_id or f"{group}_{x}", group, "rod", (x, 0.0, 0.0), (x, 0.0, -3.0), radius)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_reference_case_within_tolerance(client, case_id):
    cases = {**CASES, "cases": [case for case in CASES["cases"] if case["id"] == case_id]}
    failures = [row for row in validate(client, cases) if not row["passed"] and not row["known_deviation"]]
    assert not failures, [(r["label"], r["value"], r["reference"], f"{100 * r['deviation_rel']:+.2f} %") for r in failures]


def test_reference_cases_record_provenance():
    for case in CASES["cases"]:
        for check in case["checks"]:
            if check.get("status") == "known-deviation":
                assert len(check.get("note", "")) > 80, "a known deviation must explain the investigation"
            source = CASES["sources"][check["source"]]
            assert source["citation"] and source["method"] and source["version"]
            assert 0 < check["tolerance_rel"] <= 0.05


def test_grid_discretization_converges(client):
    case = next(case for case in CASES["cases"] if case["id"] == "ieee80_annex_h_grid1")
    report = convergence(client, case, discretizations_m=[3.5, 1.75, 1.0], raster_spacings_m=[1.0, 0.5],
                         segmentation="uniform")
    changes = [row["change_rel"] for row in report["segment_sweep"][1:]]
    for quantity in range(len(case["checks"])):
        assert changes[-1][quantity] < changes[0][quantity], report["quantities"][quantity]
    resistance, touch, worst_touch, step = changes[-1][:4]
    assert resistance < 0.005 and touch < 0.01 and worst_touch < 0.01 and step < 0.02
    assert max(report["raster_sweep"][-1]["change_rel"]) < 0.01


def _corner_step(client, case, segments):
    s = math.sqrt(0.5)
    result = client.calculate(soil=case_soil(case), segments=segments, injections_a=case["injections_a"],
                              points=[PotentialPoint("c", (0, 0, 0)), PotentialPoint("d", (-s, -s, 0))])
    return result["potentials_v"]["c"] - result["potentials_v"]["d"]


def test_graded_segmentation_matches_converged_corner_step_with_fewer_segments(client):
    """Backlog acceptance: Grid 1 converged S1 (91.24 V) with < 500 segments; Grids 2-3 converge faster."""
    converged = {"ieee80_annex_h_grid1": 91.24, "ieee80_annex_h_grid2": 69.78, "ieee80_annex_h_grid3": 100.47}
    for case_id, reference in converged.items():
        case = next(case for case in CASES["cases"] if case["id"] == case_id)
        graded = case_segments(case, 1.0, "graded")
        uniform = case_segments(case, 0.7, "uniform")
        graded_error = abs(_corner_step(client, case, graded) / reference - 1)
        uniform_error = abs(_corner_step(client, case, uniform) / reference - 1)
        assert len(graded) < 0.6 * len(uniform), case_id
        assert graded_error < uniform_error / 2, (case_id, graded_error, uniform_error)
        if case_id == "ieee80_annex_h_grid1":
            assert len(graded) < 500 and graded_error < 0.001


def test_graded_lengths_grow_geometrically_and_cover_the_piece():
    lengths = graded_lengths(14.0, 7.0, 0.25, 1.0, 2.0)
    assert math.isclose(sum(lengths), 14.0) and lengths[0] == 0.25 and lengths[-1] == 1.0
    assert all(b / a <= 2.0 + 1e-9 for a, b in zip(lengths[:5], lengths[1:5]))
    assert max(lengths) <= 7.0
    assert graded_lengths(0.3, 7.0, 0.25, 0.25, 2.0) == [0.3]
    assert math.isclose(sum(graded_lengths(1.4, 7.0, 0.25, None, 2.0)), 1.4)
    assert graded_lengths(10.0, 3.0, None, None, 2.0) == [2.5] * 4


def test_discretize_refines_critical_nodes_only():
    z = -0.5
    # An L corner at the origin, a free end at (10, 0), a straight split at (5, 0) and a rod joint at (0, 10).
    pieces = [
        ElectrodeSegment("a", "g", "grid", (0, 0, z), (5, 0, z), 0.005),
        ElectrodeSegment("b", "g", "grid", (5, 0, z), (10, 0, z), 0.005),
        ElectrodeSegment("c", "g", "grid", (0, 0, z), (0, 10, z), 0.005),
        ElectrodeSegment("r", "g", "rod", (0, 10, z), (0, 10, z - 3), 0.008),
    ]
    segments = discretize(pieces, Segmentation.for_discretization("graded", 1.0))
    by_piece = {key: [s for s in segments if s.id.startswith(key + ".")] for key in "abcr"}
    length = lambda s: math.dist(s.start_m, s.end_m)  # noqa: E731
    assert math.isclose(length(by_piece["a"][0]), 0.25) and length(by_piece["a"][-1]) > 0.25  # corner, split
    assert math.isclose(length(by_piece["b"][-1]), 0.25) and length(by_piece["b"][0]) > 0.25  # split, free end
    assert math.isclose(length(by_piece["r"][0]), 0.25) and math.isclose(length(by_piece["r"][-1]), 0.25)
    assert math.isclose(sum(map(length, segments)), 23.0)
    assert [s.id for s in discretize(pieces[:1], Segmentation("uniform", 2.0))] == ["a.0", "a.1", "a.2"]


def test_graded_segmentation_keeps_a_node_at_the_soil_interface():
    case = next(case for case in CASES["cases"] if case["id"] == "ieee80_annex_h_grid3")
    segments = case_segments(case, 1.0, "graded")
    rod_ends = {round(z, 9) for s in segments if s.kind == "rod" for z in (s.start_m[2], s.end_m[2])}
    assert -6.096 in rod_ends
    assert all(max(s.start_m[2], s.end_m[2]) <= -6.096 + 1e-9 or min(s.start_m[2], s.end_m[2]) >= -6.096 - 1e-9
               for s in segments)
    assert min(math.dist(s.start_m, s.end_m) / s.radius_m for s in segments) >= 5


def test_result_carries_diagnostics_and_trace(client):
    result = client.calculate(
        soil_resistivity_ohm_m=100, segments=[rod("a"), rod("b", x=10)],
        injections_a={"a": 10.0}, points=[PotentialPoint("p", (5, 0, 0))],
        injection_origins={"a": "fault:bus-1"},
    )
    diagnostics = result["diagnostics"]
    assert diagnostics["backward_error"] < 1e-12
    assert diagnostics["max_relative_balance_error"] < 1e-12
    assert 1 <= diagnostics["condition_1norm_estimate"] < 1e6
    assert 0 < diagnostics["pivot_ratio"] <= 1
    assert result["groups"]["b"]["resistance_to_remote_earth_ohm"] is None
    assert abs(result["groups"]["b"]["current_balance_error_a"]) < 1e-12
    assert result["groups"]["a"]["injection_origin"] == "fault:bus-1"
    trace = result["trace"]
    assert trace["protocol"] == PROTOCOL and trace["solver_version"]
    assert "homogeneous" in trace["assumptions"] and "resistivity=ohm_m" in trace["units"]
    assert len(trace["request_sha256"]) == 64 and trace["engine_sha256"]
    assert trace["injections"] == [{"group": "a", "current_a": 10.0, "origin": "fault:bus-1"}]
    assert [s["id"] for s in trace["segments"]] == ["a_0.0", "b_10"]


def test_zero_injection_is_flagged(client):
    result = client.calculate(soil_resistivity_ohm_m=100, segments=[rod()], injections_a={}, points=[])
    assert [w["code"] for w in result["warnings"]] == ["no-injection"]


def test_currents_balance_and_potentials_are_linear(client):
    case = next(case for case in CASES["cases"] if case["id"] == "two_rods_coupled_groups")
    segments = case_segments(case)
    one = client.calculate(soil_resistivity_ohm_m=100, segments=segments, injections_a={"rod_a": 1.0}, points=[])
    two = client.calculate(soil_resistivity_ohm_m=100, segments=segments, injections_a={"rod_b": 1.0}, points=[])
    assert math.isclose(one["groups"]["rod_b"]["potential_v"], two["groups"]["rod_a"]["potential_v"], rel_tol=1e-6)
    assert math.isclose(sum(one["segment_currents_a"].values()), 1.0, rel_tol=1e-12)
    both = evaluate_case(client, case)["values"]
    expected_a = one["groups"]["rod_a"]["potential_v"] - 0.5 * two["groups"]["rod_a"]["potential_v"]
    assert math.isclose(both[0], expected_a, rel_tol=1e-9)


@pytest.mark.parametrize(("segments", "injections", "points", "message"), [
    ([rod(), rod(segment_id="copy")], {"rod": 1}, [], "duplicate segment geometry"),
    ([rod(), rod(segment_id="rod_0.0")], {"rod": 1}, [], "duplicate segment id"),
    ([rod("a"), ElectrodeSegment("b", "b", "grid", (-1, 0, -1), (1, 0, -1), 0.005)], {"a": 1}, [], "different groups"),
    ([ElectrodeSegment("s", "g", "grid", (0, 0, 0), (5, 0, 0), 0.005)], {"g": 1}, [], "surface"),
    ([ElectrodeSegment("s", "g", "grid", (0, 0, -1), (0.02, 0, -1), 0.005)], {"g": 1}, [], "5 radii"),
    ([rod(radius=0.6)], {"rod": 1}, [], "radius"),
    ([rod()], {"rod": math.inf}, [], "finite"),
    ([rod()], {"other": 1}, [], "no electrode segments"),
    ([rod()], {"rod": 1}, [PotentialPoint("p", (0, 0, -1))], "above z=0"),
])
def test_invalid_requests_are_rejected_before_running(segments, injections, points, message):
    with pytest.raises(ValueError, match=message):
        validate_request(100, segments, injections, points)


def test_soil_resistivity_must_be_positive():
    with pytest.raises(ValueError, match="resistivity"):
        validate_request(0, [rod()], {"rod": 1}, [])


@pytest.mark.parametrize(("rows", "message"), [
    (["a g rod 0 0 0 0 0 -3 0.008", "b g rod 0 0 -3 0 0 0 0.008"], "duplicate segment geometry"),
    (["a g rod 0 0 0 0 0 -3 0.008", "b h rod 0 0 -1 0 0 -2 0.008"], "overlapping collinear"),
    (["a g rod 0 0 0 0 0 -3 0.008", "b h grid -1 0 -1 1 0 -1 0.005"], "different groups"),
])
def test_engine_rejects_invalid_geometry(client, rows, message):
    payload = "\n".join([PROTOCOL, f"homogeneous 100 {len(rows)}", *rows, "1", "g 1 test", "0", "END", ""])
    done = subprocess.run([client.executable], input=payload, capture_output=True, text=True)
    assert done.returncode == 2
    assert done.stdout.startswith(f"{PROTOCOL}\tERROR\t") and message in done.stdout


def test_timeout_is_enforced(client):
    slow = PotentialEngineClient(client.executable, timeout_s=1e-4)
    case = next(case for case in CASES["cases"] if case["id"] == "ieee80_annex_h_grid1")
    with pytest.raises(PotentialEngineError, match="time limit"):
        slow.calculate(soil_resistivity_ohm_m=140, segments=case_segments(case), injections_a={"grid": 1}, points=[])


def rod_segments(top=0.0, bottom=-3.0, pieces=12, group="g", x=0.0):
    return [ElectrodeSegment(f"{group}{k}", group, "rod", (x, 0.0, top + (bottom - top) * k / pieces),
                             (x, 0.0, top + (bottom - top) * (k + 1) / pieces), 0.008) for k in range(pieces)]


def resistance(client, soil, segments, group="g"):
    result = client.calculate(soil=soil, segments=segments, injections_a={group: 1.0}, points=[])
    return result["groups"][group]["resistance_to_remote_earth_ohm"]


def test_two_layer_limits_recover_homogeneous_soil(client):
    shallow, buried = rod_segments(), rod_segments(-0.5, -3.5)
    # A very thick upper layer behaves as homogeneous rho1; a very thin one as homogeneous rho2.
    assert math.isclose(resistance(client, TwoLayerSoil(300, 100, 1000), shallow),
                        resistance(client, HomogeneousSoil(300), shallow), rel_tol=1e-3)
    assert math.isclose(resistance(client, TwoLayerSoil(300, 100, 0.01), buried),
                        resistance(client, HomogeneousSoil(100), buried), rel_tol=1e-3)


def test_equal_layers_reproduce_homogeneous_result_exactly(client):
    segments = rod_segments()
    homogeneous = client.calculate(soil=HomogeneousSoil(140), segments=segments, injections_a={"g": 1}, points=[])
    equal = client.calculate(soil=TwoLayerSoil(140, 140, 2), segments=segments, injections_a={"g": 1}, points=[])
    assert equal["segment_currents_a"] == homogeneous["segment_currents_a"]
    assert [w["code"] for w in equal["warnings"]] == ["equal-layers"]


def test_two_layer_result_reports_series_and_soil_trace(client):
    result = client.calculate(soil=TwoLayerSoil(300, 100, 1.3), segments=rod_segments(),
                              injections_a={"g": 1}, points=[PotentialPoint("p", (2, 0, 0))])
    assert 1 <= result["diagnostics"]["image_terms"] <= 2000
    assert 0 < result["diagnostics"]["image_series_tail_bound"] <= 1e-7
    assert result["trace"]["soil"] == {"model": "two-layer", "upper_resistivity_ohm_m": 300,
                                       "lower_resistivity_ohm_m": 100, "upper_thickness_m": 1.3}
    assert result["trace"]["soil_reflection_coefficient"] == "-0.5"
    assert "two-layer" in result["trace"]["assumptions"]
    # The rod crosses the interface at 1.3 m: the client split the segment that straddled it.
    assert {"g5.u", "g5.l"} <= set(result["segment_currents_a"])


def test_two_layer_transfer_potential_is_reciprocal(client):
    segments = rod_segments(group="a") + rod_segments(-0.5, -5.0, 9, group="b", x=7.0)
    soil = TwoLayerSoil(100, 400, 2.0)
    one = client.calculate(soil=soil, segments=segments, injections_a={"a": 1.0}, points=[])
    two = client.calculate(soil=soil, segments=segments, injections_a={"b": 1.0}, points=[])
    assert math.isclose(one["groups"]["b"]["potential_v"], two["groups"]["a"]["potential_v"], rel_tol=1e-4)


def test_resistance_varies_continuously_with_layer_thickness(client):
    values = [resistance(client, TwoLayerSoil(300, 100, h), rod_segments()) for h in (2.95, 3.0, 3.05)]
    assert values[0] < values[1] < values[2] and values[2] - values[0] < 0.1 * values[1]


def test_split_at_interface_cuts_straddling_segments():
    soil = TwoLayerSoil(300, 100, 1.0)
    parts = split_at_interface([ElectrodeSegment("r", "g", "rod", (0, 0, -0.5), (0, 0, -2.0), 0.008)], soil)
    assert [(p.id, p.start_m[2], p.end_m[2]) for p in parts] == [("r.u", -0.5, -1.0), ("r.l", -1.0, -2.0)]
    with pytest.raises(ValueError, match="shorter than 5 radii"):
        split_at_interface([ElectrodeSegment("r", "g", "rod", (0, 0, -0.98), (0, 0, -2.0), 0.008)], soil)


@pytest.mark.parametrize(("soil", "message"), [
    (TwoLayerSoil(300, 100, 0.001), "thickness"),
    (TwoLayerSoil(300, -1, 2), "resistivity"),
])
def test_invalid_two_layer_soil_is_rejected(soil, message):
    with pytest.raises(ValueError, match=message):
        validate_request(soil, rod_segments(), {"g": 1}, [])


def test_segment_crossing_interface_is_rejected_without_split():
    crossing = [ElectrodeSegment("r", "g", "rod", (0, 0, 0), (0, 0, -3), 0.008)]
    with pytest.raises(ValueError, match="crosses the soil interface"):
        validate_request(TwoLayerSoil(300, 100, 1.0), crossing, {"g": 1}, [])


@pytest.mark.parametrize(("soil_line", "rows", "message"), [
    ("two-layer 300 100 1 1", ["a g rod 0 0 0 0 0 -3 0.008"], "crosses the soil interface"),
    ("two-layer 1 1000000 5 1", ["a g rod 0 0 0 0 0 -3 0.008"], "contrast is too high"),
    ("layered 300 1", ["a g rod 0 0 0 0 0 -3 0.008"], "soil line must be"),
])
def test_engine_rejects_invalid_two_layer_requests(client, soil_line, rows, message):
    payload = "\n".join([PROTOCOL, soil_line, *rows, "1", "g 1 test", "0", "END", ""])
    done = subprocess.run([client.executable], input=payload, capture_output=True, text=True)
    assert done.returncode == 2 and message in done.stdout
