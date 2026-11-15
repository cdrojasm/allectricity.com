"""Topological operators on the geometry graph (OPT-009).

Add, remove, split, connect and reconnect segments; add, move and remove rods. Each operator is a
small frozen value with `apply` and an `inverse` computed from the graph it is applied to, so every
change can be undone exactly (up to the canonical hash). `apply_operator` runs the operator and then
checks the result against the site, the single-network rule and the constructive limits, raising
`OperatorRejected` with the kind of failure instead of returning an invalid graph:

  missing       the operator names a node, segment or rod that does not exist (or already exists)
  domain        the result leaves the allowed polygons, crosses a structure, overlaps or floats a rod
  connectivity  the result is not one connected network
  constructive  a piece shorter than `min_segment_m`, too many segments or rods, a rod length out of range
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Union

from src.domain.spat import geometry_graph as gg
from src.domain.spat.grid_geometry import MAX_CONDUCTORS, MAX_RODS
from src.domain.spat.optimizer_constraints import evaluate_optimizer_geometry


class OperatorRejected(ValueError):
    def __init__(self, kind: str, reason: str):
        self.kind, self.reason = kind, reason
        super().__init__(f"{kind}: {reason}")


@dataclass(frozen=True)
class OperatorConstraints:
    min_segment_m: float = 0.5
    max_segments: int = MAX_CONDUCTORS
    max_rods: int = MAX_RODS
    rod_length_range_m: tuple[float, float] = (1.0, 10.0)
    # Only horizontal and vertical runs are built (diagonals are hard to lay out on site). A diagonal the base design
    # already had (`inherited_diagonals`, as (a, b) point pairs) is kept: the rule is about what the search adds.
    orthogonal: bool = False
    inherited_diagonals: tuple = ()


is_diagonal = gg.is_diagonal


def diagonals_of(geometry: dict) -> tuple:
    """The diagonal runs of a geometry, to keep them allowed when the search is orthogonal."""
    graph = gg.from_geometry(geometry)
    return tuple((a, b) for a, b, _ in sorted(graph.segments) if is_diagonal(a, b))


def _on_piece(p: gg.Point, a: gg.Point, b: gg.Point) -> bool:
    return gg._distance_to(p, a, b) <= 2 * 10 ** -gg.DECIMALS


def _pieces_along(graph: gg.GeometryGraph, a: gg.Point, b: gg.Point) -> list[gg.Segment]:
    """Pieces of the graph lying on the straight run a-b (a segment may have been cut by crossings)."""
    return [s for s in graph.segments if _on_piece(s[0], a, b) and _on_piece(s[1], a, b)]


def _overlaps(graph: gg.GeometryGraph, a: gg.Point, b: gg.Point) -> bool:
    """Whether any existing piece lies on the line a-b and shares some length with the run."""
    length = gg._dist(a, b)
    if not length:
        return False
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    tol = 2 * 10 ** -gg.DECIMALS
    for p, q, _ in graph.segments:
        along = [((n[0] - a[0]) * ux + (n[1] - a[1]) * uy, abs((n[0] - a[0]) * uy - (n[1] - a[1]) * ux)) for n in (p, q)]
        if all(off <= tol for _, off in along):
            low, high = sorted(t for t, _ in along)
            if min(high, length) - max(low, 0.0) > tol:
                return True
    return False


@dataclass(frozen=True)
class AddSegment:
    """A new run a-b; at least one end must be an existing node so the network stays one piece.

    `free` waives that rule for the steps of a compound move, whose final result is what gets checked.
    """
    a: gg.Point
    b: gg.Point
    material: str = gg.DEFAULT_MATERIAL
    free: bool = False

    def apply(self, graph):
        nodes = graph.nodes()
        if not self.free and self.a not in nodes and self.b not in nodes:
            raise OperatorRejected("missing", "a new segment must start at an existing node")
        if self.a == self.b or _overlaps(graph, self.a, self.b):
            raise OperatorRejected("missing", "that run overlaps a conductor that already exists, or has no length")
        return gg.GeometryGraph(graph.site, graph.segments | {gg.segment(self.a, self.b, self.material)}, graph.rods)

    def inverse(self, before):
        return RemoveSegment(self.a, self.b)


@dataclass(frozen=True)
class ConnectNodes:
    """A new run between two nodes that already exist."""
    a: gg.Point
    b: gg.Point
    material: str = gg.DEFAULT_MATERIAL

    def apply(self, graph):
        nodes = graph.nodes()
        if self.a not in nodes or self.b not in nodes:
            raise OperatorRejected("missing", "connect needs two existing nodes")
        return AddSegment(self.a, self.b, self.material).apply(graph)

    def inverse(self, before):
        return RemoveSegment(self.a, self.b)


@dataclass(frozen=True)
class RemoveSegment:
    """Remove the run a-b (all the pieces on it). Nodes left without conductors disappear."""
    a: gg.Point
    b: gg.Point

    def apply(self, graph):
        pieces = _pieces_along(graph, self.a, self.b)
        if not pieces:
            raise OperatorRejected("missing", "no segment lies on that run")
        return gg.GeometryGraph(graph.site, graph.segments - set(pieces), graph.rods)

    def inverse(self, before):
        pieces = _pieces_along(before, self.a, self.b)
        return AddSegment(self.a, self.b, min(m for _, _, m in pieces) if pieces else gg.DEFAULT_MATERIAL)


@dataclass(frozen=True)
class SplitSegment:
    """Insert a node at `at` on the straight run a-b, so it can be connected to or reconnected from."""
    a: gg.Point
    b: gg.Point
    at: gg.Point

    def apply(self, graph):
        target = next((s for s in _pieces_along(graph, self.a, self.b)
                       if _on_piece(self.at, s[0], s[1]) and self.at not in (s[0], s[1])), None)
        if target is None:
            raise OperatorRejected("missing", "the split point must lie inside a piece of that run")
        return gg.GeometryGraph(graph.site, (graph.segments - {target}) | {
            gg.segment(target[0], self.at, target[2]), gg.segment(self.at, target[1], target[2])}, graph.rods)

    def inverse(self, before):
        return MergeSegments(self.a, self.at, self.b)


@dataclass(frozen=True)
class MergeSegments:
    """Undo a split: join the pieces of the run a-b into one when the nodes between them are plain."""
    a: gg.Point
    node: gg.Point
    b: gg.Point

    def apply(self, graph):
        pieces = _pieces_along(graph, self.a, self.b)
        interior = {p for s in pieces for p in (s[0], s[1])} - {self.a, self.b}
        degree = graph.degree()
        if len(pieces) < 2 or self.node not in interior:
            raise OperatorRejected("missing", "the node is not a split point of that run")
        if any(degree.get(p) != 2 or p in graph.rod_nodes() for p in interior) or len({m for _, _, m in pieces}) != 1:
            raise OperatorRejected("missing", "the run has joints, rods or mixed materials between its ends")
        return gg.GeometryGraph(graph.site, (graph.segments - set(pieces)) | {gg.segment(self.a, self.b, pieces[0][2])}, graph.rods)

    def inverse(self, before):
        return SplitSegment(self.a, self.b, self.node)


@dataclass(frozen=True)
class ReconnectSegment:
    """Move one end of the run a-b ('a' or 'b') onto another node `to`.

    `create` lets the target be a point that no longer exists: the inverse of a move needs it, since
    moving the end of a leaf makes its old node disappear.
    """
    a: gg.Point
    b: gg.Point
    end: str
    to: gg.Point
    create: bool = False

    def apply(self, graph):
        pieces = _pieces_along(graph, self.a, self.b)
        if not pieces or self.end not in ("a", "b"):
            raise OperatorRejected("missing", "no such run or end")
        moving, fixed = (self.a, self.b) if self.end == "a" else (self.b, self.a)
        if (self.to not in graph.nodes() and not self.create) or self.to in (moving, fixed):
            raise OperatorRejected("missing", "reconnect needs a different existing node")
        if _pieces_along(graph, self.to, fixed):
            raise OperatorRejected("missing", "that connection already exists")
        return gg.GeometryGraph(graph.site, (graph.segments - set(pieces)) | {
            gg.segment(self.to, fixed, min(m for _, _, m in pieces))}, graph.rods)

    def inverse(self, before):
        moving, fixed = (self.a, self.b) if self.end == "a" else (self.b, self.a)
        return ReconnectSegment(self.to, fixed, "a", moving, create=True)


@dataclass(frozen=True)
class AddRod:
    node: gg.Point
    length_m: float
    material: str = gg.DEFAULT_MATERIAL

    def apply(self, graph):
        if self.node not in graph.nodes():
            raise OperatorRejected("missing", "a rod stands on an existing node")
        if self.node in graph.rod_nodes():
            raise OperatorRejected("missing", "that node already has a rod")
        return gg.GeometryGraph(graph.site, graph.segments, graph.rods | {(self.node, round(self.length_m, gg.DECIMALS), self.material)})

    def inverse(self, before):
        return RemoveRod(self.node)


@dataclass(frozen=True)
class RemoveRod:
    node: gg.Point

    def apply(self, graph):
        rod = next((r for r in graph.rods if r[0] == self.node), None)
        if rod is None:
            raise OperatorRejected("missing", "no rod at that node")
        return gg.GeometryGraph(graph.site, graph.segments, graph.rods - {rod})

    def inverse(self, before):
        rod = next(r for r in before.rods if r[0] == self.node)
        return AddRod(rod[0], rod[1], rod[2])


@dataclass(frozen=True)
class MoveRod:
    node: gg.Point
    to: gg.Point

    def apply(self, graph):
        rod = next((r for r in graph.rods if r[0] == self.node), None)
        if rod is None:
            raise OperatorRejected("missing", "no rod at that node")
        if self.to not in graph.nodes() or self.to in graph.rod_nodes():
            raise OperatorRejected("missing", "the rod moves to a free existing node")
        return gg.GeometryGraph(graph.site, graph.segments, (graph.rods - {rod}) | {(self.to, rod[1], rod[2])})

    def inverse(self, before):
        return MoveRod(self.to, self.node)


Operator = Union[AddSegment, ConnectNodes, RemoveSegment, SplitSegment, MergeSegments, ReconnectSegment, AddRod, RemoveRod, MoveRod]


@dataclass(frozen=True)
class Applied:
    graph: gg.GeometryGraph
    inverse: Operator


def check(graph: gg.GeometryGraph, constraints: OperatorConstraints = OperatorConstraints(), base: dict | None = None) -> None:
    """Raise OperatorRejected unless the graph is one connected network that is valid on its site."""
    if not graph.segments:
        raise OperatorRejected("connectivity", "the geometry has no conductors")
    if len(graph.segments) > constraints.max_segments or len(graph.rods) > constraints.max_rods:
        raise OperatorRejected("constructive", "too many segments or rods")
    shortest = min(gg._dist(a, b) for a, b, _ in graph.segments)
    if shortest < constraints.min_segment_m - 1e-9:
        raise OperatorRejected("constructive", f"a piece is {shortest:.3f} m long; the minimum is {constraints.min_segment_m} m")
    low, high = constraints.rod_length_range_m
    if any(not low <= length <= high for _, length, _ in graph.rods):
        raise OperatorRejected("constructive", f"rod lengths must stay within {low}-{high} m")
    if constraints.orthogonal:
        for a, b, _ in graph.segments:
            if is_diagonal(a, b) and not any(_on_piece(a, p, q) and _on_piece(b, p, q) for p, q in constraints.inherited_diagonals):
                raise OperatorRejected("constructive", f"a diagonal run {a}-{b}; only horizontal and vertical runs are built")
    if not gg.is_connected(graph):
        raise OperatorRejected("connectivity", f"the geometry splits into {len(gg.components(graph))} parts")
    report = evaluate_optimizer_geometry(gg.to_geometry(graph, base))
    if report["violations"]:
        raise OperatorRejected("domain", report["violations"][0]["message"])


def apply_operator(graph: gg.GeometryGraph, operator: Operator, constraints: OperatorConstraints = OperatorConstraints(),
                   base: dict | None = None) -> Applied:
    """Apply, re-node the crossings it creates, validate, and return the new graph with its inverse."""
    result = gg.noded(operator.apply(graph))
    # Split and merge only move a node, which the canonical form ignores; every other operator must change the network.
    if not isinstance(operator, (SplitSegment, MergeSegments)) and gg.canonical_hash(result) == gg.canonical_hash(graph):
        raise OperatorRejected("missing", "the operator changes nothing (that run or rod already exists)")
    check(result, constraints, base)
    return Applied(result, operator.inverse(graph))


KINDS = ("add", "remove", "split", "connect", "reconnect", "add_rod", "move_rod", "remove_rod")
# More copper and more rods lower the touch and step voltages, so a design that violates is repaired by adding.
REPAIR_WEIGHTS = (4.0, 0.25, 1.0, 4.0, 1.0, 4.0, 1.0, 0.25)


def random_repair_operator(graph: gg.GeometryGraph, rng: random.Random, orthogonal: bool = False) -> Operator:
    """Like `random_operator`, biased toward adding conductors and rods, for a design that violates."""
    return random_operator(graph, rng, REPAIR_WEIGHTS, orthogonal=orthogonal)


def _aligned(node: gg.Point, others: list[gg.Point]) -> list[gg.Point]:
    return [n for n in others if n != node and not is_diagonal(node, n)]


def random_operator(graph: gg.GeometryGraph, rng: random.Random, weights: tuple[float, ...] | None = None,
                    kind: str | None = None, orthogonal: bool = False) -> Operator:
    """One plausible operator for the graph; it may still be rejected by `apply_operator`.

    With no weights every kind is equally likely (and the random stream is what it always was). `kind` forces one.
    With `orthogonal`, new runs are horizontal or vertical (the random stream differs from the unconstrained one).
    """
    nodes, segments = sorted(graph.nodes()), sorted(graph.segments)
    if kind is None:
        kind = rng.choice(KINDS) if weights is None else rng.choices(KINDS, weights=weights)[0]
    if kind == "add":
        a = rng.choice(nodes)
        if orthogonal:
            step = rng.choice((-6, -4, -3, 3, 4, 6))
            return AddSegment(a, gg.point(a[0] + step, a[1]) if rng.random() < 0.5 else gg.point(a[0], a[1] + step))
        return AddSegment(a, gg.point(a[0] + rng.choice((-6, -4, -3, 3, 4, 6)), a[1] + rng.choice((-6, -4, -3, 0, 3, 4, 6))))
    if kind == "remove":
        s = rng.choice(segments)
        return RemoveSegment(s[0], s[1])
    if kind == "split":
        s = rng.choice(segments)
        t = rng.choice((0.25, 0.5, 0.75))
        return SplitSegment(s[0], s[1], gg.point(s[0][0] + t * (s[1][0] - s[0][0]), s[0][1] + t * (s[1][1] - s[0][1])))
    if kind == "connect":
        a, b = rng.sample(nodes, 2)
        if orthogonal:
            pairs = [(n, m) for n in nodes for m in _aligned(n, nodes) if n < m]
            a, b = rng.choice(pairs) if pairs else (a, b)
        return ConnectNodes(a, b)
    if kind == "reconnect":
        s = rng.choice(segments)
        end = rng.choice("ab")
        targets = nodes
        if orthogonal:                       # the moved end must stay level or plumb with the end that stays
            fixed = s[1] if end == "a" else s[0]
            targets = _aligned(fixed, nodes) or nodes
        return ReconnectSegment(s[0], s[1], end, rng.choice(targets))
    rods = sorted(graph.rods)
    if kind == "add_rod" or not rods:
        return AddRod(rng.choice(nodes), rng.choice((1.5, 2.4, 3.0, 6.0)))
    if kind == "move_rod":
        return MoveRod(rng.choice(rods)[0], rng.choice(nodes))
    return RemoveRod(rng.choice(rods)[0])
