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
