"""BL-15 / EG-21: deterministic coherence checks of the inputs a potential calculation depends on.

Every rule is cheap and explainable: a range a value must stay in, or a relation between two values,
with the source of the limit. An `error` means the calculation would run on data no grounding design
can have (or that contradicts another input), so the calculation is refused; a `warning` is unusual
but possible, and travels with the result as a model warning. Nothing is repaired silently and no
value is inferred: a missing input is not a coherence problem here (`missing_for_calculation` reports it).
"""

from __future__ import annotations

from math import isfinite, sqrt
from typing import Any

IEEE80 = "IEEE 80-2013"
# Dalziel's tolerable body current (IEEE 80-2013 §8.3, Eq. 7) is stated for 0.03 s <= t_s <= 3.0 s.
DALZIEL_RANGE_S = (0.03, 3.0)
ONE_CYCLE_60HZ_S = 1.0 / 60.0
MAX_CLEARING_TIME_S = 10.0
# Ground fault current: anything above 300 kA is beyond any power system; below 100 A a grid is rarely sized.
FAULT_CURRENT_ERROR_A = 300_000.0
FAULT_CURRENT_WARNING_A = (100.0, 100_000.0)
# Surface layer: the Cs expression (IEEE 80-2013 Eq. 27) is fitted for layers up to about 0.3 m thick;
# layers thinner than 0.05 m are not what Table 7 describes as a protective layer.
SURFACE_THICKNESS_ERROR_M = 0.3
SURFACE_THICKNESS_WARNING_M = 0.05
SURFACE_RESISTIVITY_WARNING_OHM_M = 50_000_000.0   # IEEE 80-2013 Table 7 tops out at dry asphalt, 3e7 ohm-m
# Soil: IEEE 80-2013 Table 2 runs from wet organic soil (10 ohm-m) to bedrock (10 000 ohm-m).
SOIL_RESISTIVITY_ERROR_OHM_M = (0.1, 1_000_000.0)
SOIL_RESISTIVITY_WARNING_OHM_M = (5.0, 10_000.0)
MIN_LAYER_THICKNESS_WARNING_M = 0.1
# Sverak's formula (IEEE 80-2013 Eq. 52) against the engine: a plausibility bracket, not a validation.
SVERAK_RATIO_RANGE = (0.2, 5.0)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return float(value)


def _diagnostic(path: str, kind: str, severity: str, message: str, value=None, expected: str | None = None,
                source: str = IEEE80, related: list[str] | None = None) -> dict[str, Any]:
    return {"path": path, "kind": kind, "severity": severity, "message": message, "value": value,
            "expected": expected, "source": source, "related": related or []}


