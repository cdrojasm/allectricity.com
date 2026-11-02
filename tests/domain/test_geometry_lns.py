"""OPT-011: large-neighbourhood moves and adaptive operator selection."""

import random

import pytest
from src.domain.spat import geometry_graph as gg, geometry_lns as lns, geometry_operators as ops, geometry_seeds as seeds
from src.domain.spat.operator_selection import ARMS, LNS_ARMS, AdaptiveOperatorSelector

DOMAIN = {
    "length_m": 36, "width_m": 28, "burial_depth_m": 0.6,
    "areas": [{"type": "intervenible", "label": "lote", "polygon": [
        {"x": 2, "y": 2}, {"x": 34, "y": 2}, {"x": 34, "y": 14}, {"x": 22, "y": 14}, {"x": 22, "y": 26}, {"x": 2, "y": 26}]}],
    "structures": [{"x": 10, "y": 18, "width": 5, "height": 4, "label": "edificio"}],
}
C = ops.OperatorConstraints()


@pytest.fixture(scope="module")
def graphs():
    return [gg.from_geometry(s.geometry) for s in seeds.generate_seeds(DOMAIN, seed=3, count=5)]


def planned_moves(graph, tries=6):
    region = lns.make_region(DOMAIN)
    for destroy in lns.DESTROY:
        for repair in lns.REPAIR:
            for k in range(tries):
                move = lns.plan(graph, random.Random(31 * k + len(destroy) + len(repair)), destroy, repair, region, C)
                if move is not None:
                    yield destroy, repair, move


def test_compound_moves_replace_sets_of_conductors_and_leave_one_valid_network(graphs):
    seen_kinds, replaced = set(), 0
    for graph in graphs:
        for destroy, repair, move in planned_moves(graph):
            try:
                applied = ops.apply_operator(graph, move, C, DOMAIN)
            except ops.OperatorRejected:
                continue                                         # a rejected move is fine; an accepted one must be valid
            ops.check(applied.graph, C, DOMAIN)
            assert gg.is_connected(applied.graph)
            destroyed = sum(isinstance(step, ops.RemoveSegment) for step in move.steps)
            added = {s for s in applied.graph.segments if s not in graph.segments}
            assert destroyed >= 2                                # coordinated: a set of conductors goes in one move
            assert gg.canonical_hash(applied.graph) != gg.canonical_hash(graph)      # and it is never a no-op
            replaced += bool(added)
            seen_kinds.add((destroy, repair))
    assert seen_kinds >= {("region", "reconnect"), ("random", "reconnect"), ("random", "regrid")} and replaced > 0


def test_every_compound_move_is_undone_exactly(graphs):
    checked = 0
    for graph in graphs:
        start = gg.canonical_hash(graph)
        for _, _, move in planned_moves(graph, tries=3):
            try:
                applied = ops.apply_operator(graph, move, C, DOMAIN)
            except ops.OperatorRejected:
                continue
            back = ops.apply_operator(applied.graph, applied.inverse, ops.OperatorConstraints(min_segment_m=0.0), DOMAIN)
            assert gg.canonical_hash(back.graph) == start
            checked += 1
    assert checked >= 20


def test_a_compound_move_that_would_break_the_rules_is_rejected_as_a_whole(graphs):
    graph = graphs[0]
    far = gg.point(40.0, 3.0)                                    # outside the allowed polygon
    node = sorted(graph.nodes())[0]
    bad = lns.CompositeOperator((ops.AddSegment(node, far, free=True),))
    with pytest.raises(ops.OperatorRejected) as raised:
        ops.apply_operator(graph, bad, C, DOMAIN)
    assert raised.value.kind in {"domain", "constructive"}      # either way the whole move is refused


# ---- adaptive selection -------------------------------------------------------------------------------

def feed(selector, arm, outcome, times, repairing=False):
    for _ in range(times):
        selector.report(arm, outcome, repairing)


def test_a_rewarded_arm_gains_weight_and_a_useless_one_loses_it_down_to_a_floor():
    selector = AdaptiveOperatorSelector(DOMAIN, segment=10, floor=0.05)
    feed(selector, "atomic:add", "incumbent", 10)
    feed(selector, "atomic:split", "invalid", 10)
    weights = selector.weights["improve"]
    assert weights["atomic:add"] > 1.0 > weights["atomic:split"] >= 0.05
    for _ in range(30):
        feed(selector, "atomic:split", "duplicate", 10)
    assert selector.weights["improve"]["atomic:split"] == pytest.approx(0.05)
    assert weights["atomic:add"] > weights["atomic:remove"]


def test_improve_and_repair_contexts_learn_separately_and_repair_starts_with_a_prior_for_adding():
    selector = AdaptiveOperatorSelector(DOMAIN, segment=10)
    prior = selector.weights["repair"]
    assert prior["atomic:add"] > prior["atomic:remove"] and selector.weights["improve"]["atomic:add"] == selector.weights["improve"]["atomic:remove"]
    feed(selector, "atomic:remove", "improving", 10, repairing=False)
    assert selector.weights["improve"]["atomic:remove"] > 1.0 and selector.weights["repair"]["atomic:remove"] == prior["atomic:remove"]


def test_selection_is_deterministic_for_a_random_stream_and_covers_both_kinds_of_move(graphs):
    def draw(seed):
        selector, rng, arms = AdaptiveOperatorSelector(DOMAIN), random.Random(seed), []
        for _ in range(120):
            arm, _operator = selector.propose(graphs[0], rng, repairing=False)
            arms.append(arm)
            selector.report(arm, "novel", False)
        return arms
    assert draw(4) == draw(4) and draw(4) != draw(5)
    used = set(draw(4))
    assert any(a.startswith("atomic:") for a in used) and any(a.startswith("lns:") for a in used)
    assert set(draw(4)) <= set(ARMS)


def test_without_large_neighbourhoods_only_atomic_arms_exist():
    selector = AdaptiveOperatorSelector(DOMAIN, use_lns=False)
    assert not set(selector.arms) & set(LNS_ARMS) and len(selector.arms) == 8
