"""Large-neighbourhood moves: replace a set of conductors with a coordinated sequence of operators (OPT-011).

A move destroys part of the network and repairs it:

  destroy "region"   every piece whose midpoint lies within a radius of a random node
          "random"   a few pieces chosen at random
          "branch"   a limb, from a leaf back to the nearest junction
  repair  "reconnect"  join the leftover parts with the shortest valid links (usually fewer conductors)
          "regrid"     lay a small mesh over the destroyed area, then join what is left

The result is a `CompositeOperator`: a tuple of the atomic operators of `geometry_operators`, applied one
after the other, each followed by the re-noding a single operator gets. Only the final graph is checked
(`apply_operator` does that), since the steps in between may be disconnected on purpose. Its inverse is the
reverse sequence of the inverses, so a compound move is undone as exactly as an atomic one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from src.domain.spat import geometry_graph as gg
from src.domain.spat.geometry_operators import (
    AddSegment, ConnectNodes, Operator, OperatorConstraints, OperatorRejected, RemoveRod, RemoveSegment)
from src.domain.spat.geometry_seeds import SeedConstraints, _Region

DESTROY = ("region", "random", "branch")
REPAIR = ("reconnect", "regrid")


@dataclass(frozen=True)
class CompositeOperator:
    steps: tuple

    def _walk(self, graph):
        states = [graph]
        for step in self.steps:
            states.append(gg.noded(step.apply(states[-1])))
        return states

    def apply(self, graph):
        return self._walk(graph)[-1]

    def inverse(self, before):
        states = self._walk(before)
        inverses = (step.inverse(state) for step, state in reversed(list(zip(self.steps, states))))
        # The states in between can be disconnected, so an add in the reverse sequence must not insist on touching the network.
        return CompositeOperator(tuple(replace(op, free=True) if isinstance(op, AddSegment) else op for op in inverses))


def _mid(piece):
    return ((piece[0][0] + piece[1][0]) / 2, (piece[0][1] + piece[1][1]) / 2)


def _destroy(graph: gg.GeometryGraph, rng: random.Random, kind: str):
    """Pieces to remove, as a list of (a, b) runs."""
    pieces = sorted(graph.segments)
    if len(pieces) < 4:
        return []
    cap = max(2, int(0.4 * len(pieces)))
    if kind == "region":
        center = rng.choice(sorted(graph.nodes()))
        for radius in (rng.choice((3.0, 5.0, 8.0)), 3.0, 2.0):
            chosen = [p for p in pieces if math.dist(_mid(p), center) <= radius]
            if 2 <= len(chosen) <= cap:
                return [(p[0], p[1]) for p in chosen]
        return []
    if kind == "random":
        return [(p[0], p[1]) for p in rng.sample(pieces, k=min(cap, rng.randint(2, 5)))]
    # branch: walk from a leaf toward the network until a junction or a rod
    degree = graph.degree()
    leaves = sorted(n for n, d in degree.items() if d == 1 and n not in graph.rod_nodes())
    if not leaves:
        return []
    node, removed = rng.choice(leaves), []
    for _ in range(6):
        piece = next((p for p in pieces if node in (p[0], p[1]) and (p[0], p[1]) not in removed), None)
        if piece is None:
            break
        removed.append((piece[0], piece[1]))
        node = piece[1] if piece[0] == node else piece[0]
        if degree.get(node, 0) != 2 or node in graph.rod_nodes():
            break
    return removed if 2 <= len(removed) <= cap else []     # one piece is just the atomic remove


def _link_candidates(graph: gg.GeometryGraph):
    """Node pairs from different components, nearest first."""
    parts = gg.components(graph)
    owner = {n: i for i, part in enumerate(parts) for n in part}
    nodes = sorted(owner)
    pairs = [(math.dist(a, b), a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if owner[a] != owner[b]]
    return sorted(pairs)


def plan(graph: gg.GeometryGraph, rng: random.Random, destroy: str, repair: str, region: _Region,
         constraints: OperatorConstraints) -> CompositeOperator | None:
    """Plan one destroy-and-repair move, or None when it cannot be made valid from here."""
    removed = _destroy(graph, rng, destroy)
    if not removed:
        return None
    steps: list[Operator] = []
    work = graph

    def run(step: Operator) -> bool:
        nonlocal work
        try:
            work = gg.noded(step.apply(work))
        except OperatorRejected:
            return False
        steps.append(step)
        return True

    touched = {p for run_ in removed for p in run_}
    for a, b in removed:
        run(RemoveSegment(a, b))
    for node in sorted(n for n in work.rod_nodes() if n not in work.nodes()):
        run(RemoveRod(node))                       # a rod whose node vanished cannot stay
    if not work.segments:
        return None
    if repair == "regrid":
        xs = [p[0] for p in touched]
        ys = [p[1] for p in touched]
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) > 150.0:
            return None                            # a mesh over a very large area is a different design, not a repair
        spacing = rng.choice((3.0, 4.0, 5.0))
        cols = max(1, math.ceil((max(xs) - min(xs)) / spacing))
        rows = max(1, math.ceil((max(ys) - min(ys)) / spacing))
        lx = [min(xs) + (max(xs) - min(xs)) * i / cols for i in range(cols + 1)]
        ly = [min(ys) + (max(ys) - min(ys)) * j / rows for j in range(rows + 1)]
        lines = [(gg.point(x, ly[0]), gg.point(x, ly[-1])) for x in lx] + [(gg.point(lx[0], y), gg.point(lx[-1], y)) for y in ly]
        for a, b in lines:
            if a != b and gg._dist(a, b) >= constraints.min_segment_m and region.edge_ok(a, b, sample_m=0.5):
                run(AddSegment(a, b, free=True))
    tries = 0
    undone = {frozenset(run_) for run_ in removed}     # putting a destroyed run straight back would make the move a no-op
    while len(gg.components(work)) > 1 and tries < 40:
        for distance, a, b in _link_candidates(work):
            if frozenset((a, b)) in undone:
                continue
            tries += 1
            if distance >= constraints.min_segment_m and region.edge_ok(a, b, sample_m=0.5) and run(ConnectNodes(a, b)):
                break
            if tries >= 40:
                break
        else:
            break
    if len(gg.components(work)) != 1 or not steps or work == graph:
        return None
    return CompositeOperator(tuple(steps))


def make_region(domain: dict) -> _Region:
    return _Region(domain, SeedConstraints())
