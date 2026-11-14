"""The conductor chooses its thermal standard (IEEE 80, IEC 60364-5-54 or RETIE) and the choice reaches the result."""

import copy

import pytest
from pydantic import ValidationError

from src.domain.spat.artifact_contract import snapshot_fields, validate_artifact
from src.infrastructure.calculations.conductor_thermal import calculate_thermal_size
from src.infrastructure.calculations.conductor_thermal_profiles import (
    calculate_conductor_thermal, calculate_iec_size, calculate_retie_size, thermal_material_ids, thermal_profile_catalog)
from src.infrastructure.entrypoint.api.schemas import GroundingArtifactRequest, GroundingConductorRequest

from tests.infrastructure.test_identity import env, headers  # noqa: F401

BASE = {"material_id": "copper_hard_drawn", "cross_section_mm2": 70.0, "joint_type": "welded", "maximum_temperature_c": 250.0,
        "thermal_duration_s": 0.5, "ambient_temperature_c": 40.0}


def conductor(**changes):
    return GroundingConductorRequest.model_validate({**BASE, **changes})


def test_a_conductor_without_a_profile_keeps_using_ieee_80() -> None:
    model = GroundingConductorRequest()
    assert (model.thermal_profile, model.voltage_level) == ("IEEE 80-2013", "medium_high_extra_high")
    legacy = calculate_conductor_thermal({k: v for k, v in BASE.items()}, 10_000)
    assert legacy["profile"] == "IEEE 80-2013" and legacy["warnings"] == [] and legacy["joint_type"] == "welded"
    assert legacy["minimum_section_mm2"] == calculate_thermal_size(10_000, 0.5, 40, 250, "copper_hard_drawn", 70.0)["minimum_section_mm2"]


@pytest.mark.parametrize("changes,message", [
    ({"thermal_profile": "IEC 60949"}, "Perfil térmico no soportado"),
    ({"voltage_level": "ultra"}, "voltage_level"),
    ({"material_id": "copper_soft"}, "Material IEEE 80 no soportado"),                                   # a RETIE id on IEEE
    ({"thermal_profile": "RETIE 2024", "material_id": "copper_hard_drawn"}, "no soportado por RETIE 2024"),   # an IEEE id on RETIE
    ({"thermal_profile": "RETIE 2024", "material_id": "copper_soft", "ambient_temperature_c": 30}, "40 °C"),
    ({"thermal_profile": "RETIE 2024", "voltage_level": "low", "material_id": "copper_soft"}, "no soportado por RETIE 2024 \\(low\\)"),
    ({"thermal_profile": "IEC 60364-5-54:2011", "material_id": "copper", "thermal_duration_s": 5.5}, "IEC 60949"),
    ({"thermal_profile": "IEC 60364-5-54:2011", "material_id": "copper", "maximum_temperature_c": 30}, "superior a la temperatura ambiente"),
    ({"thermal_profile": "IEC 60364-5-54:2011", "material_id": "copper_hard_drawn"}, "no soportado por IEC"),
    ({"maximum_temperature_c": 1500}, "fusión"),
])
def test_the_conductor_is_validated_against_its_profile(changes, message) -> None:
    with pytest.raises(ValidationError, match=message):
        conductor(**changes)


def test_each_profile_accepts_its_own_materials() -> None:
    assert conductor(material_id="copper_clad_rod_20")  # retired IEEE id, still accepted (alias)
    assert conductor(thermal_profile="IEC 60364-5-54:2011", material_id="aluminium", maximum_temperature_c=300)
    assert conductor(thermal_profile="RETIE 2024", material_id="steel_1020", ambient_temperature_c=40)
    assert conductor(thermal_profile="RETIE 2024", voltage_level="low", material_id="steel", thermal_duration_s=5.0)


def test_the_catalog_and_the_validator_agree_on_every_material() -> None:
    catalog = thermal_profile_catalog()
    assert [entry["profile"] for entry in catalog] == ["IEEE 80-2013", "IEC 60364-5-54:2011", "RETIE 2024"]
    for entry in catalog:
        for mode in entry["modes"]:
            ids = [m["id"] for m in mode["materials"]]
            assert ids and len(ids) == len(set(ids))
            assert set(ids) <= thermal_material_ids(entry["profile"], mode["voltage_level"])
            for material_id in ids:
                level = mode["voltage_level"] or "medium_high_extra_high"
                temperatures = {"maximum_temperature_c": 250.0}
                assert conductor(thermal_profile=entry["profile"], voltage_level=level, material_id=material_id, **temperatures)
    retie = next(entry for entry in catalog if entry["profile"] == "RETIE 2024")
    assert {mode["voltage_level"]: mode["temperature_inputs"] for mode in retie["modes"]} == {
        "medium_high_extra_high": "table", "low": "initial_and_final"}


