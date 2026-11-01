"""Plan geometry of the artifact's site and grounding grid.

Coordinates are in metres on the plan, with the origin at one corner of the site:
0 <= x <= length_m and 0 <= y <= width_m. The site may be divided into polygonal `areas`:
when any is `intervenible`, the grid must stay inside them; `non_intervenible` areas and
`structures` (existing buildings, foundations...) cannot be crossed. Areas are available space:
the grid may use one of them, or part of one. A grid is either regular (conductors every
`conductor_spacing_x_m` along X and every `conductor_spacing_y_m` along Y; both fall back to
`conductor_spacing_m`) or drawn conductor by conductor (`conductors`). Rods are either spread
along the perimeter (`rods_count`) or placed explicitly (`rods`), and must touch a conductor.
"""

from collections import defaultdict
from math import ceil, floor, hypot

TOLERANCE_M = 1e-3
DEFAULT_SNAP_M = 0.5  # construction step for generated lines when geometry.snap_m is not set
MAX_CONDUCTORS = 400
MAX_RODS = 500
Line = tuple[tuple[float, float], tuple[float, float]]


def axis_positions(span: float, spacing: float) -> list[float]:
    """Equally spaced lines covering `span`, never further apart than `spacing` (engine rule)."""
    count = max(2, int(ceil(span / spacing)) + 1)
    return [i * span / (count - 1) for i in range(count)]


def spacings(geometry: dict) -> tuple[float | None, float | None]:
    base = geometry.get("conductor_spacing_m")
    return geometry.get("conductor_spacing_x_m") or base, geometry.get("conductor_spacing_y_m") or base


def is_explicit(geometry: dict) -> bool:
    return bool(geometry.get("conductors")) or bool(geometry.get("rods"))


def conductor_lines(geometry: dict) -> list[Line]:
    if geometry.get("conductors"):
        return [((c["start"]["x"], c["start"]["y"]), (c["end"]["x"], c["end"]["y"])) for c in geometry["conductors"]]
    length, width = float(geometry["length_m"]), float(geometry["width_m"])
    spacing_x, spacing_y = spacings(geometry)
    along_x = [((0.0, y), (length, y)) for y in axis_positions(width, float(spacing_y))]
    along_y = [((x, 0.0), (x, width)) for x in axis_positions(length, float(spacing_x))]
    return along_x + along_y


def footprint(geometry: dict) -> tuple[float, float, float, float]:
    """Bounding box (x_min, x_max, y_min, y_max) of the conductors: the part of the site the grid occupies."""
    points = [p for line in conductor_lines(geometry) for p in line]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def perimeter_rods(count: int, length: float, width: float) -> list[tuple[float, float]]:
    """Rods spread evenly along the outline from the origin corner (engine rule)."""
    perimeter = 2.0 * (length + width)
    points = []
    for index in range(count):
        position = perimeter * index / max(count, 1)
        if position < length:
            points.append((position, 0.0))
        elif position < length + width:
            points.append((length, position - length))
        elif position < 2 * length + width:
            points.append((length - (position - length - width), width))
        else:
            points.append((0.0, width - (position - 2 * length - width)))
    return points


def rod_points(geometry: dict) -> list[tuple[float, float, float]]:
    default_length = float(geometry.get("rod_length_m") or 2.4)
    if geometry.get("rods"):
        return [(r["x"], r["y"], float(r.get("length_m") or default_length)) for r in geometry["rods"]]
    return [(x, y, default_length) for x, y in
            perimeter_rods(int(geometry.get("rods_count") or 0), float(geometry["length_m"]), float(geometry["width_m"]))]


def site_areas(geometry: dict, kind: str) -> list[dict]:
    """Areas of one type (`intervenible` or `non_intervenible`)."""
    return [area for area in geometry.get("areas") or [] if area.get("type") == kind]


def area_polygon(area: dict) -> list[tuple[float, float]]:
    """Polygon vertices, accepting legacy rectangular area dictionaries while artifacts migrate."""
    polygon = area.get("polygon") or area.get("vertices")
    if polygon:
        return [(float(p["x"]), float(p["y"])) if isinstance(p, dict) else (float(p[0]), float(p[1]))
                for p in polygon]
    return [(float(area["x_min"]), float(area["y_min"])), (float(area["x_max"]), float(area["y_min"])),
            (float(area["x_max"]), float(area["y_max"])), (float(area["x_min"]), float(area["y_max"]))]


