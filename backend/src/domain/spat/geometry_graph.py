"""Canonical graph of a drawn grounding geometry (OPT-007).

A geometry is a set of conductor segments between nodes, rods standing on nodes, and the site that
bounds them (allowed polygons and structures). Nodes are plain rounded (x, y) points, so a graph is
hashable and operators can name nodes without ids.

Two drawings of the same network must hash equal. `normalize` therefore: rounds to 1 mm; cuts every
segment at crossings, junctions, rod tops and overlaps; drops zero-length and duplicate pieces; and
merges the collinear same-material pieces that meet at a node holding nothing else (a conductor drawn
in two halves is one conductor). Segment direction, list order and regular-versus-drawn description
do not matter. `canonical_hash` covers the normalized network and the normalized site.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

from src.domain.spat import grid_geometry as gg

DECIMALS = 3                      # 1 mm
DEFAULT_MATERIAL = "unspecified"
Point = tuple[float, float]
Segment = tuple[Point, Point, str]   # endpoints in sorted order, then material
Rod = tuple[Point, float, str]       # node, length_m, material


def point(x: float, y: float) -> Point:
    return (round(float(x), DECIMALS) + 0.0, round(float(y), DECIMALS) + 0.0)   # + 0.0 turns -0.0 into 0.0


def segment(a: Point, b: Point, material: str = DEFAULT_MATERIAL) -> Segment:
    a, b = point(*a), point(*b)
    return (a, b, material) if a <= b else (b, a, material)


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _distance_to(p: Point, a: Point, b: Point) -> float:
    return gg._point_segment_distance(p, (a, b))


def is_diagonal(a: Point, b: Point) -> bool:
    """Neither horizontal nor vertical."""
    tol = 2 * 10 ** -DECIMALS
    return abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _round_numbers(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, DECIMALS) + 0.0
    if isinstance(value, dict):
        return {key: _round_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_numbers(item) for item in value]
    return value


def _normal_area(area: dict) -> dict:
    """Polygon area with counter-clockwise vertices starting at the lowest-left one."""
    polygon = gg.area_polygon(area)
    polygon = [point(x, y) for x, y in polygon]
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1])) < 0:
        polygon.reverse()
    start = polygon.index(min(polygon))
    polygon = polygon[start:] + polygon[:start]
    return {"type": area.get("type"), "label": area.get("label") or "",
            "polygon": [{"x": x, "y": y} for x, y in polygon]}


@dataclass(frozen=True)
class Site:
    length_m: float
    width_m: float
    burial_depth_m: float
    areas: tuple[str, ...]        # canonical JSON, sorted
    structures: tuple[str, ...]   # canonical JSON, sorted

    @classmethod
    def from_geometry(cls, geometry: dict) -> "Site":
        return cls(
            float(geometry["length_m"]), float(geometry["width_m"]), float(geometry.get("burial_depth_m") or 0.0),
            tuple(sorted(_json(_normal_area(a)) for a in geometry.get("areas") or [])),
            tuple(sorted(_json(_round_numbers(dict(s))) for s in geometry.get("structures") or [])))

    def form(self) -> dict:
        return {"length_m": self.length_m, "width_m": self.width_m, "burial_depth_m": self.burial_depth_m,
                "areas": [json.loads(a) for a in self.areas], "structures": [json.loads(s) for s in self.structures]}


@dataclass(frozen=True)
class GeometryGraph:
    site: Site
    segments: frozenset
    rods: frozenset

    def nodes(self) -> set[Point]:
        return {p for a, b, _ in self.segments for p in (a, b)} | {node for node, _, _ in self.rods}

    def rod_nodes(self) -> set[Point]:
        return {node for node, _, _ in self.rods}

    def degree(self) -> dict[Point, int]:
        counts: dict[Point, int] = {}
        for a, b, _ in self.segments:
            counts[a] = counts.get(a, 0) + 1
            counts[b] = counts.get(b, 0) + 1
        return counts

    def total_length_m(self) -> float:
        return sum(_dist(a, b) for a, b, _ in self.segments)


def _material_at(p: Point, sources: Iterable[Segment]) -> str:
    found = sorted(m for a, b, m in sources if _distance_to(p, a, b) <= 2 * 10 ** -DECIMALS)
    return found[0] if found else DEFAULT_MATERIAL


def _cut(sources: Iterable[Segment], rod_nodes: Iterable[Point]) -> frozenset:
    """Cut at crossings, junctions, rod tops and overlaps; drop zero-length and duplicate pieces."""
    sources = [s for s in sources if _dist(s[0], s[1]) > 0]
    lines = [(a, b) for a, b, _ in sources]
    pieces = gg.split_lines(lines, list(rod_nodes))
    out: dict[tuple[Point, Point], str] = {}
    for a, b in pieces:
        a, b = point(*a), point(*b)
        if a == b:
            continue
        key = (a, b) if a <= b else (b, a)
        material = _material_at(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), sources)
        out[key] = min(material, out.get(key, material))
    return frozenset((a, b, m) for (a, b), m in out.items())


def _merge_collinear(segments: frozenset, keep: set[Point]) -> frozenset:
    """Join pieces that meet at a degree-2 node holding no rod when they are collinear and share a material."""
    current = set(segments)
    while True:
        incident: dict[Point, list[Segment]] = {}
        for s in current:
            incident.setdefault(s[0], []).append(s)
            incident.setdefault(s[1], []).append(s)
        merged = False
        for node in sorted(incident):
            pieces = incident[node]
            if node in keep or len(pieces) != 2 or pieces[0][2] != pieces[1][2]:
                continue
            ends = [s[0] if s[1] == node else s[1] for s in pieces]
            if ends[0] == ends[1] or _distance_to(node, ends[0], ends[1]) > 2 * 10 ** -DECIMALS \
                    or not (min(ends[0][0], ends[1][0]) - 1e-9 <= node[0] <= max(ends[0][0], ends[1][0]) + 1e-9
                            and min(ends[0][1], ends[1][1]) - 1e-9 <= node[1] <= max(ends[0][1], ends[1][1]) + 1e-9):
                continue
            current -= set(pieces)
            current.add(segment(ends[0], ends[1], pieces[0][2]))
            merged = True
            break
        if not merged:
            return frozenset(current)


@functools.lru_cache(maxsize=16384)
def normalize(graph: GeometryGraph) -> GeometryGraph:
    """Memoized: graphs are immutable, and searches normalize and hash the same graph many times."""
    rod_nodes = graph.rod_nodes()
    noded = _cut(graph.segments, rod_nodes)
    return GeometryGraph(graph.site, _merge_collinear(noded, rod_nodes), graph.rods)


@functools.lru_cache(maxsize=16384)
def noded(graph: GeometryGraph) -> GeometryGraph:
    """Cut at crossings and junctions but keep every node: the working form operators act on."""
    return GeometryGraph(graph.site, _cut(graph.segments, graph.rod_nodes()), graph.rods)


def from_geometry(geometry: dict, default_material: str = DEFAULT_MATERIAL) -> GeometryGraph:
    """Graph of a regular or drawn geometry dictionary, noded but not yet merged."""
    drawn = geometry.get("conductors") or []
    sources: list[Segment] = []
    if drawn:
        for c in drawn:
            a = point(c["start"]["x"], c["start"]["y"])
            b = point(c["end"]["x"], c["end"]["y"])
            sources.append(segment(a, b, c.get("material") or default_material))
    else:
        sources = [segment(a, b, default_material) for a, b in gg.conductor_lines(geometry)]
    rods = frozenset(
        (point(x, y), round(float(length), DECIMALS), (r.get("material") if r else None) or default_material)
        for (x, y, length), r in zip(
            gg.rod_points(geometry), list(geometry.get("rods") or []) or [None] * len(gg.rod_points(geometry))))
    return noded(GeometryGraph(Site.from_geometry(geometry), frozenset(sources), rods))


def to_geometry(graph: GeometryGraph, base: dict | None = None) -> dict:
    """Plain geometry dictionary (drawn conductors and rods) for the solver and the checks."""
    form = graph.site.form()
    out = {key: value for key, value in (base or {}).items()
           if key not in {"conductors", "rods", "rods_count", "conductor_spacing_m", "conductor_spacing_x_m",
                          "conductor_spacing_y_m", "areas", "structures"}}
    out.update(length_m=form["length_m"], width_m=form["width_m"], burial_depth_m=form["burial_depth_m"],
               areas=form["areas"], structures=form["structures"])
    out["conductors"] = [
        {"start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]},
         **({"material": m} if m != DEFAULT_MATERIAL else {})} for a, b, m in sorted(graph.segments)]
    out["rods"] = [{"x": n[0], "y": n[1], "length_m": length, **({"material": m} if m != DEFAULT_MATERIAL else {})}
                   for n, length, m in sorted(graph.rods)]
    return out


def canonical_form(graph: GeometryGraph) -> dict:
    n = normalize(graph)
    return {"site": n.site.form(),
            "segments": [[a[0], a[1], b[0], b[1], m] for a, b, m in sorted(n.segments)],
            "rods": [[node[0], node[1], length, m] for node, length, m in sorted(n.rods)]}


@functools.lru_cache(maxsize=16384)
def canonical_hash(graph: GeometryGraph) -> str:
    """Same for every drawing of the same network on the same site."""
    return hashlib.sha256(_json(canonical_form(graph)).encode()).hexdigest()


def geometry_hash(geometry: dict) -> str:
    return canonical_hash(from_geometry(geometry))


def components(graph: GeometryGraph) -> list[set[Point]]:
    parent: dict[Point, Point] = {}

    def find(p: Point) -> Point:
        while parent.setdefault(p, p) != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for a, b, _ in graph.segments:
        parent[find(a)] = find(b)
    groups: dict[Point, set[Point]] = {}
    for p in list(parent):
        groups.setdefault(find(p), set()).add(p)
    return sorted(groups.values(), key=lambda g: min(g))


def is_connected(graph: GeometryGraph) -> bool:
    return len(components(graph)) == 1


def intersections(source: GeometryGraph | dict) -> list[Point]:
    """Interior points where two conductors cross or one ends on another's interior (before noding)."""
    if isinstance(source, dict):
        drawn = source.get("conductors") or []
        lines = [(point(c["start"]["x"], c["start"]["y"]), point(c["end"]["x"], c["end"]["y"])) for c in drawn] \
            if drawn else [(point(*a), point(*b)) for a, b in gg.conductor_lines(source)]
    else:
        lines = [(a, b) for a, b, _ in source.segments]
    found: set[Point] = set()
    for i, (a, b) in enumerate(lines):
        for c, d in lines[i + 1:]:
            denominator = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
            if abs(denominator) < 1e-12:
                continue
            t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / denominator
            s = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / denominator
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= s <= 1 + 1e-9:
                p = point(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                if p not in (a, b) or p not in (c, d):   # shared endpoints are junctions, not crossings
                    found.add(p)
    return sorted(found)


def stats(graph: GeometryGraph) -> dict[str, Any]:
    n = normalize(graph)
    degree = n.degree()
    return {"nodes": len(n.nodes()), "segments": len(n.segments), "rods": len(n.rods),
            "total_length_m": round(n.total_length_m(), 3), "components": len(components(n)),
            "junctions": sum(1 for d in degree.values() if d >= 3), "leaves": sum(1 for d in degree.values() if d == 1)}
