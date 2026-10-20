from src.infrastructure.calculations import artifact_potential
from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient, PotentialPoint
from src.infrastructure.calculations.solver_evaluation import evaluate


def test_evaluation_is_deterministic_and_points_are_order_independent(monkeypatch):
    monkeypatch.setattr(artifact_potential, "_segments", lambda *args: ["segment"])

    def fake_field(*args):
        first = {
            "groups": {"grid": {"resistance_to_remote_earth_ohm": 2.5}},
            "diagnostics": {"backward_error": 0.0}, "warnings": [],
            "trace": {"protocol": "SPAT-POTENTIAL-3"},
        }
        return {
            "first": first, "gpr_v": 250.0,
            "max_step_v": {"value": 30.0, "from_m": [1.0, 0.0], "to_m": [2.0, 0.0]},
            "max_touch_v": {"value": 40.0, "x_m": 0.5, "y_m": 0.5},
        }

    monkeypatch.setattr(artifact_potential, "_field", fake_field)
    monkeypatch.setattr(artifact_potential, "_solve", lambda client, soil, segments, current, points, origin:
                        (None, {point.id: float(index) for index, point in enumerate(points)}, []))
    client = PotentialEngineClient()
    points = [PotentialPoint("b", (1.0, 0.0, 0.0)), PotentialPoint("a", (0.0, 1.0, 0.0))]
    args = {"geometry": {"length_m": 4.0}, "soil": 100.0, "injection_a": 100.0, "client": client}

    first = evaluate(**args, points=points)
    reordered = evaluate(**args, points=list(reversed(points)))
    changed = evaluate(**{**args, "injection_a": 101.0}, points=points)

    assert first["input_sha256"] == reordered["input_sha256"]
    assert first["input_sha256"] != changed["input_sha256"]
    assert first["quantities"] == {"Rg_ohm": 2.5, "GPR_v": 250.0, "Vs_v": 30.0, "Vt_v": 40.0}
    assert first["locations"]["Vs"]["from_m"] == [1.0, 0.0]
    assert first["point_potentials_v"] == {"b": 0.0, "a": 1.0}
    assert first["status"] == "approximate"


def test_evaluation_rejects_duplicate_point_ids():
    point = PotentialPoint("same", (0.0, 0.0, 0.0))
    try:
        evaluate(geometry={}, soil=100.0, injection_a=1.0, points=[point, point], client=PotentialEngineClient())
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate point IDs must be rejected")