def _point_on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    (x, y), (ax, ay), (bx, by) = point, a, b
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    return abs(cross) <= TOLERANCE_M * max(1.0, hypot(bx - ax, by - ay)) and \
        min(ax, bx) - TOLERANCE_M <= x <= max(ax, bx) + TOLERANCE_M and \
        min(ay, by) - TOLERANCE_M <= y <= max(ay, by) + TOLERANCE_M


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    point = (x, y)
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if _point_on_segment(point, a, b):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def obstacles(geometry: dict) -> list[tuple[str, dict, dict]]:
    """Every rectangle the grid cannot enter: (name used in messages, rectangle, reference)."""
    named = [(f"structure [{i}]", s, {"kind": "structure", "index": i, "label": s.get("label")})
             for i, s in enumerate(geometry.get("structures") or [])]
    return named


def _point_in_area(x: float, y: float, area: dict) -> bool:
    return _point_in_polygon(x, y, area_polygon(area))


def _line_intersects_polygon(line: Line, polygon: list[tuple[float, float]]) -> bool:
    (x1, y1), (x2, y2) = line
    if _point_in_polygon(x1, y1, polygon) or _point_in_polygon(x2, y2, polygon):
        return True
    dx, dy = x2 - x1, y2 - y1
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if _point_on_segment(a, (x1, y1), (x2, y2)) or _point_on_segment(b, (x1, y1), (x2, y2)):
            return True
        ex, ey = b[0] - a[0], b[1] - a[1]
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-12:
            continue
        t = ((a[0] - x1) * ey - (a[1] - y1) * ex) / denominator
        u = ((a[0] - x1) * dy - (a[1] - y1) * dx) / denominator
        if -TOLERANCE_M <= t <= 1 + TOLERANCE_M and -TOLERANCE_M <= u <= 1 + TOLERANCE_M:
            return True
    return False


def _segment_within_areas(line: Line, areas: list[dict]) -> bool:
    """True when every point of the conductor lies in some area (borders included)."""
    (x1, y1), (x2, y2) = line
    dx, dy = x2 - x1, y2 - y1
    length = hypot(dx, dy)
    if length < TOLERANCE_M:
        return any(_point_in_area(x1, y1, area) for area in areas)
    cuts = [0.0, 1.0]
    for area in areas:
        polygon = area_polygon(area)
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            ex, ey = b[0] - a[0], b[1] - a[1]
            denominator = dx * ey - dy * ex
            if abs(denominator) < 1e-12:
                continue
            t = ((a[0] - x1) * ey - (a[1] - y1) * ex) / denominator
            u = ((a[0] - x1) * dy - (a[1] - y1) * dx) / denominator
            if -TOLERANCE_M <= t <= 1 + TOLERANCE_M and -TOLERANCE_M <= u <= 1 + TOLERANCE_M:
                cuts.append(min(1.0, max(0.0, t)))
    cuts = sorted(set(round(t, 10) for t in cuts))
    samples = cuts + [(a + b) / 2 for a, b in zip(cuts, cuts[1:])]
    return all(any(_point_in_area(x1 + t * dx, y1 + t * dy, area) for area in areas) for t in samples)


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + TOLERANCE_M:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _scanline_spans(polygon: list[tuple[float, float]], fixed: float, horizontal: bool,
                    low: float, high: float) -> list[tuple[float, float]]:
    crossings = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        av, bv = (a[1], b[1]) if horizontal else (a[0], b[0])
        if (av <= fixed < bv) or (bv <= fixed < av):
            u = (fixed - av) / (bv - av)
            crossings.append((a[0] + u * (b[0] - a[0])) if horizontal else (a[1] + u * (b[1] - a[1])))
    crossings = sorted(set(round(v, 8) for v in crossings))
    spans = []
    for a, b in zip(crossings[::2], crossings[1::2]):
        a, b = max(a, low), min(b, high)
        if b - a > TOLERANCE_M:
            spans.append((a, b))
    return spans


