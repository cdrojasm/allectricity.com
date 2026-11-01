"""Validation for bounded optimizer design variables."""

from __future__ import annotations

from math import isfinite
from typing import Any


def _numeric_paths(value: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, bool):
        return result
    if isinstance(value, (int, float)):
        if isfinite(value):
            result[prefix] = float(value)
        return result
    if isinstance(value, list):
        for index, item in enumerate(value):
            result.update(_numeric_paths(item, f"{prefix}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_numeric_paths(item, path))
    return result


def validate_variable_bounds(parameters: dict[str, Any]) -> None:
    """Ensure every supplied numeric variable stays inside its declared inclusive bounds.

    Bounds use dotted paths and zero-based list indices, for example
    `rod_lengths_m[0]` or `conductor_endpoint_deltas[2].start_dx_m`.
    """
    bounds = parameters.get("variable_bounds")
    if bounds is None:
        return
    if not isinstance(bounds, dict):
        raise ValueError("variable_bounds must be an object keyed by parameter path")
    values = _numeric_paths({key: value for key, value in parameters.items() if key != "variable_bounds"})
    for path, interval in bounds.items():
        if path not in values:
            raise ValueError(f"variable_bounds refers to unknown or nonnumeric parameter {path!r}")
        if not isinstance(interval, dict) or set(interval) != {"min", "max"}:
            raise ValueError(f"variable_bounds[{path!r}] must contain exactly min and max")
        low, high = interval["min"], interval["max"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
               for value in (low, high)):
            raise ValueError(f"variable_bounds[{path!r}] limits must be finite numbers")
        if low > high:
            raise ValueError(f"variable_bounds[{path!r}] min must not exceed max")
        if not low <= values[path] <= high:
            raise ValueError(f"{path}={values[path]} is outside [{low}, {high}]")
