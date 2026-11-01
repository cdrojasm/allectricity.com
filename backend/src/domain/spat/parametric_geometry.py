"""Parametric generation helpers for drawn grounding grids.

The helpers in this module transform an existing explicit grid without adding or
removing conductors or rods.  They are intentionally conservative: a candidate
is returned only when its geometry remains valid inside the intervenible areas
and clear of obstacles.
"""

from __future__ import annotations

from copy import deepcopy
from math import hypot, isfinite
from typing import Any

from src.domain.spat.grid_geometry import (
    MAX_CONDUCTORS,
    MAX_RODS,
    TOLERANCE_M,
    geometry_conflicts,
    grid_parts,
    perimeter_rods,
    rod_points,
)
from src.domain.spat.optimizer_parameters import validate_variable_bounds


TRACED_PARAMETER_KEYS = frozenset({
    "translate_x_m", "translate_y_m", "perimeter_extension_m", "burial_depth_m",
    "rod_length_m", "rod_lengths_m", "conductor_endpoint_deltas", "conductor_radius_m",
    "variable_bounds",
})


def _check_parameter_keys(parameters: dict[str, Any]) -> None:
    unknown = sorted(set(parameters) - TRACED_PARAMETER_KEYS)
    if unknown:
        raise ValueError(f"unsupported traced-grid parameter(s): {', '.join(unknown)}")
    if "rod_length_m" in parameters and "rod_lengths_m" in parameters:
        raise ValueError("use rod_length_m or rod_lengths_m, not both")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _explicit_topology(geometry: dict[str, Any]) -> tuple[int, int, int]:
    conductors = geometry.get("conductors")
    if not isinstance(conductors, list) or not conductors:
        raise ValueError("the baseline must contain explicit drawn conductors")
    return len(conductors), len(rod_points(geometry)), grid_parts(geometry)


def _contact_pairs(geometry: dict[str, Any]) -> frozenset[tuple[int, int]]:
    """Return the conductor contact graph; preserving it prevents topology drift."""
    lines = [
        ((float(c["start"]["x"]), float(c["start"]["y"])),
         (float(c["end"]["x"]), float(c["end"]["y"])))
        for c in geometry["conductors"]
    ]

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(p, a, b):
        return (min(a[0], b[0]) - TOLERANCE_M <= p[0] <= max(a[0], b[0]) + TOLERANCE_M
                and min(a[1], b[1]) - TOLERANCE_M <= p[1] <= max(a[1], b[1]) + TOLERANCE_M
                and abs(cross(a, b, p)) <= TOLERANCE_M * max(hypot(b[0] - a[0], b[1] - a[1]), 1.0))

    contacts = set()
    for i, (a, b) in enumerate(lines):
        for j in range(i + 1, len(lines)):
            c, d = lines[j]
            o1, o2, o3, o4 = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
            intersects = ((o1 <= 0 <= o2 or o2 <= 0 <= o1)
                          and (o3 <= 0 <= o4 or o4 <= 0 <= o3)
                          and (on_segment(c, a, b) or on_segment(d, a, b)
                               or on_segment(a, c, d) or on_segment(b, c, d)))
            if intersects:
                contacts.add((i, j))
    return frozenset(contacts)


