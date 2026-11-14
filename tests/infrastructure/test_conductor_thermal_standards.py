"""IEC 60364-5-54:2011 and RETIE 2024 thermal sizing against the printed tables and equations.

Compared with the licensed IEC text and the official RETIE resolution (Resolución 40117 de 2024, Libro 3, 3.12.2.2)
on 2026-11-14. The rows below are transcribed from the printed tables, apart from the profile data under test.
"""

from math import sqrt

import pytest

from src.domain.spat.thermal_profile import load_profile
from src.infrastructure.calculations.conductor_thermal import calculate_thermal_size
from src.infrastructure.calculations.conductor_thermal_profiles import (
    calculate_iec_size, calculate_retie_size, iec_k_factor)

IEC = load_profile("IEC 60364-5-54:2011")
RETIE = load_profile("RETIE 2024")

# IEC 60364-5-54:2011, Table A.54.1: (material, published Qc(β+20)/ρ20 in A·√s/mm²)
A541 = {"copper": 226, "aluminium": 148, "steel": 78}
# Table A.54.6 and A.54.3, printed k values: (material, initial, final, k)
PRINTED_K = [("copper", 30, 500, 228), ("copper", 30, 200, 159), ("copper", 30, 150, 138), ("copper", 30, 220, 166),
             ("aluminium", 30, 300, 125), ("aluminium", 30, 200, 105), ("aluminium", 30, 150, 91), ("aluminium", 30, 220, 110),
             ("steel", 30, 500, 82), ("steel", 30, 200, 58), ("steel", 30, 150, 50), ("steel", 30, 220, 60)]

# RETIE Tabla 3.12.2.2.a as printed: (id, conductivity %, Tm °C, Kf)
RETIE_PRINTED = [
    ("copper_soft", 100, 1083, 7.0), ("copper_hard_exothermic", 97, 1084, 7.06), ("copper_hard_mechanical", 97, 250, 11.78),
    ("copper_clad_wire_40", 40, 1084, 10.45), ("copper_clad_wire_30", 30, 1084, 14.64), ("copper_clad_rod_20", 20, 1084, 14.64),
    ("aluminium_ec", 61, 657, 12.12), ("aluminium_alloy_5005", 53.5, 652, 12.41), ("aluminium_alloy_6201", 52.5, 654, 12.47),
    ("aluminum_clad_steel", 20.3, 657, 17.2), ("steel_1020", 10.8, 1510, 15.95), ("stainless_clad_rod", 9.8, 1400, 14.72),
    ("zinc_coated_steel_rod", 8.5, 419, 28.96), ("stainless_304", 2.4, 1400, 30.05)]


@pytest.mark.parametrize("material,published", A541.items())
def test_annex_a_parameters_reproduce_the_published_term(material, published) -> None:
    row = next(m for m in IEC["materials"] if m["id"] == material)
    assert sqrt(row["qc_j_c_mm3"] * (row["beta_c"] + 20.0) / row["rho20_ohm_mm"]) == pytest.approx(published, rel=5e-3)
    assert row["published_sqrt_term"] == published


@pytest.mark.parametrize("material,initial,final,printed", PRINTED_K)
def test_k_from_annex_a_matches_the_printed_tables(material, initial, final, printed) -> None:
    # Tables A.54.3 and A.54.6 print k as integers, hence half a unit plus the rounding of the table's own inputs.
    assert iec_k_factor(material, initial, final) == pytest.approx(printed, abs=0.6)


def test_the_profile_records_every_printed_k_and_they_agree_with_this_file() -> None:
    recorded = {(e["material_id"], e["initial_c"], e["final_c"], e["k"]) for e in IEC["published_k"]}
    assert recorded == set(PRINTED_K)


def test_iec_section_is_i_root_t_over_k() -> None:
    result = calculate_iec_size(10_000, 1.0, "copper", 30, 200, 70.0)
    assert result["minimum_section_mm2"] == pytest.approx(10_000 * 1.0 / 159, rel=5e-3)
    assert result["status"] == "cumple" and result["suggested_standard_section_mm2"] == 70.0
    short = calculate_iec_size(10_000, 1.0, "copper", 30, 200, 50.0)
    assert short["status"] == "no_cumple" and short["margin_mm2"] < 0 and short["suggested_standard_section_mm2"] == 70.0


def test_iec_formula_is_limited_to_five_seconds() -> None:
    assert calculate_iec_size(1000, 5.0, "copper", 30, 200, 16.0)["thermal_duration_s"] == 5.0
    with pytest.raises(ValueError, match="IEC 60949"):
        calculate_iec_size(1000, 5.01, "copper", 30, 200, 16.0)


@pytest.mark.parametrize("args,message", [
    ((1000, 1, "brass", 30, 200, 16), "no soportado"),
    ((1000, 1, "copper", 200, 200, 16), "superior a la inicial"),
    ((0, 1, "copper", 30, 200, 16), "positivos"),
    ((1000, 1, "copper", 30, 200, 0), "positiva"),
])
def test_iec_rejects_invalid_inputs(args, message) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_iec_size(*args)


