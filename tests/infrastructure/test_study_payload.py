from src.infrastructure.entrypoint.api.study_routes import RESULT_DETAIL_KEYS, _calculation_detail
from tests.infrastructure.test_identity import env, headers  # noqa: F401


def test_public_study_detail_carries_what_the_workspace_results_panel_draws():
    calculation = {
        "parameters": {"touch_reach_m": 1.5, "safety_standards": ["IEEE 80-2013"], "justification": "internal note"},
        "result": {"grid_resistance_ohm": 3.1, "gpr_v": 26000.0, "injected_current_a": 8500.0, "safety": [{"standard": "IEEE 80-2013"}],
                   "conductor_thermal": {"status": "cumple"}, "surface_potential": {"nx": 2, "ny": 2, "values_v": [1, 2, 3, 4]},
                   "model_warnings": ["w"], "max_touch_v": {"value": 1.0, "x_m": 0, "y_m": 0}, "max_step_v": {"value": 2.0}, "trace": {"private": "not published"}, "segment_count": 546},
    }
    detail = _calculation_detail(calculation)
    assert set(detail["result"]) == set(RESULT_DETAIL_KEYS)
    assert "trace" not in detail["result"] and "segment_count" not in detail["result"]
    assert detail["parameters"] == {"touch_reach_m": 1.5, "safety_standards": ["IEEE 80-2013"]}


def test_public_study_detail_tolerates_a_result_without_the_workspace_fields():
    assert _calculation_detail({"parameters": None, "result": {"scenario_results": {}}}) == {
        "result": {}, "parameters": {"touch_reach_m": None, "safety_standards": None}}


def test_a_summary_that_denies_existing_results_is_detected():
    from src.infrastructure.entrypoint.api.study_routes import _denies_results

    assert _denies_results("Aún no se cuenta con resultados de tensiones de contacto.")
    assert not _denies_results("El diseño no cumple el criterio de contacto.")


def test_publishing_a_non_compliant_design_needs_explicit_confirmation(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from src.infrastructure.entrypoint.api import study_routes

    monkeypatch.setattr(study_routes, "_verdict", lambda db, study: "no_cumple")

    class Db:
        def one(self, table, **kw): return {"id": "s", "artifact_id": "a", "artifact_version": 1, "published_at": None} if table == "studies" else {"id": "art"}
        def change(self, *a, **k): self.changed = True

    class Store:
        def transaction(self, write=False):
            from contextlib import contextmanager
            @contextmanager
            def cm(): yield Db()
            return cm()

    class Req:
        class app:
            class state:
                class services:
                    store = Store()

    monkeypatch.setattr(study_routes, "_owned_project", lambda *a, **k: None)
    with pytest.raises(HTTPException) as err:
        study_routes.publish_study("p", "s", study_routes.PublishRequest(status="published"), Req, actor=None)
    assert err.value.status_code == 409 and err.value.detail["code"] == "non_compliant"


def test_agent_assumptions_that_change_the_result_mark_the_study_as_draft():
    from src.infrastructure.entrypoint.api.study_routes import _client_assumptions

    provenance = {
        "name": {"kind": "assumption", "note": "Nombre generado"},
        "conductor.material_id": {"kind": "assumption", "note": "Material típico"},
        "geometry.burial_depth_m": {"kind": "assumption", "note": "Profundidad típica"},
        "geometry.length_m": {"kind": "user", "ref": "m1"},
        "geometry.snap_m": {"kind": "assumption"},
        "schema_version": {"kind": "schema_default"},
    }
    assert _client_assumptions(provenance) == ["conductor.material_id", "geometry.burial_depth_m"]
    assert _client_assumptions({}) == [] and _client_assumptions(None) == []


def test_generated_text_does_not_quote_verdict_codes():
    from src.infrastructure.entrypoint.api.study_routes import _plain_codes

    assert _plain_codes('El sistema no cumple con IEEE 80 ("no_cumple", margen -149 %).') == (
        "El sistema no cumple con IEEE 80 (no cumple, margen -149 %).")
    assert _plain_codes("Veredicto: «no_evaluado».") == "Veredicto: no evaluado."
    assert _plain_codes("El diseño cumple.") == "El diseño cumple."


def test_an_unavailable_public_study_says_why(env):  # noqa: F811
    from time import time
    _, services, client, _, tokens, _ = env
    h = headers(tokens)
    project = client.post("/api/v1/projects", json={"name": "Estudio vencido"}, headers=h).json()
    artifact = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras",
                           json={"name": "Malla", "geometry": {"length_m": 10, "width_m": 10, "burial_depth_m": 0.5,
                                                              "conductor_spacing_m": 5, "rods_count": 0, "rod_length_m": 2.4}}, headers=h).json()
    base = f"/api/v1/projects/{project['id']}/studies"
    study = client.post(base, json={"artifact_id": artifact["artifact_id"], "artifact_version": 1, "title": "Vence", "access": "link"}, headers=h).json()
    import uuid
    assert str(uuid.UUID(study["slug"])) == study["slug"]      # the public link is an opaque UUID, not the title
    assert client.get(f"/api/v1/public/studies/{study['slug']}").json()["detail"]["code"] == "not_found"   # a draft is not disclosed
    client.post(f"{base}/{study['id']}/publish", json={"status": "published", "confirm_non_compliant": True}, headers=h)
    client.patch(f"{base}/{study['id']}/access", json={"access": "link", "expires_at": int(time()) - 60}, headers=h)
    expired = client.get(f"/api/v1/public/studies/{study['slug']}")
    assert expired.status_code == 410 and expired.json()["detail"]["code"] == "expired"
    client.post(f"{base}/{study['id']}/publish", json={"status": "revoked"}, headers=h)
    revoked = client.get(f"/api/v1/public/studies/{study['slug']}")
    assert revoked.status_code == 410 and revoked.json()["detail"]["code"] == "revoked" and revoked.json()["detail"]["revoked_at"]