def _subtract_spans(spans: list[tuple[float, float]], blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    remaining = spans
    for cut_start, cut_end in _merge_spans(blocked):
        next_remaining = []
        for start, end in remaining:
            if cut_end <= start + TOLERANCE_M or cut_start >= end - TOLERANCE_M:
                next_remaining.append((start, end))
            else:
                if cut_start > start + TOLERANCE_M:
                    next_remaining.append((start, min(end, cut_start)))
                if cut_end < end - TOLERANCE_M:
                    next_remaining.append((max(start, cut_end), end))
        remaining = next_remaining
    return remaining


def snapped_positions(start: float, end: float, spacing: float, snap: float) -> list[float]:
    """Lines from `start` to `end` never further apart than `spacing`, interior ones on multiples of `snap`.

    The ends stay where they are (they are the zone's border); the interior lines are rounded to
    the construction step and more lines are added if rounding opened a gap wider than `spacing`.
    """
    span = end - start
    count = max(2, int(ceil(span / spacing - 1e-9)) + 1)
    while True:
        interior = {round(floor((start + i * span / (count - 1)) / snap + 0.5) * snap, 6) for i in range(1, count - 1)}
        points = sorted({round(start, 6), round(end, 6)} | {p for p in interior if start + TOLERANCE_M < p < end - TOLERANCE_M})
        if all(b - a <= spacing + TOLERANCE_M for a, b in zip(points, points[1:])) or count > span / snap + 2:
            return points
        count += 1


def _select_areas(geometry: dict, names: list | None) -> list[dict]:
    areas = site_areas(geometry, "intervenible")
    if not areas:
        raise ValueError("define the intervenible areas (geometry.areas) first")
    if not names:
        if len(areas) > 1:
            labels = ", ".join(repr(a.get("label") or i) for i, a in enumerate(areas))
            raise ValueError(f"the site has {len(areas)} intervenible areas ({labels}); say which one the grid uses")
        return areas
    chosen = []
    for name in names:
        match = [a for i, a in enumerate(areas)
                 if (isinstance(name, int) and name == i) or str(a.get("label") or "").casefold() == str(name).casefold()]
        if not match:
            raise ValueError(f"no intervenible area called {name!r}")
        chosen += [a for a in match if a not in chosen]
    return chosen


def area_grid(geometry: dict, spacing_x_m: float, spacing_y_m: float, areas: list | None = None,
              bounds: dict | None = None) -> list[dict]:
    """A regular grid inside the chosen intervenible areas, as explicit conductors.

    Areas are available space, not space to fill: `areas` names the ones the grid uses (labels or
    indexes among the intervenible areas; optional only when there is one), and `bounds`
    ({x_min, x_max, y_min, y_max}) limits the grid to a part of them. Each piece gets its own
    lattice with its border as outline and interior lines on multiples of `geometry.snap_m`; lines
    shared by neighbouring pieces are merged, and the parts that would run through structures or
    non-intervenible areas are removed.
    """
    if not (spacing_x_m and spacing_y_m and spacing_x_m > 0 and spacing_y_m > 0):
        raise ValueError("the area grid needs spacing_x_m and spacing_y_m")
    snap = float(geometry.get("snap_m") or DEFAULT_SNAP_M)
    pieces = []
    for area in _select_areas(geometry, areas):
        polygon = area_polygon(area)
        x_min, x_max = min(p[0] for p in polygon), max(p[0] for p in polygon)
        y_min, y_max = min(p[1] for p in polygon), max(p[1] for p in polygon)
        if bounds:
            x_min, x_max = max(x_min, float(bounds["x_min"])), min(x_max, float(bounds["x_max"]))
            y_min, y_max = max(y_min, float(bounds["y_min"])), min(y_max, float(bounds["y_max"]))
        if x_max - x_min > TOLERANCE_M and y_max - y_min > TOLERANCE_M:
            pieces.append((polygon, x_min, x_max, y_min, y_max))
    if not pieces:
        raise ValueError("the bounds leave no room inside the chosen areas")
    along_x, along_y = defaultdict(list), defaultdict(list)
    for polygon, x_min, x_max, y_min, y_max in pieces:
        for y in snapped_positions(y_min, y_max, spacing_y_m, snap):
            along_x[y].extend(_scanline_spans(polygon, y, True, x_min, x_max))
        for x in snapped_positions(x_min, x_max, spacing_x_m, snap):
            along_y[x].extend(_scanline_spans(polygon, x, False, y_min, y_max))
    conductors = [{"start": {"x": round(a, 6), "y": y}, "end": {"x": round(b, 6), "y": y}}
                  for y, spans in sorted(along_x.items()) for a, b in _merge_spans(spans)]
    conductors += [{"start": {"x": x, "y": round(a, 6)}, "end": {"x": x, "y": round(b, 6)}}
                   for x, spans in sorted(along_y.items()) for a, b in _merge_spans(spans)]
    for polygon, x_min, x_max, y_min, y_max in pieces:
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            if (x_min - TOLERANCE_M <= a[0] <= x_max + TOLERANCE_M and
                    y_min - TOLERANCE_M <= a[1] <= y_max + TOLERANCE_M and
                    x_min - TOLERANCE_M <= b[0] <= x_max + TOLERANCE_M and
                    y_min - TOLERANCE_M <= b[1] <= y_max + TOLERANCE_M):
                conductors.append({"start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]}})
    unique = {}
    for conductor in conductors:
        a = (round(conductor["start"]["x"], 6), round(conductor["start"]["y"], 6))
        b = (round(conductor["end"]["x"], 6), round(conductor["end"]["y"], 6))
        unique[tuple(sorted((a, b)))] = conductor
    conductors = list(unique.values())
    for _, rect, _ in obstacles(geometry):
        half_w, half_h = float(rect["width"]) / 2, float(rect["height"]) / 2
        conductors = clip_conductors(conductors, float(rect["x"]) - half_w, float(rect["x"]) + half_w,
                                     float(rect["y"]) - half_h, float(rect["y"]) + half_h)
    forbidden = [area_polygon(area) for area in geometry.get("areas") or []
                 if area.get("type") == "non_intervenible"]
    if forbidden:
        clipped = []
        for conductor in conductors:
            a = (conductor["start"]["x"], conductor["start"]["y"])
            b = (conductor["end"]["x"], conductor["end"]["y"])
            horizontal = abs(a[1] - b[1]) <= TOLERANCE_M
            vertical = abs(a[0] - b[0]) <= TOLERANCE_M
            if not (horizontal or vertical):
                clipped.append(conductor)
                continue
            fixed = a[1] if horizontal else a[0]
            low, high = sorted((a[0], b[0]) if horizontal else (a[1], b[1]))
            cuts = []
            for polygon in forbidden:
                for offset in (-TOLERANCE_M, 0.0, TOLERANCE_M):
                    cuts.extend((max(low, start - 2 * TOLERANCE_M), min(high, end + 2 * TOLERANCE_M))
                                for start, end in _scanline_spans(polygon, fixed + offset, horizontal, low, high))
            for start, end in _subtract_spans([(low, high)], cuts):
                first, last = ((start, fixed), (end, fixed)) if horizontal else ((fixed, start), (fixed, end))
                clipped.append({"start": {"x": first[0], "y": first[1]},
                                "end": {"x": last[0], "y": last[1]}})
        conductors = clipped
    return conductors


def rod_layout(pattern: str, geometry: dict, spacing_x_m: float | None = None,
               spacing_y_m: float | None = None, count: int | None = None) -> list[dict]:
    """Rod positions for a named pattern on the grid (`corners`, `perimeter_nodes`, `grid_nodes`,
    `lattice` or `lattice_perimeter`, whose lattices use their own spacing per axis, or `count`:
    exactly `count` rods spread over the conductor junctions)."""
    length, width = float(geometry["length_m"]), float(geometry["width_m"])
    if pattern == "count":
        return _spread_rods(geometry, count)
    if pattern == "corners":
        areas = site_areas(geometry, "intervenible")
        if areas:  # the corners of the intervenible areas the grid uses, not of the site
            lines = conductor_lines(geometry)
            points = sorted(p for p in {point for area in areas for point in area_polygon(area)}
                            if any(_point_segment_distance(p, line) <= TOLERANCE_M for line in lines))
        else:
            points = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]
    elif pattern in {"perimeter_nodes", "grid_nodes", "lattice", "lattice_perimeter"}:
        if pattern.startswith("lattice"):
            if not (spacing_x_m and spacing_y_m and spacing_x_m > 0 and spacing_y_m > 0):
                raise ValueError("lattice patterns need spacing_x_m and spacing_y_m")
            xs, ys = axis_positions(length, spacing_x_m), axis_positions(width, spacing_y_m)
        else:
            if geometry.get("conductors"):
                raise ValueError(f"{pattern} needs a regular grid; place rods explicitly on drawn conductors")
            spacing_x, spacing_y = spacings(geometry)
            xs, ys = axis_positions(length, float(spacing_x)), axis_positions(width, float(spacing_y))
        points = [(x, y) for x in xs for y in ys]
        if pattern.endswith("perimeter") or pattern == "perimeter_nodes":
            points = [(x, y) for x, y in points if x in (xs[0], xs[-1]) or y in (ys[0], ys[-1])]
    else:
        raise ValueError(f"Unknown rod pattern: {pattern}")
    return [{"x": round(x, 6), "y": round(y, 6)} for x, y in points]


def explicit_conductors(geometry: dict) -> list[dict]:
    """The grid as an explicit conductor list (a regular grid is expanded into its lines)."""
    return [{"start": {"x": round(a[0], 6), "y": round(a[1], 6)}, "end": {"x": round(b[0], 6), "y": round(b[1], 6)}}
            for a, b in conductor_lines(geometry)]


def clip_conductors(conductors: list[dict], x_min: float, x_max: float, y_min: float, y_max: float) -> list[dict]:
    """Remove the parts of the conductors that run through the interior of a rectangle.

    Conductors on the rectangle's border are kept, so clipping a zone leaves its outline.
    """
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("the zone needs x_min < x_max and y_min < y_max")

    def on_border(x, y):
        return (abs(x - x_min) <= TOLERANCE_M or abs(x - x_max) <= TOLERANCE_M
                or abs(y - y_min) <= TOLERANCE_M or abs(y - y_max) <= TOLERANCE_M)

    kept = []
    for conductor in conductors:
        (x1, y1), (x2, y2) = (conductor["start"]["x"], conductor["start"]["y"]), (conductor["end"]["x"], conductor["end"]["y"])
        dx, dy = x2 - x1, y2 - y1
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, x1 - x_min), (dx, x_max - x1), (-dy, y1 - y_min), (dy, y_max - y1)):
            if abs(p) < 1e-12:
                if q < 0:
                    t0, t1 = 1.0, 0.0
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
        length = hypot(dx, dy)
        inside = (t1 - t0) * length > TOLERANCE_M
        a, b = (x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy)
        same_edge = any(abs(u - v) <= TOLERANCE_M and abs(u - edge) <= TOLERANCE_M
                        for u, v, edge in ((a[0], b[0], x_min), (a[0], b[0], x_max), (a[1], b[1], y_min), (a[1], b[1], y_max)))
        if not inside or (same_edge and on_border(*a)):
            kept.append(conductor)
            continue
        for start, end in ((0.0, t0), (t1, 1.0)):
            if (end - start) * length > TOLERANCE_M:
                kept.append({"start": {"x": round(x1 + start * dx, 6), "y": round(y1 + start * dy, 6)},
                             "end": {"x": round(x1 + end * dx, 6), "y": round(y1 + end * dy, 6)}})
    return kept


