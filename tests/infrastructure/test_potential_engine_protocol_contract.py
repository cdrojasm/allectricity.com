"""Python/C++ contract checks for SPAT-POTENTIAL-3 (SV-07)."""

from __future__ import annotations

import subprocess
import re
from pathlib import Path

import pytest

from src.infrastructure.calculations import potential_engine_client as python_contract
from src.infrastructure.calculations.potential_engine_client import (
    DEFAULT_QUADRATURE_TOLERANCE,
    ElectrodeSegment,
    HomogeneousSoil,
    LayerStackSoil,
    PotentialEngineClient,
    PotentialPoint,
    TwoLayerSoil,
    _soil_line,
)

SOILS = [
    (HomogeneousSoil(100.0), "homogeneous 100 1"),
    (TwoLayerSoil(300.0, 100.0, 2.0), "two-layer 300 100 2 1"),
    (LayerStackSoil(((300.0, 1.0), (60.0, 2.0), (1000.0, None))),
     "n-layer 3 300 1 60 2 1000 inf 10 1"),
]
DIAGNOSTIC_FIELDS = {
    "quadrature_tolerance", "quadrature_evaluations", "quadrature_refinements", "quadrature_max_depth",
    "quadrature_interactions", "quadrature_max_evaluations_per_interaction", "quadrature_converged",
    "interaction_degenerate_pairs", "interaction_self_pairs", "interaction_shared_endpoint_pairs",
    "interaction_t_junction_pairs", "interaction_crossing_pairs", "interaction_near_pairs",
    "interaction_separated_pairs", "interaction_near_interface_pairs", "matrix_reciprocal_entries_reused",
    "profile_kernel_setup_ms", "profile_matrix_assembly_ms", "profile_factorization_ms", "profile_solve_ms",
    "profile_condition_estimation_ms", "profile_point_evaluation_ms", "profile_request_total_ms",
    "profile_peak_rss_mib",
}


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip("potential engine is not built; run `make potential-engine`")
    return engine


def _raw_request(client, soil_line: str) -> dict:
    payload = "\n".join([
        "SPAT-POTENTIAL-3", soil_line, "s g grid 0 0 -0.5 4 0 -0.5 0.005",
        "1", "g 1 test", "1", "p 2 0 0", "END", "",
    ])
    process = subprocess.run([client.executable], input=payload, capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stdout
    return client._decode(process.stdout)


@pytest.mark.parametrize(("soil", "legacy_line"), SOILS, ids=["homogeneous", "two-layer", "n-layer"])
def test_client_and_engine_accept_each_soil_schema_and_keep_legacy_requests(client, soil, legacy_line):
    tolerance = 1.0e-8
    assert _soil_line(soil, 1, tolerance) == f"{legacy_line} {tolerance:.17g}"

    # The Python client emits the extended request and parses every required diagnostic.
    configured = PotentialEngineClient(client.executable, quadrature_tolerance=tolerance)
    result = configured.calculate(
        soil=soil,
        segments=[ElectrodeSegment("s", "g", "grid", (0, 0, -0.5), (4, 0, -0.5), 0.005)],
        injections_a={"g": 1.0},
        points=[PotentialPoint("p", (2, 0, 0))],
    )
    assert result["diagnostics"]["quadrature_tolerance"] == pytest.approx(tolerance)
    assert DIAGNOSTIC_FIELDS <= result["diagnostics"].keys()
    assert result["diagnostics"]["quadrature_converged"] == 1
    assert result["trace"]["solver_version"] == "3.6.0"

    # The C++ engine still accepts the original line without the optional tolerance.
    legacy = _raw_request(client, legacy_line)
    assert legacy["diagnostics"]["quadrature_tolerance"] == pytest.approx(DEFAULT_QUADRATURE_TOLERANCE)
    assert legacy["diagnostics"]["quadrature_converged"] == 1

    # Both request forms accept the same explicit tolerance and return a parseable response.
    explicit = _raw_request(client, f"{legacy_line} {tolerance:.17g}")
    assert explicit["diagnostics"]["quadrature_tolerance"] == pytest.approx(tolerance)
    assert explicit["metadata"]["protocol"] == "SPAT-POTENTIAL-3"


@pytest.mark.parametrize("tolerance", ["1e-13", "1e-3"])
def test_python_and_engine_reject_the_same_out_of_range_quadrature_tolerances(client, tolerance):
    with pytest.raises(ValueError, match="quadrature_tolerance"):
        PotentialEngineClient(quadrature_tolerance=float(tolerance))
    process = subprocess.run(
        [client.executable],
        input=("SPAT-POTENTIAL-3\nhomogeneous 100 1 " + tolerance +
               "\ns g grid 0 0 -0.5 4 0 -0.5 0.005\n1\ng 1 test\n0\nEND\n"),
        capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 2
    assert "quadrature tolerance must be between 1e-12 and 1e-4" in process.stdout


def test_engine_default_tolerance_matches_python_client(client):
    assert client.quadrature_tolerance == DEFAULT_QUADRATURE_TOLERANCE


def test_shared_numeric_limits_match_between_python_and_cpp():
    root = Path(__file__).resolve().parents[2]
    source = (root / "services/potential_engine/src/main.cpp").read_text()
    constants = {
        "MAX_POINTS": "kMaxPoints",
        "MAX_POINT_SEGMENT_WORK": "kMaxPointSegmentWork",
        "MAX_COORDINATE_M": "kMaxCoordinateM",
        "MAX_DEPTH_M": "kMaxDepthM",
        "MIN_RADIUS_M": "kMinRadiusM",
        "MAX_RADIUS_M": "kMaxRadiusM",
        "MIN_LENGTH_TO_RADIUS": "kMinLengthToRadius",
        "MAX_RESISTIVITY_OHM_M": "kMaxResistivityOhmM",
        "MAX_CURRENT_A": "kMaxCurrentA",
        "MIN_LAYER_THICKNESS_M": "kMinLayerThicknessM",
        "MAX_LAYERS": "kMaxLayers",
        "MAX_LAYER_CONTRAST": "kMaxLayerContrast",
        "MIN_KERNEL_DENSITY": "kMinKernelDensity",
        "MAX_KERNEL_DENSITY": "kMaxKernelDensity",
        "MAX_KERNEL_TERMS": "kMaxKernelTerms",
        "MAX_KERNEL_ERROR_BOUND": "kKernelMaxErrorBound",
        "MAX_IMAGE_TERMS": "kMaxImageTerms",
        "MAX_MATRIX_IMAGE_WORK": "kMaxMatrixImageWork",
        "MAX_POINT_IMAGE_WORK": "kMaxPointImageWork",
        "MIN_QUADRATURE_TOLERANCE": "kMinQuadratureTolerance",
        "MAX_QUADRATURE_TOLERANCE": "kMaxQuadratureTolerance",
    }
    for python_name, cpp_name in constants.items():
        match = re.search(rf"constexpr [^;=]+\b{cpp_name}\s*=\s*([^;]+);", source)
        assert match, f"C++ contract constant {cpp_name} not found"
        assert float(match.group(1)) == pytest.approx(float(getattr(python_contract, python_name))), python_name
    assert re.search(r"#define SPAT_MAX_SEGMENTS\s+4000", source)
    assert python_contract.MAX_SEGMENTS == 4000