@pytest.mark.parametrize("material_id,conductivity,tm,kf", RETIE_PRINTED)
def test_the_retie_profile_holds_the_table_as_printed(material_id, conductivity, tm, kf) -> None:
    row = next(m for m in RETIE["materials"] if m["id"] == material_id)
    assert (row["conductivity_pct"], row["tm_c"], row["kf"]) == (conductivity, tm, kf)
    assert len(RETIE["materials"]) == len(RETIE_PRINTED)


def test_retie_equation_4_on_the_annex_b_hard_drawn_copper_example() -> None:
    # IEEE 80-2013 Annex B.2 (6.814 kA, 0.5 s, exothermic hard-drawn copper): 34.02 kcmil = 17.2 mm².
    result = calculate_retie_size(6814, 0.5, "copper_hard_exothermic", 70.0)
    assert result["minimum_section_mm2"] == pytest.approx(7.06 * 6.814 * sqrt(0.5) / 1.9737, rel=1e-9)
    assert result["minimum_section_mm2"] == pytest.approx(17.2, abs=0.05)
    assert result["warnings"] == []


def test_retie_soft_copper_20_ka_3_s_matches_the_ieee_80_worked_example() -> None:
    # IEEE 80-2013 11.3.1.3 (a): 20 × 7 × √3 = 242.5 kcmil.
    result = calculate_retie_size(20_000, 3.0, "copper_soft", 150.0)
    assert result["minimum_section_mm2"] * 1.9737 == pytest.approx(242.5, abs=0.05)


def test_the_retie_joint_type_changes_the_temperature_and_the_section() -> None:
    exothermic = calculate_retie_size(10_000, 1.0, "copper_hard_exothermic", 70.0)
    mechanical = calculate_retie_size(10_000, 1.0, "copper_hard_mechanical", 70.0)
    assert (exothermic["joint_type"], exothermic["maximum_temperature_c"]) == ("exothermic", 1084)
    assert (mechanical["joint_type"], mechanical["maximum_temperature_c"]) == ("mechanical", 250)
    assert mechanical["minimum_section_mm2"] / exothermic["minimum_section_mm2"] == pytest.approx(11.78 / 7.06)


def test_retie_agrees_with_the_ieee_80_profile_where_both_print_the_same_kf() -> None:
    for retie_id, ieee_id, tm in [("copper_soft", "copper_annealed", 1083), ("copper_hard_exothermic", "copper_hard_drawn", 1084),
                                  ("copper_hard_mechanical", "copper_hard_drawn", 250), ("copper_clad_wire_40", "copper_clad_40", 1084)]:
        ieee = calculate_thermal_size(12_000, 0.8, 40.0, tm, ieee_id, 100.0)["minimum_section_mm2"]
        assert calculate_retie_size(12_000, 0.8, retie_id, 100.0)["minimum_section_mm2"] == pytest.approx(ieee, rel=2e-3)


@pytest.mark.parametrize("material_id,warned", [
    ("steel_1020", True),             # RETIE keeps the 2000-edition Kf 15.95; IEEE 80-2013 gives 18.39
    ("copper_clad_rod_20", True),     # 14.64 printed; Table 1 of IEEE 80-2013 derives 15.84
    ("stainless_clad_rod", True),     # 14.72 printed; Table 1 of IEEE 80-2013 derives 18.26
    ("copper_clad_wire_30", False),   # 14.64 printed (a copy of the rod); IEEE 80-2013 gives 12.06: RETIE is the larger
    ("copper_soft", False), ("aluminium_ec", False),
])
def test_retie_reports_when_its_kf_is_below_ieee_80_2013_without_changing_it(material_id, warned) -> None:
    result = calculate_retie_size(10_000, 1.0, material_id, 100.0)
    assert bool(result["warnings"]) is warned
    printed = next(kf for mid, _, _, kf in RETIE_PRINTED if mid == material_id)
    assert result["kf_kcmil_per_ka_sqrt_s"] == printed


def test_the_steel_1020_warning_quantifies_the_difference() -> None:
    result = calculate_retie_size(10_000, 1.0, "steel_1020", 100.0)
    assert result["ieee80_2013_kf_kcmil_per_ka_sqrt_s"] == pytest.approx(18.39, rel=1e-3)
    assert "15,95" not in result["warnings"][0] and "15.95" in result["warnings"][0] and "15 %" in result["warnings"][0]


def test_retie_low_voltage_is_not_calculated_here() -> None:
    with pytest.raises(ValueError, match="IEC 60364-5-54"):
        calculate_retie_size(5000, 1.0, "copper_soft", 35.0, voltage_level="low")
    with pytest.raises(ValueError, match="no soportado"):
        calculate_retie_size(5000, 1.0, "copper_soft", 35.0, voltage_level="ultra")
    with pytest.raises(ValueError, match="Material RETIE"):
        calculate_retie_size(5000, 1.0, "unobtainium", 35.0)
