"""Resistivity sounding readings: unit conversion and checks against their source text."""

import re
from math import isclose, pi

TOKEN = re.compile(r"\d[\d.,]*")


def apparent_resistivity(array: str, spacing_m: float, resistance_ohm: float,
                         potential_spacing_m: float | None = None) -> float:
    """Apparent resistivity from a measured resistance R.

    Wenner: rho = 2·pi·a·R. Schlumberger (spacing = AB/2 = L, potential spacing MN):
    rho = pi·R·(L² − (MN/2)²) / MN.
    """
    if spacing_m <= 0 or resistance_ohm <= 0:
        raise ValueError("spacing and resistance must be positive")
    if array == "wenner":
        return 2 * pi * spacing_m * resistance_ohm
    if array == "schlumberger":
        if not potential_spacing_m or potential_spacing_m <= 0:
            raise ValueError("Schlumberger readings given as resistance need the potential spacing MN")
        half = potential_spacing_m / 2
        if half >= spacing_m:
            raise ValueError("MN/2 must be smaller than AB/2")
        return pi * resistance_ohm * (spacing_m ** 2 - half ** 2) / potential_spacing_m
    raise ValueError(f"Unknown array: {array}")


def number_candidates(text: str) -> list[float]:
    """Every value a number in the text may stand for (comma or point decimals, thousands)."""
    values = []
    for token in TOKEN.findall(text or ""):
        token = token.rstrip(".,")
        variants = {token.replace(",", "."), token.replace(".", "").replace(",", "."), token.replace(",", "")}
        for variant in variants:
            try:
                values.append(float(variant))
            except ValueError:
                continue
    return values


def missing_in_text(values: list[float], text: str) -> list[float]:
    """Values that do not appear in the text (the model must not invent readings)."""
    candidates = number_candidates(text)
    return [value for value in values
            if not any(isclose(value, c, rel_tol=1e-9, abs_tol=1e-9) for c in candidates)]