def test_the_dispatcher_applies_the_chosen_profile() -> None:
    iec = calculate_conductor_thermal({**BASE, "material_id": "copper", "thermal_profile": "IEC 60364-5-54:2011",
                                       "ambient_temperature_c": 30.0, "maximum_temperature_c": 200.0}, 10_000)
    assert iec["profile"] == "IEC 60364-5-54:2011"
    assert iec["minimum_section_mm2"] == calculate_iec_size(10_000, 0.5, "copper", 30, 200, 70.0)["minimum_section_mm2"]
    retie = calculate_conductor_thermal({**BASE, "material_id": "steel_1020", "thermal_profile": "RETIE 2024"}, 10_000)
    assert retie["profile"] == "RETIE 2024" and retie["maximum_temperature_c"] == 1510  # the table's Tm, not the 250 °C input
    assert retie["minimum_section_mm2"] == calculate_retie_size(10_000, 0.5, "steel_1020", 70.0)["minimum_section_mm2"]
    low = calculate_conductor_thermal({**BASE, "material_id": "copper", "thermal_profile": "RETIE 2024", "voltage_level": "low",
                                       "ambient_temperature_c": 30.0, "maximum_temperature_c": 200.0}, 10_000)
    assert low["profile"] == "RETIE 2024" and low["equation_source"] == "IEC 60364-5-54:2011"
    assert low["minimum_section_mm2"] == iec["minimum_section_mm2"]


def test_retie_warns_about_its_kf_and_about_a_joint_that_does_not_match_the_row() -> None:
    steel = calculate_conductor_thermal({**BASE, "material_id": "steel_1020", "thermal_profile": "RETIE 2024"}, 10_000)
    assert len(steel["warnings"]) == 1 and "IEEE 80-2013" in steel["warnings"][0] and "15,95" not in steel["warnings"][0]
    exothermic = {**BASE, "material_id": "copper_hard_exothermic", "thermal_profile": "RETIE 2024"}
    assert calculate_conductor_thermal({**exothermic, "joint_type": "welded"}, 10_000)["warnings"] == []
    mismatched = calculate_conductor_thermal({**exothermic, "joint_type": "bolted"}, 10_000)
    assert "soldadura exotérmica" in mismatched["warnings"][0] and "apernada" in mismatched["warnings"][0]
    assert calculate_conductor_thermal({**exothermic, "material_id": "copper_hard_mechanical", "joint_type": "bolted"}, 10_000)["warnings"] == []
    assert mismatched["joint_type"] == "bolted" and mismatched["retie_joint_type"] == "exothermic"


def test_the_dispatcher_rejects_a_material_of_another_profile() -> None:
    with pytest.raises(ValueError, match="no existe en el perfil RETIE 2024"):
        calculate_conductor_thermal({**BASE, "thermal_profile": "RETIE 2024"}, 10_000)  # copper_hard_drawn is an IEEE id


def test_only_a_chosen_profile_is_stored_so_existing_artifacts_do_not_change() -> None:
    for version in ("1.0", "2.0"):
        default = snapshot_fields(GroundingArtifactRequest(schema_version=version, name="d").model_dump(mode="json"))
        assert "thermal_profile" not in default["conductor"] and "voltage_level" not in default["conductor"]
        iec = snapshot_fields(GroundingArtifactRequest(schema_version=version, name="i", conductor=conductor(
            thermal_profile="IEC 60364-5-54:2011", material_id="copper")).model_dump(mode="json"))
        assert iec["conductor"]["thermal_profile"] == "IEC 60364-5-54:2011" and "voltage_level" not in iec["conductor"]
        low = snapshot_fields(GroundingArtifactRequest(schema_version=version, name="r", conductor=conductor(
            thermal_profile="RETIE 2024", voltage_level="low", material_id="copper")).model_dump(mode="json"))
        assert low["conductor"]["thermal_profile"] == "RETIE 2024" and low["conductor"]["voltage_level"] == "low"
        medium = snapshot_fields(GroundingArtifactRequest(schema_version=version, name="m", conductor=conductor(
            thermal_profile="RETIE 2024", material_id="copper_soft")).model_dump(mode="json"))
        assert medium["conductor"]["thermal_profile"] == "RETIE 2024" and "voltage_level" not in medium["conductor"]
        for stored in (default, iec, low, medium):
            validate_artifact(copy.deepcopy(stored))  # both schema versions accept what is stored


def test_a_saved_artifact_keeps_its_profile_and_the_catalog_is_served(env) -> None:  # noqa: F811
    _, _, client, _, tokens, _ = env
    assert client.get("/api/v1/perfiles-termicos").status_code == 401
    catalog = client.get("/api/v1/perfiles-termicos", headers=headers(tokens)).json()
    assert [entry["profile"] for entry in catalog] == ["IEEE 80-2013", "IEC 60364-5-54:2011", "RETIE 2024"]
    project = client.post("/api/v1/projects", json={"name": "Subestación"}, headers=headers(tokens)).json()
    base = f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras"
    payload = {"name": "RETIE", "conductor": {**BASE, "material_id": "steel_1020", "thermal_profile": "RETIE 2024"}}
    created = client.post(base, json=payload, headers=headers(tokens))
    assert created.status_code in (200, 201), created.text
    assert created.json()["snapshot"]["conductor"]["thermal_profile"] == "RETIE 2024"
    bad = client.post(base, json={"name": "x", "conductor": {**BASE, "thermal_profile": "RETIE 2024"}}, headers=headers(tokens))
    assert bad.status_code == 422 and "RETIE 2024" in bad.text
