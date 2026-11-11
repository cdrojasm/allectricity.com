"""Validation of the IEEE Std 80-2013 thermal sizing against the published Tables 1 and 2 and the worked examples.

The licensed copy was compared page by page (Tables 1 and 2, 11.3.1.2, 11.3.1.3 and Annex B). The numbers in this
file are the printed ones. Where the norm contradicts itself the test says so and pins the behaviour we chose.
"""

from math import log, sqrt

import pytest

from src.domain.spat.thermal_profile import load_profile
from src.infrastructure.calculations.conductor_thermal import MATERIALS, MATERIAL_ALIASES, calculate_thermal_size

PROFILE = load_profile("IEEE 80-2013")
ROWS = {material["id"]: material for material in PROFILE["materials"]}


def size(material_id, current_a, duration_s, max_temp_c, ambient_c=40.0, section_mm2=1000.0):
    return calculate_thermal_size(current_a, duration_s, ambient_c, max_temp_c, material_id, section_mm2)


def kf_of(material_id, max_temp_c):
    return size(material_id, 1000.0, 1.0, max_temp_c)["kf_kcmil_per_ka_sqrt_s"]


def eq46_kcmil(row, current_ka, duration_s, max_temp_c, ambient_c=40.0):
    """IEEE 80-2013 Eq. (46) written apart from the module under test, in the norm's English-unit form."""
    return current_ka * 197.4 / sqrt(row["tcap_j_cm3_c"] / (duration_s * row["alpha_r"] * row["resistivity_micro_ohm_cm"])
                                     * log((row["k0_c"] + max_temp_c) / (row["k0_c"] + ambient_c)))


CONSISTENT = [(m["id"], entry["tm_c"], entry["value"]) for m in PROFILE["materials"]
              for entry in m["published_kf"] if entry["status"] == "consistent"]
STALE = [(m["id"], entry["tm_c"], entry["value"]) for m in PROFILE["materials"]
         for entry in m["published_kf"] if entry["status"] == "stale_in_norm"]


@pytest.mark.parametrize("material_id,tm_c,published", CONSISTENT)
def test_kf_matches_table_2_for_every_consistent_row(material_id, tm_c, published) -> None:
    # Table 2 prints Kf to two decimals; the unrounded TCAP behind Table 1 explains the rest of the gap.
    assert kf_of(material_id, tm_c) == pytest.approx(published, rel=1e-3)


@pytest.mark.parametrize("material_id", sorted(ROWS))
def test_the_module_agrees_with_an_independent_eq_46(material_id) -> None:
    row = ROWS[material_id]
    for tm_c in (min(row["fusion_temp_c"], 700.0), row["fusion_temp_c"]):
        # 197.4 is the norm's rounding of 1/0.506707, hence 1e-3.
        assert size(material_id, 12_500.0, 0.75, tm_c)["minimum_section_kcmil"] == pytest.approx(
            eq46_kcmil(row, 12.5, 0.75, tm_c), rel=1e-3)


@pytest.mark.parametrize("material_id,tm_c,published", STALE)
def test_table_2_rows_the_norm_did_not_update_stay_conservative(material_id, tm_c, published) -> None:
    # Table 1 (2013) changed these rods but Table 2 still prints the previous edition's Kf. We follow Table 1
    # (the primary data, with the derivation printed for the copper-clad rod); its Kf is larger, so the section too.
    assert kf_of(material_id, tm_c) > published * 1.05


def test_the_two_stale_rows_are_exactly_the_documented_ones() -> None:
    assert sorted(item[0] for item in STALE) == ["copper_clad_rod_17", "stainless_clad_rod"]
    assert kf_of("copper_clad_rod_17", 1084) == pytest.approx(15.84, abs=0.01)
    assert kf_of("stainless_clad_rod", 1400) == pytest.approx(18.26, abs=0.01)


def test_worked_example_11_3_1_2_copper_clad_steel_30_percent() -> None:
    result = size("copper_clad_30", 1000, 1, 1084)
    assert result["minimum_section_kcmil"] == pytest.approx(12.06, abs=0.01)
    assert result["minimum_section_mm2"] == pytest.approx(6.11, abs=0.01)


@pytest.mark.parametrize("material_id,tm_c,published_kcmil", [("copper_annealed", 1083, 242.5), ("copper_clad_40", 1084, 362.0)])
def test_worked_examples_11_3_1_3_20_ka_3_s(material_id, tm_c, published_kcmil) -> None:
    assert size(material_id, 20_000, 3, tm_c)["minimum_section_kcmil"] == pytest.approx(published_kcmil, rel=1e-3)


def test_steel_example_of_11_3_1_3_is_superseded_by_table_2() -> None:
    # The printed example (c) uses Kf 15.95 (2000 edition, 552.5 kcmil); the 2013 Tables 1 and 2 agree on 18.39.
    assert 20 * 15.95 * sqrt(3) == pytest.approx(552.5, abs=0.05)
    assert size("steel_1020", 20_000, 3, 1510)["minimum_section_kcmil"] == pytest.approx(20 * 18.39 * sqrt(3), rel=1e-3)


def test_annex_b_hard_drawn_copper_example() -> None:
    result = size("copper_hard_drawn", 6814, 0.5, 1084)
    assert result["minimum_section_kcmil"] == pytest.approx(34.02, rel=2e-3)
    assert result["minimum_section_mm2"] == pytest.approx(17.2, abs=0.05)


def test_annex_b_copper_clad_example_is_not_reproducible_from_its_printed_inputs() -> None:
    # Annex B prints 59.81 kcmil for 30 % copper-clad steel, 0.5 s, 700 °C, 6.814 kA, but Eq. (46) with the inputs printed
    # in the same line gives 65.88 kcmil. We keep the formula; the printed result is recorded here as a suspected erratum.
    assert size("copper_clad_30", 6814, 0.5, 700)["minimum_section_kcmil"] == pytest.approx(65.88, abs=0.05)


def test_tcap_and_kf_forms_are_the_same_calculation_in_two_unit_systems() -> None:
    # Both forms derive from the same constants, so this only proves the unit conversion; the contrast with the
    # norm is what the tests above do.
    result = size("copper_clad_30", 1000, 1, 1084)
    assert abs(result["minimum_section_kcmil_kf"] - result["minimum_section_kcmil"]) < 1e-10
    assert result["tcap_kf_difference_percent"] < 1e-10


def test_saved_artifacts_with_the_retired_rod_id_use_the_current_row() -> None:
    assert MATERIAL_ALIASES == {"copper_clad_rod_20": "copper_clad_rod_17"}
    legacy, current = size("copper_clad_rod_20", 5000, 1, 1084), size("copper_clad_rod_17", 5000, 1, 1084)
    assert legacy["minimum_section_mm2"] == current["minimum_section_mm2"]
    assert legacy["material_id"] == "copper_clad_rod_17" and legacy["material_id_requested"] == "copper_clad_rod_20"
    assert "material_id_requested" not in current
    assert MATERIALS["copper_clad_rod_20"] is MATERIALS["copper_clad_rod_17"]


def test_the_result_names_the_source_of_the_constants() -> None:
    assert size("steel_1020", 1000, 1, 600)["material_constants_source"] == "IEEE Std 80-2013, Table 1, row 'Steel, 1020'"


def test_the_maximum_temperature_cannot_exceed_the_fusion_point() -> None:
    with pytest.raises(ValueError, match="fusión"):
        size("zinc_coated_steel_rod", 1000, 1, 500)
