"""Deterministic optimizer primitives that do not depend on the solver or persistence."""

from __future__ import annotations

from copy import deepcopy
from math import ceil, isfinite
from typing import Any

from src.domain.spat.grid_geometry import geometry_conflicts, perimeter_rods
from src.domain.spat.optimizer_parameters import validate_variable_bounds


RECTANGULAR_PARAMETER_KEYS = frozenset({
    "length_m", "width_m", "conductor_spacing_x_m", "conductor_spacing_y_m",
    "rod_length_m", "rod_lengths_m", "burial_depth_m", "conductor_radius_m",
    "perimeter_extension_m", "variable_bounds",
})


def safety_utilization(*, Vs_v: float, Vt_v: float, Vs_lim_v: float, Vt_lim_v: float,
                       standard: str, edition: str) -> dict[str, Any]:
    """Report a combined utilization while keeping optimizer constraints independent."""
    values = (Vs_v, Vt_v, Vs_lim_v, Vt_lim_v)
    if any(not isinstance(value, (int, float)) or not isfinite(value) for value in values):
        raise ValueError("voltages and tolerable limits must be finite numbers")
    if Vs_v < 0 or Vt_v < 0 or Vs_lim_v <= 0 or Vt_lim_v <= 0:
        raise ValueError("actual voltages must be nonnegative and tolerable limits must be positive")
    if not standard or not edition:
        raise ValueError("the selected standard and edition must be recorded")
    step = Vs_v / Vs_lim_v
    touch = Vt_v / Vt_lim_v
    return {
        "schema_version": "spat.safety-utilization/1.0",
        "Phi": max(step, touch),
        "feasible": step <= 1.0 and touch <= 1.0,
        "constraints": {
            "step": {"actual_v": Vs_v, "limit_v": Vs_lim_v, "utilization": step, "feasible": step <= 1.0},
            "touch": {"actual_v": Vt_v, "limit_v": Vt_lim_v, "utilization": touch, "feasible": touch <= 1.0},
        },
        "criterion": {"standard": standard, "edition": edition},
    }


def _positive(parameters: dict[str, Any], key: str) -> float:
    value = parameters.get(key)
    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be a positive finite number")
    return float(value)


def generate_rectangular_grid(base_geometry: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Generate a regular grid while preserving its baseline line counts (fixed topology).

    Parameters are site dimensions (`length_m`, `width_m`), maximum line spacings on each
    axis, rod length, and an optional outward perimeter extension in metres. The requested
    spacings must produce the same number of lines as the baseline; changing topology is rejected.
    """
    if base_geometry.get("conductors"):
        raise ValueError("parametric rectangular generation requires a regular baseline geometry")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    validate_variable_bounds(parameters)
    unknown = sorted(set(parameters) - RECTANGULAR_PARAMETER_KEYS)
    if unknown:
        raise ValueError(f"unsupported rectangular-grid parameter(s): {', '.join(unknown)}")
    if "rod_length_m" in parameters and "rod_lengths_m" in parameters:
        raise ValueError("use rod_length_m or rod_lengths_m, not both")
    base_x = base_geometry.get("conductor_spacing_x_m") or base_geometry.get("conductor_spacing_m")
    base_y = base_geometry.get("conductor_spacing_y_m") or base_geometry.get("conductor_spacing_m")
    if not base_x or not base_y:
        raise ValueError("the baseline must define conductor spacing on both axes")
    old_length, old_width = _positive(base_geometry, "length_m"), _positive(base_geometry, "width_m")
    nx, ny = max(2, ceil(old_length / float(base_x)) + 1), max(2, ceil(old_width / float(base_y)) + 1)

    length = _positive(parameters, "length_m")
    width = _positive(parameters, "width_m")
    sx = _positive(parameters, "conductor_spacing_x_m")
    sy = _positive(parameters, "conductor_spacing_y_m")
    rod_length = _positive(parameters, "rod_length_m") if "rod_length_m" in parameters else float(base_geometry.get("rod_length_m", 2.4))
    burial_depth = _positive(parameters, "burial_depth_m") if "burial_depth_m" in parameters else float(base_geometry.get("burial_depth_m", 0.5))
    conductor_radius = float(parameters.get("conductor_radius_m", 0.00525))
    if not isfinite(conductor_radius) or conductor_radius <= 0:
        raise ValueError("conductor_radius_m must be a positive finite number")
    if min(length, width) < 5.0 * conductor_radius:
        raise ValueError("generated conductor segments must be at least five conductor radii long")
    extension = parameters.get("perimeter_extension_m", 0.0)
    if not isinstance(extension, (int, float)) or not isfinite(extension) or extension < 0:
        raise ValueError("perimeter_extension_m must be a nonnegative finite number")
    if max(2, ceil(length / sx) + 1) != nx or max(2, ceil(width / sy) + 1) != ny:
        raise ValueError("requested dimensions and spacings change the baseline topology")

    result = deepcopy(base_geometry)
    result["length_m"], result["width_m"] = length + 2 * extension, width + 2 * extension
    result["conductor_spacing_x_m"], result["conductor_spacing_y_m"] = sx, sy
    result.pop("conductor_spacing_m", None)
    result["rod_length_m"] = rod_length
    result["burial_depth_m"] = burial_depth
    if "rod_length_m" in parameters and result.get("rods"):
        for rod in result["rods"]:
            rod["length_m"] = rod_length
    # Center the original grid in the extended footprint. Keep rod count and all other attributes.
    if extension:
        if base_geometry.get("rods"):
            raise ValueError("perimeter extension for explicitly positioned rods is not supported")
        result["rods_count"] = int(base_geometry.get("rods_count") or 0)
    baseline_rods = len(base_geometry["rods"]) if base_geometry.get("rods") else int(base_geometry.get("rods_count") or 0)
    if "rod_lengths_m" in parameters:
        lengths = parameters["rod_lengths_m"]
        if not isinstance(lengths, list) or len(lengths) != baseline_rods:
            raise ValueError("rod_lengths_m must contain one length for each baseline rod")
        if base_geometry.get("rods"):
            rods = deepcopy(base_geometry["rods"])
        else:
            rods = [{"x": x, "y": y} for x, y in
                    perimeter_rods(baseline_rods, float(result["length_m"]), float(result["width_m"]))]
        for index, (rod, value) in enumerate(zip(rods, lengths)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"rod_lengths_m[{index}] must be a positive finite number")
            rod["length_m"] = float(value)
        result["rods"] = rods
        result["rods_count"] = baseline_rods
    if geometry_signature(result) != (nx, ny, baseline_rods):
        raise ValueError("perimeter extension changes the baseline topology")
    issues = geometry_conflicts(result)
    if issues:
        raise ValueError("generated geometry is invalid: " + "; ".join(issue["message"] for issue in issues))
    return result


def geometry_signature(geometry: dict[str, Any]) -> tuple[int, int, int]:
    """Topology signature for regular rectangular grids: X lines, Y lines, rods."""
    length, width = float(geometry["length_m"]), float(geometry["width_m"])
    sx = geometry.get("conductor_spacing_x_m") or geometry.get("conductor_spacing_m")
    sy = geometry.get("conductor_spacing_y_m") or geometry.get("conductor_spacing_m")
    if not sx or not sy:
        raise ValueError("regular geometry must define both conductor spacings")
    rods = len(geometry["rods"]) if geometry.get("rods") else int(geometry.get("rods_count") or 0)
    return max(2, ceil(length / float(sx)) + 1), max(2, ceil(width / float(sy)) + 1), rods
