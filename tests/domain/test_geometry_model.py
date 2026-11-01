"""OPT-006 to OPT-009: costs, canonical graph, seeds and topological operators. No solver is involved."""

import random

import pytest
from src.domain.spat import geometry_cost, geometry_graph as gg, geometry_operators as ops, geometry_seeds as seeds
from src.domain.spat.optimizer_constraints import evaluate_optimizer_geometry
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.calculations.optimizer_evaluation import EvaluationContext, evaluate_design

DOMAIN = {
    "length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
    "areas": [{"type": "intervenible", "label": "lote", "polygon": [
        {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
    "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}],
}
CROSS = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "rods": [], "conductors": [
    {"start": {"x": 0, "y": 5}, "end": {"x": 20, "y": 5}}, {"start": {"x": 10, "y": 0}, "end": {"x": 10, "y": 20}}]}
RATES = {"currency": "COP", "assumptions": {"trench_width_m": 0.4},
         "rates": {"material.conductor.unspecified": "18000", "material.rod.unspecified": "25000", "excavation.trench": "60000",
                   "installation.conductor": "7000", "installation.rod": "40000", "installation.connection": "15000"}}


@pytest.fixture(scope="module")
def generated():
    return seeds.generate_seeds(DOMAIN, seed=7, count=8)


# ---- OPT-007: canonical representation -------------------------------------------------------------

def test_equivalent_drawings_of_one_network_hash_equal():
    redrawn = {**CROSS, "conductors": [
        {"start": {"x": 20, "y": 5}, "end": {"x": 10, "y": 5}},          # reversed half
        {"start": {"x": 0, "y": 5}, "end": {"x": 12, "y": 5}},            # overlapping half
        {"start": {"x": 10, "y": 20}, "end": {"x": 10, "y": 0}},
        {"start": {"x": 10, "y": 0}, "end": {"x": 10, "y": 8}},           # duplicate stretch
        {"start": {"x": 10.0004, "y": 8}, "end": {"x": 10, "y": 20}}]}    # sub-millimetre noise
    assert gg.geometry_hash(CROSS) == gg.geometry_hash(redrawn)
    regular = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "conductor_spacing_m": 10}
    drawn = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.5, "conductors": [
        {"start": {"x": x0, "y": y0}, "end": {"x": x1, "y": y1}} for x0, y0, x1, y1 in
        [(0, 0, 20, 0), (0, 10, 20, 10), (0, 20, 20, 20), (0, 0, 0, 20), (10, 0, 10, 20), (20, 0, 20, 20)]]}
    assert gg.geometry_hash(regular) == gg.geometry_hash(drawn)


def test_different_networks_materials_rods_and_sites_hash_differently():
    base = gg.geometry_hash(CROSS)
    moved = {**CROSS, "conductors": [CROSS["conductors"][0], {"start": {"x": 11, "y": 0}, "end": {"x": 11, "y": 20}}]}
    copper = {**CROSS, "conductors": [{**CROSS["conductors"][0], "material": "copper"}, CROSS["conductors"][1]]}
    with_rod = {**CROSS, "rods": [{"x": 10, "y": 5, "length_m": 2.4}]}
    shallower = {**CROSS, "burial_depth_m": 0.8}
    assert len({base, gg.geometry_hash(moved), gg.geometry_hash(copper), gg.geometry_hash(with_rod), gg.geometry_hash(shallower)}) == 5


def test_connectivity_intersections_and_stats():
    assert gg.intersections(CROSS) == [(10.0, 5.0)]
    graph = gg.from_geometry(CROSS)
    assert gg.is_connected(graph) and gg.stats(graph)["junctions"] == 1 and gg.stats(graph)["segments"] == 4
    apart = {**CROSS, "conductors": CROSS["conductors"][:1] + [{"start": {"x": 0, "y": 15}, "end": {"x": 20, "y": 15}}]}
    assert len(gg.components(gg.from_geometry(apart))) == 2 and not gg.is_connected(gg.from_geometry(apart))


def test_geometry_round_trips_through_the_graph():
    rodded = {**CROSS, "rods": [{"x": 10, "y": 5, "length_m": 3.0}]}
    again = gg.to_geometry(gg.normalize(gg.from_geometry(rodded)), rodded)
    assert gg.geometry_hash(again) == gg.geometry_hash(rodded)
    assert evaluate_optimizer_geometry(again)["status"] == "valid"


# ---- OPT-006: cost ---------------------------------------------------------------------------------

def test_cost_is_itemised_reproducible_and_matches_a_hand_calculation():
    geometry = {"length_m": 20, "width_m": 20, "burial_depth_m": 0.6, "conductor_spacing_m": 10, "rods_count": 4, "rod_length_m": 2.4}
    result = geometry_cost.evaluate_geometry_cost(geometry, RATES)
    assert result["status"] == "complete" and result["solver_evaluations_used"] == 0
    assert result["by_group"] == {"materials": "2400000.0", "excavation": "1728000.0", "installation": "1135000.0"}
    assert result["total"] == "5263000.0"
    assert result["takeoff"]["conductor_length_total_m"] == 120.0 and result["takeoff"]["connections"] == 9
    assert result == geometry_cost.evaluate_geometry_cost(geometry, RATES)
    assert sum(float(line["amount"]) for line in result["lines"]) == pytest.approx(float(result["total"]))


def test_missing_rates_or_assumptions_leave_the_cost_incomplete_instead_of_guessing():
    no_rod_rate = {**RATES, "rates": {k: v for k, v in RATES["rates"].items() if k != "installation.rod"}}
    rodded = {**CROSS, "rods": [{"x": 10, "y": 5, "length_m": 3.0}]}
    incomplete = geometry_cost.evaluate_geometry_cost(rodded, no_rod_rate)
    assert incomplete["status"] == "incomplete" and any("rod driving" in w for w in incomplete["warnings"])
    no_width = geometry_cost.evaluate_geometry_cost(CROSS, {**RATES, "assumptions": {}})
    assert no_width["status"] == "incomplete" and any("trench_width_m" in w for w in no_width["warnings"])
    assert geometry_cost.evaluate_geometry_cost(CROSS, no_rod_rate)["status"] == "complete"   # no rods, so no rod rate is needed


def test_every_valid_geometry_gets_a_complete_cost_and_L0_does_not_spend_the_budget(generated):
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError("cost must not reach the solver")
    exposure = safety_criteria.FaultExposure(0.5, 70, 3000, 0.1, 100)
    for seed in generated:
        assert geometry_cost.evaluate_geometry_cost(seed.geometry, RATES)["status"] == "complete"
    context = EvaluationContext()
    result = evaluate_design(design_parameters=None, base_geometry=generated[0].geometry, soil=100.0, injection_a=1000.0,
                             points=[], client=Forbidden(), exposure=exposure, standards=[], context=context,
                             level="L0", cost_rates=RATES)
    assert result["Cost"]["status"] == "complete" and context.evaluation_count == 0


# ---- OPT-008: seeds --------------------------------------------------------------------------------

def test_seeds_are_valid_single_network_diverse_and_deterministic(generated):
    assert len(generated) == 8 and len({s.graph_hash for s in generated}) == 8
    assert {s.family for s in generated} >= {"perimeter", "inscribed", "branched"}
    for s in generated:
        assert evaluate_optimizer_geometry(s.geometry)["status"] == "valid"
        assert s.metadata["components"] == 1
    assert seeds.diversity(generated) > 0.5
    again = seeds.generate_seeds(DOMAIN, seed=7, count=8)
    assert [s.graph_hash for s in again] == [s.graph_hash for s in generated]
    assert [s.graph_hash for s in seeds.generate_seeds(DOMAIN, seed=8, count=4)] != [s.graph_hash for s in generated[:4]]


def test_seeds_stay_inside_the_allowed_polygon_and_away_from_the_building(generated):
    from src.domain.spat.grid_geometry import _point_in_polygon, area_polygon
    polygon = area_polygon(DOMAIN["areas"][0])
    for s in generated:
        for c in s.geometry["conductors"]:
            for end in ("start", "end"):
                x, y = c[end]["x"], c[end]["y"]
                assert _point_in_polygon(x, y, polygon)
                assert not (7.5 < x < 12.5 and 16 < y < 20)


def test_a_users_initial_geometry_is_kept_first_and_normalized():
    drawn = {**DOMAIN, "conductors": [{"start": {"x": 4, "y": 4}, "end": {"x": 20, "y": 4}},
                                      {"start": {"x": 12, "y": 4}, "end": {"x": 12, "y": 12}}], "rods": []}
    produced = seeds.generate_seeds(DOMAIN, seed=1, count=4, initial=drawn)
    assert produced[0].family == "user" and produced[0].graph_hash == gg.geometry_hash(drawn)


# ---- OPT-009: operators ----------------------------------------------------------------------------

def _graph():
    return gg.from_geometry({**DOMAIN, "conductors": [
        {"start": {"x": 4, "y": 4}, "end": {"x": 28, "y": 4}}, {"start": {"x": 4, "y": 4}, "end": {"x": 4, "y": 20}},
        {"start": {"x": 28, "y": 4}, "end": {"x": 28, "y": 12}}, {"start": {"x": 4, "y": 12}, "end": {"x": 28, "y": 12}}], "rods": []})


@pytest.mark.parametrize("operator", [
    ops.SplitSegment((4.0, 4.0), (28.0, 4.0), (16.0, 4.0)),
    ops.AddSegment((28.0, 12.0), (24.0, 13.0)),
    ops.AddSegment((4.0, 12.0), (10.0, 14.0)),
    ops.RemoveSegment((4.0, 12.0), (28.0, 12.0)),
    ops.ConnectNodes((4.0, 4.0), (28.0, 12.0)),
    ops.AddRod((4.0, 4.0), 3.0),
    ops.ReconnectSegment((28.0, 4.0), (28.0, 12.0), "b", (4.0, 12.0)),
])
def test_every_operator_is_undone_by_its_inverse(operator):
    graph = _graph()
    applied = ops.apply_operator(graph, operator, ops.OperatorConstraints(), DOMAIN)
    assert gg.canonical_hash(applied.graph) != gg.canonical_hash(graph) or isinstance(operator, ops.SplitSegment)
    back = ops.apply_operator(applied.graph, applied.inverse, ops.OperatorConstraints(min_segment_m=0.0), DOMAIN)
    assert gg.canonical_hash(back.graph) == gg.canonical_hash(graph)


def test_rod_operators_add_move_and_remove():
    graph = _graph()
    with_rod = ops.apply_operator(graph, ops.AddRod((4.0, 4.0), 3.0), base=DOMAIN)
    moved = ops.apply_operator(with_rod.graph, ops.MoveRod((4.0, 4.0), (28.0, 4.0)), base=DOMAIN)
    assert moved.graph.rod_nodes() == {(28.0, 4.0)}
    gone = ops.apply_operator(moved.graph, ops.RemoveRod((28.0, 4.0)), base=DOMAIN)
    assert not gone.graph.rods and gg.canonical_hash(gone.graph) == gg.canonical_hash(graph)


@pytest.mark.parametrize("operator,kind", [
    (ops.AddSegment((28.0, 12.0), (40.0, 12.0)), "domain"),                    # leaves the allowed polygon
    (ops.AddSegment((4.0, 20.0), (14.0, 18.0)), "domain"),                     # runs through the building
    (ops.AddSegment((28.0, 4.0), (28.0, 8.0)), "missing"),                     # lies on a conductor that already exists
    (ops.SplitSegment((4.0, 4.0), (28.0, 4.0), (4.1, 4.0)), "constructive"),   # piece shorter than the minimum
    (ops.AddRod((4.0, 4.0), 30.0), "constructive"),                            # rod too long
    (ops.AddRod((9.0, 9.0), 3.0), "missing"),                                  # not a node
])
def test_operators_that_break_the_rules_are_rejected_with_their_kind(operator, kind):
    with pytest.raises(ops.OperatorRejected) as raised:
        ops.apply_operator(_graph(), operator, base=DOMAIN)
    assert raised.value.kind == kind


def test_removing_a_bridge_is_rejected_for_connectivity():
    chain = gg.from_geometry({**DOMAIN, "conductors": [
        {"start": {"x": 4, "y": 4}, "end": {"x": 14, "y": 4}}, {"start": {"x": 14, "y": 4}, "end": {"x": 24, "y": 4}},
        {"start": {"x": 24, "y": 4}, "end": {"x": 30, "y": 4}}], "rods": []})
    with pytest.raises(ops.OperatorRejected) as raised:
        ops.apply_operator(chain, ops.RemoveSegment((14.0, 4.0), (24.0, 4.0)), base=DOMAIN)
    assert raised.value.kind == "connectivity"
    # a leaf is not a bridge: removing it keeps one network
    assert ops.apply_operator(chain, ops.RemoveSegment((24.0, 4.0), (30.0, 4.0)), base=DOMAIN).graph.segments


def test_random_operator_sequences_stay_valid_and_are_fully_reversible(generated):
    for seed in generated[:3]:
        start = gg.from_geometry(seed.geometry)
        rng, graph, undo = random.Random(5), start, []
        for _ in range(25):
            try:
                applied = ops.apply_operator(graph, ops.random_operator(graph, rng), base=DOMAIN)
            except ops.OperatorRejected:
                continue
            graph = applied.graph
            ops.check(graph, base=DOMAIN)       # every intermediate graph is valid
            undo.append(applied.inverse)
        assert undo
        for inverse in reversed(undo):
            graph = ops.apply_operator(graph, inverse, ops.OperatorConstraints(min_segment_m=0.0), DOMAIN).graph
        assert gg.canonical_hash(graph) == gg.canonical_hash(start)
