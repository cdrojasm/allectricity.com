"""Tolerable touch and step voltages for an explicitly selected standard and edition.

The potential engine computes the field (GPR, surface potentials); this module only turns a fault
exposure into tolerable limits and compares them with field values. The standard and edition are
always given by the caller and never inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

IEEE80_2013 = "IEEE 80-2013"
EN50522_2010 = "EN 50522:2010"
RETIE_2013 = "RETIE 2013"

# Limits that come from normative tables; they are not loaded until someone transcribes them
# from a licensed or official copy and records the source. Never fill them from memory.
PENDING_TABLES = {
    EN50522_2010: "Tabla pendiente de cargar desde la norma: curva UTp vs. duración de falla (EN 50522:2010, Anexo B).",
    RETIE_2013: "Tabla pendiente de cargar desde la norma: tensiones de contacto máximas vs. tiempo de despeje (RETIE, Tabla 15.1).",
}
SUPPORTED_STANDARDS = (IEEE80_2013, *PENDING_TABLES)

# IEEE Std 80-2013, clause 5: Dalziel body-current constants k = sqrt(S_B) for 50 kg and 70 kg bodies.
IEEE80_BODY_CURRENT_K = {50: 0.116, 70: 0.157}
IEEE80_BODY_RESISTANCE_OHM = 1000.0
# IEEE Std 80-2013, clause 5: the body-current equation is based on tests between 0.03 s and 3 s.
IEEE80_CLEARING_TIME_RANGE_S = (0.03, 3.0)


class StandardNotLoadedError(LookupError):
    """The standard's tolerable limits come from a table that has not been loaded yet."""


@dataclass(frozen=True)
class FaultExposure:
    clearing_time_s: float
    body_weight_kg: float
    surface_resistivity_ohm_m: float
    surface_thickness_m: float
    soil_resistivity_ohm_m: float


def surface_layer_factor(soil_resistivity_ohm_m: float, surface_resistivity_ohm_m: float, surface_thickness_m: float) -> float:
    """IEEE Std 80-2013 eq. (27): Cs = 1 - 0.09 (1 - rho/rho_s) / (2 h_s + 0.09)."""
    return 1.0 - 0.09 * (1.0 - soil_resistivity_ohm_m / surface_resistivity_ohm_m) / (2.0 * surface_thickness_m + 0.09)


def ieee80_2013_limits(exposure: FaultExposure) -> dict[str, Any]:
    """Tolerable step and touch voltages from IEEE Std 80-2013 eqs. (27), (29)-(30) and (32)-(33)."""
    low, high = IEEE80_CLEARING_TIME_RANGE_S
    if not low <= exposure.clearing_time_s <= high:
        raise ValueError(f"IEEE 80-2013 solo es válida para tiempos de despeje entre {low} y {high} s")
    # Only 50 kg and 70 kg bodies are defined; intermediate weights use the conservative 50 kg limit.
    weight = 70 if exposure.body_weight_kg >= 70 else 50
    k = IEEE80_BODY_CURRENT_K[weight]
    cs = surface_layer_factor(exposure.soil_resistivity_ohm_m, exposure.surface_resistivity_ohm_m,
                              exposure.surface_thickness_m)
    body_current_a = k / sqrt(exposure.clearing_time_s)
    rho_s = exposure.surface_resistivity_ohm_m
    return {
        "standard": IEEE80_2013,
        "touch_v": (IEEE80_BODY_RESISTANCE_OHM + 1.5 * cs * rho_s) * body_current_a,
        "step_v": (IEEE80_BODY_RESISTANCE_OHM + 6.0 * cs * rho_s) * body_current_a,
        "parameters": {
            "surface_layer_factor_cs": cs,
            "body_weight_kg_used": weight,
            "body_current_constant_k": k,
            "body_current_a": body_current_a,
            "body_resistance_ohm": IEEE80_BODY_RESISTANCE_OHM,
        },
        "formulas": {
            "cs": "Cs = 1 - 0.09 (1 - rho/rho_s) / (2 h_s + 0.09)  [IEEE 80-2013 eq. 27]",
            "touch_v": f"E_touch{weight} = (1000 + 1.5 Cs rho_s) k / sqrt(t_s)  [IEEE 80-2013 eq. {32 if weight == 50 else 33}]",
            "step_v": f"E_step{weight} = (1000 + 6 Cs rho_s) k / sqrt(t_s)  [IEEE 80-2013 eq. {29 if weight == 50 else 30}]",
        },
    }


def tolerable_limits(standard: str, exposure: FaultExposure) -> dict[str, Any]:
    if standard == IEEE80_2013:
        return ieee80_2013_limits(exposure)
    if standard in PENDING_TABLES:
        raise StandardNotLoadedError(PENDING_TABLES[standard])
    raise ValueError(f"Norma no soportada: {standard}. Opciones: {', '.join(SUPPORTED_STANDARDS)}")


def _criterion(name: str, actual: float, tolerable: float, formula: str) -> dict[str, Any]:
    margin = tolerable - actual
    return {"criterion": name, "actual_v": actual, "tolerable_v": tolerable, "margin_v": margin,
            "margin_rel": margin / tolerable, "status": "cumple" if actual <= tolerable else "no_cumple",
            "formula": formula}


def evaluate(field: dict[str, float], exposure: FaultExposure, standards: list[str]) -> list[dict[str, Any]]:
    """Compare field values (`touch_v`, `step_v`, `gpr_v`) with each selected standard's limits.

    A standard whose limits cannot be computed is reported as `no_evaluable` with the reason,
    instead of failing the whole calculation.
    """
    evaluations = []
    for standard in standards:
        try:
            limits = tolerable_limits(standard, exposure)
        except (StandardNotLoadedError, ValueError) as exc:
            evaluations.append({"standard": standard, "status": "no_evaluable", "reason": str(exc), "criteria": []})
            continue
        criteria = [
            _criterion("touch", field["touch_v"], limits["touch_v"], limits["formulas"]["touch_v"]),
            _criterion("step", field["step_v"], limits["step_v"], limits["formulas"]["step_v"]),
        ]
        evaluations.append({
            "standard": standard,
            "status": "cumple" if all(c["status"] == "cumple" for c in criteria) else "no_cumple",
            "criteria": criteria,
            # IEEE 80-2013 design procedure (Figure 33, step 5): a GPR below the tolerable touch voltage
            # means no further analysis is needed; it is reported, not used to override the criteria.
            "gpr_below_tolerable_touch": field["gpr_v"] <= limits["touch_v"],
            "parameters": limits["parameters"],
            "cs_formula": limits["formulas"]["cs"],
        })
    return evaluations
