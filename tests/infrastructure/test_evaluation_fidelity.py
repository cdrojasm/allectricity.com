from pathlib import Path

import pytest
from src.infrastructure.calculations import safety_criteria, solver_evaluation
from src.infrastructure.calculations.optimizer_evaluation import EvaluationContext, evaluate_design
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient

GEOMETRY = {"length_m": 30, "width_m": 30, "conductor_spacing_m": 5.0, "burial_depth_m": 0.5,
            "rods_count": 0, "rod_length_m": 2.4}
EXPOSURE = safety_criteria.FaultExposure(
    clearing_time_s=0.5, body_weight_kg=70, surface_resistivity_ohm_m=3000,
    surface_thickness_m=0.1, soil_resistivity_ohm_m=100)


@pytest.fixture(scope="module")
def client():
    engine = PotentialEngineClient()
    if not Path(engine.executable).is_file():
        pytest.skip(f"potential engine not built at {engine.executable}; run `make potential-engine`")
    return engine


class ForbiddenSolver:
    def __getattr__(self, name):
        raise AssertionError("L0 must not reach the solver")


def test_l1_values_are_lower_bounds_of_l2_and_faster_to_compute(client):
    kwargs = dict(geometry=GEOMETRY, soil=100.0, injection_a=1000.0, points=[], client=client)
    coarse = solver_evaluation.evaluate(level="L1", **kwargs)
    full = solver_evaluation.evaluate(**kwargs)
    assert coarse["fidelity"] == {"level": "L1", "values_are": "lower_bounds"}
    assert full["fidelity"]["level"] == "L2"
    for name in ("Vt_v", "Vs_v"):
        # Close on a regular grid. No upper bound against L2: both levels are sampled searches and
        # on drawn geometries L1 can find the higher Vt (see the 700-geometry study).
        assert coarse["quantities"][name] >= 0.9 * full["quantities"][name]
    # The system solved is identical, only the surface search differs.
    assert coarse["quantities"]["Rg_ohm"] == full["quantities"]["Rg_ohm"]
    assert coarse["quantities"]["GPR_v"] == full["quantities"]["GPR_v"]


def test_default_level_keeps_the_l2_fingerprint(client):
    kwargs = dict(geometry=GEOMETRY, soil=100.0, injection_a=1000.0, points=[], client=client)
    assert solver_evaluation.evaluate(**kwargs)["input_sha256"] == solver_evaluation.evaluate(level="L2", **kwargs)["input_sha256"]
    assert solver_evaluation.evaluate(level="L1", **kwargs)["input_sha256"] != solver_evaluation.evaluate(**kwargs)["input_sha256"]


def test_solver_rejects_levels_it_cannot_serve(client):
    for level in ("L0", "L3"):
        with pytest.raises(ValueError):
            solver_evaluation.evaluate(geometry=GEOMETRY, soil=100.0, injection_a=1.0, points=[], client=client, level=level)


def test_l0_checks_geometry_without_solver_or_budget():
    context = EvaluationContext()
    result = evaluate_design(
        design_parameters=None, base_geometry=GEOMETRY, soil=100.0, injection_a=1000.0, points=[],
        client=ForbiddenSolver(), exposure=EXPOSURE, standards=[], context=context, level="L0")
    assert result["Fidelity"]["level"] == "L0"
    assert result["OptimizerGeometryCheck"]["status"] == "valid"
    assert result["Feasible"] is None and result["Vs"] is None
    assert context.evaluation_count == 0


def test_l1_pass_is_not_certified_but_a_violation_is_conclusive(client):
    common = dict(design_parameters=None, base_geometry=GEOMETRY, soil=100.0, injection_a=1000.0,
                  points=[], client=client, standards=[safety_criteria.IEEE80_2013])
    easy = safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100)
    full = evaluate_design(exposure=easy, level="L2", **common)
    coarse = evaluate_design(exposure=easy, level="L1", **common)
    assert coarse["Fidelity"]["values_are"] == "lower_bounds"
    if full["Feasible"] is True:
        assert coarse["Feasible"] is None          # a pass on lower bounds proves nothing
    # A current large enough to violate the limits fails at L1 too, which is enough to prune.
    harsh = dict(common, injection_a=50000.0)
    assert evaluate_design(exposure=easy, level="L1", **harsh)["Feasible"] is False


# Two verticals 1 cm apart, crossed by a horizontal: valid on paper, but the horizontal is cut into
# a 1 cm piece between them, shorter than the 5 radii (2.6 cm) the thin-wire model needs.
THIN_PIECE = {
    "length_m": 10, "width_m": 10, "burial_depth_m": 0.5, "rods": [],
    "conductors": [
        {"start": {"x": 0, "y": 5}, "end": {"x": 10, "y": 5}},
        {"start": {"x": 5.0, "y": 0}, "end": {"x": 5.0, "y": 10}},
        {"start": {"x": 5.01, "y": 0}, "end": {"x": 5.01, "y": 10}},
    ],
}


