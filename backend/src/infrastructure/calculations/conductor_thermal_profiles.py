"""Thermal sizing of grounding conductors by the IEC 60364-5-54 and RETIE 2024 profiles.

IEEE Std 80-2013 lives in `conductor_thermal`. These two follow other equation forms:
IEC 60364-5-54:2011 543.1.2 sizes with S = I·√t / k, k being derived from Annex A; the
Colombian RETIE (Resolución 40117 de 2024, Libro 3, 3.12.2.2) uses that same IEC equation for
low voltage and the IEEE 80 Kf form with its own table for medium, high and extra high voltage.
"""

from __future__ import annotations

from math import log, sqrt
from typing import Any

from src.domain.spat.thermal_profile import load_profile
from src.infrastructure.calculations.conductor_thermal import (
    IEEE80_PROFILE, STANDARD_SECTIONS_MM2, calculate_thermal_size, equivalent_radius_m)

IEC_PROFILE = "IEC 60364-5-54:2011"
RETIE_PROFILE = "RETIE 2024"
# A RETIE Kf below the IEEE 80-2013 value for the same material and Tm is reported, never silently corrected.
RETIE_KF_WARNING_THRESHOLD = 0.99


def _positive(current_a: float, duration_s: float, selected_section_mm2: float) -> None:
    if current_a <= 0 or duration_s <= 0:
        raise ValueError("La corriente y el tiempo de despeje deben ser positivos.")
    if selected_section_mm2 <= 0:
        raise ValueError("La sección elegida debe ser positiva.")


def _verdict(minimum_mm2: float, selected_mm2: float) -> dict[str, Any]:
    return {
        "status": "cumple" if selected_mm2 >= minimum_mm2 else "no_cumple",
        "minimum_section_mm2": minimum_mm2,
        "selected_section_mm2": selected_mm2,
        "margin_mm2": selected_mm2 - minimum_mm2,
        "margin_percent": 100.0 * (selected_mm2 - minimum_mm2) / minimum_mm2,
        "suggested_standard_section_mm2": next((s for s in STANDARD_SECTIONS_MM2 if s >= minimum_mm2), None),
        "equivalent_radius_m": equivalent_radius_m(selected_mm2),
    }


def iec_k_factor(material_id: str, initial_c: float, final_c: float) -> float:
    """k = sqrt( Qc (β + 20) / ρ20 · ln((β + θf) / (β + θi)) ), IEC 60364-5-54:2011 Annex A."""
    profile = load_profile(IEC_PROFILE)
    material = next((m for m in profile["materials"] if m["id"] == material_id), None)
    if material is None:
        raise ValueError(f"Material IEC 60364-5-54 no soportado: {material_id}.")
    if final_c <= initial_c:
        raise ValueError("La temperatura final debe ser superior a la inicial.")
    beta = material["beta_c"]
    if beta + initial_c <= 0:
        raise ValueError("La temperatura inicial está fuera del rango válido del modelo.")
    return sqrt(material["qc_j_c_mm3"] * (beta + 20.0) / material["rho20_ohm_mm"] * log((beta + final_c) / (beta + initial_c)))


def calculate_iec_size(current_a: float, duration_s: float, material_id: str, initial_c: float, final_c: float,
                       selected_section_mm2: float) -> dict[str, Any]:
    """Minimum section S = I·√t / k (IEC 60364-5-54:2011 543.1.2), adiabatic, for disconnection times up to 5 s.

    `current_a` is the r.m.s. fault current in amperes for a fault of negligible impedance.
    """
    profile = load_profile(IEC_PROFILE)
    _positive(current_a, duration_s, selected_section_mm2)
    if duration_s > profile["max_duration_s"]:
        raise ValueError(f"La fórmula de IEC 60364-5-54 543.1.2 solo aplica a tiempos de desconexión de hasta "
                         f"{profile['max_duration_s']:g} s; para tiempos mayores se requiere IEC 60949.")
    k = iec_k_factor(material_id, initial_c, final_c)
    minimum = current_a * sqrt(duration_s) / k
    material = next(m for m in profile["materials"] if m["id"] == material_id)
    return {
        "profile": IEC_PROFILE, **_verdict(minimum, float(selected_section_mm2)),
        "current_a": current_a, "thermal_duration_s": duration_s,
        "material_id": material_id, "material_name": material["name"], "material_constants_source": material["source"],
        "initial_temperature_c": initial_c, "final_temperature_c": final_c, "k_factor": k,
        "equation": "S[mm²] = I[A]·√t[s] / k; k = sqrt(Qc·(β+20)/ρ20 · ln((β+θf)/(β+θi)))",
        "reference": profile["reference"],
        "assumptions": ["Calentamiento adiabático para t ≤ 5 s; no incluye el efecto limitador de corriente de las impedancias ni la limitación de I²t del dispositivo (Notas 1 y 2 de 543.1.2).",
                        "Las temperaturas inicial y final deben respetar el material vecino y el entorno (Tablas A.54.2 a A.54.6).",
                        "Si la sección calculada no es normalizada se usa la normalizada inmediatamente superior."],
    }


