"""Adapter from PE-09 tolerable limits to optimizer safety utilization (OP-01).

This module is the integration boundary: normative limits are calculated by
``safety_criteria`` and the domain primitive reports their independent
step/touch constraints and combined utilization.
"""

from __future__ import annotations

from typing import Any

from src.domain.spat.optimizer_foundations import safety_utilization
from src.infrastructure.calculations import safety_criteria


_STANDARD_EDITIONS = {
    safety_criteria.IEEE80_2013: "2013",
    safety_criteria.EN50522_2010: "2010",
    safety_criteria.RETIE_2013: "2013",
    safety_criteria.RETIE_2026: "2026",
}


def utilization_from_exposure(
    *,
    touch_v: float,
    step_v: float,
    exposure: safety_criteria.FaultExposure,
    standard: str,
) -> dict[str, Any]:
    """Calculate OP-01 utilization directly from PE-09 limits.

    ``touch_v`` and ``step_v`` are the field maxima from the potential solver;
    ``exposure`` contains the fault and surface assumptions used by PE-09.
    The selected standard is explicit, and unsupported/unloaded normative
    limits raise the same errors as :func:`safety_criteria.tolerable_limits`.
    """
    limits = safety_criteria.tolerable_limits(standard, exposure)
    if "step_v" not in limits:
        raise safety_criteria.StandardNotLoadedError(
            f"{standard} no proporciona todavía un límite evaluable de paso para calcular utilización conjunta."
        )
    edition = _STANDARD_EDITIONS.get(standard)
    if edition is None:
        # Do not silently attach guessed provenance to a newly added standard.
        raise ValueError(f"Falta registrar explícitamente la edición de {standard}")

    utilization = safety_utilization(
        Vs_v=step_v,
        Vt_v=touch_v,
        Vs_lim_v=limits["step_v"],
        Vt_lim_v=limits["touch_v"],
        standard=standard,
        edition=edition,
    )
    return {
        "schema_version": "spat.optimizer-safety-evaluation/1.0",
        **utilization,
        "limits": {
            "step_v": limits["step_v"],
            "touch_v": limits["touch_v"],
            "parameters": limits["parameters"],
            "formulas": limits["formulas"],
        },
        "exposure": {
            "clearing_time_s": exposure.clearing_time_s,
            "body_weight_kg": exposure.body_weight_kg,
            "surface_resistivity_ohm_m": exposure.surface_resistivity_ohm_m,
            "surface_thickness_m": exposure.surface_thickness_m,
            "soil_resistivity_ohm_m": exposure.soil_resistivity_ohm_m,
        },
    }
