"""Seeded generator of drawn (free-form) grounding geometries for the fidelity benchmark.

Seven structural families (regular, diagonals, branching, irregular, dense-close, boundary, radial)
over rectangular, notched and trapezoidal intervenible areas, with optional buildings and rods of
mixed length. valid_geometry() only returns plans that pass the OP-05 geometry check. Everything
is driven by the random.Random it receives, so a seed reproduces the same geometries.
"""

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.domain.spat.optimizer_constraints import evaluate_optimizer_geometry  # noqa: E402

SITE_L, SITE_W = 36.0, 28.0
FAMILIES = ("regular", "diagonals", "branching", "irregular", "dense-close", "boundary", "radial")


def _round(v):  # snap to 5 cm so shared nodes are shared exactly
    return round(v / 0.05) * 0.05


def _components(nodes, edges):
    parent = {n: n for n in nodes}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for a, b in edges:
        parent[find(a)] = find(b)
    groups = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    return max(groups.values(), key=len)


def _area(rng):
    kind = rng.choice(("rect", "rect", "notch", "trapezoid"))
    x0, y0 = rng.uniform(1, 4), rng.uniform(1, 4)
    x1, y1 = SITE_L - rng.uniform(1, 4), SITE_W - rng.uniform(1, 4)
    if kind == "rect":
        poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    elif kind == "notch":
        nx, ny = x1 - rng.uniform(6, 14), y1 - rng.uniform(5, 10)
        poly = [(x0, y0), (x1, y0), (x1, ny), (nx, ny), (nx, y1), (x0, y1)]
    else:
        cut = rng.uniform(3, 8)
        poly = [(x0, y0), (x1, y0), (x1 - cut, y1), (x0 + cut, y1)]
    return kind, [(_round(x), _round(y)) for x, y in poly]


def _on_boundary(poly, x, y, tol=1e-6):
    for a, b in zip(poly, poly[1:] + poly[:1]):
        cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
        if abs(cross) <= tol * max(1.0, math.hypot(b[0] - a[0], b[1] - a[1])) and \
                min(a[0], b[0]) - tol <= x <= max(a[0], b[0]) + tol and min(a[1], b[1]) - tol <= y <= max(a[1], b[1]) + tol:
            return True
    return False


def _inside(poly, x, y):
    if _on_boundary(poly, x, y):
        return True
    inside = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _edge_ok(poly, structures, p, q):
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
        if not _inside(poly, x, y):
            return False
        if any(abs(x - st["x"]) < st["width"] / 2 + 0.3 and abs(y - st["y"]) < st["height"] / 2 + 0.3 for st in structures):
            return False
    return True


