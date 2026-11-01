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
RETIE_2026 = "RETIE 2026 (Resolución 40284)"

# Limits that come from normative tables; they are not loaded until someone transcribes them
# from a licensed or official copy and records the source. Never fill them from memory.
PENDING_TABLES = {
    EN50522_2010: "Tabla pendiente de cargar desde la norma: curva UTp vs. duración de falla (EN 50522:2010, Anexo B).",
    RETIE_2013: "Tabla pendiente de cargar desde la norma: tensiones de contacto máximas vs. tiempo de despeje (RETIE, Tabla 15.1).",
}
SUPPORTED_STANDARDS = (IEEE80_2013, RETIE_2026, *PENDING_TABLES)

# RETIE Resolution 40284 (2026), Book 3, Table 3.12.1.a. Values are RMS AC
# maximum applied touch voltage, keyed by the exact clearing-time rows published
# in the table. Selection for times between rows is a conservative product policy:
# use the next longer listed time, which never raises the allowed voltage.
RETIE_2026_TOUCH_TABLE = (
    (2.0, 50.0, 82.0),
    (1.0, 55.0, 116.0),
    (0.7, 70.0, 138.0),
    (0.5, 80.0, 164.0),
    (0.4, 130.0, 183.0),
    (0.3, 200.0, 211.0),
    (0.2, 270.0, 259.0),
    (0.15, 300.0, 299.0),
    (0.1, 320.0, 366.0),
    (0.05, 345.0, 518.0),
)

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
    exposure_class: str | None = None
    surface_layer_present: bool | None = None


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
    # IEEE 80's Cs correction represents a resistive surface layer. When the
    # user explicitly states that no layer exists, the surface and top-soil
    # resistivities are the same and its thickness is zero (therefore Cs = 1).
    # Do not use stale surface inputs in this case.
    if exposure.surface_layer_present is False:
        rho_s = exposure.soil_resistivity_ohm_m
        h_s = 0.0
    else:
        rho_s = exposure.surface_resistivity_ohm_m
        h_s = exposure.surface_thickness_m
    if exposure.soil_resistivity_ohm_m <= 0 or rho_s <= 0 or h_s < 0:
        raise ValueError("Las resistividades deben ser positivas y el espesor de capa no puede ser negativo")
    cs = surface_layer_factor(exposure.soil_resistivity_ohm_m, rho_s, h_s)
    body_current_a = k / sqrt(exposure.clearing_time_s)
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
            "surface_layer_present": exposure.surface_layer_present,
            "surface_resistivity_ohm_m_used": rho_s,
            "surface_thickness_m_used": h_s,
        },
        "formulas": {
            "cs": "Cs = 1 - 0.09 (1 - rho/rho_s) / (2 h_s + 0.09)  [IEEE 80-2013 eq. 27]",
            "touch_v": f"E_touch{weight} = (1000 + 1.5 Cs rho_s) k / sqrt(t_s)  [IEEE 80-2013 eq. {32 if weight == 50 else 33}]",
            "step_v": f"E_step{weight} = (1000 + 6 Cs rho_s) k / sqrt(t_s)  [IEEE 80-2013 eq. {29 if weight == 50 else 30}]",
        },
    }


def retie_2026_touch_limit(exposure: FaultExposure) -> dict[str, Any]:
    """Return the RETIE 2026 Table 3.12.1.a touch limit with explicit applicability.

    RETIE limits this table to cases without a surface layer. It has separate
    public and occupational columns; neither class is inferred. The published
    table does not specify interpolation, so intervening times use the next
    longer row as a documented conservative policy. Times below 50 ms are not
    covered by the table and remain unevaluable.
    """
    if exposure.exposure_class not in {"public", "occupational"}:
        raise StandardNotLoadedError("RETIE 2026 requiere exposure_class='public' u 'occupational'.")
    if exposure.surface_layer_present is not False:
        raise StandardNotLoadedError(
            "RETIE 2026 Tabla 3.12.1.a aplica cuando no hay capa superficial; "
            "confirme explícitamente surface_layer_present=False."
        )
    if exposure.clearing_time_s < 0.05:
        raise StandardNotLoadedError("RETIE 2026 Tabla 3.12.1.a no contiene tiempos menores de 50 ms.")

    # Rows are descending in time. Pick the first published duration >= actual
    # duration, or the final 50 ms row. This is conservative between breakpoints.
    row = next((item for item in RETIE_2026_TOUCH_TABLE if exposure.clearing_time_s <= item[0]),
               RETIE_2026_TOUCH_TABLE[-1])
    # For a duration above 2 s the table explicitly provides a >2 s row.
    # That row is represented at 2 s and selected as the most restrictive row.
    if exposure.clearing_time_s > 2.0:
        row = RETIE_2026_TOUCH_TABLE[0]
    _, public_limit, occupational_limit = row
    limit = public_limit if exposure.exposure_class == "public" else occupational_limit
    return {
        "touch_v": limit,
        "table_row": ">2 s" if exposure.clearing_time_s > 2.0 else f"{row[0]:g} s",
        "exposure_class": exposure.exposure_class,
        "parameters": {
            "clearing_time_s": exposure.clearing_time_s,
            "selected_table_row": ">2 s" if exposure.clearing_time_s > 2.0 else f"{row[0]:g} s",
            "conservative_row_selection": "next_longer_published_time",
            "surface_layer_present": False,
        },
        "formulas": {
            "touch_v": "RETIE 2026 Libro 3 Tabla 3.12.1.a (rms c.a.; límite de contacto aplicado)"
        },
        "source": {
            "document": "RETIE, Resolución 40284 de 2026, Libro 3",
            "edition": "2026-06-23",
            "clause": "Artículo 3.12.1 literal g, Tabla 3.12.1.a",
            "url": "https://www.minenergia.gov.co/documents/15921/Libro-3-Resolucion-40284-23-06-2026.pdf",
        },
    }


