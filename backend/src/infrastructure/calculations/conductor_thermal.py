"""IEEE Std 80-2013 thermal sizing for grounding conductors (Clause 11.3)."""

from __future__ import annotations

from math import log, pi, sqrt
from typing import Any

from src.domain.spat.thermal_profile import load_profile


IEEE80_PROFILE = "IEEE 80-2013"
REFERENCE = "IEEE Std 80-2013, 11.3.1, Eq. (37), Table 1; corrigendum 1-2015"

# Material constants come from the versioned profile (IEEE 80-2013 Table 1, each row with its source).
# Resistivity is in micro-ohm-cm, TCAP in J/(cm³·°C), and alpha in 1/°C.
_PROFILE = load_profile(IEEE80_PROFILE)
MATERIALS: dict[str, dict[str, Any]] = {
    material["id"]: {"name": material["name"], "alpha": material["alpha_r"], "k0_c": material["k0_c"],
                     "resistivity_micro_ohm_cm": material["resistivity_micro_ohm_cm"],
                     "tcap_j_cm3_c": material["tcap_j_cm3_c"], "fusion_temp_c": material["fusion_temp_c"],
                     "source": material["source"]}
    for material in _PROFILE["materials"]
}
# Retired identifiers still found in saved artifacts resolve to their current material.
MATERIAL_ALIASES: dict[str, str] = dict(_PROFILE["aliases"])
MATERIALS.update({alias: MATERIALS[target] for alias, target in MATERIAL_ALIASES.items()})

# Nominal metric sections used only to suggest a next standard size, not to
# imply compliance with a particular procurement catalogue.
STANDARD_SECTIONS_MM2 = (16.0, 25.0, 35.0, 50.0, 70.0, 95.0, 120.0, 150.0,
                         185.0, 240.0, 300.0, 400.0, 500.0, 630.0, 800.0, 1000.0)


def equivalent_radius_m(section_mm2: float) -> float:
    """Equivalent solid circular radius for the potential solver."""
    if section_mm2 <= 0:
        raise ValueError("La sección del conductor debe ser positiva.")
    return sqrt(section_mm2 / pi) / 1000.0


def calculate_thermal_size(current_a: float, duration_s: float, ambient_temp_c: float,
                           max_temp_c: float, material_id: str, selected_section_mm2: float) -> dict[str, Any]:
    """Compute minimum area from the adiabatic heat balance used by IEEE 80 Eq. (37).

    The SI conversion is written explicitly to avoid mixing the standard's cm³,
    micro-ohm-cm, kcmil and mm² forms. It assumes symmetrical RMS current; callers
    must apply D_f when required and state the current basis in the trace.
    """
    if material_id not in MATERIALS:
        raise ValueError(f"Material IEEE 80 no soportado: {material_id}.")
    if current_a <= 0 or duration_s <= 0:
        raise ValueError("La corriente y la duración térmica t_c deben ser positivas.")
    if selected_section_mm2 <= 0:
        raise ValueError("La sección elegida debe ser positiva.")
    if ambient_temp_c < -273.15 or max_temp_c <= ambient_temp_c:
        raise ValueError("La temperatura máxima debe ser superior a la temperatura ambiente.")
    canonical_id = MATERIAL_ALIASES.get(material_id, material_id)
    material = MATERIALS[canonical_id]
    if material["k0_c"] + ambient_temp_c <= 0:
        raise ValueError("La temperatura ambiente está fuera del rango válido del modelo térmico.")
    if max_temp_c > material["fusion_temp_c"]:
        raise ValueError(f"La temperatura máxima supera la de fusión del material ({material['fusion_temp_c']:g} °C).")
    logarithm = log((material["k0_c"] + max_temp_c) / (material["k0_c"] + ambient_temp_c))
    # j [A/mm²] = 10 sqrt(TCAP / (rho[µΩ·cm] alpha t) · ln(...)).
    current_density_a_mm2 = 10.0 * sqrt(
        material["tcap_j_cm3_c"] * logarithm /
        (material["resistivity_micro_ohm_cm"] * material["alpha"] * duration_s)
    )
    minimum = current_a / current_density_a_mm2
    # IEEE 80's simplified English-unit form is A[kcmil] = I[kA]·Kf·sqrt(t[s]).
    # Derive Kf from the same material/temperature constants, then independently
    # convert its result back to mm² to make unit and algebra agreement visible.
    kf_kcmil_per_ka_sqrt_s = (
        1000.0 / (0.506707 * 10.0)
        * sqrt(material["resistivity_micro_ohm_cm"] * material["alpha"] /
               (material["tcap_j_cm3_c"] * logarithm))
    )
    minimum_kcmil_kf = (current_a / 1000.0) * kf_kcmil_per_ka_sqrt_s * sqrt(duration_s)
    minimum_mm2_kf = minimum_kcmil_kf * 0.506707
    kf_difference_percent = 100.0 * abs(minimum_mm2_kf - minimum) / minimum
    commercial = next((section for section in STANDARD_SECTIONS_MM2 if section >= minimum), None)
    selected = float(selected_section_mm2)
    return {
        "profile": IEEE80_PROFILE,
        "status": "cumple" if selected >= minimum else "no_cumple",
        "current_a": current_a,
        "current_basis": "corriente RMS inyectada a la malla después de D_f y S_f cuando fueron suministrados; no representa la distribución por tramo",
        "thermal_duration_s": duration_s,
        "ambient_temperature_c": ambient_temp_c,
        "maximum_temperature_c": max_temp_c,
        "material_id": canonical_id,
        **({"material_id_requested": material_id} if canonical_id != material_id else {}),
        "material_name": material["name"],
        "material_constants_source": material["source"],
        "selected_section_mm2": selected,
        "selected_section_kcmil": selected / 0.506707,
        "minimum_section_mm2": minimum,
        "minimum_section_kcmil": minimum / 0.506707,
        "minimum_section_kcmil_kf": minimum_kcmil_kf,
        "kf_kcmil_per_ka_sqrt_s": kf_kcmil_per_ka_sqrt_s,
        "tcap_kf_difference_percent": kf_difference_percent,
        "margin_mm2": selected - minimum,
        "margin_percent": 100.0 * (selected - minimum) / minimum,
        "suggested_standard_section_mm2": commercial,
        "equivalent_radius_m": equivalent_radius_m(selected),
        "equation": "TCAP: A(mm²)=I(A)/[10·sqrt(TCAP·ln((K0+Tm)/(K0+Ta))/(rho_r·alpha_r·t_c))]; Kf: A(kcmil)=I(kA)·Kf·sqrt(t_c), Kf derived from the same IEEE 80 material constants",
        "reference": REFERENCE,
        "standard_url": "https://standards.ieee.org/ieee/80/4089/",
        "assumptions": ["Calentamiento adiabático; no incluye energía no adiabática ni reparto de corriente por conductor.",
                        "La temperatura máxima seleccionada debe respetar conductor, conexión y entorno; se registra como entrada.",
                        "La sección comercial sugerida es orientativa y debe comprobarse con el catálogo aplicable."],
        "material_constants": {key: material[key] for key in (
            "alpha", "k0_c", "resistivity_micro_ohm_cm", "tcap_j_cm3_c", "fusion_temp_c")},
    }
