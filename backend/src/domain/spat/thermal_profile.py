"""Versioned thermal sizing profiles: the normative constants as data, each with its source.

A profile is a JSON document validated against `thermal_profiles/thermal-profile-1.0.json`. Unknown
or incomplete profiles are rejected with an explicit error instead of falling back to defaults.
The joint-type temperature limit is not part of a profile: IEEE 80-2013 gives none (11.3.3 defers
to IEEE 837 and the manufacturer), so it stays an explicit input of the calculation.
"""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

PROFILE_DIR = Path(__file__).with_name("thermal_profiles")
SCHEMA_PATH = PROFILE_DIR / "thermal-profile-1.0.json"
PROFILE_FILES = {"IEEE 80-2013": PROFILE_DIR / "ieee-80-2013.json"}
TCAP_PRINTED_TOLERANCE = 0.051  # the unrounded TCAP may differ from the printed one by its rounding only


def validate_profile(profile) -> dict:
    """Return the profile if it satisfies the schema and its own consistency rules, else raise ValueError."""
    if not isinstance(profile, dict):
        raise ValueError("El perfil térmico debe ser un objeto.")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(profile), key=lambda e: list(e.absolute_path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "$"
        raise ValueError(f"Perfil térmico inválido en {location}: {errors[0].message}")
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
    return profile


@lru_cache(maxsize=None)
def load_profile(profile_id: str) -> dict:
    path = PROFILE_FILES.get(profile_id)
    if path is None:
        raise ValueError(f"Perfil térmico no soportado: {profile_id!r}.")
    return validate_profile(json.loads(path.read_text(encoding="utf-8")))