def generate_traced_grid(
    base_geometry: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Translate or uniformly expand a drawn grid while keeping its topology fixed.

    Parameters:
      * ``translate_x_m`` / ``translate_y_m`` move the complete grid and all rods.
      * ``perimeter_extension_m`` (default 0) scales coordinates from the lower-left
        site corner so the upper and right grid bounds grow by that amount. The site
        dimensions grow by the same amount on both axes. No conductors are added.
      * ``burial_depth_m`` (optional) sets the shared depth of the grid.
      * ``rod_length_m`` (optional) sets the length of every rod, preserving count
        and positions. Without it, existing per-rod lengths are preserved.
      * ``conductor_radius_m`` sets the conductor radius used by the minimum segment
        rule (five radii, default 5.25 mm).

    Intervenible areas and obstacles remain fixed in site coordinates. The transformed
    grid is checked against them; an invalid candidate raises ``ValueError``.
    Explicit rod count, conductor count, connected component count, and conductor
    contact graph must remain unchanged.
    """
    if not isinstance(base_geometry, dict) or not isinstance(parameters, dict):
        raise ValueError("base_geometry and parameters must be objects")
    validate_variable_bounds(parameters)
    _check_parameter_keys(parameters)
    topology = _explicit_topology(base_geometry)
    contacts = _contact_pairs(base_geometry)
    baseline_rods = rod_points(base_geometry)
    old_length = _finite(base_geometry.get("length_m"), "length_m")
    old_width = _finite(base_geometry.get("width_m"), "width_m")
    if old_length <= 0 or old_width <= 0:
        raise ValueError("baseline site dimensions must be positive")

    dx = _finite(parameters.get("translate_x_m", 0.0), "translate_x_m")
    dy = _finite(parameters.get("translate_y_m", 0.0), "translate_y_m")
    extension = _finite(parameters.get("perimeter_extension_m", 0.0), "perimeter_extension_m")
    radius = _finite(parameters.get("conductor_radius_m", 0.00525), "conductor_radius_m")
    burial_depth = _finite(parameters.get("burial_depth_m", base_geometry.get("burial_depth_m", 0.5)), "burial_depth_m")
    rod_length = _finite(parameters["rod_length_m"], "rod_length_m") if "rod_length_m" in parameters else None
    if extension < 0:
        raise ValueError("perimeter_extension_m must be nonnegative")
    if radius <= 0:
        raise ValueError("conductor_radius_m must be positive")
    if burial_depth <= 0:
        raise ValueError("burial_depth_m must be positive")
    if rod_length is not None and rod_length <= 0:
        raise ValueError("rod_length_m must be positive")

    sx, sy = (old_length + extension) / old_length, (old_width + extension) / old_width
    result = deepcopy(base_geometry)
    if baseline_rods:
        result["rods"] = [
            {"x": x, "y": y, "length_m": length}
            for x, y, length in baseline_rods
        ]
    result["length_m"], result["width_m"] = old_length + extension, old_width + extension
    result["burial_depth_m"] = burial_depth
    if rod_length is not None:
        result["rod_length_m"] = rod_length
        for rod in result.get("rods") or []:
            rod["length_m"] = rod_length
    for conductor in result["conductors"]:
        for endpoint in (conductor["start"], conductor["end"]):
            endpoint["x"] = round(float(endpoint["x"]) * sx + dx, 6)
            endpoint["y"] = round(float(endpoint["y"]) * sy + dy, 6)
    for rod in result.get("rods") or []:
        rod["x"] = round(float(rod["x"]) * sx + dx, 6)
        rod["y"] = round(float(rod["y"]) * sy + dy, 6)

    lengths = parameters.get("rod_lengths_m")
    if lengths is not None:
        if not isinstance(lengths, list) or len(lengths) != len(result.get("rods") or []):
            raise ValueError("rod_lengths_m must contain one length for each explicit rod")
        for index, (rod, value) in enumerate(zip(result["rods"], lengths)):
            length = _finite(value, f"rod_lengths_m[{index}]")
            if length <= 0:
                raise ValueError(f"rod_lengths_m[{index}] must be positive")
            rod["length_m"] = length

    endpoint_deltas = parameters.get("conductor_endpoint_deltas")
    if endpoint_deltas is not None:
        if not isinstance(endpoint_deltas, list) or len(endpoint_deltas) != len(result["conductors"]):
            raise ValueError("conductor_endpoint_deltas must contain one entry per conductor")
        delta_keys = {"start_dx_m", "start_dy_m", "end_dx_m", "end_dy_m"}
        for index, (conductor, deltas) in enumerate(zip(result["conductors"], endpoint_deltas)):
            if not isinstance(deltas, dict) or set(deltas) - delta_keys:
                raise ValueError(f"conductor_endpoint_deltas[{index}] must contain endpoint coordinate deltas")
            for endpoint, dx_key, dy_key in (("start", "start_dx_m", "start_dy_m"),
                                             ("end", "end_dx_m", "end_dy_m")):
                conductor[endpoint]["x"] = round(float(conductor[endpoint]["x"]) +
                                                   _finite(deltas.get(dx_key, 0.0), f"conductor_endpoint_deltas[{index}].{dx_key}"), 6)
                conductor[endpoint]["y"] = round(float(conductor[endpoint]["y"]) +
                                                   _finite(deltas.get(dy_key, 0.0), f"conductor_endpoint_deltas[{index}].{dy_key}"), 6)

    if topology != _explicit_topology(result) or contacts != _contact_pairs(result):
        raise ValueError("requested transformation changes the baseline topology")
    if len(result["conductors"]) > MAX_CONDUCTORS or len(result.get("rods") or []) > MAX_RODS:
        raise ValueError("generated geometry exceeds the solver element limits")
    for index, conductor in enumerate(result["conductors"]):
        a, b = conductor["start"], conductor["end"]
        if hypot(float(b["x"]) - float(a["x"]), float(b["y"]) - float(a["y"])) < 5 * radius:
            raise ValueError(f"generated conductor {index} is shorter than five conductor radii")

    issues = geometry_conflicts(result)
    if issues:
        raise ValueError("generated geometry is invalid: " + "; ".join(issue["message"] for issue in issues))
    return result
