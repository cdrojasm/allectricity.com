"""Python pipe client for the standalone C++ grounding-potential solver."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from math import ceil

PROTOCOL = "SPAT-POTENTIAL-3"
# Operational limits mirrored from services/potential_engine/src/main.cpp.
MAX_SEGMENTS = 1500
MAX_POINTS = 100_000
MAX_POINT_SEGMENT_WORK = 2.0e7
MAX_COORDINATE_M = 1.0e5
MAX_DEPTH_M = 1000.0
MIN_RADIUS_M = 1.0e-4
MAX_RADIUS_M = 0.5
MIN_LENGTH_TO_RADIUS = 5.0
MAX_RESISTIVITY_OHM_M = 1.0e6
MAX_CURRENT_A = 1.0e6
MIN_LAYER_THICKNESS_M = 0.01
IMAGE_SERIES_TOLERANCE = 1.0e-7
MAX_IMAGE_TERMS = 2000
MAX_MATRIX_IMAGE_WORK = 4.0e9
MAX_POINT_IMAGE_WORK = 4.0e9
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MEMORY_LIMIT_MB = 512


@dataclass(frozen=True)
class ElectrodeSegment:
    id: str
    group: str
    kind: str
    start_m: tuple[float, float, float]
    end_m: tuple[float, float, float]
    radius_m: float


@dataclass(frozen=True)
class PotentialPoint:
    id: str
    xyz_m: tuple[float, float, float]


@dataclass(frozen=True)
class HomogeneousSoil:
    resistivity_ohm_m: float


@dataclass(frozen=True)
class TwoLayerSoil:
    """Upper layer of `upper_thickness_m` over a semi-infinite lower layer."""

    upper_resistivity_ohm_m: float
    lower_resistivity_ohm_m: float
    upper_thickness_m: float


SoilModel = HomogeneousSoil | TwoLayerSoil


def as_soil(soil: SoilModel | float) -> SoilModel:
    """Accept a soil model or a plain homogeneous resistivity in ohm-m."""
    if isinstance(soil, (HomogeneousSoil, TwoLayerSoil)):
        return soil
    return HomogeneousSoil(float(soil))


def soil_record(soil: SoilModel) -> dict[str, Any]:
    model = "two-layer" if isinstance(soil, TwoLayerSoil) else "homogeneous"
    return {"model": model, **asdict(soil)}


def _soil_line(soil: SoilModel, segment_count: int) -> str:
    if isinstance(soil, TwoLayerSoil):
        values = (soil.upper_resistivity_ohm_m, soil.lower_resistivity_ohm_m, soil.upper_thickness_m)
        return "two-layer " + " ".join(format(float(v), ".17g") for v in values) + f" {segment_count}"
    return f"homogeneous {float(soil.resistivity_ohm_m):.17g} {segment_count}"


def image_terms(soil: TwoLayerSoil, max_depth_m: float, extent_m: float) -> int | None:
    """Image orders the engine sums for a two-layer soil (mirror of `choose_image_terms` in main.cpp).

    Returns None when the series would need more than MAX_IMAGE_TERMS orders.
    """
    rho1, rho2, h = soil.upper_resistivity_ohm_m, soil.lower_resistivity_ohm_m, soil.upper_thickness_m
    k = abs((rho2 - rho1) / (rho2 + rho1))
    c = 8.0 * max(1.0, rho2 / rho1)
    for n in range(1, MAX_IMAGE_TERMS + 1):
        gap = 2.0 * (n + 1) * h - 2.0 * max_depth_m
        if gap > h and c * k ** (n + 1) / ((1.0 - k) * gap) * extent_m <= IMAGE_SERIES_TOLERANCE:
            return n
    return None


def image_work(soil: SoilModel, segments: list[ElectrodeSegment], points: list[PotentialPoint]) -> tuple[float, float]:
    """(matrix, surface-point) image evaluations of a two-layer request; (0, 0) for homogeneous soil."""
    if not isinstance(soil, TwoLayerSoil) or soil.upper_resistivity_ohm_m == soil.lower_resistivity_ohm_m:
        return 0.0, 0.0
    xs = [c[0] for s in segments for c in (s.start_m, s.end_m)] + [p.xyz_m[0] for p in points]
    ys = [c[1] for s in segments for c in (s.start_m, s.end_m)] + [p.xyz_m[1] for p in points]
    depth = max([-c[2] for s in segments for c in (s.start_m, s.end_m)] + [abs(p.xyz_m[2]) for p in points] + [0.0])
    extent = max(1.0, math.hypot(max(xs) - min(xs), max(ys) - min(ys)) + 2.0 * depth)
    n = image_terms(soil, depth, extent)
    if n is None:
        raise ValueError("two-layer image series needs more than 2000 terms; the resistivity contrast is too high")
    sizes = [[4 * n + 2, 2 * (n + 1)], [2 * (n + 1), n + 3]]  # images[source layer][observation layer]
    lower = sum(1 for s in segments if -0.5 * (s.start_m[2] + s.end_m[2]) >= soil.upper_thickness_m)
    count = [len(segments) - lower, lower]
    matrix = sum(count[t] * count[s] * sizes[s][t] for t in range(2) for s in range(2))
    return float(matrix), float(len(points) * sum(count[s] * sizes[s][0] for s in range(2)))


def point_batch_size(soil: SoilModel, segments: list[ElectrodeSegment], points: list[PotentialPoint]) -> int:
    """Most surface points per request that respect every work limit (with a 1 % margin)."""
    batch = max(1, min(MAX_POINTS, int(MAX_POINT_SEGMENT_WORK // max(len(segments), 1))))
    _, point_work = image_work(as_soil(soil), segments, points)
    if point_work and points:
        batch = min(batch, max(1, int(0.99 * MAX_POINT_IMAGE_WORK / (point_work / len(points)))))
    return batch


def split_at_interface(segments: list[ElectrodeSegment], soil: SoilModel) -> list[ElectrodeSegment]:
    """Cut every segment that crosses the two-layer interface into an upper (`.u`) and lower (`.l`) part.

    The engine assigns each segment to the layer of its mid-point and refuses segments that cross
    the interface, so rods driven through the upper layer must be split at its depth. A part shorter
    than the thin-wire minimum (5 radii) is refused: discretise conductors with a node at the
    interface instead (`rectangular_grid_segments(interface_depth_m=...)`).
    """
    if not isinstance(soil, TwoLayerSoil):
        return list(segments)
    z = -float(soil.upper_thickness_m)
    tolerance = 1e-9 * max(1.0, float(soil.upper_thickness_m))
    result: list[ElectrodeSegment] = []
    for segment in segments:
        z1, z2 = segment.start_m[2], segment.end_m[2]
        if min(z1, z2) < z - tolerance and max(z1, z2) > z + tolerance:
            t = (z - z1) / (z2 - z1)
            cut = tuple(a + (b - a) * t for a, b in zip(segment.start_m, segment.end_m))
            cut = (cut[0], cut[1], z)
            first, second = (".u", ".l") if z1 > z2 else (".l", ".u")
            if min(_distance(segment.start_m, cut), _distance(cut, segment.end_m)) < MIN_LENGTH_TO_RADIUS * segment.radius_m:
                raise ValueError(
                    f"segment {segment.id} crosses the soil interface leaving a part shorter than 5 radii; "
                    "discretise the conductor with a node at the interface depth"
                )
            result.append(ElectrodeSegment(segment.id + first, segment.group, segment.kind, segment.start_m, cut, segment.radius_m))
            result.append(ElectrodeSegment(segment.id + second, segment.group, segment.kind, cut, segment.end_m, segment.radius_m))
        else:
            result.append(segment)
    return result


@dataclass(frozen=True)
class Segmentation:
    """How each conductor between two nodes is cut into engine segments.

    `uniform`: equal pieces of at most `max_length_m`.
    `graded`: pieces start at `node_length_m` next to critical nodes (free ends, corners, T and other
    irregular junctions, rod joints and the soil interface, where leakage current concentrates) and
    at `crossing_length_m` next to plain four-way crossings (`None`: no refinement there), then grow
    geometrically by `ratio` up to `max_length_m`. A remainder shorter than the smallest piece is
    merged into its neighbour, so a piece can exceed `max_length_m` by less than `node_length_m`.
    """

    mode: str = "uniform"
    max_length_m: float = 1.0
    node_length_m: float = 0.25
    crossing_length_m: float | None = 1.0
    ratio: float = 2.0

    def __post_init__(self) -> None:
        if self.mode not in ("uniform", "graded"):
            raise ValueError("segmentation mode must be 'uniform' or 'graded'")
        lengths = [self.max_length_m, self.node_length_m] + ([self.crossing_length_m] if self.crossing_length_m else [])
        if not all(math.isfinite(v) and v > 0 for v in lengths) or not 1.0 < self.ratio <= 4.0:
            raise ValueError("segmentation lengths must be positive and the ratio in (1, 4]")

    @classmethod
    def for_discretization(cls, mode: str, discretization_m: float) -> Segmentation:
        """Segmentation family driven by one refinement length `d`.

        `uniform`: pieces of at most `d`. `graded`: 0.25·d next to critical nodes, d next to plain
        crossings, ratio 2, at most 7·d. With d = 1 m the graded family matches the converged corner
        step voltage of IEEE 80 Annex H Grid 1 (91.24 V) within 0.01 % with 452 segments, where
        uniform 1 m pieces need 840 segments and remain 0.29 % low (validation/segmentation_study.py).
        """
        if mode == "uniform":
            return cls("uniform", discretization_m)
        return cls("graded", 7.0 * discretization_m, 0.25 * discretization_m, discretization_m, 2.0)

    def scaled(self, factor: float) -> Segmentation:
        """The same segmentation with every length multiplied by `factor` (for refinement studies)."""
        return Segmentation(self.mode, self.max_length_m * factor, self.node_length_m * factor,
                            None if self.crossing_length_m is None else self.crossing_length_m * factor, self.ratio)

    def record(self) -> dict[str, Any]:
        return asdict(self)


def graded_lengths(length: float, max_length: float, start_length: float | None, end_length: float | None,
                   ratio: float) -> list[float]:
    """Piece lengths along one conductor, growing geometrically from each refined end."""
    def ramp(first: float | None, limit: float) -> list[float]:
        pieces, size, total = [], first, 0.0
        while size is not None and size < max_length and total + size <= limit:
            pieces.append(size)
            total += size
            size *= ratio
        return pieces

    both = start_length is not None and end_length is not None
    head = ramp(start_length, length / 2 if both else length)
    tail = ramp(end_length, length / 2 if both else length)
    middle = length - sum(head) - sum(tail)
    body: list[float] = []
    if middle > 1e-12 * length:
        count = max(1, ceil(middle / max_length - 1e-9))
        smallest = min([p for p in (start_length, end_length) if p is not None], default=0.0)
        if count == 1 and middle < smallest and (head or tail):
            # Too short to stand alone: merge into the shorter neighbouring ramp piece.
            if head and (not tail or head[-1] <= tail[-1]):
                head[-1] += middle
            else:
                tail[-1] += middle
        else:
            body = [middle / count] * count
    return head + body + tail[::-1]


def _node_key(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(round(c, 6) for c in point)


def discretize(pieces: list[ElectrodeSegment], segmentation: Segmentation,
               interface_z: float | None = None) -> list[ElectrodeSegment]:
    """Cut node-to-node conductor pieces into segments following `segmentation`.

    Pieces must already end at every junction (crossings, rod joints, soil interface at
    `interface_z`). Node types are inferred from the pieces that meet there: free ends, corners,
    rod joints, irregular junctions and points on the soil interface are critical; four horizontal
    pieces form a plain crossing; two collinear pieces elsewhere are a plain split and not refined.
    """
    if segmentation.mode == "uniform":
        result: list[ElectrodeSegment] = []
        for piece in pieces:
            result += _cut(piece, [], segmentation.max_length_m)
        return result
    meeting: dict[tuple[float, float, float], list[tuple[float, float, float]]] = {}
    for piece in pieces:
        length = _distance(piece.start_m, piece.end_m)
        direction = tuple((b - a) / length for a, b in zip(piece.start_m, piece.end_m))
        meeting.setdefault(_node_key(piece.start_m), []).append(direction)
        meeting.setdefault(_node_key(piece.end_m), []).append(tuple(-c for c in direction))

    def refinement(point: tuple[float, float, float]) -> float | None:
        directions = meeting[_node_key(point)]
        horizontal = all(abs(d[2]) < 1e-9 for d in directions)
        on_interface = interface_z is not None and abs(point[2] - interface_z) < 1e-6
        if len(directions) == 2 and sum(a * b for a, b in zip(*directions)) < -1 + 1e-9 and not on_interface:
            return None
        if horizontal and len(directions) == 4:
            return segmentation.crossing_length_m
        return segmentation.node_length_m

    result = []
    for piece in pieces:
        floor = MIN_LENGTH_TO_RADIUS * piece.radius_m
        start, end = refinement(piece.start_m), refinement(piece.end_m)
        lengths = graded_lengths(_distance(piece.start_m, piece.end_m), segmentation.max_length_m,
                                 None if start is None else max(start, floor), None if end is None else max(end, floor),
                                 segmentation.ratio)
        result += _cut(piece, lengths, segmentation.max_length_m)
    return result


def _cut(piece: ElectrodeSegment, lengths: list[float], max_length: float) -> list[ElectrodeSegment]:
    total = _distance(piece.start_m, piece.end_m)
    if not lengths:
        count = max(1, ceil(total / max_length - 1e-9))
        lengths = [total / count] * count
    positions, accumulated = [0.0], 0.0
    for length in lengths:
        accumulated += length
        positions.append(accumulated / total)
    positions[-1] = 1.0
    return [
        ElectrodeSegment(
            f"{piece.id}.{k}", piece.group, piece.kind,
            tuple(a + (b - a) * positions[k] for a, b in zip(piece.start_m, piece.end_m)),
            tuple(a + (b - a) * positions[k + 1] for a, b in zip(piece.start_m, piece.end_m)),
            piece.radius_m,
        )
        for k in range(len(positions) - 1)
    ]


class PotentialEngineError(RuntimeError):
    pass


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _segment_distance(p1, q1, p2, q2) -> float:
    """Closest distance between two 3D segments."""
    d1 = [q - p for p, q in zip(p1, q1)]
    d2 = [q - p for p, q in zip(p2, q2)]
    r = [a - b for a, b in zip(p1, p2)]
    dot = lambda u, v: sum(x * y for x, y in zip(u, v))  # noqa: E731
    a, e, f, c, b = dot(d1, d1), dot(d2, d2), dot(d2, r), dot(d1, r), dot(d1, d2)
    denom = a * e - b * b
    s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-12 * a * e else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, min(max(-c / a, 0.0), 1.0)
    elif t > 1.0:
        t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    return _distance(tuple(p + d * s for p, d in zip(p1, d1)), tuple(p + d * t for p, d in zip(p2, d2)))


def validate_request(
    soil: SoilModel | float,
    segments: list[ElectrodeSegment],
    injections_a: dict[str, float],
    points: list[PotentialPoint],
    injection_origins: dict[str, str] | None = None,
) -> None:
    """Reject requests outside the engine's validated operating range before starting a process.

    Segments must already be split at a two-layer interface (see `split_at_interface`).
    """
    soil = as_soil(soil)
    if isinstance(soil, TwoLayerSoil):
        resistivities = (soil.upper_resistivity_ohm_m, soil.lower_resistivity_ohm_m)
        thickness = float(soil.upper_thickness_m)
        if not math.isfinite(thickness) or not MIN_LAYER_THICKNESS_M <= thickness <= MAX_DEPTH_M:
            raise ValueError("upper-layer thickness must be between 0.01 and 1000 m")
    else:
        resistivities = (soil.resistivity_ohm_m,)
    for rho in map(float, resistivities):
        if not math.isfinite(rho) or not 0 < rho <= MAX_RESISTIVITY_OHM_M:
            raise ValueError("soil resistivity must be in (0, 1e6] ohm-m")
    if not segments or len(segments) > MAX_SEGMENTS:
        raise ValueError(f"segment count must be between 1 and {MAX_SEGMENTS}")
    if len(points) > MAX_POINTS or len(points) * len(segments) > MAX_POINT_SEGMENT_WORK:
        raise ValueError(f"at most {MAX_POINTS} points and 2e7 points x segments per request")
    matrix_work, point_work = image_work(soil, segments, points)
    if matrix_work > MAX_MATRIX_IMAGE_WORK:
        raise ValueError("two-layer system needs more than 4e9 image evaluations; use fewer segments")
    if point_work > MAX_POINT_IMAGE_WORK:
        raise ValueError("two-layer surface query needs more than 4e9 image evaluations; split the points "
                         "into batches (see point_batch_size)")
    groups: set[str] = set()
    ids: set[str] = set()
    for segment in segments:
        _token(segment.id, "segment id"), _token(segment.group, "group id"), _token(segment.kind, "element kind")
        if segment.id in ids:
            raise ValueError(f"duplicate segment id: {segment.id}")
        ids.add(segment.id)
        groups.add(segment.group)
        coordinates = (*segment.start_m, *segment.end_m, segment.radius_m)
        if len(segment.start_m) != 3 or len(segment.end_m) != 3 or not all(map(math.isfinite, coordinates)):
            raise ValueError(f"segment {segment.id} coordinates must be finite x, y, z")
        for x, y, z in (segment.start_m, segment.end_m):
            if abs(x) > MAX_COORDINATE_M or abs(y) > MAX_COORDINATE_M or abs(z) > MAX_DEPTH_M:
                raise ValueError(f"segment {segment.id} coordinates exceed the supported extent")
            if z > 0:
                raise ValueError(f"segment {segment.id} must be at or below z=0")
        if not MIN_RADIUS_M <= segment.radius_m <= MAX_RADIUS_M:
            raise ValueError(f"segment {segment.id} radius must be between 1e-4 and 0.5 m")
        if _distance(segment.start_m, segment.end_m) < MIN_LENGTH_TO_RADIUS * segment.radius_m:
            raise ValueError(f"segment {segment.id} must be at least 5 radii long (thin-wire model)")
        if -0.5 * (segment.start_m[2] + segment.end_m[2]) < segment.radius_m:
            raise ValueError(f"segment {segment.id} lies on the surface; bury its mid-point at least one radius")
        if isinstance(soil, TwoLayerSoil):
            depths = (-segment.start_m[2], -segment.end_m[2])
            tolerance = 1e-9 * max(1.0, float(soil.upper_thickness_m))
            if min(depths) < soil.upper_thickness_m - tolerance and max(depths) > soil.upper_thickness_m + tolerance:
                raise ValueError(f"segment {segment.id} crosses the soil interface; split it with split_at_interface")
    seen: dict[tuple, str] = {}
    for segment in segments:
        ends = tuple(sorted((tuple(round(c, 9) for c in segment.start_m), tuple(round(c, 9) for c in segment.end_m))))
        if ends in seen:
            raise ValueError(f"duplicate segment geometry: {seen[ends]} and {segment.id}")
        seen[ends] = segment.id
    for i, p in enumerate(segments):
        for q in segments[i + 1:]:
            if p.group != q.group and _segment_distance(p.start_m, p.end_m, q.start_m, q.end_m) <= p.radius_m + q.radius_m:
                raise ValueError(f"segments of different groups touch or cross: {p.id} and {q.id}")
    for group, current in injections_a.items():
        _token(group, "injection group")
        if group not in groups:
            raise ValueError(f"injection group has no electrode segments: {group}")
        if not math.isfinite(float(current)) or abs(float(current)) > MAX_CURRENT_A:
            raise ValueError(f"injected current for {group} must be finite and at most 1e6 A")
    for group, origin in (injection_origins or {}).items():
        _token(origin, "injection origin")
        if group not in injections_a:
            raise ValueError(f"injection origin given for a group without injection: {group}")
    point_ids: set[str] = set()
    for point in points:
        _token(point.id, "point id")
        if point.id in point_ids:
            raise ValueError(f"duplicate point id: {point.id}")
        point_ids.add(point.id)
        x, y, z = point.xyz_m
        if not all(map(math.isfinite, point.xyz_m)) or abs(x) > MAX_COORDINATE_M or abs(y) > MAX_COORDINATE_M:
            raise ValueError(f"point {point.id} coordinates are invalid")
        if not 0 <= z <= MAX_DEPTH_M:
            raise ValueError("potential query points must be at or above z=0")


def _limit_memory(limit_mb: int):
    """Return a pre-exec hook that caps the engine's address space where the OS enforces it."""
    if not sys.platform.startswith("linux") or not limit_mb:
        return None

    def apply() -> None:
        import resource
        limit = int(limit_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return apply


def potential_difference_v(result: dict[str, Any], point_a_id: str, point_b_id: str) -> float:
    """Return absolute potential difference between two queried surface points."""
    potentials = result["potentials_v"]
    return abs(float(potentials[point_a_id]) - float(potentials[point_b_id]))


def touch_voltage_v(result: dict[str, Any], electrode_group: str, surface_point_id: str) -> float:
    """Return potential difference from an equipotential metal group to a surface point."""
    metal_v = result["groups"][electrode_group]["potential_v"]
    soil_v = result["potentials_v"][surface_point_id]
    return abs(float(metal_v) - float(soil_v))


def _token(value: str, label: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
    if not value or len(value) > 80 or any(char not in allowed for char in value):
        raise ValueError(f"{label} must use at most 80 letters, digits, _, ., : or -")
    return value


def _floats(values: tuple[float, float, float]) -> str:
    if len(values) != 3:
        raise ValueError("coordinates must contain x, y, z")
    return " ".join(format(float(value), ".17g") for value in values)


class PotentialEngineClient:
    """Runs the compiled engine once per calculation using a Popen stdin/stdout pipe."""

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
    ):
        default = Path(__file__).resolve().parents[4] / "services" / "potential_engine" / "build" / "spat-potential-engine"
        self.executable = str(executable or os.getenv("SPAT_POTENTIAL_ENGINE", default))
        self.timeout_s = timeout_s
        self.memory_limit_mb = memory_limit_mb

    def calculate(
        self,
        *,
        segments: list[ElectrodeSegment],
        injections_a: dict[str, float],
        points: list[PotentialPoint],
        soil_resistivity_ohm_m: float | None = None,
        soil: SoilModel | None = None,
        injection_origins: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Solve and return currents, potentials, solver diagnostics and a traceability record.

        Give either `soil_resistivity_ohm_m` (homogeneous soil) or `soil` (`HomogeneousSoil` or
        `TwoLayerSoil`). In two-layer soil, segments crossing the interface are split first, so
        `segment_currents_a` and the trace use the `.u`/`.l` ids of the parts.
        `injection_origins` maps each injected group to a token naming where its current came
        from (for example `user`, `fault:bus-7`); it defaults to `unspecified`.
        """
        if (soil is None) == (soil_resistivity_ohm_m is None):
            raise ValueError("give exactly one of soil_resistivity_ohm_m or soil")
        soil = as_soil(soil if soil is not None else soil_resistivity_ohm_m)
        segments = split_at_interface(segments, soil)
        validate_request(soil, segments, injections_a, points, injection_origins)
        origins = {group: (injection_origins or {}).get(group, "unspecified") for group in injections_a}
        lines = [PROTOCOL, _soil_line(soil, len(segments))]
        for segment in segments:
            row = [
                segment.id, segment.group, segment.kind, _floats(segment.start_m),
                _floats(segment.end_m), format(float(segment.radius_m), ".17g"),
            ]
            lines.append(" ".join(row))
        lines.append(str(len(injections_a)))
        for group, current in injections_a.items():
            lines.append(f"{group} {float(current):.17g} {origins[group]}")
        lines.append(str(len(points)))
        for point in points:
            lines.append(f"{point.id} {_floats(point.xyz_m)}")
        lines.append("END")
        payload = "\n".join(lines) + "\n"

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [self.executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, preexec_fn=_limit_memory(self.memory_limit_mb),
            )
        except OSError as exc:
            raise PotentialEngineError(f"could not start C++ potential engine: {exc}") from exc
        try:
            stdout, stderr = process.communicate(payload, timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise PotentialEngineError("C++ potential calculation exceeded its time limit") from exc
        if process.returncode:
            message = stdout.strip().split("\t", 2)
            detail = message[2] if len(message) > 2 and message[1] == "ERROR" else stderr.strip()
            raise PotentialEngineError(detail or f"C++ engine exited with status {process.returncode}")
        result = self._decode(stdout)
        result["trace"] = {
            **result.pop("metadata"),
            "engine_executable": self.executable,
            "engine_sha256": _file_sha256(self.executable),
            "request_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(time.monotonic() - started, 6),
            "injections": [
                {"group": group, "current_a": float(current), "origin": origins[group]}
                for group, current in injections_a.items()
            ],
            "soil": soil_record(soil),
            "segments": [asdict(segment) for segment in segments],
        }
        return result

    @staticmethod
    def _decode(stdout: str) -> dict[str, Any]:
        rows = stdout.splitlines()
        if not rows or rows[0] != f"{PROTOCOL}\tOK" or rows[-1] != "END":
            raise PotentialEngineError("C++ engine returned an invalid response")
        result: dict[str, Any] = {
            "segment_currents_a": {}, "groups": {}, "potentials_v": {},
            "diagnostics": {}, "warnings": [], "metadata": {},
        }
        for row in rows[1:-1]:
            fields = row.split("\t")
            if fields[0] == "SEGMENT" and len(fields) == 3:
                result["segment_currents_a"][fields[1]] = float(fields[2])
            elif fields[0] == "GROUP" and len(fields) == 8:
                result["groups"][fields[1]] = {
                    "injected_current_a": float(fields[2]),
                    "potential_v": float(fields[3]),
                    "resistance_to_remote_earth_ohm": None if fields[4] == "null" else float(fields[4]),
                    "injection_origin": fields[5],
                    "current_balance_error_a": float(fields[6]),
                    "potential_spread_v": float(fields[7]),
                }
            elif fields[0] == "POINT" and len(fields) == 3:
                result["potentials_v"][fields[1]] = float(fields[2])
            elif fields[0] == "DIAG" and len(fields) == 3:
                result["diagnostics"][fields[1]] = float(fields[2])
            elif fields[0] == "META" and len(fields) == 3:
                result["metadata"][fields[1]] = fields[2]
            elif fields[0] == "WARNING" and len(fields) == 3:
                result["warnings"].append({"code": fields[1], "message": fields[2]})
            else:
                raise PotentialEngineError("C++ engine returned an invalid data row")
        return result


def _file_sha256(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def rectangular_grid_segments(
    *,
    length_m: float,
    width_m: float,
    conductor_spacing_m: float,
    burial_depth_m: float,
    conductor_radius_m: float,
    group: str = "grid",
    rods_count: int = 0,
    rod_length_m: float = 2.4,
    discretization_m: float | None = None,
    interface_depth_m: float | None = None,
    segmentation: str = "uniform",
) -> list[ElectrodeSegment]:
    """Create a centered rectangular mesh and perimeter ground rods as line elements.

    With `interface_depth_m` (two-layer soil), rods crossing that depth are cut there before
    discretisation so that no segment straddles the interface. `segmentation="graded"` cuts the
    mesh at every crossing and grades each piece with `Segmentation.for_discretization`.
    """
    if segmentation == "graded":
        # Uniform pieces one conductor spacing long end exactly at the crossings (and the interface).
        pieces = rectangular_grid_segments(
            length_m=length_m, width_m=width_m, conductor_spacing_m=conductor_spacing_m,
            burial_depth_m=burial_depth_m, conductor_radius_m=conductor_radius_m, group=group,
            rods_count=rods_count, rod_length_m=rod_length_m, discretization_m=conductor_spacing_m,
            interface_depth_m=interface_depth_m,
        )
        step = float(discretization_m or conductor_spacing_m)
        return discretize(pieces, Segmentation.for_discretization("graded", step),
                          None if interface_depth_m is None else -float(interface_depth_m))
    if segmentation != "uniform":
        raise ValueError("segmentation must be 'uniform' or 'graded'")
    values = (length_m, width_m, conductor_spacing_m, burial_depth_m,
              conductor_radius_m, rod_length_m)
    if any(float(value) <= 0 for value in values) or rods_count < 0:
        raise ValueError("grid dimensions, spacing, burial depth, radius and rod length must be positive")
    max_piece = float(discretization_m or conductor_spacing_m)
    if max_piece <= 0:
        raise ValueError("discretization_m must be positive")
    step = min(float(conductor_spacing_m), max_piece)
    result: list[ElectrodeSegment] = []

    def axis_positions(span: float, target_spacing: float) -> list[float]:
        count = max(2, int(ceil(span / target_spacing)) + 1)
        return [-span / 2 + i * span / (count - 1) for i in range(count)]

    def add_line(prefix: str, kind: str, start: tuple[float, float, float], end: tuple[float, float, float], radius: float) -> None:
        pieces = max(1, int(ceil(sum((b-a)**2 for a, b in zip(start, end)) ** 0.5 / step)))
        for piece in range(pieces):
            t0, t1 = piece / pieces, (piece + 1) / pieces
            a = tuple(start[i] + (end[i] - start[i]) * t0 for i in range(3))
            b = tuple(start[i] + (end[i] - start[i]) * t1 for i in range(3))
            result.append(ElectrodeSegment(f"{prefix}_{piece}", group, kind, a, b, radius))

    z = -float(burial_depth_m)
    spacing = float(conductor_spacing_m)
    for index, y in enumerate(axis_positions(float(width_m), spacing)):
        add_line(f"grid_x{index}", "grid", (-length_m / 2, y, z), (length_m / 2, y, z), conductor_radius_m)
    for index, x in enumerate(axis_positions(float(length_m), spacing)):
        add_line(f"grid_y{index}", "grid", (x, -width_m / 2, z), (x, width_m / 2, z), conductor_radius_m)

    perimeter = 2.0 * (float(length_m) + float(width_m))
    for index in range(rods_count):
        position = perimeter * index / max(rods_count, 1)
        if position < length_m:
            x, y = -length_m / 2 + position, -width_m / 2
        elif position < length_m + width_m:
            x, y = length_m / 2, -width_m / 2 + position - length_m
        elif position < 2 * length_m + width_m:
            x, y = length_m / 2 - (position - length_m - width_m), width_m / 2
        else:
            x, y = -length_m / 2, width_m / 2 - (position - 2 * length_m - width_m)
        bottom = z - rod_length_m
        cut = -float(interface_depth_m) if interface_depth_m is not None else None
        if cut is not None and bottom < cut < z:
            if min(z - cut, cut - bottom) < MIN_LENGTH_TO_RADIUS * conductor_radius_m:
                raise ValueError("a rod crosses the soil interface within 5 radii of its end; adjust the rod "
                                 "length or the layer thickness")
            add_line(f"rod{index}u", "rod", (x, y, z), (x, y, cut), conductor_radius_m)
            add_line(f"rod{index}l", "rod", (x, y, cut), (x, y, bottom), conductor_radius_m)
        else:
            add_line(f"rod{index}", "rod", (x, y, z), (x, y, bottom), conductor_radius_m)
    return result


def rectangular_surface_points(
    *, x_min_m: float, x_max_m: float, y_min_m: float, y_max_m: float,
    spacing_m: float, z_m: float = 0.0,
) -> list[PotentialPoint]:
    """Create a regular set of points for plotting surface-potential contours."""
    if spacing_m <= 0 or x_max_m <= x_min_m or y_max_m <= y_min_m or z_m < 0:
        raise ValueError("surface bounds, spacing and elevation are invalid")
    nx = int(ceil((x_max_m - x_min_m) / spacing_m))
    ny = int(ceil((y_max_m - y_min_m) / spacing_m))
    return [
        PotentialPoint(f"surface_{ix}_{iy}", (x_min_m + (x_max_m-x_min_m)*ix/nx,
                                               y_min_m + (y_max_m-y_min_m)*iy/ny, z_m))
        for iy in range(ny + 1) for ix in range(nx + 1)
    ]
