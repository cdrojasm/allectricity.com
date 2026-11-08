"""Bound-aware finite-difference sensitivities for optimizer diagnostics (OP-11).

This is a diagnostic aid for the discrete search, not a gradient supplied to an optimizer.
Each evaluation must use the caller's normal geometry, safety, and cost validation path.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Callable


METRICS = ("cost", "Vs", "Vt")


def _read_path(value: Any, path: str) -> Any:
    current = value
    for token in path.replace("[", ".").replace("]", "").split("."):
        if token:
            current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def _write_path(value: Any, path: str, replacement: float) -> None:
    tokens = [token for token in path.replace("[", ".").replace("]", "").split(".") if token]
    current = value
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    if isinstance(current, list):
        current[int(tokens[-1])] = replacement
    else:
        current[tokens[-1]] = replacement


def finite_difference_sensitivities(
    *,
    parameters: dict[str, Any],
    variables: dict[str, dict[str, float]],
    evaluate: Callable[[dict[str, Any]], dict[str, float | None]],
    relative_step: float = 1e-3,
    discontinuity_tolerance: float = 0.25,
) -> dict[str, Any]:
    """Estimate d(cost, Vs, Vt)/d(variable), using central or bound-aware one-sided differences.

    Each variable entry has numeric `min`, `max` and optional positive `step`. Missing bounds,
    non-numeric variables, infeasible probes or missing metrics are reported as unavailable; they
    are never silently imputed. A left/right slope disagreement above the configured fraction is
    flagged as locally discontinuous/non-smooth.
    """
    if not 0 < relative_step < 1 or not 0 <= discontinuity_tolerance < 1:
        raise ValueError("relative_step must be in (0, 1) and discontinuity_tolerance in [0, 1)")
    try:
        baseline = evaluate(deepcopy(parameters))
    except Exception as exc:
        return {
            "schema_version": "spat.optimizer-sensitivities/1.0",
            "method": "finite_difference",
            "baseline": None,
            "status": "unavailable",
            "reason": f"baseline_evaluation_failed: {exc}",
            "variables": {
                path: {"status": "unavailable", "reason": "baseline_evaluation_failed"}
                for path in sorted(variables)
            },
        }
    output: dict[str, Any] = {"schema_version": "spat.optimizer-sensitivities/1.0", "method": "finite_difference",
                              "baseline": baseline, "status": "complete", "variables": {}}
    for path, bounds in sorted(variables.items()):
        try:
            x = _read_path(parameters, path)
            lo, hi = float(bounds["min"]), float(bounds["max"])
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not all(map(isfinite, (float(x), lo, hi))) or lo >= hi:
                raise ValueError("variable and finite bounds required")
            x = float(x)
            if not lo <= x <= hi:
                raise ValueError("baseline outside variable bounds")
            step = float(bounds.get("step", max(abs(x) * relative_step, (hi - lo) * relative_step)))
            if not isfinite(step) or step <= 0:
                raise ValueError("step must be positive and finite")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            output["variables"][path] = {"status": "unavailable", "reason": str(exc)}
            continue
        left_x, right_x = max(lo, x - step), min(hi, x + step)
        probes: dict[str, dict[str, float | None]] = {}
        for side, probe_x in (("left", left_x), ("right", right_x)):
            if probe_x == x:
                continue
            candidate = deepcopy(parameters)
            _write_path(candidate, path, probe_x)
            try:
                probes[side] = evaluate(candidate)
            except Exception as exc:
                probes[side] = {"_error": str(exc)}
        metrics: dict[str, Any] = {}
        unavailable = False
        nonsmooth = False
        for metric in METRICS:
            y0 = baseline.get(metric)
            if y0 is None or isinstance(y0, bool) or not isinstance(y0, (int, float)) or not isfinite(float(y0)):
                metrics[metric] = {"status": "unavailable", "reason": "baseline_metric_missing"}
                unavailable = True
                continue
            slopes = {}
            for side, probe_x in (("left", left_x), ("right", right_x)):
                values = probes.get(side)
                y1 = values.get(metric) if values else None
                if y1 is not None and not isinstance(y1, bool) and isinstance(y1, (int, float)) and isfinite(float(y1)):
                    slopes[side] = (float(y1) - float(y0)) / (probe_x - x)
            if not slopes:
                metrics[metric] = {"status": "unavailable", "reason": "probe_failed_or_metric_missing"}
                unavailable = True
                continue
            values = list(slopes.values())
            disagreement = (abs(values[0] - values[1]) / max(abs(values[0]), abs(values[1]), 1e-12)
                            if len(values) == 2 else None)
            metric_nonsmooth = disagreement is not None and disagreement > discontinuity_tolerance
            nonsmooth |= metric_nonsmooth
            metrics[metric] = {"status": "estimated", "derivative": sum(values) / len(values),
                               "units": f"{metric}_units_per_{path}", "one_sided": len(values) == 1,
                               "left_derivative": slopes.get("left"), "right_derivative": slopes.get("right"),
                               "relative_slope_disagreement": disagreement, "nonsmooth": metric_nonsmooth}
        output["variables"][path] = {"status": "partial" if unavailable else "estimated",
                                     "baseline_value": x, "bounds": {"min": lo, "max": hi},
                                     "probe_values": {"left": left_x, "right": right_x}, "metrics": metrics,
                                     "nonsmooth": nonsmooth}
    return output