@pytest.mark.parametrize("level", ["L0", "L1", "L2"])
def test_thin_wire_pieces_are_rejected_before_the_budget_and_the_solver(level):
    from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected, require_optimizer_geometry
    assert require_optimizer_geometry(THIN_PIECE)["status"] == "valid"      # the plan itself is fine
    context = EvaluationContext()
    with pytest.raises(OptimizerGeometryRejected) as raised:
        evaluate_design(design_parameters=None, base_geometry=THIN_PIECE, soil=100.0, injection_a=1000.0,
                        points=[], client=ForbiddenSolver(), exposure=EXPOSURE, standards=[],
                        context=context, level=level)
    violation = raised.value.report["violations"][0]
    assert violation["kind"] == "thin_wire" and violation["element"] == "conductor" and violation["index"] == 0
    assert violation["length_m"] < violation["minimum_m"]
    assert context.evaluation_count == 0


def test_regular_grids_and_junction_free_geometry_pass_the_discretization_check():
    assert solver_evaluation.discretization_violations(GEOMETRY, 100.0) == []
    two_layer = {"length_m": 10, "width_m": 10, "burial_depth_m": 0.5, "rods": [],
                 "conductors": [{"start": {"x": 0, "y": 5}, "end": {"x": 10, "y": 5}},
                                {"start": {"x": 5, "y": 0}, "end": {"x": 5, "y": 10}}]}
    assert solver_evaluation.discretization_violations(two_layer, 100.0) == []


def test_l2_plus_is_never_below_l1_or_l2(client):
    """OPT-002: the union search keeps every maximum either level found."""
    import random
    import sys
    validation = Path(__file__).resolve().parents[2] / "services" / "potential_engine" / "validation"
    sys.path.insert(0, str(validation))
    import free_geometry_generator as generator
    rng, checked = random.Random(11), 0
    for family in generator.FAMILIES:
        produced = generator.valid_geometry(rng, family)
        if not produced or solver_evaluation.discretization_violations(produced[0], 100.0):
            continue
        kwargs = dict(geometry=produced[0], soil=100.0, injection_a=1000.0, points=[], client=client)
        levels = {name: solver_evaluation.evaluate(level=name, **kwargs)["quantities"] for name in ("L1", "L2", "L2+")}
        for quantity in ("Vt_v", "Vs_v"):
            assert levels["L2+"][quantity] >= max(levels["L1"][quantity], levels["L2"][quantity]) * (1 - 1e-9), (family, quantity)
        checked += 1
    assert checked >= 4


@pytest.mark.parametrize("side,soil,vt,vs", [
    (20, 100.0, 577.9, 377.8),
    (40, 100.0, 229.6, 151.9),
])
def test_original_l2_values_are_unchanged(client, side, soil, vt, vs):
    """OPT-002 compatibility: values measured before L2+ and duplicate-free queries existed."""
    geometry = {**GEOMETRY, "length_m": side, "width_m": side}
    quantities = solver_evaluation.evaluate(geometry=geometry, soil=soil, injection_a=1000.0, points=[], client=client)["quantities"]
    assert quantities["Vt_v"] == pytest.approx(vt, rel=5e-4)
    assert quantities["Vs_v"] == pytest.approx(vs, rel=5e-4)


def test_l2_plus_fingerprint_differs_and_l2_keeps_its_own(client):
    kwargs = dict(geometry=GEOMETRY, soil=100.0, injection_a=1000.0, points=[], client=client)
    hashes = {level: solver_evaluation.evaluate(level=level, **kwargs)["input_sha256"] for level in ("L1", "L2", "L2+")}
    assert len(set(hashes.values())) == 3
    assert hashes["L2"] == solver_evaluation.evaluate(**kwargs)["input_sha256"]


def test_a_grid_wholly_inside_a_building_has_no_touch_area_and_is_rejected_before_the_solver():
    from src.domain.spat.optimizer_constraints import OptimizerGeometryRejected
    inside_building = {
        "length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "rods": [],
        "structures": [{"x": 10, "y": 10, "width": 12, "height": 12, "label": "edificio"}],
        "conductors": [{"start": {"x": 7, "y": 10}, "end": {"x": 13, "y": 10}},
                       {"start": {"x": 10, "y": 7}, "end": {"x": 10, "y": 13}}],
    }
    kinds = [v["kind"] for v in solver_evaluation.discretization_violations(inside_building, 100.0)]
    assert "no_touch_area" in kinds
    with pytest.raises(OptimizerGeometryRejected):
        evaluate_design(design_parameters=None, base_geometry=inside_building, soil=100.0, injection_a=1000.0,
                        points=[], client=ForbiddenSolver(), exposure=EXPOSURE, standards=[], level="L2+")
    assert solver_evaluation.discretization_violations(GEOMETRY, 100.0) == []
