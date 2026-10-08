"""Plan geometry of the artifact's grounding grid.

Coordinates are in metres on the plan, with the origin at one corner of the grid outline:
0 <= x <= length_m and 0 <= y <= width_m. A grid is either regular (conductors every
`conductor_spacing_x_m` along X and every `conductor_spacing_y_m` along Y; both fall back to
`conductor_spacing_m`) or drawn conductor by conductor (`conductors`). Rods are either spread
along the perimeter (`rods_count`) or placed explicitly (`rods`), and must touch a conductor.
"""

from math import ceil, hypot

TOLERANCE_M = 1e-3
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


def rod_layout(pattern: str, geometry: dict, spacing_x_m: float | None = None,
               spacing_y_m: float | None = None, count: int | None = None) -> list[dict]:
    """Rod positions for a named pattern on the grid (`corners`, `perimeter_nodes`, `grid_nodes`,
    `lattice` or `lattice_perimeter`, whose lattices use their own spacing per axis, or `count`:
    exactly `count` rods spread over the conductor junctions)."""
    length, width = float(geometry["length_m"]), float(geometry["width_m"])
    if pattern == "count":
        return _spread_rods(geometry, count)
    if pattern == "corners":
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


def geometry_problems(geometry: dict) -> list[str]:
    """Plan errors that make the grid unbuildable or impossible to calculate."""
    length, width = geometry.get("length_m"), geometry.get("width_m")
    if not all(isinstance(v, (int, float)) and v > 0 for v in (length, width)):
        return ["geometry.length_m and geometry.width_m must be positive"]
    problems = []
    if not geometry.get("conductors"):
        spacing_x, spacing_y = spacings(geometry)
        if not spacing_x or not spacing_y:
            return ["geometry needs conductor_spacing_m (or conductor_spacing_x_m and conductor_spacing_y_m) "
                    "or explicit conductors"]
        if spacing_x > length + TOLERANCE_M:
            problems.append("geometry.conductor_spacing_x_m must not exceed length_m")
        if spacing_y > width + TOLERANCE_M:
            problems.append("geometry.conductor_spacing_y_m must not exceed width_m")
        if problems:
            return problems
    lines = conductor_lines(geometry)
    if len(lines) > MAX_CONDUCTORS:
        problems.append(f"the grid has {len(lines)} conductors; the limit is {MAX_CONDUCTORS}")

    def inside(x, y):
        return -TOLERANCE_M <= x <= length + TOLERANCE_M and -TOLERANCE_M <= y <= width + TOLERANCE_M

    for index, line in enumerate(lines):
        (x1, y1), (x2, y2) = line
        if not (inside(x1, y1) and inside(x2, y2)):
            problems.append(f"geometry.conductors[{index}] leaves the grid outline (0..{length:g} x 0..{width:g} m)")
        if hypot(x2 - x1, y2 - y1) < TOLERANCE_M:
            problems.append(f"geometry.conductors[{index}] has zero length")
        for structure_index, structure in enumerate(geometry.get("structures") or []):
            if _segment_crosses_structure(line, structure):
                problems.append(f"geometry.conductors[{index}] crosses structure [{structure_index}]")
    if geometry.get("conductors"):
        for i, a in enumerate(lines):
            for j in range(i + 1, len(lines)):
                if hypot(a[1][0] - a[0][0], a[1][1] - a[0][1]) >= TOLERANCE_M and _collinear_overlap(a, lines[j]):
                    problems.append(f"geometry.conductors[{i}] and [{j}] overlap")
    rods = rod_points(geometry)
    if len(rods) > MAX_RODS:
        problems.append(f"the grid has {len(rods)} rods; the limit is {MAX_RODS}")
    for index, (x, y, _) in enumerate(rods):
        if not any(_point_segment_distance((x, y), line) <= TOLERANCE_M for line in lines):
            problems.append(f"geometry.rods[{index}] at ({x:g}, {y:g}) does not touch any conductor")
        for structure_index, structure in enumerate(geometry.get("structures") or []):
            if _point_in_structure(x, y, structure):
                problems.append(f"geometry.rods[{index}] is inside structure [{structure_index}]")
    for structure_index, structure in enumerate(geometry.get("structures") or []):
        half_w, half_h = float(structure["width"]) / 2, float(structure["height"]) / 2
        if not (-TOLERANCE_M <= structure["x"] - half_w and structure["x"] + half_w <= length + TOLERANCE_M
                and -TOLERANCE_M <= structure["y"] - half_h and structure["y"] + half_h <= width + TOLERANCE_M):
            problems.append(f"geometry.structures[{structure_index}] leaves the grid outline")
    return problems


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
