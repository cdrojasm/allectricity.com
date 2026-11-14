from src.infrastructure.entrypoint.api.study_routes import RESULT_DETAIL_KEYS, _calculation_detail


def test_public_study_detail_carries_what_the_workspace_results_panel_draws():
    calculation = {
        "parameters": {"touch_reach_m": 1.5, "safety_standards": ["IEEE 80-2013"], "justification": "internal note"},
        "result": {"grid_resistance_ohm": 3.1, "gpr_v": 26000.0, "injected_current_a": 8500.0, "safety": [{"standard": "IEEE 80-2013"}],
                   "conductor_thermal": {"status": "cumple"}, "surface_potential": {"nx": 2, "ny": 2, "values_v": [1, 2, 3, 4]},
                   "model_warnings": ["w"], "trace": {"private": "not published"}, "segment_count": 546},
    }
    detail = _calculation_detail(calculation)
    assert set(detail["result"]) == set(RESULT_DETAIL_KEYS)
    assert "trace" not in detail["result"] and "segment_count" not in detail["result"]
    assert detail["parameters"] == {"touch_reach_m": 1.5, "safety_standards": ["IEEE 80-2013"]}


def test_public_study_detail_tolerates_a_result_without_the_workspace_fields():
    assert _calculation_detail({"parameters": None, "result": {"scenario_results": {}}}) == {
        "result": {}, "parameters": {"touch_reach_m": None, "safety_standards": None}}