def _retie_2026_limits(exposure: FaultExposure) -> dict[str, Any]:
    """Return RETIE touch and step criteria with explicit applicability.

    RETIE Table 3.12.1.a supplies touch only when there is no surface layer.
    Step is evaluated with IEEE 80-2013 in either surface condition. If a
    surface layer exists, IEEE 80 supplies both touch and step and the RETIE
    touch table is not applied.
    """
    if exposure.exposure_class not in {"public", "occupational"}:
        raise StandardNotLoadedError("RETIE 2026 requiere exposure_class='public' u 'occupational'.")
    if exposure.surface_layer_present is None:
        raise StandardNotLoadedError("RETIE 2026 requiere confirmar explícitamente si existe capa superficial.")

    ieee_limits = ieee80_2013_limits(exposure)
    if exposure.surface_layer_present is False:
        table_limit = retie_2026_touch_limit(exposure)
        touch_limit = table_limit["touch_v"]
        touch_formula = table_limit["formulas"]["touch_v"]
        touch_source = table_limit["source"]
        touch_method = "RETIE 2026 Tabla 3.12.1.a; fila conservadora de tiempo publicada"
    else:
        touch_limit = ieee_limits["touch_v"]
        touch_formula = ieee_limits["formulas"]["touch_v"]
        touch_source = {
            "document": "IEEE Std 80-2013",
            "edition": "2013",
            "clause": "Cláusula 8, ecuaciones (27), (32)-(33)",
        }
        touch_method = "IEEE 80-2013; la tabla RETIE 3.12.1.a no aplica con capa superficial"

    return {
        "touch_v": touch_limit,
        "step_v": ieee_limits["step_v"],
        "formulas": {
            "touch_v": touch_formula,
            "step_v": ieee_limits["formulas"]["step_v"],
            "cs": ieee_limits["formulas"]["cs"],
        },
        "touch_formula": touch_formula,
        "step_formula": ieee_limits["formulas"]["step_v"],
        "touch_method": touch_method,
        "step_method": "IEEE 80-2013; ecuación de tensión tolerable de paso",
        "touch_source": touch_source,
        "step_source": {
            "document": "IEEE Std 80-2013",
            "edition": "2013",
            "clause": "Cláusula 8, ecuaciones (27), (29)-(30)",
        },
        "parameters": {**ieee_limits["parameters"],
                       "retie_touch_table_applicable": exposure.surface_layer_present is False,
                       "exposure_class": exposure.exposure_class},
    }


def tolerable_limits(standard: str, exposure: FaultExposure) -> dict[str, Any]:
    if standard == IEEE80_2013:
        return ieee80_2013_limits(exposure)
    if standard == RETIE_2026:
        return _retie_2026_limits(exposure)
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
        if standard == RETIE_2026:
            try:
                limits = _retie_2026_limits(exposure)
                if "touch_v" not in field or "step_v" not in field:
                    raise KeyError("field requiere touch_v y step_v")
            except (StandardNotLoadedError, ValueError) as exc:
                evaluations.append({"standard": standard, "status": "no_evaluable", "reason": str(exc), "criteria": []})
                continue
            except KeyError as exc:
                evaluations.append({"standard": standard, "status": "no_evaluable", "reason": str(exc), "criteria": []})
                continue
            touch = _criterion("touch", field["touch_v"], limits["touch_v"], limits["touch_formula"])
            step = _criterion("step", field["step_v"], limits["step_v"], limits["step_formula"])
            evaluations.append({
                "standard": standard,
                "status": "no_evaluable",
                "reason": "La tensión transferida aún no tiene un escenario y límite evaluable.",
                "criteria": [
                    touch,
                    step,
                    {"criterion": "transferred", "status": "no_evaluable",
                     "reason": "Se requiere definir el conductor transferido accesible, su punto remoto y el límite aplicable."},
                ],
                "unassessed_criteria": ["transferred"],
                "parameters": limits["parameters"],
                "methods": {"touch": limits["touch_method"], "step": limits["step_method"]},
                "sources": {"touch": limits["touch_source"], "step": limits["step_source"]},
            })
            continue
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
