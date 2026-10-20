"""Python pipe client for the standalone C++ grounding-potential solver."""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROTOCOL = "SPAT-POTENTIAL-3"
PROTOCOL_V4 = "SPAT-POTENTIAL-4"
PROTOCOL_V5 = "SPAT-POTENTIAL-5"
# Operational limits mirrored from services/potential_engine/src/main.cpp.
MAX_SEGMENTS = 4000
MAX_POINTS = 100_000
MAX_SCENARIOS = 1_000
MAX_SCENARIO_RESULT_ROWS = 2_000_000
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
# N-layer kernel limits (main.cpp, "N-layer soil").
MAX_LAYERS = 8
MAX_LAYER_CONTRAST = 1.0e4
DEFAULT_KERNEL_DENSITY = 10
MIN_KERNEL_DENSITY = 6
MAX_KERNEL_DENSITY = 12
MAX_KERNEL_TERMS = 120
KERNEL_DEPTH_FACTOR = 17.0
MAX_KERNEL_ERROR_BOUND = 1.0e-4
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MEMORY_LIMIT_MB = 512
DEFAULT_QUADRATURE_TOLERANCE = 1.0e-9
MIN_QUADRATURE_TOLERANCE = 1.0e-12
MAX_QUADRATURE_TOLERANCE = 1.0e-4


@dataclass(frozen=True)
class ElectrodeSegment:
    id: str
    group: str
    kind: str
    start_m: tuple[float, float, float]
    end_m: tuple[float, float, float]
    radius_m: float


@dataclass(frozen=True)
class ElectricalConnection:
    """Explicit electrical connection between two equipotential conductor groups.

    A `bond` merges groups into one ideal node. A `resistor` preserves separate node potentials
    and joins them through a finite resistance in ohms.
    """

    id: str
    kind: Literal["bond", "resistor"]
    group_a: str
    group_b: str
    resistance_ohm: float | None = None


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


@dataclass(frozen=True)
class LayerStackSoil:
    """1 to 8 horizontal layers from the surface down as (resistivity ohm-m, thickness m).

    Every layer except the last has a finite thickness; the last is a half-space (thickness None).
    Solved with the engine's n-layer kernel (`n-layer` soil line); `kernel_density` is the number of
    fitted images per decade of depth (6-12) and only matters for refinement studies.
    """

    layers: tuple[tuple[float, float | None], ...]
    kernel_density: int = DEFAULT_KERNEL_DENSITY

    def __post_init__(self) -> None:
        if not 1 <= len(self.layers) <= MAX_LAYERS:
            raise ValueError(f"layer stack must contain between 1 and {MAX_LAYERS} layers")
        for index, (rho, thickness) in enumerate(self.layers):
            if not isinstance(rho, (int, float)) or not math.isfinite(rho) or not 0 < rho <= MAX_RESISTIVITY_OHM_M:
                raise ValueError(f"soil layer {index + 1} resistivity must be in (0, 1e6] ohm-m")
            last = index == len(self.layers) - 1
            if last and thickness is not None:
                raise ValueError("the bottom soil layer must be a half-space (thickness None)")
            if not last and (thickness is None or not math.isfinite(thickness) or
                             not MIN_LAYER_THICKNESS_M <= thickness <= MAX_DEPTH_M):
                raise ValueError(f"soil layer {index + 1} thickness must be between 0.01 and 1000 m")
        rhos = [float(rho) for rho, _ in self.layers]
        if max(rhos) / min(rhos) > MAX_LAYER_CONTRAST:
            raise ValueError("n-layer resistivity contrast (max/min) exceeds 1e4")
        if not isinstance(self.kernel_density, int) or not MIN_KERNEL_DENSITY <= self.kernel_density <= MAX_KERNEL_DENSITY:
            raise ValueError("kernel_density must be an integer between 6 and 12")

    def merged(self) -> tuple[list[float], list[float]]:
        """(resistivities, finite thicknesses) after merging adjacent equal layers, as the engine does."""
        rhos, thicknesses, run = [float(self.layers[0][0])], [], 0.0
        for (rho, thickness), (below, _) in zip(self.layers, self.layers[1:]):
            run += float(thickness)
            if float(below) != float(rho):
                rhos.append(float(below))
                thicknesses.append(run)
                run = 0.0
        return rhos, thicknesses


