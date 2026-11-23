"""The redundancy constraint of the topology search: every run on a closed loop, tails to a rod excepted."""

import pytest

from src.domain.spat import geometry_graph as gg, geometry_seeds as seeds
from src.domain.spat.geometry_operators import OperatorConstraints, OperatorRejected, bridges_of, check, loose_runs
from src.domain.spat.optimizer_topology_search import search_topology
from tests.domain.test_topology_search import DOMAIN, Model


def _run(a, b):
    return {"start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]}}


RING = [_run((4, 4), (20, 4)), _run((20, 4), (20, 12)), _run((20, 12), (4, 12)), _run((4, 12), (4, 4))]
REDUNDANT = OperatorConstraints(redundant=True)


def _graph(conductors, rods=()):
    return gg.noded(gg.from_geometry({**DOMAIN, "conductors": conductors,
                                      "rods": [{"x": x, "y": y, "length_m": 2.4} for x, y in rods]}))


def test_bridges_are_the_runs_on_no_loop():
    assert gg.bridges(_graph(RING)) == []
    tail = _graph(RING + [_run((20, 12), (26, 12))])
    assert [(a, b) for a, b, _ in gg.bridges(tail)] == [((20.0, 12.0), (26.0, 12.0))]
    # two loops joined by a single run: the joint is a bridge even though nothing hangs loose
    other = [_run((24, 4), (30, 4)), _run((30, 4), (30, 10)), _run((30, 10), (24, 10)), _run((24, 10), (24, 4))]
    joined = _graph(RING + other + [_run((20, 8), (24, 8))])
    assert [(a, b) for a, b, _ in gg.bridges(joined)] == [((20.0, 8.0), (24.0, 8.0))]


def test_a_closed_ring_passes_and_a_loose_cable_is_rejected():
    check(_graph(RING), REDUNDANT, DOMAIN)
    loose = _graph(RING + [_run((20, 12), (26, 12))])
    with pytest.raises(OperatorRejected, match="no closed loop") as rejected:
        check(loose, REDUNDANT, DOMAIN)
    assert rejected.value.kind == "constructive"
    check(loose, OperatorConstraints(), DOMAIN)                         # the unconstrained search is unchanged


def test_only_a_short_straight_tail_to_a_rod_may_hang_loose():
    check(_graph(RING + [_run((20, 12), (23, 12))], rods=[(23, 12)]), REDUNDANT, DOMAIN)
    with pytest.raises(OperatorRejected):                                # no rod at its end
        check(_graph(RING + [_run((20, 12), (23, 12))]), REDUNDANT, DOMAIN)
    with pytest.raises(OperatorRejected):                                # longer than the limit
        check(_graph(RING + [_run((20, 12), (26, 12))], rods=[(26, 12)]), REDUNDANT, DOMAIN)
    check(_graph(RING + [_run((20, 12), (26, 12))], rods=[(26, 12)]),
          OperatorConstraints(redundant=True, stub_max_m=6.0), DOMAIN)


def test_loose_runs_of_the_base_design_are_kept():
    base = {**DOMAIN, "conductors": RING + [_run((20, 12), (26, 12))]}
    inherited = bridges_of(base)
    graph = gg.noded(gg.from_geometry(base))
    check(graph, OperatorConstraints(redundant=True, inherited_bridges=inherited), DOMAIN)
    assert loose_runs(graph, REDUNDANT)


def test_redundant_seeds_have_no_loose_runs_and_no_trees():
    start = seeds.generate_seeds(DOMAIN, seed=3, count=6, constraints=seeds.SeedConstraints(orthogonal=True, redundant=True))
    assert start and all(s.family != "branched" for s in start)
    assert not any(loose_runs(gg.normalize(gg.from_geometry(s.geometry)), REDUNDANT) for s in start)


@pytest.mark.parametrize("adaptive", [False, True])
def test_a_redundant_search_never_evaluates_a_loose_cable(adaptive):
    from src.domain.spat.operator_selection import AdaptiveOperatorSelector

    constraints = OperatorConstraints(orthogonal=True, redundant=True)
    start = seeds.generate_seeds(DOMAIN, seed=3, count=4, constraints=seeds.SeedConstraints(orthogonal=True, redundant=True))

    class Recording(Model):
        def electrical(self, level, geometry):
            self.seen = getattr(self, "seen", []) + [geometry]
            return super().electrical(level, geometry)

    model = Recording()
    options = {"operator_selector": AdaptiveOperatorSelector(DOMAIN, constraints)} if adaptive else {}
    result = search_topology(domain=DOMAIN, seeds=start, evaluate_cost=model.cost, evaluate_electrical=model.electrical,
                             seed=3, max_solver_calls=80, constraints=constraints, **options)
    assert result["best"] is not None and len(model.seen) > 10
    assert not any(loose_runs(gg.normalize(gg.from_geometry(g)), constraints) for g in model.seen)