def _junctions(geometry: dict) -> list[tuple[float, float]]:
    """Points where conductors meet or end, in a stable order."""
    lines = conductor_lines(geometry)
    points = set()
    for a, b in split_lines(lines, []):
        points.add((round(a[0], 6), round(a[1], 6)))
        points.add((round(b[0], 6), round(b[1], 6)))
    return sorted(points)


def _spread_rods(geometry: dict, count: int | None) -> list[dict]:
    """Exactly `count` rods on conductor junctions: corners first, then the rest of the outline,
    then the interior, each group taken at even intervals."""
    if not count or count < 1:
        raise ValueError("the count pattern needs count >= 1")
    length, width = float(geometry["length_m"]), float(geometry["width_m"])
    nodes = _junctions(geometry)
    if count > len(nodes):
        raise ValueError(f"the grid has only {len(nodes)} conductor junctions for {count} rods; "
                         "refine the spacing or place rods explicitly along the conductors")

    def on_outline(p):
        return min(p[0], length - p[0], p[1], width - p[1]) <= TOLERANCE_M

    def outline_position(p):  # distance along the outline from the origin corner, counter-clockwise
        x, y = p
        if y <= TOLERANCE_M:
            return x
        if x >= length - TOLERANCE_M:
            return length + y
        if y >= width - TOLERANCE_M:
            return 2 * length + width - x
        return 2 * (length + width) - y

    corners = [p for p in nodes if on_outline(p) and min(p[0], length - p[0]) <= TOLERANCE_M
               and min(p[1], width - p[1]) <= TOLERANCE_M]
    outline = sorted((p for p in nodes if on_outline(p) and p not in corners), key=outline_position)
    interior = [p for p in nodes if not on_outline(p)]

    def take(points, n):
        if n >= len(points):
            return list(points)
        return [points[int(i * len(points) / n)] for i in range(n)]

    chosen = take(corners, count)
    chosen += take(outline, count - len(chosen))
    chosen += take(interior, count - len(chosen))
    return [{"x": x, "y": y} for x, y in chosen]