SoilModel = HomogeneousSoil | TwoLayerSoil | LayerStackSoil


def as_soil(soil: SoilModel | float) -> SoilModel:
    """Accept a soil model or a plain homogeneous resistivity in ohm-m."""
    if isinstance(soil, (HomogeneousSoil, TwoLayerSoil, LayerStackSoil)):
        return soil
    return HomogeneousSoil(float(soil))


def soil_record(soil: SoilModel) -> dict[str, Any]:
    if isinstance(soil, LayerStackSoil):
        return {"model": "n-layer", "layers": [
            {"resistivity_ohm_m": rho, "thickness_m": thickness} for rho, thickness in soil.layers
        ], "kernel_density": soil.kernel_density}
    model = "two-layer" if isinstance(soil, TwoLayerSoil) else "homogeneous"
    return {"model": model, **asdict(soil)}


def _soil_line(soil: SoilModel, segment_count: int,
               quadrature_tolerance: float = DEFAULT_QUADRATURE_TOLERANCE) -> str:
    if isinstance(soil, LayerStackSoil):
        values = []
        for rho, thickness in soil.layers:
            values += [format(float(rho), ".17g"), "inf" if thickness is None else format(float(thickness), ".17g")]
        return f"n-layer {len(soil.layers)} " + " ".join(values) + f" {soil.kernel_density} {segment_count} {quadrature_tolerance:.17g}"
    if isinstance(soil, TwoLayerSoil):
        values = (soil.upper_resistivity_ohm_m, soil.lower_resistivity_ohm_m, soil.upper_thickness_m)
        return "two-layer " + " ".join(format(float(v), ".17g") for v in values) + f" {segment_count} {quadrature_tolerance:.17g}"
    return f"homogeneous {float(soil.resistivity_ohm_m):.17g} {segment_count} {quadrature_tolerance:.17g}"


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


def interface_depths(soil: SoilModel) -> tuple[float, ...]:
    """Depths (m, positive down) of the interfaces the engine distinguishes, increasing."""
    if isinstance(soil, TwoLayerSoil):
        return (float(soil.upper_thickness_m),)
    if isinstance(soil, LayerStackSoil):
        depths, depth = [], 0.0
        for thickness in soil.merged()[1]:
            depth += thickness
            depths.append(depth)
        return tuple(depths)
    return ()


def _layer_of(depth: float, interfaces: tuple[float, ...]) -> int:
    """Layer index of a depth; a point on an interface belongs to the layer below (as main.cpp)."""
    return sum(1 for interface in interfaces if depth >= interface)


def kernel_terms(soil: LayerStackSoil) -> int:
    """Fitted images per coefficient function of the n-layer kernel (mirror of `kernel_plan`); 0 if homogeneous."""
    rhos, thicknesses = soil.merged()
    if len(rhos) == 1:
        return 0
    kappa = (max(rhos) - min(rhos)) / (max(rhos) + min(rhos))
    b_min = min(thicknesses)
    b_max = max(4.0 * b_min, 2.0 * sum(thicknesses) * KERNEL_DEPTH_FACTOR / (1.0 - kappa))
    return math.ceil(math.log10(b_max / b_min) * soil.kernel_density) + 1


def _nlayer_images(soil: LayerStackSoil) -> list[list[int]]:
    """images[source layer][observation layer] of the n-layer kernel (mirror of `nlayer_table`)."""
    count, terms = len(soil.merged()[0]), kernel_terms(soil)
    if terms > MAX_KERNEL_TERMS:
        raise ValueError(f"n-layer kernel needs {terms} images per coefficient (limit {MAX_KERNEL_TERMS}); the "
                         "resistivity contrast or the ratio of total depth to thinnest layer is too high")
    return [[(1 if i == j else 0) + (2 if i < count - 1 else 1) * (2 if j < count - 1 else 1) * (terms + 1)
             for j in range(count)] for i in range(count)]


