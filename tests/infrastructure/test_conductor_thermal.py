from src.infrastructure.calculations.conductor_thermal import calculate_thermal_size


def test_tcap_and_kf_forms_match_ieee_80_copper_clad_example() -> None:
    # IEEE 80-2013 §11.3.1.3 worked material example: 30% copper-clad steel,
    # 1 kA, 1 s, 40 °C ambient and 1084 °C maximum; A = 12.06 kcmil/kA.
    result = calculate_thermal_size(
        current_a=1000,
        duration_s=1,
        ambient_temp_c=40,
        max_temp_c=1084,
        material_id="copper_clad_30",
        selected_section_mm2=16,
    )

    assert abs(result["minimum_section_kcmil"] - 12.06) < 0.01
    assert abs(result["minimum_section_kcmil_kf"] - result["minimum_section_kcmil"]) < 1e-10
    assert result["tcap_kf_difference_percent"] < 1e-10
