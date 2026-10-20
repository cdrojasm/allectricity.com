"""Geometries for the singularity regression suite (SV-04).

Each case is a handful of explicit segments (no discretization), so every pair interaction of the
Galerkin matrix is a known situation. ``category`` names the situation in
`interaction_classifier`; the suite asserts that the classifier sees it in the geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tests.infrastructure.galerkin_reference import Homogeneous, Seg, TwoLayer

RADIUS = 0.005
DEPTH = 1.0


@dataclass(frozen=True)
class Case:
    name: str
    category: str                 # interaction category the case is built around
    segments: tuple[Seg, ...]
    ref_soil: object
    engine_soil: tuple            # ("homogeneous", rho) | ("two-layer", rho1, rho2, h) | ("n-layer", ...)
    note: str = ""


def _h(x0, x1, y=0.0, z=-DEPTH, r=RADIUS):
    return Seg((x0, y, z), (x1, y, z), r)


HOMOGENEOUS = (Homogeneous(100.0), ("homogeneous", 100.0))


def homogeneous_cases() -> list[Case]:
    soil, eng = HOMOGENEOUS
    a15 = math.radians(15.0)
    return [
        Case("single_segment", "self", (_h(0, 4),), soil, eng),
        Case("collinear_touching", "shared_endpoint", (_h(0, 2), _h(2, 4)), soil, eng,
             "equal currents on collinear halves must reproduce the single 4 m segment exactly"),
        Case("perpendicular_corner", "shared_endpoint",
             (_h(0, 3), Seg((3, 0, -DEPTH), (3, 3, -DEPTH), RADIUS)), soil, eng),
        Case("acute_corner_15deg", "shared_endpoint",
             (_h(0, 3), Seg((0, 0, -DEPTH), (3 * math.cos(a15), 3 * math.sin(a15), -DEPTH), RADIUS)), soil, eng),
        Case("horizontal_rod_t_junction", "t_junction",
             (_h(0, 4), Seg((2, 0, -DEPTH), (2, 0, -DEPTH - 3), RADIUS)), soil, eng),
        Case("crossing_same_depth", "crossing",
             (_h(-2, 2), Seg((0, -2, -DEPTH), (0, 2, -DEPTH), RADIUS)), soil, eng),
        Case("crossing_5cm_apart", "near",
             (_h(-2, 2), Seg((0, -2, -DEPTH - 0.05), (0, 2, -DEPTH - 0.05), RADIUS)), soil, eng),
        Case("parallel_3cm", "near", (_h(0, 3), _h(0, 3, y=0.03)), soil, eng),
        Case("parallel_6_radii", "near", (_h(0, 3), _h(0, 3, y=6 * RADIUS)), soil, eng),
        Case("short_next_to_long", "shared_endpoint", (_h(0, 10), _h(10, 10.1)), soil, eng),
        Case("minimum_length_stub", "shared_endpoint",
             (Seg((0, 0, -DEPTH), (2, 0, -DEPTH), 1e-4), Seg((2, 0, -DEPTH), (2.0005, 0, -DEPTH), 1e-4)), soil, eng,
             "stub of exactly 5 radii, the shortest segment the thin-wire model accepts"),
        Case("thick_conductor", "shared_endpoint", (_h(0, 1, r=0.05), _h(1, 2, r=0.05)), soil, eng),
        Case("buried_near_surface_2cm", "self", (_h(0, 3, z=-0.02),), soil, eng,
             "the image is 4 cm away: near-singular through the air boundary"),
        Case("separated_pair", "separated", (_h(0, 3), _h(20, 23)), soil, eng),
    ]


def layered_cases(rho1: float, rho2: float, h: float, label: str) -> list[Case]:
    soil, eng = TwoLayer(rho1, rho2, h), ("two-layer", rho1, rho2, h)
    mid, near_above, near_below = 0.5 * h, 0.97 * h, 1.03 * h
    return [
        Case(f"{label}_mid_layer_wire", "self", (_h(0, 4, z=-mid),), soil, eng),
        Case(f"{label}_wire_3pct_above_interface", "self", (_h(0, 4, z=-near_above),), soil, eng,
             "the first reflection is nearly at the segment"),
        Case(f"{label}_wire_3pct_below_interface", "self", (_h(0, 4, z=-near_below),), soil, eng),
        Case(f"{label}_corner_mid_layer", "shared_endpoint",
             (_h(0, 3, z=-mid), Seg((3, 0, -mid), (3, 3, -mid), RADIUS)), soil, eng),
        Case(f"{label}_rod_across_interface", "shared_endpoint",
             (Seg((0, 0, -0.3 * h), (0, 0, -h), RADIUS), Seg((0, 0, -h), (0, 0, -h - 3), RADIUS)), soil, eng,
             "a rod split at the interface: both halves touch the interface"),
    ]


CONTRASTS = {
    "K-0.5": (300.0, 100.0, 2.0),
    "K+0.82": (100.0, 1000.0, 2.0),
    "K+0.905": (100.0, 2000.0, 1.5),
    "K-0.905": (1000.0, 50.0, 1.5),
}


def all_cases() -> list[Case]:
    cases = homogeneous_cases()
    for label, (rho1, rho2, h) in CONTRASTS.items():
        cases += layered_cases(rho1, rho2, h, label)
    return cases