def _point_segment_distance(point, line: Line) -> float:
    (x1, y1), (x2, y2) = line
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point[0] - x1) * dx + (point[1] - y1) * dy) / length2))
    return hypot(point[0] - (x1 + t * dx), point[1] - (y1 + t * dy))


def _point_in_structure(x: float, y: float, structure: dict) -> bool:
    half_w, half_h = float(structure["width"]) / 2, float(structure["height"]) / 2
    return (float(structure["x"]) - half_w + TOLERANCE_M < x < float(structure["x"]) + half_w - TOLERANCE_M
            and float(structure["y"]) - half_h + TOLERANCE_M < y < float(structure["y"]) + half_h - TOLERANCE_M)


def _segment_crosses_structure(line: Line, structure: dict) -> bool:
    """Return true when a conductor enters an obstacle interior; its border is allowed."""
    (x1, y1), (x2, y2) = line
    if _point_in_structure(x1, y1, structure) or _point_in_structure(x2, y2, structure):
        return True
    half_w, half_h = float(structure["width"]) / 2, float(structure["height"]) / 2
    left, right = float(structure["x"]) - half_w, float(structure["x"]) + half_w
    bottom, top = float(structure["y"]) - half_h, float(structure["y"]) + half_h
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - left), (dx, right - x1), (-dy, y1 - bottom), (dy, top - y1)):
        if abs(p) <= 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t1 - t0 <= 1e-9:
        return False
    middle = (t0 + t1) / 2
    return _point_in_structure(x1 + middle * dx, y1 + middle * dy, structure)