def image_work(soil: SoilModel, segments: list[ElectrodeSegment], points: list[PotentialPoint]) -> tuple[float, float]:
    """(matrix, surface-point) image evaluations of a layered request; (0, 0) when solved as homogeneous."""
    if isinstance(soil, LayerStackSoil):
        interfaces = interface_depths(soil)
        if not interfaces:
            return 0.0, 0.0
        sizes = _nlayer_images(soil)
    elif not isinstance(soil, TwoLayerSoil) or soil.upper_resistivity_ohm_m == soil.lower_resistivity_ohm_m:
        return 0.0, 0.0
    else:
        interfaces = interface_depths(soil)
        xs = [c[0] for s in segments for c in (s.start_m, s.end_m)] + [p.xyz_m[0] for p in points]
        ys = [c[1] for s in segments for c in (s.start_m, s.end_m)] + [p.xyz_m[1] for p in points]
        depth = max([-c[2] for s in segments for c in (s.start_m, s.end_m)] + [abs(p.xyz_m[2]) for p in points] + [0.0])
        extent = max(1.0, math.hypot(max(xs) - min(xs), max(ys) - min(ys)) + 2.0 * depth)
        n = image_terms(soil, depth, extent)
        if n is None:
            raise ValueError("two-layer image series needs more than 2000 terms; the resistivity contrast is too high")
        sizes = [[4 * n + 2, 2 * (n + 1)], [2 * (n + 1), n + 3]]  # images[source layer][observation layer]
    count = [0] * len(sizes)
    for s in segments:
        count[_layer_of(-0.5 * (s.start_m[2] + s.end_m[2]), interfaces)] += 1
    layers = range(len(sizes))
    matrix = sum(count[t] * count[s] * sizes[s][t] for t in layers for s in layers)
    return float(matrix), float(len(points) * sum(count[s] * sizes[s][0] for s in layers))


