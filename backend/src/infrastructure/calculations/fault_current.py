"""Grid current I_G from the symmetrical fault current: decrement factor and current division.

IEEE Std 80-2013 defines the maximum grid current as I_G = D_f · S_f · 3I0 (eq. 64), where
3I0 is the symmetrical RMS ground-fault current, D_f the decrement factor for the DC offset
(eq. 79, with T_a = X / (ωR), eq. 74/80) and S_f the fraction of fault current that returns
to remote earth through the grid instead of through shield wires, neutrals, cable screens
and other remote grounds (§15.9).

The split here is the lumped current divider between the grid resistance R_g and the
parallel combination Z_eq of the return paths; each path is one complex impedance to remote
earth supplied by the user (for example from a shield-wire ladder study). The distributed
ladder model of shield wires (self/mutual impedance per span and tower-footing resistances,
IEEE 80 Annex C) is out of scope until it can be validated against a cited reference.

R_g comes from the potential engine and does not depend on the injected current, so it can
be solved first and I_G applied afterwards; every potential and voltage scales linearly with
the injected current.
"""

from __future__ import annotations

import cmath
from dataclasses import dataclass
from math import degrees, exp, isfinite, pi, sqrt
from typing import Any

SOURCE = "IEEE Std 80-2013, §15.9-15.10, eqs. (64), (74), (79)"


@dataclass(frozen=True)
class ReturnPath:
    name: str
    kind: str
    impedance_ohm: complex


def decrement_factor(x_over_r: float, fault_duration_s: float, frequency_hz: float = 60.0) -> float:
    """D_f = sqrt(1 + (T_a/t_f)(1 - exp(-2 t_f / T_a))), with T_a = (X/R) / (2 π f)."""
    if not isfinite(x_over_r) or x_over_r < 0:
        raise ValueError("X/R must be finite and non-negative")
    if not isfinite(fault_duration_s) or fault_duration_s <= 0:
        raise ValueError("fault duration must be positive")
    if frequency_hz <= 0:
        raise ValueError("frequency must be positive")
    if x_over_r == 0:
        return 1.0
    time_constant = x_over_r / (2 * pi * frequency_hz)
    ratio = time_constant / fault_duration_s
    return sqrt(1 + ratio * (1 - exp(-2 * fault_duration_s / time_constant)))


def _phasor(value: complex) -> dict[str, float]:
    return {"magnitude": abs(value), "angle_deg": degrees(cmath.phase(value)) if value else 0.0,
            "real": value.real, "imag": value.imag}


def split_from_paths(grid_resistance_ohm: float, paths: list[ReturnPath]) -> dict[str, Any]:
    """Current divider between R_g and the parallel return paths, per unit fault current (0° reference)."""
    if not isfinite(grid_resistance_ohm) or grid_resistance_ohm <= 0:
        raise ValueError("grid resistance must be positive")
    if not paths:
        raise ValueError("at least one return path is required")
    for path in paths:
        if not abs(path.impedance_ohm) > 0 or not all(map(isfinite, (path.impedance_ohm.real, path.impedance_ohm.imag))):
            raise ValueError(f"return path {path.name} needs a finite, non-zero impedance")
        if path.impedance_ohm.real < 0:
            raise ValueError(f"return path {path.name} cannot have negative resistance")
    admittance = sum(1 / path.impedance_ohm for path in paths)
    zeq = 1 / admittance
    grid_share = zeq / (zeq + grid_resistance_ohm)
    voltage = grid_share * grid_resistance_ohm  # grid potential per ampere of fault current
    return {
        "split_factor": abs(grid_share),
        "equivalent_impedance_ohm": _phasor(zeq),
        "grid_share": _phasor(grid_share),
        "paths": [
            {"name": path.name, "kind": path.kind, "impedance_ohm": _phasor(path.impedance_ohm),
             "share": _phasor(voltage / path.impedance_ohm)}
            for path in paths
        ],
    }


def grid_current(
    symmetrical_fault_current_a: float,
    fault_duration_s: float,
    *,
    grid_resistance_ohm: float | None = None,
    x_over_r: float | None = None,
    frequency_hz: float = 60.0,
    split_factor: float | None = None,
    split_factor_origin: str | None = None,
    return_paths: list[ReturnPath] | None = None,
) -> dict[str, Any]:
    """Return I_G and its breakdown; S_f comes from the user or from return paths, never both."""
    if not isfinite(symmetrical_fault_current_a) or symmetrical_fault_current_a <= 0:
        raise ValueError("symmetrical fault current must be positive")
    if split_factor is not None and return_paths:
        raise ValueError("give either a split factor or return paths, not both")
    df = 1.0 if x_over_r is None else decrement_factor(x_over_r, fault_duration_s, frequency_hz)
    breakdown: dict[str, Any] = {
        "source": SOURCE,
        "symmetrical_fault_current_a": symmetrical_fault_current_a,
        "fault_duration_s": fault_duration_s,
        "decrement_factor": df,
        "decrement_origin": "not-provided (D_f = 1)" if x_over_r is None else f"X/R = {x_over_r:g} at {frequency_hz:g} Hz",
    }
    if split_factor is not None:
        if not isfinite(split_factor) or not 0 < split_factor <= 1:
            raise ValueError("split factor must be in (0, 1]")
        if not split_factor_origin:
            raise ValueError("a user split factor needs its origin")
        sf, origin = split_factor, f"user: {split_factor_origin}"
    elif return_paths:
        if grid_resistance_ohm is None:
            raise ValueError("return paths need the grid resistance")
        split = split_from_paths(grid_resistance_ohm, return_paths)
        sf, origin = split["split_factor"], "return paths current divider"
        breakdown["grid_resistance_ohm"] = grid_resistance_ohm
        breakdown["equivalent_impedance_ohm"] = split["equivalent_impedance_ohm"]
        breakdown["paths"] = [
            {**path, "current_a": df * symmetrical_fault_current_a * path["share"]["magnitude"]}
            for path in split["paths"]
        ]
    else:
        sf, origin = 1.0, "not-provided (S_f = 1, all fault current through the grid)"
    breakdown.update({
        "split_factor": sf,
        "split_origin": origin,
        "grid_current_a": df * sf * symmetrical_fault_current_a,
    })
    return breakdown
