import math
from pathlib import Path
import subprocess

import pytest
from src.infrastructure.calculations.potential_engine_client import (
    PROTOCOL,
    ElectrodeSegment,
    PotentialEngineClient,
    PotentialEngineError,
    PotentialPoint,
    validate_request,
)
from src.infrastructure.calculations.potential_engine_validation import (
    case_segments,
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
    failures = [row for row in validate(client, cases) if not row["passed"]]
    assert not failures, [(r["label"], r["value"], r["reference"], f"{100 * r['deviation_rel']:+.2f} %") for r in failures]


def test_reference_cases_record_provenance():
    for case in CASES["cases"]:
        for check in case["checks"]:
            source = CASES["sources"][check["source"]]
            assert source["citation"] and source["method"] and source["version"]
            assert 0 < check["tolerance_rel"] <= 0.05


def test_grid_discretization_converges(client):
    case = next(case for case in CASES["cases"] if case["id"] == "ieee80_annex_h_grid1")
    report = convergence(client, case, discretizations_m=[3.5, 1.75, 1.0], raster_spacings_m=[1.0, 0.5])
    changes = [row["change_rel"] for row in report["segment_sweep"][1:]]
    for quantity in range(len(case["checks"])):
        assert changes[-1][quantity] < changes[0][quantity], report["quantities"][quantity]
    resistance, touch, worst_touch, step = changes[-1][:4]
    assert resistance < 0.005 and touch < 0.01 and worst_touch < 0.01 and step < 0.02
    assert max(report["raster_sweep"][-1]["change_rel"]) < 0.01


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
    payload = "\n".join([PROTOCOL, f"100 {len(rows)}", *rows, "1", "g 1 test", "0", "END", ""])
    done = subprocess.run([client.executable], input=payload, capture_output=True, text=True)
    assert done.returncode == 2
    assert done.stdout.startswith(f"{PROTOCOL}\tERROR\t") and message in done.stdout


def test_timeout_is_enforced(client):
    slow = PotentialEngineClient(client.executable, timeout_s=1e-4)
    case = next(case for case in CASES["cases"] if case["id"] == "ieee80_annex_h_grid1")
    with pytest.raises(PotentialEngineError, match="time limit"):
        slow.calculate(soil_resistivity_ohm_m=140, segments=case_segments(case), injections_a={"grid": 1}, points=[])