def _collinear_overlap(a: Line, b: Line) -> bool:
    (ax1, ay1), (ax2, ay2) = a
    dx, dy = ax2 - ax1, ay2 - ay1
    length = hypot(dx, dy)
    for point in b:
        if abs((point[0] - ax1) * dy - (point[1] - ay1) * dx) / length > TOLERANCE_M:
            return False
    project = sorted(((p[0] - ax1) * dx + (p[1] - ay1) * dy) / length for p in b)
    return min(length, project[1]) - max(0.0, project[0]) > TOLERANCE_M


def _conflict(element: str, index: int | None, kind: str, message: str, obstacle: dict | None = None,
              other: int | None = None) -> dict:
    return {"element": element, "index": index, "kind": kind, "message": message, "obstacle": obstacle, "other": other}


def geometry_conflicts(geometry: dict) -> list[dict]:
    """Plan errors that make the grid unbuildable or impossible to calculate, one per element.

    Each conflict names the element (`geometry`, `area`, `structure`, `conductor` or `rod`) and its
    index, a `kind` and, for collisions, the `obstacle` it collides with ({"kind", "index", "label"}).
    """
    length, width = geometry.get("length_m"), geometry.get("width_m")
    if not all(isinstance(v, (int, float)) and v > 0 for v in (length, width)):
        return [_conflict("geometry", None, "site", "geometry.length_m and geometry.width_m must be positive")]
    conflicts = []
    if not geometry.get("conductors"):
        spacing_x, spacing_y = spacings(geometry)
        if not spacing_x or not spacing_y:
            return [_conflict("geometry", None, "spacing",
                              "geometry needs conductor_spacing_m (or conductor_spacing_x_m and conductor_spacing_y_m) "
                              "or explicit conductors")]
        if spacing_x > length + TOLERANCE_M:
            conflicts.append(_conflict("geometry", None, "spacing", "geometry.conductor_spacing_x_m must not exceed length_m"))
        if spacing_y > width + TOLERANCE_M:
            conflicts.append(_conflict("geometry", None, "spacing", "geometry.conductor_spacing_y_m must not exceed width_m"))
        if conflicts:
            return conflicts
    for area_index, area in enumerate(geometry.get("areas") or []):
        try:
            polygon = area_polygon(area)
            valid_polygon = len(polygon) >= 3 and abs(sum(a[0] * b[1] - b[0] * a[1]
                                                          for a, b in zip(polygon, polygon[1:] + polygon[:1]))) > TOLERANCE_M
        except (KeyError, TypeError, ValueError):
            polygon, valid_polygon = [], False
        if not valid_polygon:
            conflicts.append(_conflict("area", area_index, "polygon",
                                       f"geometry.areas[{area_index}] needs a non-degenerate polygon with at least 3 vertices"))
        elif any(x < -TOLERANCE_M or y < -TOLERANCE_M or x > length + TOLERANCE_M or y > width + TOLERANCE_M
                 for x, y in polygon):
            conflicts.append(_conflict("area", area_index, "outside_site",
                                       f"geometry.areas[{area_index}] leaves the site (0..{length:g} x 0..{width:g} m)"))
    if conflicts:
        return conflicts
    allowed = site_areas(geometry, "intervenible")
    blocked = obstacles(geometry)
    explicit = bool(geometry.get("conductors"))
    if allowed and not explicit:
        conflicts.append(_conflict("geometry", None, "regular_grid_over_areas",
                                   "the regular grid covers the whole site but the site has intervenible areas; "
                                   "draw the grid inside them (explicit conductors, for example with grid_in_areas)"))
    lines = conductor_lines(geometry)
    if len(lines) > MAX_CONDUCTORS:
        conflicts.append(_conflict("geometry", None, "limit",
                                   f"the grid has {len(lines)} conductors; the limit is {MAX_CONDUCTORS}"))

    def inside(x, y):
        return -TOLERANCE_M <= x <= length + TOLERANCE_M and -TOLERANCE_M <= y <= width + TOLERANCE_M

    for index, line in enumerate(lines):
        (x1, y1), (x2, y2) = line
        if not (inside(x1, y1) and inside(x2, y2)):
            conflicts.append(_conflict("conductor", index, "outside_site",
                                       f"geometry.conductors[{index}] leaves the grid outline (0..{length:g} x 0..{width:g} m)"))
        if hypot(x2 - x1, y2 - y1) < TOLERANCE_M:
            conflicts.append(_conflict("conductor", index, "zero_length", f"geometry.conductors[{index}] has zero length"))
        for name, rect, ref in blocked:
            if _segment_crosses_structure(line, rect):
                conflicts.append(_conflict("conductor", index, "crosses_obstacle",
                                           f"geometry.conductors[{index}] crosses {name}", ref))
        for area_index, area in enumerate(geometry.get("areas") or []):
            if area.get("type") == "non_intervenible" and _line_intersects_polygon(line, area_polygon(area)):
                conflicts.append(_conflict("conductor", index, "crosses_obstacle",
                                           f"geometry.conductors[{index}] crosses non-intervenible area [{area_index}]"
                                           + (f" ({area['label']})" if area.get("label") else ""),
                                           {"kind": "area", "index": area_index, "label": area.get("label")}))
        if allowed and explicit and not _segment_within_areas(line, allowed):
            conflicts.append(_conflict("conductor", index, "outside_areas",
                                       f"geometry.conductors[{index}] leaves the intervenible areas"))
    if explicit:
        for i, a in enumerate(lines):
            for j in range(i + 1, len(lines)):
                if hypot(a[1][0] - a[0][0], a[1][1] - a[0][1]) >= TOLERANCE_M and _collinear_overlap(a, lines[j]):
                    conflicts.append(_conflict("conductor", i, "overlap", f"geometry.conductors[{i}] and [{j}] overlap",
                                               other=j))
    rods = rod_points(geometry)
    if len(rods) > MAX_RODS:
        conflicts.append(_conflict("geometry", None, "limit", f"the grid has {len(rods)} rods; the limit is {MAX_RODS}"))
    for index, (x, y, _) in enumerate(rods):
        if not any(_point_segment_distance((x, y), line) <= TOLERANCE_M for line in lines):
            conflicts.append(_conflict("rod", index, "not_on_conductor",
                                       f"geometry.rods[{index}] at ({x:g}, {y:g}) does not touch any conductor"))
        for name, rect, ref in blocked:
            if _point_in_structure(x, y, rect):
                conflicts.append(_conflict("rod", index, "inside_obstacle", f"geometry.rods[{index}] is inside {name}", ref))
        for area_index, area in enumerate(geometry.get("areas") or []):
            if area.get("type") == "non_intervenible" and _point_in_area(x, y, area):
                conflicts.append(_conflict("rod", index, "inside_obstacle",
                                           f"geometry.rods[{index}] is inside non-intervenible area [{area_index}]",
                                           {"kind": "area", "index": area_index, "label": area.get("label")}))
        if allowed and not any(_point_in_area(x, y, area) for area in allowed):
            conflicts.append(_conflict("rod", index, "outside_areas",
                                       f"geometry.rods[{index}] at ({x:g}, {y:g}) is outside the intervenible areas"))
    for structure_index, structure in enumerate(geometry.get("structures") or []):
        half_w, half_h = float(structure["width"]) / 2, float(structure["height"]) / 2
        if not (-TOLERANCE_M <= structure["x"] - half_w and structure["x"] + half_w <= length + TOLERANCE_M
                and -TOLERANCE_M <= structure["y"] - half_h and structure["y"] + half_h <= width + TOLERANCE_M):
            conflicts.append(_conflict("structure", structure_index, "outside_site",
                                       f"geometry.structures[{structure_index}] leaves the grid outline"))
    return conflicts