def generate(rng, family):
    kind, poly = _area(rng)
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    structures = []
    if rng.random() < 0.4:
        w, h = rng.uniform(3, 7), rng.uniform(3, 6)
        structures.append({"x": rng.uniform(bx0 + w, bx1 - w), "y": rng.uniform(by0 + h, by1 - h), "width": w, "height": h, "label": "edificio"})
    spacing = rng.choice((3.0, 4.0, 5.0, 6.0, 8.0)) if family != "branching" else rng.choice((5.0, 6.0, 8.0))
    jitter = rng.uniform(0.15, 0.35) * spacing if family == "irregular" else 0.0
    inset = 0.25 if family == "boundary" else 0.0
    nodes, edges = {}, set()
    cols = max(2, int((bx1 - bx0 - 2 * inset) / spacing) + 1)
    rows = max(2, int((by1 - by0 - 2 * inset) / spacing) + 1)
    sx = (bx1 - bx0 - 2 * inset) / (cols - 1)
    sy = (by1 - by0 - 2 * inset) / (rows - 1)
    for i in range(cols):
        for j in range(rows):
            x = bx0 + inset + i * sx + (rng.uniform(-jitter, jitter) if 0 < i < cols - 1 else 0)
            y = by0 + inset + j * sy + (rng.uniform(-jitter, jitter) if 0 < j < rows - 1 else 0)
            nodes[(i, j)] = (_round(x), _round(y))
    keep = {"branching": 0.5}.get(family, 1.0)
    diag = 0.55 if family == "diagonals" else 0.0
    for i in range(cols):
        for j in range(rows):
            for di, dj, p in ((1, 0, keep), (0, 1, keep), (1, 1, diag), (1, -1, diag)):
                k = (i + di, j + dj)
                if k in nodes and rng.random() < p and _edge_ok(poly, structures, nodes[(i, j)], nodes[k]):
                    edges.add(((i, j), k))
    if family == "boundary":
        for i in range(cols - 1):
            edges.add(((i, 0), (i + 1, 0))); edges.add(((i, rows - 1), (i + 1, rows - 1)))
        for j in range(rows - 1):
            edges.add(((0, j), (0, j + 1))); edges.add(((cols - 1, j), (cols - 1, j + 1)))
    if family == "radial":
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        nodes["c"] = (_round(cx), _round(cy))
        for key in [(i, 0) for i in range(cols)] + [(i, rows - 1) for i in range(cols)] + [(0, j) for j in range(rows)] + [(cols - 1, j) for j in range(rows)]:
            if rng.random() < 0.3:
                edges.add((("c"), key))
        for i in range(cols - 1):
            edges.add(((i, 0), (i + 1, 0))); edges.add(((i, rows - 1), (i + 1, rows - 1)))
        for j in range(rows - 1):
            edges.add(((0, j), (0, j + 1))); edges.add(((cols - 1, j), (cols - 1, j + 1)))
    if not edges:
        return None
    used = {n for e in edges for n in e}
    comp = set(_components(list(used), edges))
    edges = {e for e in edges if e[0] in comp and e[1] in comp}
    conductors = []
    for a, b in sorted(edges, key=str):
        (ax, ay), (bx, by) = nodes[a], nodes[b]
        if (ax, ay) != (bx, by):
            conductors.append({"start": {"x": ax, "y": ay}, "end": {"x": bx, "y": by}})
    if family == "dense-close":  # parallel conductors 0.5-1.0 m apart on some edges
        extra = []
        for c in rng.sample(conductors, k=min(len(conductors), max(2, len(conductors) // 6))):
            sx_, sy_, ex_, ey_ = c["start"]["x"], c["start"]["y"], c["end"]["x"], c["end"]["y"]
            horizontal, vertical = abs(sy_ - ey_) < 1e-9, abs(sx_ - ex_) < 1e-9
            if not (horizontal or vertical):
                continue
            magnitude = rng.choice((0.5, 0.75, 1.0))
            f0, f1 = 0.2, 0.8   # tie in the interior so no tie runs along a lattice conductor
            q0 = (_round(sx_ + f0 * (ex_ - sx_)), _round(sy_ + f0 * (ey_ - sy_)))
            q1 = (_round(sx_ + f1 * (ex_ - sx_)), _round(sy_ + f1 * (ey_ - sy_)))
            for off in rng.sample((magnitude, -magnitude), 2):
                dx, dy = (0.0, off) if horizontal else (off, 0.0)
                p1, p2 = (_round(q0[0] + dx), _round(q0[1] + dy)), (_round(q1[0] + dx), _round(q1[1] + dy))
                mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                if all(_inside(poly, *q) for q in (p1, p2, mid)) and not any(
                        abs(q[0] - st["x"]) < st["width"] / 2 + 0.3 and abs(q[1] - st["y"]) < st["height"] / 2 + 0.3
                        for st in structures for q in (p1, p2, mid)):
                    extra.append({"start": {"x": p1[0], "y": p1[1]}, "end": {"x": p2[0], "y": p2[1]}})
                    extra.append({"start": {"x": q0[0], "y": q0[1]}, "end": {"x": p1[0], "y": p1[1]}})
                    extra.append({"start": {"x": q1[0], "y": q1[1]}, "end": {"x": p2[0], "y": p2[1]}})
                    break
        conductors += extra
    total = sum(math.hypot(c["end"]["x"] - c["start"]["x"], c["end"]["y"] - c["start"]["y"]) for c in conductors)
    if not conductors or total > 520:
        return None
    node_pts = sorted({(c[k]["x"], c[k]["y"]) for c in conductors for k in ("start", "end")})
    rods = []
    for x, y in rng.sample(node_pts, k=min(len(node_pts), rng.choice((0, 0, 4, 8, 12)))):
        rods.append({"x": x, "y": y, "length_m": rng.choice((1.5, 2.4, 3.0, 6.0))})
    geometry = {
        "length_m": SITE_L, "width_m": SITE_W, "burial_depth_m": rng.choice((0.5, 0.6, 0.8, 1.0)),
        "areas": [{"type": "intervenible", "label": kind, "polygon": [{"x": x, "y": y} for x, y in poly]}],
        "structures": structures, "conductors": conductors, "rods": rods, "rod_length_m": 2.4,
    }
    meta = {"family": family, "area": kind, "conductor_count": len(conductors), "rod_count": len(rods),
            "total_length_m": round(total, 1), "structures": len(structures)}
    return geometry, meta


def valid_geometry(rng, family):
    for _ in range(200):
        out = generate(rng, family)
        if out is None:
            continue
        report = evaluate_optimizer_geometry(out[0])
        if report["status"] == "valid":
            return out
    return None