def coherence_diagnostics(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Explainable diagnostics on the artifact's inputs; `severity` is `error` or `warning`."""
    snapshot = snapshot or {}
    fault = snapshot.get("fault") or {}
    conductor = snapshot.get("conductor") or {}
    layers = [layer for layer in (snapshot.get("soil_layers") or []) if isinstance(layer, dict)]
    out: list[dict[str, Any]] = []

    current = _number(fault.get("current_a"))
    if current is not None:
        if current > FAULT_CURRENT_ERROR_A:
            out.append(_diagnostic("fault.current_a", "range", "error",
                                   f"La corriente de falla ({current:g} A) supera {FAULT_CURRENT_ERROR_A:g} A; ninguna red "
                                   "eléctrica tiene esa corriente de falla a tierra. Revisa las unidades (A, no kA).",
                                   current, f"<= {FAULT_CURRENT_ERROR_A:g} A", source="cortocircuito en redes de potencia"))
        elif not FAULT_CURRENT_WARNING_A[0] <= current <= FAULT_CURRENT_WARNING_A[1]:
            out.append(_diagnostic("fault.current_a", "range", "warning",
                                   f"La corriente de falla ({current:g} A) está fuera del rango habitual "
                                   f"{FAULT_CURRENT_WARNING_A[0]:g}–{FAULT_CURRENT_WARNING_A[1]:g} A; confirma el valor y sus unidades.",
                                   current, f"{FAULT_CURRENT_WARNING_A[0]:g}–{FAULT_CURRENT_WARNING_A[1]:g} A",
                                   source="estudios de cortocircuito típicos"))

    clearing = _number(fault.get("clearing_time_s"))
    if clearing is not None:
        if clearing < ONE_CYCLE_60HZ_S or clearing > MAX_CLEARING_TIME_S:
            out.append(_diagnostic("fault.clearing_time_s", "range", "error",
                                   f"El tiempo de despeje ({clearing:g} s) no puede ser menor que un ciclo ({ONE_CYCLE_60HZ_S:.4f} s) "
                                   f"ni mayor que {MAX_CLEARING_TIME_S:g} s; revisa las unidades (s, no ms ni ciclos).",
                                   clearing, f"{ONE_CYCLE_60HZ_S:.4f}–{MAX_CLEARING_TIME_S:g} s", source="protecciones de redes de potencia"))
        elif not DALZIEL_RANGE_S[0] <= clearing <= DALZIEL_RANGE_S[1]:
            out.append(_diagnostic("fault.clearing_time_s", "range", "warning",
                                   f"El tiempo de despeje ({clearing:g} s) está fuera del rango {DALZIEL_RANGE_S[0]:g}–{DALZIEL_RANGE_S[1]:g} s "
                                   "en que IEEE 80-2013 §8.3 enuncia la corriente tolerable de Dalziel; las tensiones tolerables se extrapolan.",
                                   clearing, f"{DALZIEL_RANGE_S[0]:g}–{DALZIEL_RANGE_S[1]:g} s", source=f"{IEEE80} §8.3"))

    thermal = _number(conductor.get("thermal_duration_s"))
    if thermal is not None and clearing is not None and thermal < clearing - 1e-9:
        out.append(_diagnostic("conductor.thermal_duration_s", "relation", "error",
                               f"El conductor se dimensiona para t_c = {thermal:g} s, menor que el tiempo de despeje t_s = {clearing:g} s; "
                               "t_c debe ser al menos t_s (IEEE 80-2013 §11.3.1 usa el tiempo de despeje del respaldo).",
                               thermal, f">= {clearing:g} s", source=f"{IEEE80} §11.3.1", related=["fault.clearing_time_s"]))

    thickness = _number(fault.get("surface_thickness_m"))
    if thickness is not None:
        if thickness > SURFACE_THICKNESS_ERROR_M:
            out.append(_diagnostic("fault.surface_thickness_m", "range", "error",
                                   f"La capa superficial ({thickness:g} m) excede {SURFACE_THICKNESS_ERROR_M:g} m, el espesor hasta el que vale "
                                   "el factor Cs (IEEE 80-2013 Ec. 27); revisa las unidades (m, no cm).",
                                   thickness, f"<= {SURFACE_THICKNESS_ERROR_M:g} m", source=f"{IEEE80} Ec. 27"))
        elif thickness < SURFACE_THICKNESS_WARNING_M:
            out.append(_diagnostic("fault.surface_thickness_m", "range", "warning",
                                   f"La capa superficial ({thickness:g} m) es más delgada que {SURFACE_THICKNESS_WARNING_M:g} m; "
                                   "una capa tan fina rara vez se mantiene y aporta poco al factor Cs.",
                                   thickness, f">= {SURFACE_THICKNESS_WARNING_M:g} m", source=f"{IEEE80} §7.4 y Tabla 7"))

    surface_rho = _number(fault.get("surface_resistivity_ohm_m"))
    top_rho = _number(layers[0].get("resistivity_ohm_m")) if layers else None
    if surface_rho is not None:
        if surface_rho > SURFACE_RESISTIVITY_WARNING_OHM_M:
            out.append(_diagnostic("fault.surface_resistivity_ohm_m", "range", "warning",
                                   f"La resistividad de la capa superficial ({surface_rho:g} Ω·m) supera la del asfalto seco "
                                   f"({SURFACE_RESISTIVITY_WARNING_OHM_M:g} Ω·m, IEEE 80-2013 Tabla 7); confirma el material y las unidades.",
                                   surface_rho, f"<= {SURFACE_RESISTIVITY_WARNING_OHM_M:g} Ω·m", source=f"{IEEE80} Tabla 7"))
        elif top_rho is not None and surface_rho < top_rho and fault.get("surface_layer_present") is not False:
            out.append(_diagnostic("fault.surface_resistivity_ohm_m", "relation", "warning",
                                   f"La capa superficial ({surface_rho:g} Ω·m) es menos resistiva que el suelo bajo ella ({top_rho:g} Ω·m): "
                                   "no protege (Cs > 1). Si no hay capa superficial, decláralo en lugar de bajar su resistividad.",
                                   surface_rho, f">= {top_rho:g} Ω·m", source=f"{IEEE80} §7.4", related=["soil_layers[0].resistivity_ohm_m"]))

    for index, layer in enumerate(layers):
        rho = _number(layer.get("resistivity_ohm_m"))
        if rho is not None:
            if not SOIL_RESISTIVITY_ERROR_OHM_M[0] <= rho <= SOIL_RESISTIVITY_ERROR_OHM_M[1]:
                out.append(_diagnostic(f"soil_layers[{index}].resistivity_ohm_m", "range", "error",
                                       f"La resistividad de la capa {index + 1} ({rho:g} Ω·m) está fuera de "
                                       f"{SOIL_RESISTIVITY_ERROR_OHM_M[0]:g}–{SOIL_RESISTIVITY_ERROR_OHM_M[1]:g} Ω·m; ningún suelo la tiene. "
                                       "Revisa las unidades (Ω·m, no Ω·cm).",
                                       rho, f"{SOIL_RESISTIVITY_ERROR_OHM_M[0]:g}–{SOIL_RESISTIVITY_ERROR_OHM_M[1]:g} Ω·m",
                                       source=f"{IEEE80} Tabla 2"))
            elif not SOIL_RESISTIVITY_WARNING_OHM_M[0] <= rho <= SOIL_RESISTIVITY_WARNING_OHM_M[1]:
                out.append(_diagnostic(f"soil_layers[{index}].resistivity_ohm_m", "range", "warning",
                                       f"La resistividad de la capa {index + 1} ({rho:g} Ω·m) está fuera de los valores típicos "
                                       f"{SOIL_RESISTIVITY_WARNING_OHM_M[0]:g}–{SOIL_RESISTIVITY_WARNING_OHM_M[1]:g} Ω·m de IEEE 80-2013 Tabla 2; "
                                       "confirma la medición.",
                                       rho, f"{SOIL_RESISTIVITY_WARNING_OHM_M[0]:g}–{SOIL_RESISTIVITY_WARNING_OHM_M[1]:g} Ω·m",
                                       source=f"{IEEE80} Tabla 2"))
        depth = _number(layer.get("depth_m"))
        if depth is not None and index < len(layers) - 1 and depth < MIN_LAYER_THICKNESS_WARNING_M:
            out.append(_diagnostic(f"soil_layers[{index}].depth_m", "range", "warning",
                                   f"La capa {index + 1} tiene {depth:g} m de espesor; una capa más delgada que "
                                   f"{MIN_LAYER_THICKNESS_WARNING_M:g} m no se resuelve con sondeos de campo y apenas cambia el resultado.",
                                   depth, f">= {MIN_LAYER_THICKNESS_WARNING_M:g} m", source="interpretación de sondeos Wenner/Schlumberger"))
    return out


def coherence_errors(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [d for d in coherence_diagnostics(snapshot) if d["severity"] == "error"]


def coherence_warnings(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [d for d in coherence_diagnostics(snapshot) if d["severity"] == "warning"]


def sverak_resistance_ohm(resistivity_ohm_m: float, area_m2: float, total_length_m: float, burial_depth_m: float) -> float:
    """IEEE 80-2013 Eq. 52: grid resistance in uniform soil from area, buried length and depth."""
    if min(resistivity_ohm_m, area_m2, total_length_m) <= 0 or burial_depth_m < 0:
        raise ValueError("Sverak needs positive resistivity, area and conductor length and a non-negative depth")
    return resistivity_ohm_m * (1.0 / total_length_m
                                + 1.0 / sqrt(20.0 * area_m2) * (1.0 + 1.0 / (1.0 + burial_depth_m * sqrt(20.0 / area_m2))))


def resistance_plausibility(geometry: dict[str, Any], soil_layers: list[dict[str, Any]], resistance_ohm: float) -> dict[str, Any] | None:
    """Compare the engine's resistance with Sverak's estimate for the top-layer resistivity.

    Returns a warning diagnostic when the ratio leaves `SVERAK_RATIO_RANGE`, None otherwise (also when the
    estimate cannot be formed). The estimate assumes uniform soil, so deep contrasts widen the ratio
    legitimately; the bracket is wide for that reason and the message says so.
    """
    from src.domain.spat import geometry_graph as gg
    from src.domain.spat.geometry_cost import takeoff

    try:
        rho = float(soil_layers[0]["resistivity_ohm_m"])
        quantities = takeoff(geometry)
        graph = gg.normalize(gg.from_geometry(geometry))
        xs = [c for a, b, _ in graph.segments for c in (a[0], b[0])]
        ys = [c for a, b, _ in graph.segments for c in (a[1], b[1])]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0.0
        if area <= 0:   # a single straight conductor: use its length times one metre as the footprint
            area = max(quantities["conductor_length_total_m"], 1.0)
        total = quantities["conductor_length_total_m"] + sum(r["length_m"] for r in quantities["rods"].values())
        estimate = sverak_resistance_ohm(rho, area, total, float(geometry.get("burial_depth_m") or 0.0))
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if not (isfinite(resistance_ohm) and resistance_ohm > 0 and estimate > 0):
        return None
    ratio = resistance_ohm / estimate
    if SVERAK_RATIO_RANGE[0] <= ratio <= SVERAK_RATIO_RANGE[1]:
        return None
    return _diagnostic("result.grid_resistance_ohm", "plausibility", "warning",
                       f"La resistencia calculada ({resistance_ohm:.3g} Ω) difiere {ratio:.2g}× de la estimación de Sverak "
                       f"({estimate:.3g} Ω para {rho:g} Ω·m, {area:.0f} m² y {total:.0f} m enterrados). Si el suelo es estratificado "
                       "con contraste fuerte puede ser legítimo; si no, revisa la geometría, el suelo y las unidades.",
                       resistance_ohm, f"{SVERAK_RATIO_RANGE[0]:g}–{SVERAK_RATIO_RANGE[1]:g} × {estimate:.3g} Ω",
                       source=f"{IEEE80} Ec. 52 (Sverak)", related=["geometry", "soil_layers[0].resistivity_ohm_m"])