def geometry_problems(geometry: dict) -> list[str]:
    """Plan errors as messages (see geometry_conflicts)."""
    return [conflict["message"] for conflict in geometry_conflicts(geometry)]


def grid_parts(geometry: dict) -> int:
    """Number of electrically separate pieces of the grid (conductors that touch are joined)."""
    pieces = split_lines(conductor_lines(geometry), [])
    parent = {}

    def find(p):
        while parent.setdefault(p, p) != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for a, b in pieces:
        parent[find((round(a[0], 4), round(a[1], 4)))] = find((round(b[0], 4), round(b[1], 4)))
    return len({find(p) for p in list(parent)})


def geometry_warnings(geometry: dict) -> list[dict]:
    """Things a valid plan may still get wrong; they never block saving or calculating."""
    try:
        parts = grid_parts(geometry)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return []
    if parts > 1:
        return [{"kind": "disconnected", "parts": parts,
                 "message": f"the grid has {parts} separate parts; the calculation treats them as one conductor, "
                            "which holds only if a bonding conductor joins them"}]
    return []


def split_lines(lines: list[Line], nodes: list[tuple[float, float]]) -> list[Line]:
    """Cut every conductor at its crossings, at junctions with other conductors and at rod tops."""
    pieces = []
    for i, ((x1, y1), (x2, y2)) in enumerate(lines):
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        cuts = {0.0, 1.0}

        def add_point(px, py):
            t = ((px - x1) * dx + (py - y1) * dy) / length2
            if -1e-9 <= t <= 1 + 1e-9 and _point_segment_distance((px, py), lines[i]) <= TOLERANCE_M:
                cuts.add(min(1.0, max(0.0, t)))

        for j, ((u1, v1), (u2, v2)) in enumerate(lines):
            if i == j:
                continue
            du, dv = u2 - u1, v2 - v1
            denominator = dx * dv - dy * du
            if abs(denominator) > 1e-12:
                t = ((u1 - x1) * dv - (v1 - y1) * du) / denominator
                s = ((u1 - x1) * dy - (v1 - y1) * dx) / denominator
                if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= s <= 1 + 1e-9:
                    cuts.add(min(1.0, max(0.0, t)))
            for px, py in ((u1, v1), (u2, v2)):
                add_point(px, py)
        for px, py in nodes:
            add_point(px, py)
        ordered = sorted(cuts)
        merged = [ordered[0]]
        for t in ordered[1:]:
            if (t - merged[-1]) * length2 ** 0.5 > 1e-6:
                merged.append(t)
        merged[-1] = 1.0
        for a, b in zip(merged, merged[1:]):
            pieces.append(((x1 + a * dx, y1 + a * dy), (x1 + b * dx, y1 + b * dy)))
    return pieces


def missing_for_calculation(snapshot: dict) -> list[str]:
    """Inputs the potential calculation needs that the artifact does not have yet."""
    if snapshot.get("schema_version") == "2.0":
        entities = [*snapshot.get("networks", []), *snapshot.get("electrodes", [])]
        missing = [] if entities else ["networks/electrodes"]
        for entity in entities:
            if not entity.get("geometry"):
                missing.append(f"geometry.{entity.get('id', 'unknown')}")
    else:
        missing = [] if snapshot.get("geometry") else ["geometry"]
    layers = snapshot.get("soil_layers") or []
    if not layers:
        missing.append("soil_layers")
    elif any(layer.get("resistivity_ohm_m") is None for layer in layers):
        missing.append("soil_layers.resistivity_ohm_m")
    fault = snapshot.get("fault") or {}
    for key in ("current_a", "clearing_time_s"):
        if fault.get(key) is None:
            missing.append(f"fault.{key}")
    return missing
