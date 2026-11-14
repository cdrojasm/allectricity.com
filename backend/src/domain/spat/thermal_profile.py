"""Versioned thermal sizing profiles: the normative constants as data, each with its source.

A profile is a JSON document validated against the schema of its equation form (`thermal_profiles/`). Unknown
or incomplete profiles are rejected with an explicit error instead of falling back to defaults.
IEEE 80-2013 gives no temperature limit per joint type (11.3.3 defers to IEEE 837 and the
manufacturer), so there it stays an explicit input; the RETIE profile does tabulate one for hard-drawn copper.
"""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

DEFAULT_THERMAL_PROFILE = "IEEE 80-2013"
RETIE_PROFILE_ID = "RETIE 2024"
DEFAULT_VOLTAGE_LEVEL = "medium_high_extra_high"
PROFILE_DIR = Path(__file__).with_name("thermal_profiles")
PROFILE_FILES = {"IEEE 80-2013": PROFILE_DIR / "ieee-80-2013.json",
                 "IEC 60364-5-54:2011": PROFILE_DIR / "iec-60364-5-54-2011.json",
                 "RETIE 2024": PROFILE_DIR / "retie-2024.json"}
# One schema per equation form: TCAP (IEEE 80), tabulated Kf (RETIE) and k from Annex A (IEC).
SCHEMA_FILES = {"tcap": PROFILE_DIR / "thermal-profile-1.0.json",
                "kf": PROFILE_DIR / "thermal-profile-kf-1.0.json",
                "k_factor": PROFILE_DIR / "thermal-profile-k-factor-1.0.json"}
TCAP_PRINTED_TOLERANCE = 0.051  # the unrounded TCAP may differ from the printed one by its rounding only


def _check_tcap(profile: dict) -> None:
    ids = [material["id"] for material in profile["materials"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Perfil térmico inválido: identificadores de material repetidos.")
    for alias, target in profile["aliases"].items():
        if target not in ids or alias in ids:
            raise ValueError(f"Perfil térmico inválido: el alias {alias!r} debe apuntar a un material existente y no ser uno.")
    for material in profile["materials"]:
        if abs(material["tcap_j_cm3_c"] - material["tcap_printed_j_cm3_c"]) > TCAP_PRINTED_TOLERANCE:
            raise ValueError(f"Perfil térmico inválido: TCAP de {material['id']} no concuerda con el valor impreso.")
        if any(entry["tm_c"] > material["fusion_temp_c"] for entry in material["published_kf"]):
            raise ValueError(f"Perfil térmico inválido: Kf de {material['id']} a una temperatura sobre su fusión.")


def _check_kf(profile: dict) -> None:
    ids = [material["id"] for material in profile["materials"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Perfil térmico inválido: identificadores de material repetidos.")


def _check_k_factor(profile: dict) -> None:
    ids = [material["id"] for material in profile["materials"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Perfil térmico inválido: identificadores de material repetidos.")
    for entry in profile["published_k"]:
        if entry["material_id"] not in ids:
            raise ValueError(f"Perfil térmico inválido: k publicado de un material desconocido ({entry['material_id']!r}).")
        if entry["final_c"] <= entry["initial_c"]:
            raise ValueError("Perfil térmico inválido: la temperatura final de un k publicado no supera la inicial.")


CHECKS = {"tcap": _check_tcap, "kf": _check_kf, "k_factor": _check_k_factor}


def validate_profile(profile) -> dict:
    """Return the profile if it satisfies the schema of its equation form and its own consistency rules, else raise ValueError."""
    if not isinstance(profile, dict):
        raise ValueError("El perfil térmico debe ser un objeto.")
    form = profile.get("equation_form")
    if form not in SCHEMA_FILES:
        raise ValueError(f"Perfil térmico inválido en equation_form: {form!r} no es una forma de ecuación soportada.")
    schema = json.loads(SCHEMA_FILES[form].read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(profile), key=lambda e: list(e.absolute_path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "$"
        raise ValueError(f"Perfil térmico inválido en {location}: {errors[0].message}")
    CHECKS[form](profile)
    return profile


@lru_cache(maxsize=None)
def load_profile(profile_id: str) -> dict:
    path = PROFILE_FILES.get(profile_id)
    if path is None:
        raise ValueError(f"Perfil térmico no soportado: {profile_id!r}.")
    return validate_profile(json.loads(path.read_text(encoding="utf-8")))