def calculate_retie_size(current_a: float, duration_s: float, material_id: str, selected_section_mm2: float,
                         voltage_level: str = "medium_high_extra_high") -> dict[str, Any]:
    """Minimum section of the earthing conductor by RETIE 2024, Libro 3, 3.12.2.2, Equation 4.

    A[mm²] = I[kA]·Kf·√tc / 1,9737 for medium, high and extra high voltage, with Kf and Tm taken as printed in
    Table 3.12.2.2.a. Low voltage uses IEC 60364-5-54 (Equation 3, `calculate_iec_size`) or the NTC 2050 table.
    """
    profile = load_profile(RETIE_PROFILE)
    if voltage_level == "low":
        raise ValueError("RETIE 2024 usa en baja tensión la Ecuación 3 (IEC 60364-5-54, calculate_iec_size) o la Tabla 250-66 "
                         "de la NTC 2050, que no está cargada; no se calcula aquí.")
    if voltage_level != "medium_high_extra_high":
        raise ValueError(f"Nivel de tensión no soportado por RETIE 2024: {voltage_level!r}.")
    _positive(current_a, duration_s, selected_section_mm2)
    material = next((m for m in profile["materials"] if m["id"] == material_id), None)
    if material is None:
        raise ValueError(f"Material RETIE 2024 no soportado: {material_id}.")
    divisor = profile["area_divisor_kcmil_per_mm2"]
    minimum = (current_a / 1000.0) * material["kf"] * sqrt(duration_s) / divisor
    warnings = []
    ieee_id = material["ieee80_2013_material_id"]
    ieee_kf = None
    if ieee_id:
        ieee_kf = calculate_thermal_size(1000.0, 1.0, profile["default_ambient_c"], material["tm_c"], ieee_id,
                                         float(selected_section_mm2))["kf_kcmil_per_ka_sqrt_s"]
        if material["kf"] < ieee_kf * RETIE_KF_WARNING_THRESHOLD:
            warnings.append(
                f"El Kf de RETIE ({material['kf']:g}) es menor que el de IEEE 80-2013 para el mismo material y Tm ({ieee_kf:.2f}); "
                f"la sección mínima por IEEE 80-2013 sería {100.0 * (ieee_kf / material['kf'] - 1.0):.0f} % mayor. "
                "Se aplica el valor del reglamento.")
    return {
        "profile": RETIE_PROFILE, **_verdict(minimum, float(selected_section_mm2)),
        "current_a": current_a, "thermal_duration_s": duration_s, "voltage_level": voltage_level,
        "material_id": material_id, "material_name": material["name"], "material_constants_source": material["source"],
        **({"joint_type": material["joint_type"]} if "joint_type" in material else {}),
        "maximum_temperature_c": material["tm_c"], "kf_kcmil_per_ka_sqrt_s": material["kf"],
        "ieee80_2013_kf_kcmil_per_ka_sqrt_s": ieee_kf, "ieee80_2013_profile": IEEE80_PROFILE,
        "equation": profile["voltage_levels"]["medium_high_extra_high"]["equation"],
        "reference": profile["reference"], "issuing_act": profile["issuing_act"],
        "warnings": warnings,
        "assumptions": ["Corriente simétrica de falla a tierra en kA suministrada por el operador de red y tiempo de despeje de la falla.",
                        "La temperatura no debe superar la del aislamiento de los conductores activos alojados en la misma canalización (nota a).",
                        "La sección comercial sugerida es orientativa y debe comprobarse con el catálogo aplicable."],
    }
