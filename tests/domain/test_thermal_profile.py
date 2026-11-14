import copy

import pytest

from src.domain.spat.thermal_profile import load_profile, validate_profile


def profile():
    return copy.deepcopy(load_profile("IEEE 80-2013"))


def test_the_ieee_80_profile_is_versioned_and_every_row_has_its_source() -> None:
    loaded = load_profile("IEEE 80-2013")
    assert loaded["schema_version"] == "1.0" and loaded["equation_form"] == "tcap" and loaded["default_ambient_c"] == 40.0
    assert all(m["source"].startswith("IEEE Std 80-2013, Table 1") and m["published_kf"] for m in loaded["materials"])


def test_an_unknown_profile_is_rejected_with_an_explicit_error() -> None:
    with pytest.raises(ValueError, match="Perfil térmico no soportado: 'IEC 60949'"):
        load_profile("IEC 60949")


@pytest.mark.parametrize("mutate,message", [
    (lambda p: p["materials"][0].pop("source"), "source"),
    (lambda p: p.pop("reference"), "reference"),
    (lambda p: p["materials"][0].update(alpha_r=-0.1), "alpha_r"),
    (lambda p: p["materials"][0].update(tcap_j_cm3_c=0), "tcap_j_cm3_c"),
    (lambda p: p["materials"][0].update(fusion_temp_c="1083"), "fusion_temp_c"),
    (lambda p: p["materials"][0]["published_kf"][0].update(status="maybe"), "status"),
    (lambda p: p.update(equation_form="adiabatic"), "equation_form"),
    (lambda p: p["materials"].append(copy.deepcopy(p["materials"][0])), "repetidos"),
    (lambda p: p["aliases"].update(old="no_such_material"), "alias"),
    (lambda p: p["materials"][0].update(tcap_j_cm3_c=9.0), "TCAP"),
    (lambda p: p["materials"][0]["published_kf"][0].update(tm_c=5000), "Kf"),
])
def test_incomplete_or_inconsistent_profiles_are_rejected(mutate, message) -> None:
    broken = profile()
    mutate(broken)
    with pytest.raises(ValueError, match=message):
        validate_profile(broken)


def test_iec_and_retie_profiles_load_and_carry_their_sources() -> None:
    iec, retie = load_profile("IEC 60364-5-54:2011"), load_profile("RETIE 2024")
    assert iec["equation_form"] == "k_factor" and iec["max_duration_s"] == 5.0 and len(iec["published_k"]) == 18
    assert retie["equation_form"] == "kf" and len(retie["materials"]) == 14
    assert all("Tabla 3.12.2.2.a" in m["source"] for m in retie["materials"])
    assert {m["joint_type"] for m in retie["materials"] if "joint_type" in m} == {"exothermic", "mechanical"}


@pytest.mark.parametrize("profile_id,mutate,message", [
    ("IEC 60364-5-54:2011", lambda p: p["materials"][0].pop("beta_c"), "beta_c"),
    ("IEC 60364-5-54:2011", lambda p: p["published_k"][0].update(material_id="brass"), "desconocido"),
    ("IEC 60364-5-54:2011", lambda p: p["published_k"][0].update(final_c=10), "no supera"),
    ("IEC 60364-5-54:2011", lambda p: p["materials"].append(copy.deepcopy(p["materials"][0])), "repetidos"),
    ("IEC 60364-5-54:2011", lambda p: p.update(max_duration_s=0), "max_duration_s"),
    ("RETIE 2024", lambda p: p["materials"][0].pop("kf"), "kf"),
    ("RETIE 2024", lambda p: p["materials"][0].update(joint_type="bolted"), "joint_type"),
    ("RETIE 2024", lambda p: p["materials"].append(copy.deepcopy(p["materials"][0])), "repetidos"),
    ("RETIE 2024", lambda p: p["voltage_levels"].pop("low"), "low"),
    ("RETIE 2024", lambda p: p.update(equation_form="adiabatic"), "equation_form"),
])
def test_incomplete_iec_and_retie_profiles_are_rejected(profile_id, mutate, message) -> None:
    broken = copy.deepcopy(load_profile(profile_id))
    mutate(broken)
    with pytest.raises(ValueError, match=message):
        validate_profile(broken)
