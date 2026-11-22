"""Deterministic starting geometries for the optimizer (OPT-008).

Given the site (its allowed polygons and structures) and a seed number, produce geometries that are
valid and connected as one network: the user's own drawing when there is one, a perimeter ring
inset from the allowed polygon, a grid inscribed in the largest axis-aligned rectangle that fits, and
branched trees. The same domain and seed always give the same list; different seeds vary the inset,
spacing, branching and rods. Every candidate must pass the OP-05 geometry check and keep every piece
at least `min_segment_m` long, and duplicates (same canonical hash) are dropped.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from src.domain.spat import geometry_graph as gg
from src.domain.spat.grid_geometry import _point_in_polygon, area_polygon, site_areas
from src.domain.spat.optimizer_constraints import evaluate_optimizer_geometry

FAMILIES = ("user", "perimeter", "inscribed", "branched")


@dataclass(frozen=True)
class SeedConstraints:
    margin_m: float = 0.5          # clearance from the allowed polygon's edge
    structure_clearance_m: float = 0.5
    min_segment_m: float = 0.5
    spacing_choices_m: tuple[float, ...] = (3.0, 4.0, 5.0, 6.0, 8.0)
    rod_length_choices_m: tuple[float, ...] = (1.5, 2.4, 3.0, 6.0)
    max_attempts: int = 80
    orthogonal: bool = False       # only horizontal and vertical runs
    redundant: bool = False        # every run on a closed loop (no branched trees); see OperatorConstraints.redundant
    stub_max_m: float = 3.0


@dataclass(frozen=True)
class Seed:
    family: str
    geometry: dict[str, Any]
    graph_hash: str
    metadata: dict[str, Any]


class _Region:
    """Where conductors may go: inside an intervenible polygon with margin, away from structures."""

    def __init__(self, domain: dict, constraints: SeedConstraints):
        self.c = constraints
        areas = site_areas(domain, "intervenible")
        self.polygons = [area_polygon(a) for a in areas] or [
            [(0.0, 0.0), (float(domain["length_m"]), 0.0), (float(domain["length_m"]), float(domain["width_m"])),
             (0.0, float(domain["width_m"]))]]
        self.blocked = [(s["x"] - s["width"] / 2 - constraints.structure_clearance_m, s["x"] + s["width"] / 2 + constraints.structure_clearance_m,
                         s["y"] - s["height"] / 2 - constraints.structure_clearance_m, s["y"] + s["height"] / 2 + constraints.structure_clearance_m)
                        for s in domain.get("structures") or [] if "x" in s]
        xs = [p[0] for poly in self.polygons for p in poly]
        ys = [p[1] for poly in self.polygons for p in poly]
        self.box = (min(xs), max(xs), min(ys), max(ys))

    def usable(self, x: float, y: float) -> bool:
        if any(x0 < x < x1 and y0 < y < y1 for x0, x1, y0, y1 in self.blocked):
            return False
        for poly in self.polygons:
            if _point_in_polygon(x, y, poly) and min(
                    gg._distance_to((x, y), a, b) for a, b in zip(poly, poly[1:] + poly[:1])) >= self.c.margin_m - 1e-9:
                return True
        return False

    def edge_ok(self, p: gg.Point, q: gg.Point, sample_m: float = 0.25) -> bool:
        steps = max(2, int(gg._dist(p, q) / sample_m) + 1)
        return all(self.usable(p[0] + (q[0] - p[0]) * i / steps, p[1] + (q[1] - p[1]) * i / steps) for i in range(steps + 1))


def _build(domain: dict, segments: list[tuple[gg.Point, gg.Point]], rods: list[tuple[gg.Point, float]]) -> gg.GeometryGraph:
    site = gg.Site.from_geometry(domain)
    graph = gg.GeometryGraph(site, frozenset(gg.segment(a, b) for a, b in segments),
                             frozenset((gg.point(*n), round(length, gg.DECIMALS), gg.DEFAULT_MATERIAL) for n, length in rods))
    return gg.normalize(gg.noded(graph))


def _perimeter(region: _Region, rng: random.Random, domain: dict, c: SeedConstraints):
    poly = max(region.polygons, key=lambda p: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1]))))
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) < 0:
        poly = poly[::-1]
    for inset in sorted({c.margin_m, c.margin_m + 0.5 * rng.random(), c.margin_m + 1.0 + rng.random()}):
        ring = []
        n = len(poly)
        for i in range(n):
            prev, here, nxt = poly[i - 1], poly[i], poly[(i + 1) % n]
            def unit(a, b):
                d = gg._dist(a, b) or 1.0
                return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
            u, v = unit(prev, here), unit(here, nxt)
            nu, nv = (-u[1], u[0]), (-v[1], v[0])            # inward normals of a counter-clockwise polygon
            bis = (nu[0] + nv[0], nu[1] + nv[1])
            denominator = bis[0] * nu[0] + bis[1] * nu[1]
            if abs(denominator) < 1e-6:
                ring = []
                break
            ring.append((here[0] + bis[0] * inset / denominator, here[1] + bis[1] * inset / denominator))
        ring = [gg.point(*p) for p in ring]
        if len(ring) >= 3 and all(region.edge_ok(a, b) for a, b in zip(ring, ring[1:] + ring[:1])):
            segments = list(zip(ring, ring[1:] + ring[:1]))
            if not c.orthogonal and rng.random() < 0.5:               # a cross-brace through the middle when it fits
                cx = sum(p[0] for p in ring) / len(ring)
                cy = sum(p[1] for p in ring) / len(ring)
                centre = gg.point(cx, cy)
                if region.usable(*centre):
                    for p in rng.sample(ring, k=min(2, len(ring))):
                        if region.edge_ok(centre, p):
                            segments.append((centre, p))
            rods = [(p, rng.choice(c.rod_length_choices_m)) for p in rng.sample(ring, k=rng.choice((0, min(4, len(ring)))))]
            return segments, rods
    return None


def _largest_rectangle(region: _Region, rng: random.Random):
    x0, x1, y0, y1 = region.box
    best, step = None, 0.5
    for _ in range(30):
        sx, sy = gg.point(rng.uniform(x0, x1), rng.uniform(y0, y1))
        if not region.usable(sx, sy):
            continue
        left, right, bottom, top = sx, sx, sy, sy
        grew = True
        while grew:
            grew = False
            for side in rng.sample(("l", "r", "b", "t"), 4):
                nl, nr, nb, nt = left - step * (side == "l"), right + step * (side == "r"), bottom - step * (side == "b"), top + step * (side == "t")
                strip = [((nl, nb), (nr, nb)), ((nl, nt), (nr, nt)), ((nl, nb), (nl, nt)), ((nr, nb), (nr, nt))]
                if all(region.edge_ok(gg.point(*a), gg.point(*b), sample_m=0.5) for a, b in strip):
                    left, right, bottom, top, grew = nl, nr, nb, nt, True
        area = (right - left) * (top - bottom)
        if best is None or area > best[0]:
            best = (area, left, right, bottom, top)
    return best


def _inscribed(region: _Region, rng: random.Random, domain: dict, c: SeedConstraints):
    best = _largest_rectangle(region, rng)
    if best is None or best[0] < 4.0:
        return None
    _, left, right, bottom, top = best
    spacing = rng.choice(c.spacing_choices_m)
    cols, rows = max(1, math.ceil((right - left) / spacing)), max(1, math.ceil((top - bottom) / spacing))
    xs = [left + (right - left) * i / cols for i in range(cols + 1)]
    ys = [bottom + (top - bottom) * j / rows for j in range(rows + 1)]
    segments = [(gg.point(x, ys[0]), gg.point(x, ys[-1])) for x in xs] + [(gg.point(xs[0], y), gg.point(xs[-1], y)) for y in ys]
    corners = [gg.point(x, y) for x in (xs[0], xs[-1]) for y in (ys[0], ys[-1])]
    rods = [(p, rng.choice(c.rod_length_choices_m)) for p in corners] if rng.random() < 0.6 else []
    return segments, rods


def _branched(region: _Region, rng: random.Random, domain: dict, c: SeedConstraints):
    best = _largest_rectangle(region, rng)
    if best is None:
        return None
    _, left, right, bottom, top = best
    root = gg.point((left + right) / 2, (bottom + top) / 2)
    if not region.usable(*root):
        return None
    directions = [(math.cos(a * math.pi / 4), math.sin(a * math.pi / 4)) for a in range(0, 8, 2 if c.orthogonal else 1)]
    nodes, segments, frontier = [root], [], [(root, None)]
    target = rng.randint(8, 20)
    attempts = 0
    while frontier and len(segments) < target and attempts < 400:
        attempts += 1
        base, _ = frontier[rng.randrange(len(frontier))]
        dx, dy = rng.choice(directions)
        length = rng.choice((2.0, 3.0, 4.0, 5.0, 6.0))
        end = gg.point(base[0] + dx * length, base[1] + dy * length)
        if end in nodes or not region.edge_ok(base, end):
            continue
        # keep it a tree: the new piece must not cross an existing one
        if any(_cross(base, end, a, b) for a, b in segments):
            continue
        nodes.append(end)
        segments.append((base, end))
        frontier.append((end, base))
    if len(segments) < 3:
        return None
    degree: dict[gg.Point, int] = {}
    for a, b in segments:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    leaves = sorted(n for n, d in degree.items() if d == 1)
    rods = [(n, rng.choice(c.rod_length_choices_m)) for n in rng.sample(leaves, k=min(len(leaves), rng.choice((0, 2, 4))))]
    return segments, rods


def _cross(p: gg.Point, q: gg.Point, a: gg.Point, b: gg.Point) -> bool:
    """Proper crossing or overlap of two pieces other than at a shared end node."""
    if {p, q} & {a, b}:
        shared = {p, q} & {a, b}
        if len(shared) == 2:
            return True
        other = (set((p, q)) - shared).pop(), (set((a, b)) - shared).pop()
        s = next(iter(shared))
        v1, v2 = (other[0][0] - s[0], other[0][1] - s[1]), (other[1][0] - s[0], other[1][1] - s[1])
        return abs(v1[0] * v2[1] - v1[1] * v2[0]) < 1e-9 and v1[0] * v2[0] + v1[1] * v2[1] > 0
    return bool(gg.intersections({"conductors": [{"start": {"x": p[0], "y": p[1]}, "end": {"x": q[0], "y": q[1]}},
                                                 {"start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]}}]}))


def _accept(domain: dict, graph: gg.GeometryGraph, c: SeedConstraints) -> dict | None:
    geometry = gg.to_geometry(graph, domain)
    if not graph.segments or not gg.is_connected(graph):
        return None
    if min(gg._dist(a, b) for a, b, _ in graph.segments) < c.min_segment_m:
        return None
    if c.orthogonal and any(abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6 for a, b, _ in graph.segments):
        return None
    if c.redundant:
        from src.domain.spat.geometry_operators import OperatorConstraints, loose_runs
        if loose_runs(gg.normalize(graph), OperatorConstraints(redundant=True, stub_max_m=c.stub_max_m)):
            return None
    if evaluate_optimizer_geometry(geometry)["status"] != "valid":
        return None
    return geometry


def cells(graph: gg.GeometryGraph) -> set[tuple[int, int]]:
    """1 m cells the network passes through, for comparing how different two geometries are."""
    out = set()
    for a, b, _ in graph.segments:
        steps = max(1, int(gg._dist(a, b) / 0.5))
        out.update((round(a[0] + (b[0] - a[0]) * i / steps), round(a[1] + (b[1] - a[1]) * i / steps)) for i in range(steps + 1))
    return out


def diversity(seeds: list[Seed]) -> float:
    """Mean pairwise Jaccard distance between the cells two seeds occupy: 0 identical, 1 disjoint."""
    sets = [cells(gg.from_geometry(s.geometry)) for s in seeds]
    pairs = [(a, b) for i, a in enumerate(sets) for b in sets[i + 1:]]
    return sum(1 - len(a & b) / len(a | b) for a, b in pairs) / len(pairs) if pairs else 0.0


def generate_seeds(domain: dict, *, seed: int, count: int = 8, initial: dict | None = None,
                   constraints: SeedConstraints = SeedConstraints()) -> list[Seed]:
    """Up to `count` distinct valid single-network geometries, always in the same order for a seed."""
    rng, region = random.Random(seed), _Region(domain, constraints)
    out: list[Seed] = []
    seen: set[str] = set()

    def keep(family: str, geometry: dict | None, extra: dict | None = None) -> None:
        if geometry is None:
            return
        graph = gg.from_geometry(geometry)
        digest = gg.canonical_hash(graph)
        if digest in seen:
            return
        seen.add(digest)
        out.append(Seed(family, geometry, digest, {**gg.stats(graph), **(extra or {})}))

    if initial is not None:
        graph = gg.normalize(gg.from_geometry(initial))
        keep("user", _accept(domain, graph, SeedConstraints(**{**constraints.__dict__, "min_segment_m": 0.0, "orthogonal": False,
                                                                 "redundant": False})) and gg.to_geometry(graph, initial))
    builders = {"perimeter": _perimeter, "inscribed": _inscribed, "branched": _branched}
    # A branched seed is a tree on purpose: every run of it is a bridge, so a redundant search never starts from one.
    order = ("perimeter", "inscribed") if constraints.redundant else ("perimeter", "inscribed", "branched")
    attempts = 0
    while len(out) < count and attempts < constraints.max_attempts:
        family = order[attempts % len(order)]
        attempts += 1
        built = builders[family](region, rng, domain, constraints)
        if built is None:
            continue
        graph = _build(domain, *built)
        keep(family, _accept(domain, graph, constraints), {"attempt": attempts})
    return out
