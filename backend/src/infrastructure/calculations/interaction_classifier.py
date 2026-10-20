"""Deterministic classification of segment-pair interactions for the potential engine (SV-03).

The Galerkin coefficient between two segments is singular or nearly singular in a few distinct
geometric situations, and each one needs a different quadrature. This module names those situations
with tolerances relative to the segment sizes, so the singularity regression suite can prove that it
covers every category and the C++ engine can later report the same counts as a diagnostic.

Categories, in the order they are tested:

- ``degenerate``: shorter than 5 radii, or non-finite (the thin-wire model does not apply).
- ``self``: the pair is one segment with itself.
- ``shared_endpoint``: an endpoint of one coincides with an endpoint of the other.
- ``t_junction``: an endpoint of one lies on the interior of the other.
- ``crossing``: the segments intersect at interior points of both.
- ``near``: closest distance below ``near_factor`` times the shorter length, no contact.
- ``separated``: everything else.

``near_interface`` is a flag, not a category: the pair involves a segment whose nearest end lies
within ``interface_factor`` of its own length from a soil interface (segments crossing an interface
must already be split, so they never straddle it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

Point = tuple[float, float, float]

MIN_LENGTH_TO_RADIUS = 5.0
TOUCH_TOLERANCE = 1.0e-6   # of the shorter segment length
NEAR_FACTOR = 2.0          # matches the engine's near-field threshold (2 target lengths)
INTERFACE_FACTOR = 0.1


class Interaction(str, Enum):
    DEGENERATE = "degenerate"
    SELF = "self"
    SHARED_ENDPOINT = "shared_endpoint"
    T_JUNCTION = "t_junction"
    CROSSING = "crossing"
    NEAR = "near"
    SEPARATED = "separated"


@dataclass(frozen=True)
class Classified:
    kind: Interaction
    near_interface: bool
    gap_m: float


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Point) -> float:
    return math.sqrt(_dot(a, a))


def _length(a: Point, b: Point) -> float:
    return _norm(_sub(b, a))


def _point_to_segment(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """(distance, parameter in [0, 1]) of the closest point of segment a-b to p."""
    d = _sub(b, a)
    t = min(max(_dot(_sub(p, a), d) / _dot(d, d), 0.0), 1.0)
    q = (a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t)
    return _norm(_sub(p, q)), t


def _closest(p1: Point, q1: Point, p2: Point, q2: Point) -> tuple[float, float, float]:
    """(distance, s, t): closest points p1 + s (q1 - p1) and p2 + t (q2 - p2), s and t in [0, 1]."""
    d1, d2, r = _sub(q1, p1), _sub(q2, p2), _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    c, b = _dot(d1, r), _dot(d1, d2)
    denom = a * e - b * b
    s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-12 * a * e else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, min(max(-c / a, 0.0), 1.0)
    elif t > 1.0:
        t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    x = (p1[0] + d1[0] * s, p1[1] + d1[1] * s, p1[2] + d1[2] * s)
    y = (p2[0] + d2[0] * t, p2[1] + d2[1] * t, p2[2] + d2[2] * t)
    return _norm(_sub(x, y)), s, t


def _near_interface(a: Point, b: Point, interfaces: Sequence[float], factor: float) -> bool:
    length = _length(a, b)
    depths = (-a[2], -b[2])
    return any(min(abs(d - depth) for d in depths) <= factor * length for depth in interfaces)


def classify(a: tuple[Point, Point, float], b: tuple[Point, Point, float], *, same: bool = False,
             interfaces: Sequence[float] = (), touch_tolerance: float = TOUCH_TOLERANCE,
             near_factor: float = NEAR_FACTOR, interface_factor: float = INTERFACE_FACTOR) -> Classified:
    """Classify the interaction of segments given as ``(start, end, radius)``.

    Symmetric in ``a`` and ``b``. ``interfaces`` are interface depths in metres (positive down).
    """
    (a0, a1, ra), (b0, b1, rb) = a, b
    la, lb = _length(a0, a1), _length(b0, b1)
    finite = all(map(math.isfinite, (*a0, *a1, *b0, *b1, ra, rb)))
    if not finite or la < MIN_LENGTH_TO_RADIUS * ra or lb < MIN_LENGTH_TO_RADIUS * rb:
        return Classified(Interaction.DEGENERATE, False, math.nan)
    flag = _near_interface(a0, a1, interfaces, interface_factor) or _near_interface(b0, b1, interfaces, interface_factor)
    if same:
        return Classified(Interaction.SELF, flag, 0.0)
    gap, s, t = _closest(a0, a1, b0, b1)
    tol = touch_tolerance * min(la, lb)
    if any(_length(p, q) <= tol for p in (a0, a1) for q in (b0, b1)):
        return Classified(Interaction.SHARED_ENDPOINT, flag, gap)
    if gap <= tol:
        end_of_a = s * la <= tol or (1.0 - s) * la <= tol
        end_of_b = t * lb <= tol or (1.0 - t) * lb <= tol
        kind = Interaction.T_JUNCTION if end_of_a or end_of_b else Interaction.CROSSING
        return Classified(kind, flag, gap)
    if gap < near_factor * min(la, lb):
        return Classified(Interaction.NEAR, flag, gap)
    return Classified(Interaction.SEPARATED, flag, gap)


def classify_all(segments: Sequence[tuple[Point, Point, float]], interfaces: Sequence[float] = (),
                 **options) -> dict[str, int]:
    """Counts per category (and ``near_interface``) over all unordered pairs including self pairs."""
    counts = {kind.value: 0 for kind in Interaction}
    counts["near_interface"] = 0
    for i, first in enumerate(segments):
        for j in range(i, len(segments)):
            result = classify(first, segments[j], same=i == j, interfaces=interfaces, **options)
            counts[result.kind.value] += 1
            counts["near_interface"] += result.near_interface
    return counts