def point_batch_size(soil: SoilModel, segments: list[ElectrodeSegment], points: list[PotentialPoint]) -> int:
    """Most surface points per request that respect every work limit (with a 1 % margin)."""
    batch = max(1, min(MAX_POINTS, int(MAX_POINT_SEGMENT_WORK // max(len(segments), 1))))
    _, point_work = image_work(as_soil(soil), segments, points)
    if point_work and points:
        batch = min(batch, max(1, int(0.99 * MAX_POINT_IMAGE_WORK / (point_work / len(points)))))
    return batch


def split_at_interface(segments: list[ElectrodeSegment], soil: SoilModel) -> list[ElectrodeSegment]:
    """Cut every segment at each soil interface it crosses, keeping group, kind and radius.

    The engine assigns each segment to the layer of its mid-point and refuses segments that cross an
    interface, so rods driven through several layers must be split at every interface depth. Cuts are
    ordered along the segment from `start_m` to `end_m` (also when it runs from deep to shallow).
    Two-layer parts keep the historical ids `<id>.u` / `<id>.l`; n-layer parts are `<id>.L<k>` with k
    the 1-based layer of the part, unique because a straight segment crosses each layer once. A part
    shorter than the thin-wire minimum (5 radii) is refused: discretise conductors with a node at the
    interface instead (`rectangular_grid_segments(interface_depths_m=...)`). A generated id that
    collides with another segment id, or is longer than 80 characters, is refused.
    """
    interfaces = interface_depths(soil)
    if not interfaces:
        return list(segments)
    taken = {segment.id for segment in segments}
    result: list[ElectrodeSegment] = []
    for segment in segments:
        z1, z2 = segment.start_m[2], segment.end_m[2]
        cuts: list[tuple[float, tuple[float, float, float]]] = []
        for depth in interfaces:
            z = -depth
            tolerance = 1e-9 * max(1.0, depth)
            if min(z1, z2) < z - tolerance and max(z1, z2) > z + tolerance:
                t = (z - z1) / (z2 - z1)
                point = tuple(a + (b - a) * t for a, b in zip(segment.start_m, segment.end_m))
                cuts.append((t, (point[0], point[1], z)))
        if not cuts:
            result.append(segment)
            continue
        nodes = [segment.start_m] + [point for _, point in sorted(cuts)] + [segment.end_m]
        pieces = list(zip(nodes, nodes[1:]))
        if any(_distance(start, end) < MIN_LENGTH_TO_RADIUS * segment.radius_m for start, end in pieces):
            raise ValueError(
                f"segment {segment.id} crosses a soil interface leaving a part shorter than 5 radii; "
                "discretise the conductor with a node at the interface depth"
            )
        for start, end in pieces:
            layer = _layer_of(-0.5 * (start[2] + end[2]), interfaces)
            if isinstance(soil, TwoLayerSoil):
                suffix = ".u" if layer == 0 else ".l"
            else:
                suffix = f".L{layer + 1}"
            part_id = segment.id + suffix
            if part_id in taken or len(part_id) > 80:
                raise ValueError(f"cannot name the part of segment {segment.id} in layer {layer + 1}: {part_id} "
                                 "is already used or longer than 80 characters; rename the segment")
            taken.add(part_id)
            result.append(ElectrodeSegment(part_id, segment.group, segment.kind, start, end, segment.radius_m))
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
               interface_z: float | tuple[float, ...] | list[float] | None = None) -> list[ElectrodeSegment]:
    """Cut node-to-node conductor pieces into segments following `segmentation`.

    Pieces must already end at every junction (crossings, rod joints, soil interfaces at
    `interface_z`, one height or several, z < 0). Node types are inferred from the pieces that meet there: free ends, corners,
    rod joints, irregular junctions and points on the soil interface are critical; four horizontal
    pieces form a plain crossing; two collinear pieces elsewhere are a plain split and not refined.
    """
    if segmentation.mode == "uniform":
        result: list[ElectrodeSegment] = []
        for piece in pieces:
            result += _cut(piece, [], segmentation.max_length_m)
        return result
    interface_heights = () if interface_z is None else (
        (float(interface_z),) if isinstance(interface_z, (int, float)) else tuple(map(float, interface_z)))
    meeting: dict[tuple[float, float, float], list[tuple[float, float, float]]] = {}
    for piece in pieces:
        length = _distance(piece.start_m, piece.end_m)
        direction = tuple((b - a) / length for a, b in zip(piece.start_m, piece.end_m))
        meeting.setdefault(_node_key(piece.start_m), []).append(direction)
        meeting.setdefault(_node_key(piece.end_m), []).append(tuple(-c for c in direction))

    def refinement(point: tuple[float, float, float]) -> float | None:
        directions = meeting[_node_key(point)]
        horizontal = all(abs(d[2]) < 1e-9 for d in directions)
        on_interface = any(abs(point[2] - z) < 1e-6 for z in interface_heights)
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
    connections: list[ElectricalConnection] | None = None,
) -> None:
    """Reject requests outside the engine's validated operating range before starting a process.

    Segments must already be split at a two-layer interface (see `split_at_interface`).
    """
    soil = as_soil(soil)
    if isinstance(soil, LayerStackSoil):
        resistivities = tuple(rho for rho, _ in soil.layers)  # thicknesses checked by the dataclass
    elif isinstance(soil, TwoLayerSoil):
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
    label = "n-layer" if isinstance(soil, LayerStackSoil) else "two-layer"
    if matrix_work > MAX_MATRIX_IMAGE_WORK:
        raise ValueError(f"{label} system needs more than 4e9 image evaluations; use fewer segments")
    if point_work > MAX_POINT_IMAGE_WORK:
        raise ValueError(f"{label} surface query needs more than 4e9 image evaluations; split the points "
                         "into batches (see point_batch_size)")
    interfaces = interface_depths(soil)
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
        depths = (-segment.start_m[2], -segment.end_m[2])
        for depth in interfaces:
            tolerance = 1e-9 * max(1.0, depth)
            if min(depths) < depth - tolerance and max(depths) > depth + tolerance:
                raise ValueError(f"segment {segment.id} crosses the soil interface at {depth:g} m; "
                                 "split it with split_at_interface")
    seen: dict[tuple, str] = {}
    for segment in segments:
        ends = tuple(sorted((tuple(round(c, 9) for c in segment.start_m), tuple(round(c, 9) for c in segment.end_m))))
        if ends in seen:
            raise ValueError(f"duplicate segment geometry: {seen[ends]} and {segment.id}")
        seen[ends] = segment.id
    for i, p in enumerate(segments):
        for q in segments[i + 1:]:
            if not connections and p.group != q.group and _segment_distance(p.start_m, p.end_m, q.start_m, q.end_m) <= p.radius_m + q.radius_m:
                raise ValueError(f"segments of different groups touch or cross: {p.id} and {q.id}")
    connection_ids: set[str] = set()
    for connection in connections or []:
        _token(connection.id, "connection id")
        _token(connection.group_a, "connection group")
        _token(connection.group_b, "connection group")
        if connection.id in connection_ids:
            raise ValueError(f"duplicate connection id: {connection.id}")
        connection_ids.add(connection.id)
        if connection.group_a == connection.group_b:
            raise ValueError(f"connection {connection.id} must join two different groups")
        if connection.group_a not in groups or connection.group_b not in groups:
            raise ValueError(f"connection {connection.id} references a group without electrode segments")
        if connection.kind not in ("bond", "resistor"):
            raise ValueError(f"connection {connection.id} kind must be bond or resistor")
        if connection.kind == "bond":
            if connection.resistance_ohm is not None:
                raise ValueError(f"ideal bond {connection.id} must not include resistance_ohm")
        elif (connection.resistance_ohm is None or not math.isfinite(connection.resistance_ohm)
              or not 1e-9 <= connection.resistance_ohm <= 1e9):
            raise ValueError(f"resistor {connection.id} resistance must be between 1e-9 and 1e9 ohm")
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
        if z != 0 and len(interfaces) > 0 and isinstance(soil, LayerStackSoil):
            raise ValueError(f"n-layer potential query points must lie on the surface (z = 0); point {point.id}")


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
        quadrature_tolerance: float = DEFAULT_QUADRATURE_TOLERANCE,
    ):
        default = Path(__file__).resolve().parents[4] / "services" / "potential_engine" / "build" / "spat-potential-engine"
        self.executable = str(executable or os.getenv("SPAT_POTENTIAL_ENGINE", default))
        self.remote_url = os.getenv("SPAT_POTENTIAL_ENGINE_URL", "").rstrip("/")
        self.timeout_s = timeout_s
        self.memory_limit_mb = memory_limit_mb
        if (not math.isfinite(quadrature_tolerance) or
                not MIN_QUADRATURE_TOLERANCE <= quadrature_tolerance <= MAX_QUADRATURE_TOLERANCE):
            raise ValueError(f"quadrature_tolerance must be between {MIN_QUADRATURE_TOLERANCE:g} and {MAX_QUADRATURE_TOLERANCE:g}")
        self.quadrature_tolerance = float(quadrature_tolerance)

    def calculate(
        self,
        *,
        segments: list[ElectrodeSegment],
        injections_a: dict[str, float],
        points: list[PotentialPoint],
        soil_resistivity_ohm_m: float | None = None,
        soil: SoilModel | None = None,
        injection_origins: dict[str, str] | None = None,
        connections: list[ElectricalConnection] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Solve and return currents, potentials, solver diagnostics and a traceability record.

        Give either `soil_resistivity_ohm_m` (homogeneous soil) or `soil` (`HomogeneousSoil`,
        `TwoLayerSoil` or `LayerStackSoil`). Segments crossing an interface are split first, so
        `segment_currents_a` and the trace use the ids of the parts (`.u`/`.l` in two-layer soil,
        `.L<k>` in an n-layer stack; see `split_at_interface`).
        `injection_origins` maps each injected group to a token naming where its current came
        from (for example `user`, `fault:bus-7`); it defaults to `unspecified`.
        """
        if (soil is None) == (soil_resistivity_ohm_m is None):
            raise ValueError("give exactly one of soil_resistivity_ohm_m or soil")
        soil = as_soil(soil if soil is not None else soil_resistivity_ohm_m)
        segments = split_at_interface(segments, soil)
        connections = list(connections or [])
        validate_request(soil, segments, injections_a, points, injection_origins, connections)
        origins = {group: (injection_origins or {}).get(group, "unspecified") for group in injections_a}
        protocol = PROTOCOL_V4 if connections else PROTOCOL
        lines = [protocol, _soil_line(soil, len(segments), self.quadrature_tolerance)]
        for segment in segments:
            row = [
                segment.id, segment.group, segment.kind, _floats(segment.start_m),
                _floats(segment.end_m), format(float(segment.radius_m), ".17g"),
            ]
            lines.append(" ".join(row))
        lines.append(str(len(injections_a)))
        for group, current in injections_a.items():
            lines.append(f"{group} {float(current):.17g} {origins[group]}")
        if connections:
            bonds = [item for item in connections if item.kind == "bond"]
            resistors = [item for item in connections if item.kind == "resistor"]
            lines.append(f"BOND {len(bonds)}")
            lines.extend(f"{item.id} {item.group_a} {item.group_b}" for item in bonds)
            lines.append(f"RESISTOR {len(resistors)}")
            lines.extend(f"{item.id} {item.group_a} {item.group_b} {item.resistance_ohm:.17g}" for item in resistors)
        lines.append(str(len(points)))
        for point in points:
            lines.append(f"{point.id} {_floats(point.xyz_m)}")
        lines.append("END")
        payload = "\n".join(lines) + "\n"

        started = time.monotonic()
        if self.remote_url:
            stdout = self._calculate_remote(payload, project_id)
        else:
            stdout = self._calculate_local(payload)
        result = self._decode(stdout)
        if isinstance(soil, LayerStackSoil) and result["metadata"].get("soil_model") != "n-layer":
            raise PotentialEngineError("C++ engine did not solve the n-layer soil; rebuild it (make potential-engine)")
        result["trace"] = {
            **result.pop("metadata"),
            "engine_executable": self.remote_url or self.executable,
            "engine_sha256": None if self.remote_url else _file_sha256(self.executable),
            "request_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(time.monotonic() - started, 6),
            "protocol": protocol,
            "injections": [
                {"group": group, "current_a": float(current), "origin": origins[group]}
                for group, current in injections_a.items()
            ],
            "soil": soil_record(soil),
            "segments": [asdict(segment) for segment in segments],
            "connections": [asdict(connection) for connection in connections],
        }
        return result

    def calculate_scenarios(
        self,
        *,
        scenarios: dict[str, dict[str, float]],
        segments: list[ElectrodeSegment],
        points: list[PotentialPoint],
        soil_resistivity_ohm_m: float | None = None,
        soil: SoilModel | None = None,
        injection_origins: dict[str, dict[str, str]] | None = None,
        connections: list[ElectricalConnection] | None = None,
        project_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Solve named excitation vectors against one assembled and factored system."""
        if (soil is None) == (soil_resistivity_ohm_m is None):
            raise ValueError("give exactly one of soil_resistivity_ohm_m or soil")
        if not scenarios or len(scenarios) > MAX_SCENARIOS:
            raise ValueError(f"scenario count must be between 1 and {MAX_SCENARIOS}")
        soil = as_soil(soil if soil is not None else soil_resistivity_ohm_m)
        segments = split_at_interface(segments, soil)
        connections = list(connections or [])
        origins = injection_origins or {}
        if set(origins) - set(scenarios):
            raise ValueError("injection_origins contains an unknown scenario")
        result_rows = len(scenarios) * (
            len(segments) + len(points) + len({segment.group for segment in segments}) + len(connections) + 128
        )
        if result_rows > MAX_SCENARIO_RESULT_ROWS:
            raise ValueError(f"multi-scenario response would exceed {MAX_SCENARIO_RESULT_ROWS} rows")
        lines = [PROTOCOL_V5, _soil_line(soil, len(segments), self.quadrature_tolerance)]
        for segment in segments:
            lines.append(" ".join((segment.id, segment.group, segment.kind, _floats(segment.start_m),
                                   _floats(segment.end_m), format(float(segment.radius_m), ".17g"))))
        bonds = [item for item in connections if item.kind == "bond"]
        resistors = [item for item in connections if item.kind == "resistor"]
        lines.append(f"BOND {len(bonds)}")
        lines.extend(f"{item.id} {item.group_a} {item.group_b}" for item in bonds)
        lines.append(f"RESISTOR {len(resistors)}")
        lines.extend(f"{item.id} {item.group_a} {item.group_b} {item.resistance_ohm:.17g}" for item in resistors)
        lines.append(f"SCENARIOS {len(scenarios)}")
        for scenario_id, injections in scenarios.items():
            _token(scenario_id, "scenario id")
            validate_request(soil, segments, injections, points, origins.get(scenario_id), connections)
            scenario_origins = origins.get(scenario_id) or {}
            lines.append(f"SCENARIO {scenario_id} {len(injections)}")
            for group, current in injections.items():
                lines.append(f"{group} {float(current):.17g} {scenario_origins.get(group, 'unspecified')}")
        lines.append(str(len(points)))
        for point in points:
            lines.append(f"{point.id} {_floats(point.xyz_m)}")
        lines.append("END")
        payload = "\n".join(lines) + "\n"

        started = time.monotonic()
        stdout = self._calculate_remote(payload, project_id) if self.remote_url else self._calculate_local(payload)
        results = self._decode_scenarios(stdout)
        if isinstance(soil, LayerStackSoil) and any(result["metadata"].get("soil_model") != "n-layer"
                                                   for result in results.values()):
            raise PotentialEngineError("C++ engine did not solve the n-layer soil; rebuild it (make potential-engine)")
        duration = round(time.monotonic() - started, 6)
        for scenario_id, result in results.items():
            result["trace"] = {
                **result.pop("metadata"),
                "engine_executable": self.remote_url or self.executable,
                "engine_sha256": None if self.remote_url else _file_sha256(self.executable),
                "request_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "calculated_at": datetime.now(timezone.utc).isoformat(),
                "duration_s": duration,
                "protocol": PROTOCOL_V5,
                "scenario_id": scenario_id,
                "injections": [
                    {"group": group, "current_a": float(current),
                     "origin": (origins.get(scenario_id) or {}).get(group, "unspecified")}
                    for group, current in scenarios[scenario_id].items()
                ],
                "soil": soil_record(soil),
                "segments": [asdict(segment) for segment in segments],
                "connections": [asdict(connection) for connection in connections],
            }
        return results

    def _calculate_local(self, payload: str) -> str:
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
        return stdout

    def _calculate_remote(self, payload: str, project_id: str | None = None) -> str:
        if project_id and any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for char in project_id):
            raise PotentialEngineError("project_id contains unsupported characters")
        path = f"/v1/projects/{project_id}/calculate" if project_id else "/v1/calculate"
        request = Request(
            f"{self.remote_url}{path}",
            data=payload.encode(),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return response.read().decode()
        except HTTPError as exc:
            detail = exc.read(4096).decode(errors="replace")
            raise PotentialEngineError(f"remote C++ potential engine returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise PotentialEngineError("remote C++ potential calculation exceeded its time limit") from exc

    @staticmethod
    def _decode(stdout: str) -> dict[str, Any]:
        rows = stdout.splitlines()
        if not rows or rows[0] not in (f"{PROTOCOL}\tOK", f"{PROTOCOL_V4}\tOK") or rows[-1] != "END":
            raise PotentialEngineError("C++ engine returned an invalid response")
        result: dict[str, Any] = {
            "segment_currents_a": {}, "groups": {}, "potentials_v": {},
            "connection_currents_a": {}, "diagnostics": {}, "warnings": [], "metadata": {},
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
            elif fields[0] == "CONNECTION" and len(fields) == 3:
                result["connection_currents_a"][fields[1]] = float(fields[2])
            elif fields[0] == "DIAG" and len(fields) == 3:
                result["diagnostics"][fields[1]] = float(fields[2])
            elif fields[0] == "META" and len(fields) == 3:
                result["metadata"][fields[1]] = fields[2]
            elif fields[0] == "WARNING" and len(fields) == 3:
                result["warnings"].append({"code": fields[1], "message": fields[2]})
            else:
                raise PotentialEngineError("C++ engine returned an invalid data row")
        return result

    @staticmethod
    def _decode_scenarios(stdout: str) -> dict[str, dict[str, Any]]:
        rows = stdout.splitlines()
        if not rows or rows[0] != f"{PROTOCOL_V5}\tOK" or rows[-1] != "END":
            raise PotentialEngineError("C++ engine returned an invalid multi-scenario response")
        results: dict[str, dict[str, Any]] = {}
        index = 1
        while index < len(rows) - 1:
            marker = rows[index].split("\t")
            if len(marker) != 2 or marker[0] != "SCENARIO" or marker[1] in results:
                raise PotentialEngineError("C++ engine returned an invalid scenario block")
            scenario_id = marker[1]
            index += 1
            block = []
            while index < len(rows) - 1 and rows[index] != "END_SCENARIO":
                block.append(rows[index])
                index += 1
            if index >= len(rows) - 1:
                raise PotentialEngineError("C++ engine returned an unterminated scenario block")
            decoded = PotentialEngineClient._decode("\n".join([f"{PROTOCOL}\tOK", *block, "END"]))
            results[scenario_id] = decoded
            index += 1
        if not results:
            raise PotentialEngineError("C++ engine returned no scenarios")
        return results


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
    interface_depths_m: tuple[float, ...] | list[float] | None = None,
) -> list[ElectrodeSegment]:
    """Create a centered rectangular mesh and perimeter ground rods as line elements.

    With `interface_depth_m` (two-layer soil) or `interface_depths_m` (n-layer soil, see
    `interface_depths`), rods crossing those depths are cut there before discretisation so that no
    segment straddles an interface; a rod part shorter than 5 radii is refused.
    `segmentation="graded"` cuts the mesh at every crossing and grades each piece with
    `Segmentation.for_discretization`.
    """
    depths = sorted({float(d) for d in (interface_depths_m or ())} |
                    ({float(interface_depth_m)} if interface_depth_m is not None else set()))
    if segmentation == "graded":
        # Uniform pieces one conductor spacing long end exactly at the crossings (and the interface).
        pieces = rectangular_grid_segments(
            length_m=length_m, width_m=width_m, conductor_spacing_m=conductor_spacing_m,
            burial_depth_m=burial_depth_m, conductor_radius_m=conductor_radius_m, group=group,
            rods_count=rods_count, rod_length_m=rod_length_m, discretization_m=conductor_spacing_m,
            interface_depths_m=depths,
        )
        step = float(discretization_m or conductor_spacing_m)
        return discretize(pieces, Segmentation.for_discretization("graded", step), [-d for d in depths])
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
        cuts = [-d for d in depths if bottom < -d < z]
        if not cuts:
            add_line(f"rod{index}", "rod", (x, y, z), (x, y, bottom), conductor_radius_m)
            continue
        nodes = [z] + cuts + [bottom]
        if min(a - b for a, b in zip(nodes, nodes[1:])) < MIN_LENGTH_TO_RADIUS * conductor_radius_m:
            raise ValueError("a rod crosses a soil interface within 5 radii of its end or of another interface; "
                             "adjust the rod length or the layer thicknesses")
        if len(depths) == 1:  # historical two-layer ids
            add_line(f"rod{index}u", "rod", (x, y, z), (x, y, cuts[0]), conductor_radius_m)
            add_line(f"rod{index}l", "rod", (x, y, cuts[0]), (x, y, bottom), conductor_radius_m)
            continue
        for part, (top, low) in enumerate(zip(nodes, nodes[1:])):
            add_line(f"rod{index}p{part}", "rod", (x, y, top), (x, y, low), conductor_radius_m)
    return result


def network_segments(
    *,
    lines: list[tuple[tuple[float, float], tuple[float, float]]],
    rods: list[tuple[float, float, float]],
    burial_depth_m: float,
    conductor_radius_m: float,
    group: str = "grid",
    discretization_m: float = 1.0,
    segmentation: str = "uniform",
    interface_depths_m: tuple[float, ...] | list[float] | None = None,
) -> list[ElectrodeSegment]:
    """Line elements for any network of straight buried conductors and vertical rods.

    `lines` are node-to-node conductor pieces in plan coordinates (already cut at every
    crossing, junction and rod top, see `grid_geometry.split_lines`); `rods` are (x, y, length).
    Rods are cut at the soil interfaces like in `rectangular_grid_segments`.
    """
    if segmentation not in ("uniform", "graded"):
        raise ValueError("segmentation must be 'uniform' or 'graded'")
    if burial_depth_m <= 0 or conductor_radius_m <= 0 or discretization_m <= 0:
        raise ValueError("burial depth, radius and discretization must be positive")
    depths = sorted({float(d) for d in (interface_depths_m or ())})
    z = -float(burial_depth_m)
    pieces = [ElectrodeSegment(f"line{index}", group, "grid", (a[0], a[1], z), (b[0], b[1], z), conductor_radius_m)
              for index, (a, b) in enumerate(lines)]
    for index, (x, y, length) in enumerate(rods):
        bottom = z - float(length)
        nodes = [z] + [-d for d in depths if bottom < -d < z] + [bottom]
        if min(a - b for a, b in zip(nodes, nodes[1:])) < MIN_LENGTH_TO_RADIUS * conductor_radius_m:
            raise ValueError("a rod crosses a soil interface within 5 radii of its end or of another interface; "
                             "adjust the rod length or the layer thicknesses")
        for part, (top, low) in enumerate(zip(nodes, nodes[1:])):
            pieces.append(ElectrodeSegment(f"rod{index}p{part}", group, "rod", (x, y, top), (x, y, low),
                                           conductor_radius_m))
    return discretize(pieces, Segmentation.for_discretization(segmentation, float(discretization_m)),
                      [-d for d in depths])


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
