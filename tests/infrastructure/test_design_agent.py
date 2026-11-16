import copy
import pytest
import json
from types import SimpleNamespace

from src.application.use_cases.agent_runs import AgentRuns, run_step
from src.domain.agent.run import AgentMode
from src.infrastructure.agents.design_agent import (
    ArtifactWorkspace, GroundingDesignAgent, calculation_score, reconcile_final_response,
)
import src.infrastructure.agents.design_agent as design_agent_module
from tests.infrastructure.test_agent_routes import ARTIFACT, chat, events, messages, send  # noqa: F401
from tests.infrastructure.test_identity import env, headers  # noqa: F401

PROMPTS = {"orchestrator": [{"role": "system", "content": "orquestador"}],
           "grid_designer": [{"role": "system", "content": "diseñador"}]}


class ScriptedClient:
    """Fake OpenAI client: each response is one tool call (name, arguments); a callable entry
    runs before the next response (to simulate concurrent edits)."""

    def __init__(self, calls):
        self.calls, self.requests = list(calls), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        while callable(self.calls[0]):
            self.calls.pop(0)()
        name, arguments = self.calls.pop(0)
        call = SimpleNamespace(id=f"call{len(self.requests)}",
                               function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
        message = SimpleNamespace(tool_calls=[call], content=None, model_dump=lambda **_: {
            "role": "assistant", "tool_calls": [{"id": call.id, "type": "function",
                                                 "function": {"name": name, "arguments": call.function.arguments}}]})
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def step(services, run_id, calls):
    client = ScriptedClient(calls)
    run_step(services.store, run_id, GroundingDesignAgent(services.store, client=client, prompts=PROMPTS))
    assert client.calls == [], "the script was not fully consumed"
    return client


def tool_result(llm, index):
    return json.loads(llm.requests[index]["messages"][-1]["content"])


def run_of(client, tokens, run_id):
    return client.get(f"/api/v1/agent-runs/{run_id}", headers=headers(tokens)).json()


def artifacts(client, tokens, project):
    return client.get(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", headers=headers(tokens)).json()


def updates(client, tokens, conversation):
    return [m for m in messages(client, tokens, conversation) if (m.get("payload") or {}).get("kind") == "artifact.updated"]


def designer(message_id, *changes, rationale="Pedido del usuario"):
    return ("submit_grid_design", {"rationale": rationale, "changes": [
        {"path": path, "value": value, "source_kind": kind, "message_id": message_id if kind == "user" else None,
         "note": None if kind == "user" else "Valor típico"} for path, value, kind in changes]})


def test_grid_first_without_critical_inputs(chat):
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Malla de 40 x 30 m, conductores cada 4 m en X y 6 m en Y")
    llm = step(services, sent["run_id"], [
        ("get_draft", {}),
        ("delegate_grid_designer", {"task": f"40 x 30 m, 4 m en X y 6 m en Y (mensaje {sent['id']})"}),
        designer(sent["id"], ("geometry.length_m", 40, "user"), ("geometry.width_m", 30, "user"),
                 ("geometry.conductor_spacing_x_m", 4, "user"), ("geometry.conductor_spacing_y_m", 6, "user"),
                 ("geometry.rods", {"pattern": "corners"}, "assumption")),
        ("apply_changes", {"summary": "Malla de 40 x 30 m con retícula 4 × 6 m"}),
        ("respond_to_user", {"text": "Creé la malla. Para el cálculo faltan suelo y datos de falla.",
                             "waits_for": "nothing"}),
    ])
    applied = tool_result(llm, 4)
    assert applied["version"] == 1 and "fault.current_a" in applied["missing_for_calculation"]
    assert run_of(client, tokens, sent["run_id"])["status"] == "completed"

    artifact = artifacts(client, tokens, project)[0]
    geometry = artifact["snapshot"]["geometry"]
    assert (geometry["conductor_spacing_x_m"], geometry["conductor_spacing_y_m"]) == (4, 6)
    assert geometry["rods_count"] == 4 and geometry["rods"][2] == {"x": 40.0, "y": 30.0, "length_m": None}
    assert artifact["snapshot"]["soil_layers"] == [] and artifact["snapshot"]["fault"]["current_a"] is None
    assert artifact["origin"]["provenance"]["geometry.rods"]["kind"] == "assumption"

    # The structured flag the client uses to reload and show the "artifact edited" card.
    [update] = updates(client, tokens, conversation)
    payload = update["payload"]
    assert update["source"] == "notification" and update["text"].startswith("Se creó el diseño")
    assert payload["artifact_id"] == artifact["artifact_id"] and payload["version"] == 1
    assert payload["previous_version"] is None and payload["missing_for_calculation"] == [
        "soil_layers", "fault.current_a", "fault.clearing_time_s"]
    assert {"geometry.conductor_spacing_x_m", "geometry.rods"} <= {c["path"] for c in payload["changes"]}
    assert "artifact.version_created" in [e["type"] for e in events(client, tokens, conversation)["events"]]
    # Messages of the same second keep their creation order: request, card, answer.
    assert [m["source"] for m in messages(client, tokens, conversation)] == ["user", "notification", "agent"]

    # The calculation refuses an incomplete artifact.
    blocked = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/{artifact['artifact_id']}"
                          f"/versions/1/calculos-potencial", json={}, headers=headers(tokens))
    assert blocked.status_code == 409 and "soil_layers" in blocked.json()["detail"]["missing"]


def test_drawn_conductors_edit_and_undo(chat):
    services, client, tokens, project, conversation, _, _ = chat
    created = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=ARTIFACT,
                          headers=headers(tokens)).json()
    sent = send(client, tokens, conversation, "Quita la retícula interior y deja solo el perímetro y una cruz")
    cross = [{"start": {"x": 0, "y": 0}, "end": {"x": 40, "y": 0}}, {"start": {"x": 40, "y": 0}, "end": {"x": 40, "y": 30}},
             {"start": {"x": 40, "y": 30}, "end": {"x": 0, "y": 30}}, {"start": {"x": 0, "y": 30}, "end": {"x": 0, "y": 0}},
             {"start": {"x": 20, "y": 0}, "end": {"x": 20, "y": 30}}, {"start": {"x": 0, "y": 15}, "end": {"x": 40, "y": 15}}]
    llm = step(services, sent["run_id"], [
        ("delegate_grid_designer", {"task": f"Perímetro y cruz central (mensaje {sent['id']})"}),
        designer(sent["id"], ("geometry.conductors", cross, "user"), ("geometry.rods", [{"x": 10, "y": 10}], "assumption")),
        designer(sent["id"], ("geometry.conductors", cross, "user"), ("geometry.rods", [{"x": 20, "y": 15}], "assumption")),
        ("apply_changes", {"summary": "Perímetro con cruz central"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ])
    rejected = tool_result(llm, 2)  # first designer submission: the rod is in the middle of a mesh
    assert any("does not touch any conductor" in error for error in rejected["errors"])
    applied = tool_result(llm, 4)
    assert applied["version"] == 2
    latest = artifacts(client, tokens, project)[0]
    assert len(latest["snapshot"]["geometry"]["conductors"]) == 6 and latest["snapshot"]["geometry"]["rods_count"] == 1
    [update] = updates(client, tokens, conversation)
    assert update["payload"]["previous_version"] == 1 and update["text"].startswith("Se editó el diseño")

    undo = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/{created['artifact_id']}"
                       f"/versions/1/restaurar", headers=headers(tokens))
    assert undo.status_code == 201 and undo.json()["version"] == 3
    assert undo.json()["snapshot"] == created["snapshot"] and undo.json()["origin"]["restored_from"] == 1


def test_unapplied_draft_is_pointed_out_once(chat):
    services, client, tokens, _, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Malla 20 x 20 m")
    llm = step(services, sent["run_id"], [
        ("set_fields", {"reason": "Pedido", "changes": [
            {"path": "geometry.length_m", "value": 20, "source": {"kind": "user", "ref": sent["id"], "note": None}}]}),
        ("respond_to_user", {"text": "¿Qué retícula quieres?", "waits_for": "answer"}),
        ("respond_to_user", {"text": "¿Qué retícula quieres?", "waits_for": "answer"}),
    ])
    assert "not applied" in tool_result(llm, 2)["error"]
    assert run_of(client, tokens, sent["run_id"])["status"] == "waiting_user"
    assert updates(client, tokens, conversation) == []


def test_workspace_guards_sources_and_critical_inputs(chat):
    services, client, tokens, _, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Diseña")
    runs = AgentRuns(services.store)
    run = runs.begin_step(sent["run_id"])
    workspace = ArtifactWorkspace(services.store, runs, run)
    result = workspace.set_fields({"changes": [
        {"path": "fault.current_a", "value": 5000, "source": {"kind": "assumption"}},
        {"path": "fault.clearing_time_s", "value": 0.5, "source": {"kind": "user", "ref": "no-existe"}},
        {"path": "compliance", "value": [], "source": {"kind": "user", "ref": sent["id"]}},
        {"path": "geometry.length_m", "value": 40, "source": {}},
        {"path": "geometry.width_m", "value": 30, "source": {"kind": "user", "ref": sent["id"]}},
    ]})
    assert result["applied"] == ["geometry.width_m"] and len(result["errors"]) == 4
    assert "critical input" in result["errors"][0]
    scoped = workspace.set_fields({"changes": [
        {"path": "fault.current_a", "value": 1, "source": {"kind": "user", "ref": sent["id"]}}]},
        allowed=("geometry.",))
    assert scoped["applied"] == [] and "outside" in scoped["errors"][0]
    assert workspace.apply({"summary": "x"})["error"] == "Nothing valid to save"
    with services.store.transaction() as db:
        saved = db.one("agent_runs", id=sent["run_id"])["draft_snapshot"]
    assert ArtifactWorkspace(services.store, runs, {**run, "draft_snapshot": saved}).draft["geometry"]["width_m"] == 30


def test_concurrent_version_rebases_the_draft(chat):
    services, client, tokens, project, conversation, _, _ = chat
    created = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=ARTIFACT,
                          headers=headers(tokens)).json()
    sent = send(client, tokens, conversation, "Retícula de 4 m")
    edited = {**ARTIFACT, "name": "Editado a mano"}

    def manual_edit():
        response = client.put(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/{created['artifact_id']}",
                              json=edited, headers=headers(tokens))
        assert response.status_code == 201

    llm = step(services, sent["run_id"], [
        ("set_fields", {"reason": "Pedido", "changes": [
            {"path": "geometry.conductor_spacing_m", "value": 4, "source": {"kind": "user", "ref": sent["id"], "note": None}}]}),
        manual_edit,
        ("apply_changes", {"summary": "Retícula de 4 m"}),
        ("apply_changes", {"summary": "Retícula de 4 m"}),
        ("respond_to_user", {"text": "Apliqué la retícula de 4 m sobre la versión editada.", "waits_for": "nothing"}),
    ])
    assert "rebased on version 2" in tool_result(llm, 2)["error"]
    assert tool_result(llm, 3)["version"] == 3
    latest = artifacts(client, tokens, project)[0]
    assert latest["name"] == "Editado a mano" and latest["snapshot"]["geometry"]["conductor_spacing_m"] == 4


def test_consulta_mode_has_no_write_tools(chat):
    services, client, tokens, _, conversation, _, _ = chat
    client.put(f"/api/v1/conversations/{conversation['id']}/agent-state", json={"mode": "consulta"},
               headers=headers(tokens))
    sent = send(client, tokens, conversation, "¿Qué falta?")
    llm = step(services, sent["run_id"], [("respond_to_user", {"text": "Falta todo.", "waits_for": "nothing"})])
    assert {tool["function"]["name"] for tool in llm.requests[0]["tools"]} == {
        "get_draft", "validate_draft", "lookup_soil_material", "respond_to_user"}


def test_designer_clips_a_zone_deterministically(chat):
    services, client, tokens, project, conversation, _, _ = chat
    client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras",
                json={**ARTIFACT, "geometry": {"length_m": 40, "width_m": 30, "conductor_spacing_x_m": 4,
                                               "conductor_spacing_y_m": 6}}, headers=headers(tokens))
    sent = send(client, tokens, conversation, "Quita los conductores interiores del lado derecho desde x = 20")
    llm = step(services, sent["run_id"], [
        ("delegate_grid_designer", {"task": f"Retirar conductores interiores en x 20–40 (mensaje {sent['id']})"}),
        ("clip_zone", {"x_min": 20, "x_max": 40, "y_min": 0, "y_max": 30}),
        ("submit_grid_design", {"rationale": "Zona derecha despejada", "changes": []}),
        ("apply_changes", {"summary": "Lado derecho solo con perímetro"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ])
    clipped = tool_result(llm, 2)
    assert clipped["rod_problems"] == [] and clipped["conductors"] == 13  # 7 verticals + 6 horizontals
    latest = artifacts(client, tokens, project)[0]
    assert latest["version"] == 2 and len(latest["snapshot"]["geometry"]["conductors"]) == 13
    assert latest["origin"]["provenance"]["geometry.conductors"]["kind"] == "tool"


def test_site_zones_from_chat_put_the_grid_in_the_chosen_zone(chat):
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Antejardín de 2 × 10, edificio de 20 × 10 y patio de 5 × 10; "
                                              "la malla va en el patio, cada 5 m")
    building = [{"x": 12, "y": 5, "width": 20, "height": 10, "label": "Edificio existente"}]
    areas = [{"type": "intervenible", "label": "Antejardín", "x_min": 0, "x_max": 2, "y_min": 0, "y_max": 10},
             {"type": "intervenible", "label": "Patio", "x_min": 22, "x_max": 27, "y_min": 0, "y_max": 10}]
    grid = {"pattern": "areas", "areas": ["Patio"], "spacing_x_m": 5, "spacing_y_m": 5}
    llm = step(services, sent["run_id"], [
        ("delegate_grid_designer", {"task": f"Terreno 27 × 10, malla en el patio (mensaje {sent['id']})"}),
        designer(sent["id"], ("geometry.length_m", 27, "user"), ("geometry.width_m", 10, "user"),
                 ("geometry.structures", building, "user"), ("geometry.areas", areas, "user"),
                 ("geometry.conductors", grid, "user"), ("geometry.rods", {"pattern": "corners"}, "assumption")),
        ("apply_changes", {"summary": "Malla en el patio"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ])
    design = tool_result(llm, 2)
    assert design["errors"] == [] and design["resulting_geometry"]["warnings"] == []
    artifact = artifacts(client, tokens, project)[0]
    geometry = artifact["snapshot"]["geometry"]
    xs = {c[k]["x"] for c in geometry["conductors"] for k in ("start", "end")}
    assert xs == {22, 27} and len(geometry["conductors"]) == 5
    assert {(r["x"], r["y"]) for r in geometry["rods"]} == {(22, 0), (22, 10), (27, 0), (27, 10)}
    assert geometry["structures"][0]["label"] == "Edificio existente" and [(a["type"], a["label"]) for a in geometry["areas"]] == [(a["type"], a["label"]) for a in areas]
    # Areas are stored as polygons: each rectangle becomes its four corners.
    assert geometry["areas"][1]["polygon"] == [{"x": 22.0, "y": 0.0}, {"x": 27.0, "y": 0.0},
                                               {"x": 27.0, "y": 10.0}, {"x": 22.0, "y": 10.0}]
    assert artifact["origin"]["provenance"]["geometry.conductors"]["kind"] == "user"


def test_area_grid_needs_the_zone_when_there_are_several(chat):
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Antejardín 2 × 10, edificio 20 × 10 y patio 5 × 10, malla cada 5 m")
    areas = [{"type": "intervenible", "label": "Antejardín", "x_min": 0, "x_max": 2, "y_min": 0, "y_max": 10},
             {"type": "intervenible", "label": "Patio", "x_min": 22, "x_max": 27, "y_min": 0, "y_max": 10}]
    llm = step(services, sent["run_id"], [
        ("delegate_grid_designer", {"task": f"Terreno 27 × 10 (mensaje {sent['id']})"}),
        designer(sent["id"], ("geometry.length_m", 27, "user"), ("geometry.width_m", 10, "user"),
                 ("geometry.areas", areas, "user"),
                 ("geometry.conductors", {"pattern": "areas", "spacing_x_m": 5, "spacing_y_m": 5}, "user")),
        designer(sent["id"], ("geometry.conductors", {"pattern": "areas", "areas": ["Patio"], "spacing_x_m": 5,
                                                      "spacing_y_m": 5}, "assumption")),
        ("apply_changes", {"summary": "Malla en el patio"}),
        ("respond_to_user", {"text": "Usé el patio, el área más grande.", "waits_for": "nothing"}),
    ])
    first = tool_result(llm, 2)
    assert any("say which one the grid uses" in error for error in first["errors"])
    assert tool_result(llm, 3)["errors"] == []


SPACINGS = [0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24]


def synthetic_sounding():
    from src.infrastructure.calculations.soil_model import TwoLayerSoil, apparent_resistivity

    soil = TwoLayerSoil(300.0, 100.0, 2.0)
    return [(a, round(apparent_resistivity(soil, "wenner", a), 1)) for a in SPACINGS]


def soil_step(services, run_id, calls, storage=None):
    client = ScriptedClient(calls)
    run_step(services.store, run_id, GroundingDesignAgent(services.store, client=client, prompts={
        **PROMPTS, "soil_modeler": [{"role": "system", "content": "suelo"}]}, storage=storage))
    assert client.calls == [], "the script was not fully consumed"
    return client


def test_soil_modeler_from_chat_readings(chat):
    services, client, tokens, project, conversation, _, _ = chat
    client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=ARTIFACT, headers=headers(tokens))
    readings = synthetic_sounding()
    text = "Sondeo Wenner: " + "; ".join(f"a={a} m → {str(rho).replace('.', ',')} Ω·m" for a, rho in readings)
    sent = send(client, tokens, conversation, text)
    staged = [{"spacing_m": a, "value": rho, "potential_spacing_m": None} for a, rho in readings]
    llm = soil_step(services, sent["run_id"], [
        ("delegate_soil_modeler", {"task": f"Sondeo Wenner en el mensaje {sent['id']}"}),
        ("stage_from_message", {"message_id": sent["id"], "array": "wenner", "quantity": "resistivity",
                                "readings": staged[:-1] + [{**staged[-1], "value": 999.9}]}),
        ("stage_from_message", {"message_id": sent["id"], "array": "wenner", "quantity": "resistivity",
                                "readings": staged}),
        ("fit_soil", {"layer_counts": [2, 3], "outlier_threshold": None}),
        ("lookup_soil_material", {"query": None, "resistivity_ohm_m": 300}),
        ("submit_soil_model", {"layer_count": 2, "rationale": "Dos capas bastan.", "layer_notes": ["arena", "limo"]}),
        ("apply_changes", {"summary": "Modelo de suelo de dos capas"}),
        ("respond_to_user", {"text": "Ajusté dos capas.", "waits_for": "nothing"}),
    ])
    assert tool_result(llm, 2)["not_found"] == [999.9]  # invented value rejected
    fits = tool_result(llm, 4)["fits"]
    assert fits["2"]["rms_error_percent"] < 0.5
    two = fits["2"]["soil_layers"]
    assert two[0]["resistivity_ohm_m"] == pytest.approx(300, rel=0.02) and two[0]["depth_m"] == pytest.approx(2, rel=0.05)
    assert tool_result(llm, 5)["materials"]
    latest = artifacts(client, tokens, project)[0]
    snapshot, provenance = latest["snapshot"], latest["origin"]["provenance"]
    assert snapshot["soil_measurements"]["array"] == "wenner" and len(snapshot["soil_measurements"]["measurements"]) == 10
    assert provenance["soil_measurements"] == {"kind": "user", "ref": sent["id"]}
    assert provenance["soil_layers"]["kind"] == "tool" and provenance["soil_layers"]["ref"] == "fit_sounding:2"
    [update] = updates(client, tokens, conversation)
    assert {"soil_layers", "soil_measurements"} <= {c["path"] for c in update["payload"]["changes"]}
    assert "soil_layers" not in update["payload"]["unconfirmed_critical"]
    assert "Modelador de suelo trabajando" in [e["title"] for e in events(client, tokens, conversation)["events"]]


class FakeStorage:
    def __init__(self, files):
        self.files = files

    def read_object(self, bucket, key, max_bytes):
        return self.files[(bucket, key)]


def test_soil_modeler_from_project_csv(chat):
    services, client, tokens, project, conversation, _, _ = chat
    csv_text = "Ensayo;;\na (m);R (ohm)\n" + "\n".join(
        f"{a};{str(round(rho / (2 * 3.141592653589793 * a), 4)).replace('.', ',')}" for a, rho in synthetic_sounding())
    with services.store.transaction(write=True) as db:
        owner = db.one("projects", id=project["id"])["owner_id"]
        db.add("file_uploads", id="00000000-0000-0000-0000-00000000c5v1", owner_id=owner, project_id=project["id"],
               filename="wenner.csv", quarantine_key="q/wenner.csv", target_bucket="documents",
               object_key="p/wenner.csv", expected_mime="text/csv", status="available", created_at=0, updated_at=0)
    storage = FakeStorage({("documents", "p/wenner.csv"): csv_text.encode()})
    sent = send(client, tokens, conversation, "Usa el archivo wenner.csv para el suelo")
    upload_id = "00000000-0000-0000-0000-00000000c5v1"
    llm = soil_step(services, sent["run_id"], [
        ("delegate_soil_modeler", {"task": "Sondeo en wenner.csv"}),
        ("preview_table", {"upload_id": upload_id}),
        ("stage_from_table", {"upload_id": upload_id, "sheet": None, "spacing_column": "A", "value_column": "B",
                              "potential_column": None, "first_row": 3, "last_row": 12, "decimal": "auto",
                              "array": "wenner", "quantity": "resistance"}),
        ("fit_soil", {"layer_counts": [2], "outlier_threshold": None}),
        ("submit_soil_model", {"layer_count": 2, "rationale": "Ajuste de dos capas.", "layer_notes": []}),
        ("apply_changes", {"summary": "Suelo desde wenner.csv"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ], storage=storage)
    assert tool_result(llm, 2)["sheets"][0]["rows"][1]["cells"] == ["a (m)", "R (ohm)"]
    staged = tool_result(llm, 3)
    assert staged["staged"] == 10 and staged["readings"][0]["apparent_resistivity_ohm_m"] == pytest.approx(
        synthetic_sounding()[0][1], rel=1e-3)  # R converted with 2·pi·a·R
    latest = artifacts(client, tokens, project)[0]
    assert latest["snapshot"]["soil_layers"][0]["resistivity_ohm_m"] == pytest.approx(300, rel=0.03)
    assert latest["origin"]["provenance"]["soil_measurements"]["kind"] == "document"


def test_soil_material_catalog_endpoint(chat):
    _, client, tokens, _, _, _, _ = chat
    table = client.get("/api/v1/materiales-suelo", headers=headers(tokens)).json()
    assert any(m["id"] == "humus" for m in table)
    found = client.get("/api/v1/materiales-suelo", params={"resistividad_ohm_m": 5000}, headers=headers(tokens)).json()
    assert found and all(m["min_ohm_m"] <= 5000 <= m["max_ohm_m"] for m in found)
    assert client.get("/api/v1/materiales-suelo").status_code == 401


def test_stratigraphy_without_resistivity_and_partial_apply(chat):
    """A soil section that cannot be saved never blocks the grid (the case reported from the UI)."""
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Grava 20 cm, arena 15 cm y arcilla 2 m; malla de 40 x 10 m")
    runs = AgentRuns(services.store)
    run = runs.begin_step(sent["run_id"])
    workspace = ArtifactWorkspace(services.store, runs, run)
    user = {"kind": "user", "ref": sent["id"]}
    described = workspace.set_fields({"changes": [{"path": "soil_layers", "source": user, "value": [
        {"material": "Grava", "depth_m": 0.2, "resistivity_ohm_m": None},
        {"material": "Arena", "depth_m": 0.15, "resistivity_ohm_m": None},
        {"material": "Arcilla", "depth_m": None, "resistivity_ohm_m": None}]}]})
    assert described["applied"] == ["soil_layers"]
    rejected = workspace.set_fields({"changes": [{"path": "soil_layers", "source": user,
                                                  "value": [{"depth_m": 0.2, "resistivity_ohm_m": None}]}]})
    assert rejected["applied"] == [] and "not applied" in rejected["errors"][0]

    # A draft left invalid by an earlier version of the agent: the grid is saved anyway.
    workspace.draft = {**workspace.draft, "soil_layers": [{"resistivity_ohm_m": None, "depth_m": 0.2}],
                       "geometry": {"length_m": 40, "width_m": 10, "conductor_spacing_x_m": 5,
                                    "conductor_spacing_y_m": 2}}
    workspace.set_fields({"changes": [{"path": "geometry.rods", "source": {"kind": "assumption"},
                                       "value": {"pattern": "count", "count": 45}}]})
    applied = workspace.apply({"summary": "Malla de 40 x 10 m con 45 varillas"})
    assert applied["version"] == 1 and "soil_layers" in applied["skipped"]
    latest = artifacts(client, tokens, project)[0]
    assert latest["snapshot"]["geometry"]["rods_count"] == 45 and latest["snapshot"]["soil_layers"] == []


def test_rod_count_waits_for_the_grid_and_is_reported(chat):
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Malla de 40 x 10 m con 45 varillas")
    llm = step(services, sent["run_id"], [
        ("delegate_grid_designer", {"task": f"40 x 10 m, 45 varillas (mensaje {sent['id']})"}),
        designer(sent["id"], ("geometry.length_m", 40, "user"), ("geometry.width_m", 10, "user"),
                 ("geometry.rods", {"pattern": "count", "count": 45}, "user")),
        designer(sent["id"], ("geometry.conductor_spacing_x_m", 4, "assumption"),
                 ("geometry.conductor_spacing_y_m", 5, "assumption")),
        designer(sent["id"], ("geometry.conductor_spacing_y_m", 2, "assumption")),
        ("apply_changes", {"summary": "Malla de 40 x 10 m con 45 varillas"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ])
    assert "set the outline and the conductor spacing" in tool_result(llm, 2)["errors"][0]
    assert "only 33 conductor junctions" in tool_result(llm, 3)["errors"][0]
    delegated = tool_result(llm, 4)  # the pending layout was placed once the grid allowed it
    assert delegated["resulting_geometry"]["rods"] == 45 and "rods_not_placed" not in delegated["resulting_geometry"]
    assert artifacts(client, tokens, project)[0]["snapshot"]["geometry"]["rods_count"] == 45


RESULT = {"grid_resistance_ohm": 1.234, "gpr_v": 6170.0, "injected_current_a": 5000.0,
          "max_touch_v": {"value": 980.4}, "max_step_v": {"value": 410.2}, "segment_count": 420,
          "safety": [{"standard": "IEEE 80-2013", "status": "no_cumple", "gpr_below_tolerable_touch": False,
                      "criteria": [{"criterion": "touch", "actual_v": 980.4, "tolerable_v": 830.0, "margin_rel": -0.1812,
                                    "status": "no_cumple"},
                                   {"criterion": "step", "actual_v": 410.2, "tolerable_v": 2700.0, "margin_rel": 0.848,
                                    "status": "cumple"}]}],
          "conductor_thermal": {"status": "cumple", "minimum_section_mm2": 31.2, "selected_section_mm2": 86.6,
                                "material_name": "Cobre"},
          "model_warnings": ["Sin factor de división S_f."], "engine_warnings": []}


def test_calculation_score_tracks_worst_scenario_margin_and_candidate_provenance():
    finished = {"calculation_id": "calc-2", "artifact_version": 3, "verdict": "no_cumple",
                "scenarios": {"public": {"standards": [
                    {"standard": "RETIE", "status": "no_cumple",
                     "touch": {"margin_percent": -4.5}, "step": {"margin_percent": 10.0}}]},
                    "occupational": {"standards": [
                        {"standard": "IEEE 80", "status": "no_cumple",
                         "touch": {"margin_percent": -12.0}}]}}}
    assert calculation_score(finished) == -12.0

    class RunStore:
        saved = None

        def set_usage_fields(self, run_id, **fields):
            self.saved = (run_id, fields)

    runs = RunStore()
    candidate = GroundingDesignAgent._record_design_candidate(
        None, {"id": "run-1", "usage": {}}, runs, finished)
    assert candidate["artifact_version"] == 3 and candidate["calculation_id"] == "calc-2"
    assert candidate["margin_percent"] == -12.0
    assert candidate["dominant_criterion"] == {"criterion": "touch", "standard": "IEEE 80",
                                                 "scenario": "occupational"}
    assert runs.saved == ("run-1", {"best_candidate": candidate})


@pytest.mark.parametrize("claim", [
    "No se realizaron cambios.", "No hicimos cambios.", "No hubo cambios.", "No changes were made.",
    "Actualicé el ancho a 99 m y quedó listo.",
])
def test_final_response_uses_only_the_persisted_change(claim):
    applied = {"version": 4, "summary": "Ajuste de ancho",
               "changes": [{"path": "geometry.width_m", "before": 30, "after": 31}]}
    response = reconcile_final_response(claim, applied)
    assert response == 'Se guardó la versión 4 del diseño: Ajuste de ancho. Campos guardados: geometry.width_m=31.'


def test_final_response_includes_rejected_changes_alongside_saved_changes():
    applied = {"version": 6, "summary": "Ajuste de ancho",
               "changes": [{"path": "geometry.width_m", "before": 30, "after": 38}],
               "rejected": ["geometry.burial_depth_m: not applied, debe ser positivo"]}
    assert reconcile_final_response("Listo.", applied) == (
        "Se guardó la versión 6 del diseño: Ajuste de ancho. Campos guardados: geometry.width_m=38. "
        "Cambios no aplicados: geometry.burial_depth_m: debe ser positivo.")


def test_final_response_reports_changes_rejected_after_the_saved_version():
    applied = {"version": 6, "summary": "Ancho", "rejected": [],
               "changes": [{"path": "geometry.width_m", "before": 30, "after": 38}]}
    response = reconcile_final_response("Guardé la profundidad de -2 m.", applied,
                                        ["geometry: geometry.burial_depth_m: debe ser mayor que 0"])
    assert response.startswith("Se guardó la versión 6 del diseño: Ancho. Campos guardados: geometry.width_m=38.")
    assert response.endswith("Cambios no aplicados: geometry: geometry.burial_depth_m: debe ser mayor que 0.")


def test_final_response_drops_a_rejection_that_a_retry_saved():
    applied = {"version": 2, "summary": "Ancho", "changes": [{"path": "geometry.width_m", "before": 30, "after": 31}],
               "rejected": ["geometry.width_m: m1 is not a user message of this conversation"]}
    assert "no aplicados" not in reconcile_final_response("Listo.", applied)


def test_final_response_reports_rejections_when_nothing_was_saved():
    response = reconcile_final_response("Guardé la versión 7 del diseño.", None,
                                        ["geometry.burial_depth_m: not applied, debe ser positivo"])
    assert response == ("No se guardó una versión nueva del diseño en este paso. Cambios no aplicados: "
                        "geometry.burial_depth_m: debe ser positivo.")


def test_final_response_does_not_claim_a_version_when_nothing_was_persisted():
    assert reconcile_final_response("Guardé la versión 5 del diseño.", None) == (
        "No se guardó una versión nueva del diseño en este paso.")
    assert reconcile_final_response("Falta confirmar el tiempo de despeje.", None) == (
        "Falta confirmar el tiempo de despeje.")


def test_response_does_not_claim_a_saved_version_after_change_validation_fails(chat):
    services, client, tokens, project, conversation, _, _ = chat
    sent = send(client, tokens, conversation, "Establece un criterio inexistente y guarda el diseño")
    llm = step(services, sent["run_id"], [
        ("set_fields", {"reason": "Solicitud del usuario", "changes": [
            {"path": "compliance", "value": [],
             "source": {"kind": "user", "ref": sent["id"], "note": None}}]}),
        ("respond_to_user", {"text": "Guardé la versión 1 del diseño.", "waits_for": "nothing"}),
    ])
    assert run_of(client, tokens, sent["run_id"])["status"] == "completed"
    assert artifacts(client, tokens, project) == []
    assistant = [message for message in messages(client, tokens, conversation) if message["source"] == "agent"][-1]
    assert assistant["text"] == ("No se guardó una versión nueva del diseño en este paso. "
                                 "Cambios no aplicados: el agente no puede editar este campo: compliance.")


class LoopRunsStub:
    def __init__(self):
        self.usage = []
        self.events = []

    def set_usage_fields(self, run_id, **fields):
        self.usage.append((run_id, fields))

    def progress(self, run_id, event_type, title, **kwargs):
        self.events.append((run_id, event_type, title, kwargs))


def test_autonomous_loop_closes_at_one_iteration_limit(monkeypatch):
    monkeypatch.setenv("DESIGN_MAX_ITERATIONS", "1")
    runs = LoopRunsStub()
    run = {"id": "run-1", "mode": "autonomo", "usage": {"design_iterations": 1}}
    finished = {"calculation_id": "calc-current", "verdict": "no_cumple"}
    best = {"calculation_id": "calc-current", "artifact_version": 2, "verdict": "no_cumple", "score": -5.0}
    outcome = GroundingDesignAgent(None)._automatic_iteration(
        None, None, None, run, runs, finished, AgentMode.AUTONOMO, {}, best)
    assert "límite de iteraciones" in outcome.text
    assert runs.usage[-1][1]["design_loop_result"]["reason"] == "iteration_limit"
    assert runs.events[-1][3]["payload"]["design_loop_result"]["best_candidate"] == best


def test_autonomous_loop_stops_when_the_latest_margin_is_worse(monkeypatch):
    runs = LoopRunsStub()
    run = {"id": "run-1", "mode": "autonomo", "usage": {"design_iterations": 1}}
    finished = {"calculation_id": "calc-worse", "artifact_version": 3, "verdict": "no_cumple",
                "standards": [{"standard": "IEEE 80", "touch": {"margin_percent": -20.0}}]}
    best = {"calculation_id": "calc-best", "artifact_version": 2, "verdict": "no_cumple", "score": -5.0}
    monkeypatch.setattr(design_agent_module, "run_grid_designer", lambda *_args: pytest.fail("must stop before proposing"))
    outcome = GroundingDesignAgent(None)._automatic_iteration(
        None, None, None, run, runs, finished, AgentMode.AUTONOMO, {}, best)
    assert "no mejoró" in outcome.text
    assert runs.usage[-1][1]["design_loop_result"]["reason"] == "no_improvement"


def test_autonomous_loop_closes_when_designer_cannot_propose_a_valid_change(monkeypatch):
    monkeypatch.setenv("DESIGN_MAX_ITERATIONS", "3")
    runs = LoopRunsStub()
    run = {"id": "run-1", "mode": "autonomo", "usage": {"design_iterations": 0}}
    finished = {"calculation_id": "calc-current", "artifact_version": 2, "verdict": "no_cumple"}
    best = {"calculation_id": "calc-current", "artifact_version": 2, "verdict": "no_cumple", "score": -5.0}
    monkeypatch.setattr(design_agent_module, "run_grid_designer", lambda *_args: {"applied": False})
    workspace = SimpleNamespace(discarded=0, artifact_id=None)
    workspace.discard_draft = lambda: setattr(workspace, "discarded", workspace.discarded + 1)
    outcome = GroundingDesignAgent(None)._automatic_iteration(
        None, None, workspace, run, runs, finished, AgentMode.AUTONOMO, {}, best)
    assert "No se pudo guardar una mejora válida" in outcome.text
    assert runs.usage[-1][1]["design_loop_result"]["reason"] == "no_valid_candidate"
    assert workspace.discarded == 1


def test_autonomous_loop_discards_a_designer_change_that_never_validated(monkeypatch):
    """The designer set a field but the geometry kept failing validation: never try to save it."""
    monkeypatch.setenv("DESIGN_MAX_ITERATIONS", "3")
    runs = LoopRunsStub()
    run = {"id": "run-1", "mode": "autonomo", "usage": {"design_iterations": 0}}
    finished = {"calculation_id": "calc-current", "artifact_version": 2, "verdict": "no_cumple"}
    best = {"calculation_id": "calc-current", "artifact_version": 2, "verdict": "no_cumple", "score": -5.0}
    monkeypatch.setattr(design_agent_module, "run_grid_designer", lambda *_args: {
        "applied": ["geometry.burial_depth_m"], "errors": ["geometry.burial_depth_m: debe ser positivo"]})
    workspace = SimpleNamespace(discarded=0, artifact_id=None, apply=lambda *_: pytest.fail("an invalid change must not be saved"))
    workspace.discard_draft = lambda: setattr(workspace, "discarded", workspace.discarded + 1)
    outcome = GroundingDesignAgent(None)._automatic_iteration(
        None, None, workspace, run, runs, finished, AgentMode.AUTONOMO, {}, best)
    assert runs.usage[-1][1]["design_loop_result"]["reason"] == "no_valid_candidate"
    assert "No se pudo guardar una mejora válida" in outcome.text and workspace.discarded == 1
    failed = [event for event in runs.events if event[2] == "No se pudo proponer una mejora automática"]
    assert failed[0][3]["payload"]["errors"] == ["geometry.burial_depth_m: debe ser positivo"]


def calculation_setup(chat, artifact=ARTIFACT):
    services, client, tokens, project, conversation, _, _ = chat
    created = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras", json=artifact,
                          headers=headers(tokens)).json()
    client.put(f"/api/v1/conversations/{conversation['id']}/agent-state", json={"artifact_id": created["artifact_id"]},
               headers=headers(tokens))
    return created


def calc_step(services, run_id, calls, dispatched):
    client = ScriptedClient(calls)
    prompts = {**PROMPTS, "safety_analyst": [{"role": "system", "content": "seguridad"}]}
    run_step(services.store, run_id, GroundingDesignAgent(services.store, client=client, prompts=prompts),
             dispatch_calculation=dispatched.append)
    assert client.calls == [], "the script was not fully consumed"
    return client


def test_safety_calculation_suspends_and_resumes_with_the_result(chat):
    services, client, tokens, project, conversation, _, _ = chat
    created = calculation_setup(chat)
    sent = send(client, tokens, conversation, "Comienza con el cálculo de seguridad, por favor")
    dispatched = []
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"x_over_r": 10}),
        ("respond_to_user", {"text": "Lancé el cálculo de seguridad; te aviso al terminar.", "waits_for": "calculation"}),
    ], dispatched)
    queued = tool_result(llm, 1)
    assert queued["queued"] and queued["parameters"]["x_over_r"] == 10 and dispatched == [queued["calculation_id"]]
    run = run_of(client, tokens, sent["run_id"])
    assert run["status"] == "waiting_calculation"
    polled = events(client, tokens, conversation)
    assert polled["poll_after_ms"] == 5000
    assert {"calculation.queued", "run.waiting_calculation"} <= {e["type"] for e in polled["events"]}

    # The worker stores the result and resumes the run.
    with services.store.transaction(write=True) as db:
        db.change("calculos_potencial_tierras", queued["calculation_id"], status="completed", result=RESULT)
    assert AgentRuns(services.store).calculation_finished(queued["calculation_id"]) == sent["run_id"]
    assert run_of(client, tokens, sent["run_id"])["status"] == "queued"
    llm = calc_step(services, sent["run_id"], [
        ("delegate_safety_analyst", {}),
        ("submit_safety_report", {"explanation": "La tensión de contacto excede el tolerable.",
                                  "dominant_constraint": "tensión de contacto, margen −18,1 %",
                                  "recommendations": ["Reducir la retícula perimetral"]}),
        ("respond_to_user", {"text": "No cumple: contacto 980,4 V frente a 830 V.", "waits_for": "nothing"}),
    ], dispatched)
    context = llm.requests[0]["messages"][1]["content"]
    assert '"verdict": "no_cumple"' in context and '"margin_percent": -18.1' in context
    report = tool_result(llm, 2)
    assert report["verdict"] == "no_cumple" and report["recommendations"] == ["Reducir la retícula perimetral"]
    run = run_of(client, tokens, sent["run_id"])
    assert run["status"] == "completed"
    texts = [m["text"] for m in messages(client, tokens, conversation)]
    assert "Cálculo de seguridad terminado" in texts  # mirrored milestone
    assert texts[-1].startswith("No cumple")
    assert created["artifact_id"] == queued["artifact_id"]


WORSE = {**RESULT, "max_touch_v": {"value": 1100.0},
         "safety": [{**RESULT["safety"][0], "criteria": [
             {**RESULT["safety"][0]["criteria"][0], "actual_v": 1100.0, "margin_rel": -0.3253},
             RESULT["safety"][0]["criteria"][1]]}]}


def finish(services, calculation_id, result):
    with services.store.transaction(write=True) as db:
        db.change("calculos_potencial_tierras", calculation_id, status="completed", result=result)
    AgentRuns(services.store).calculation_finished(calculation_id)


def autonomous_iteration_to_a_worse_version(chat):
    """v1 does not comply; the automatic iteration saves v2, whose result is worse than v1's."""
    services, client, tokens, project, conversation, _, _ = chat
    calculation_setup(chat)
    client.put(f"/api/v1/conversations/{conversation['id']}/agent-state", json={"mode": "autonomo"},
               headers=headers(tokens))
    sent = send(client, tokens, conversation, "Optimiza el diseño hasta que cumpla")
    dispatched = []
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"x_over_r": 12}),
        ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"}),
    ], dispatched)
    first = tool_result(llm, 1)["calculation_id"]
    finish(services, first, RESULT)
    calc_step(services, sent["run_id"], [
        designer(sent["id"], ("geometry.burial_depth_m", 0.8, "assumption"), rationale="Más profundidad"),
    ], dispatched)
    assert [a["version"] for a in artifacts(client, tokens, project)] == [2] and len(dispatched) == 2
    return services, client, tokens, project, conversation, sent, dispatched, first


def run_usage(services, run_id):
    with services.store.transaction() as db:
        return db.one("agent_runs", id=run_id)["usage"]


def test_autonomous_loop_restores_the_best_version_when_an_iteration_is_worse(chat):
    services, client, tokens, project, conversation, sent, dispatched, first = (
        autonomous_iteration_to_a_worse_version(chat))
    finish(services, dispatched[1], WORSE)

    # No model call: the loop restores v1 as v3 and recalculates it with v1's parameters.
    calc_step(services, sent["run_id"], [], dispatched)
    with services.store.transaction() as db:
        v1 = db.designs.get_version(project["id"], artifacts(client, tokens, project)[0]["artifact_id"], 1)
        restored_calc = db.one("calculos_potencial_tierras", id=dispatched[2])
        first_calc = db.one("calculos_potencial_tierras", id=first)
    [latest] = artifacts(client, tokens, project)
    assert latest["version"] == 3 and latest["snapshot"] == v1["snapshot"]
    assert latest["origin"]["restored_from"] == 1 and latest["origin"]["run_id"] == sent["run_id"]
    assert restored_calc["artifact_version"] == 3 and restored_calc["parameters"] == first_calc["parameters"]
    assert run_of(client, tokens, sent["run_id"])["status"] == "waiting_calculation"
    assert run_usage(services, sent["run_id"])["design_loop_restoring"]["restored_from"] == 1
    assert updates(client, tokens, conversation)[-1]["payload"]["version"] == 3  # card with «Deshacer»

    finish(services, dispatched[2], RESULT)
    calc_step(services, sent["run_id"], [], dispatched)
    assert len(dispatched) == 3 and run_of(client, tokens, sent["run_id"])["status"] == "completed"
    usage = run_usage(services, sent["run_id"])
    assert usage["design_loop_restoring"] is None
    result = usage["design_loop_result"]
    assert result["reason"] == "no_improvement" and result["iterations_used"] == 1
    assert result["best_candidate"]["artifact_version"] == 3 and result["best_candidate"]["restored_from"] == 1
    assert result["best_candidate"]["calculation_id"] == dispatched[2]
    final = [m for m in messages(client, tokens, conversation) if m["source"] == "agent"][-1]["text"]
    assert "versión 3 (restaurada desde la versión 1)" in final and "margen mínimo -18.1%" in final
    assert artifacts(client, tokens, project)[0]["calculation_verdict"] == "no_cumple"  # v3 has its own result


def test_autonomous_loop_never_restores_over_a_user_edit(chat):
    services, client, tokens, project, conversation, sent, dispatched, _ = (
        autonomous_iteration_to_a_worse_version(chat))
    [current] = artifacts(client, tokens, project)
    edited = client.put(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/{current['artifact_id']}",
                        json={**current["snapshot"], "name": "Editado a mano"}, headers=headers(tokens))
    assert edited.status_code == 201, edited.text
    finish(services, dispatched[1], WORSE)

    calc_step(services, sent["run_id"], [], dispatched)
    assert len(dispatched) == 2 and run_of(client, tokens, sent["run_id"])["status"] == "completed"
    [latest] = artifacts(client, tokens, project)
    assert latest["version"] == 3 and latest["name"] == "Editado a mano"
    result = run_usage(services, sent["run_id"])["design_loop_result"]
    assert result["reason"] == "no_improvement" and result["best_candidate"]["artifact_version"] == 1


def test_calculation_is_not_repeated_for_the_same_version_and_parameters(chat):
    services, client, tokens, project, conversation, _, _ = chat
    calculation_setup(chat)
    sent = send(client, tokens, conversation, "Calcula la seguridad")
    dispatched = []
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"x_over_r": 10}),
        ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"}),
    ], dispatched)
    queued = tool_result(llm, 1)
    with services.store.transaction(write=True) as db:
        db.change("calculos_potencial_tierras", queued["calculation_id"], status="completed", result=RESULT)
    AgentRuns(services.store).calculation_finished(queued["calculation_id"])

    # On resume the model asks again for the same calculation (only the note differs): it gets the stored result.
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"x_over_r": 10, "justification": "Datos confirmados por el usuario."}),
        ("respond_to_user", {"text": "No cumple: contacto 980,4 V.", "waits_for": "nothing"}),
    ], dispatched)
    repeated = tool_result(llm, 1)
    assert repeated["queued"] is False and repeated["already_calculated"] is True
    assert repeated["calculation_id"] == queued["calculation_id"] and repeated["result"]["verdict"] == "no_cumple"
    assert dispatched == [queued["calculation_id"]]
    assert run_of(client, tokens, sent["run_id"])["status"] == "completed"

    # Other parameters are a different calculation.
    sent = send(client, tokens, conversation, "Calcula con X/R 14")
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"x_over_r": 14}),
        ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"}),
    ], dispatched)
    assert tool_result(llm, 1)["queued"] is True and len(dispatched) == 2


def test_calculation_blocked_by_missing_and_unconfirmed_inputs(chat):
    services, client, tokens, project, conversation, _, _ = chat
    calculation_setup(chat, {"name": "Solo malla", "geometry": ARTIFACT["geometry"]})
    sent = send(client, tokens, conversation, "Calcula")
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {}),
        ("respond_to_user", {"text": "Faltan el suelo y los datos de falla.", "waits_for": "answer"}),
    ], [])
    blocked = tool_result(llm, 1)
    assert blocked["queued"] is False and blocked["missing"] == ["soil_layers", "fault.current_a", "fault.clearing_time_s"]
    with services.store.transaction() as db:
        assert db.many("calculos_potencial_tierras", project_id=project["id"]) == []


def test_calculation_dispatch_failure_and_manual_cancel(chat):
    services, client, tokens, project, conversation, _, _ = chat
    created = calculation_setup(chat)
    sent = send(client, tokens, conversation, "Calcula")

    def broken(_calculation_id):
        raise ConnectionError("redis")

    client_ = ScriptedClient([("request_potential_calculation", {}),
                              ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"})])
    run_step(services.store, sent["run_id"], GroundingDesignAgent(services.store, client=client_, prompts=PROMPTS),
             dispatch_calculation=broken)
    assert run_of(client, tokens, sent["run_id"])["status"] == "failed"
    with services.store.transaction() as db:
        assert db.many("calculos_potencial_tierras", project_id=project["id"])[0]["status"] == "failed"

    # Cancelling the calculation from the Cálculos panel resumes the waiting run.
    again = send(client, tokens, conversation, "Calcula otra vez")
    dispatched = []
    calc_step(services, again["run_id"], [("request_potential_calculation", {}),
                                          ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"})],
              dispatched)
    resumed = []
    from src.infrastructure.entrypoint.api import artifact_routes
    artifact_routes.enqueue_agent_step, original = resumed.append, artifact_routes.enqueue_agent_step
    try:
        cancel = client.post(f"/api/v1/projects/{project['id']}/artefactos-diseno-tierras/{created['artifact_id']}"
                             f"/calculos-potencial/{dispatched[0]}/cancelar", headers=headers(tokens))
    finally:
        artifact_routes.enqueue_agent_step = original
    assert cancel.status_code == 200 and resumed == [again["run_id"]]
    assert "calculation.failed" in [e["type"] for e in events(client, tokens, conversation)["events"]]


def test_confirming_a_default_records_it_and_unblocks_the_calculation(chat):
    """The reported loop: the user confirms 3000 ohm-m / 0.1 m, the values do not change, and the
    calculation kept asking for the confirmation."""
    services, client, tokens, project, conversation, _, _ = chat
    first = send(client, tokens, conversation, "Malla 40 x 30 m retícula 5 m, suelo 100 ohm-m, 5 kA, 0,5 s")
    user = {"kind": "user", "ref": first["id"], "note": None}
    step(services, first["run_id"], [
        ("set_fields", {"reason": "Datos", "changes": [
            {"path": "geometry.length_m", "value": 40, "source": user},
            {"path": "geometry.width_m", "value": 30, "source": user},
            {"path": "geometry.conductor_spacing_m", "value": 5, "source": user},
            {"path": "soil_layers", "value": [{"resistivity_ohm_m": 100, "depth_m": None}], "source": user},
            {"path": "fault.current_a", "value": 5000, "source": user},
            {"path": "fault.clearing_time_s", "value": 0.5, "source": user}]}),
        ("apply_changes", {"summary": "Diseño inicial"}),
        ("respond_to_user", {"text": "Listo.", "waits_for": "nothing"}),
    ])
    assert artifacts(client, tokens, project)[0]["origin"]["provenance"]["fault.surface_thickness_m"]["kind"] == "schema_default"

    confirm = send(client, tokens, conversation, "Sí, confirmo 3000 Ω·m y 0,1 m de capa superficial. Calcula.")
    yes = {"kind": "user", "ref": confirm["id"], "note": None}
    dispatched = []
    llm = calc_step(services, confirm["run_id"], [
        ("set_fields", {"reason": "Confirmación", "changes": [
            {"path": "geometry.surface_layer_thickness_m", "value": 0.1, "source": yes},
            {"path": "fault.surface_resistivity_ohm_m", "value": 3000, "source": yes},
            {"path": "fault.surface_thickness_m", "value": 0.1, "source": yes}]}),
        ("request_potential_calculation", {}),
        ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"}),
    ], dispatched)
    fields = tool_result(llm, 1)
    assert fields["applied"] == ["fault.surface_resistivity_ohm_m", "fault.surface_thickness_m"]
    assert "unknown field" in fields["errors"][0]
    queued = tool_result(llm, 2)
    assert queued["queued"] and queued["version"] == 2 and dispatched == [queued["calculation_id"]]
    latest = artifacts(client, tokens, project)[0]
    assert latest["origin"]["provenance"]["fault.surface_thickness_m"] == {"kind": "user", "ref": confirm["id"]}
    card = updates(client, tokens, conversation)[-1]["payload"]
    assert {c["path"] for c in card["changes"] if c.get("confirmed")} == {
        "fault.surface_resistivity_ohm_m", "fault.surface_thickness_m"}
    assert run_of(client, tokens, confirm["run_id"])["status"] == "waiting_calculation"


def test_confirm_inputs_tool_after_a_blocked_calculation(chat):
    services, client, tokens, project, conversation, _, _ = chat
    first = send(client, tokens, conversation, "Malla 20 x 20 m retícula 5 m, suelo 100 ohm-m, 5 kA, 0,5 s")
    user = {"kind": "user", "ref": first["id"], "note": None}
    step(services, first["run_id"], [
        ("set_fields", {"reason": "Datos", "changes": [
            {"path": "geometry.length_m", "value": 20, "source": user}, {"path": "geometry.width_m", "value": 20, "source": user},
            {"path": "geometry.conductor_spacing_m", "value": 5, "source": user},
            {"path": "soil_layers", "value": [{"resistivity_ohm_m": 100, "depth_m": None}], "source": user},
            {"path": "fault.current_a", "value": 5000, "source": user},
            {"path": "fault.clearing_time_s", "value": 0.5, "source": user}]}),
        ("apply_changes", {"summary": "Diseño"}),
        ("request_potential_calculation", {}),
        ("respond_to_user", {"text": "¿Confirmas 3000 Ω·m y 0,1 m?", "waits_for": "answer"}),
    ])
    yes = send(client, tokens, conversation, "Sí, confirmo")
    dispatched = []
    llm = calc_step(services, first["run_id"], [
        ("confirm_inputs", {"paths": ["fault.surface_resistivity_ohm_m", "fault.surface_thickness_m"], "message_id": yes["id"]}),
        ("request_potential_calculation", {}),
        ("respond_to_user", {"text": "Calculando.", "waits_for": "calculation"}),
    ], dispatched)
    assert len(tool_result(llm, 1)["confirmed"]) == 2
    assert tool_result(llm, 2)["queued"] and dispatched


def test_a_too_short_justification_does_not_stop_the_calculation(chat):
    services, client, tokens, project, conversation, _, _ = chat
    calculation_setup(chat)
    sent = send(client, tokens, conversation, "Calcula la seguridad")
    dispatched = []
    llm = calc_step(services, sent["run_id"], [
        ("request_potential_calculation", {"justification": "ok"}),
        ("respond_to_user", {"text": "Lancé el cálculo.", "waits_for": "calculation"}),
    ], dispatched)
    queued = tool_result(llm, 1)
    assert queued["queued"] is True and dispatched == [queued["calculation_id"]]


def test_rejection_reasons_reach_the_user_in_spanish():
    from src.infrastructure.agents.design_agent import _spanish_reason

    assert _spanish_reason("geometry.burial_depth_m: Input should be greater than 0") == (
        "geometry.burial_depth_m: debe ser mayor que 0")
    assert _spanish_reason("fault.current_a: not applied, Input should be greater than or equal to 1") == (
        "fault.current_a: debe ser mayor o igual que 1")
    assert _spanish_reason("geometry.foo: Extra inputs are not permitted") == "geometry.foo: no es un campo admitido"


def _budget_for(services, admin_actor, client, tokens, total, used=0):
    user_id = client.get("/api/v1/auth/me", headers=headers(tokens)).json()["id"]
    budget = services.budgets.create(admin_actor, {"user_id": user_id, "name": "Piloto", "total_tokens": total})
    if used:
        with services.store.transaction(write=True) as db:
            db.change("budget", budget["id"], used_tokens=used)
    return budget


def test_agent_does_not_call_the_model_when_the_budget_is_exhausted(chat):
    services, client, tokens, project, conversation, _, admin_actor = chat
    _budget_for(services, admin_actor, client, tokens, total=10_000, used=9_500)
    sent = send(client, tokens, conversation, "Diseña una malla de 40 x 30 m")
    llm = step(services, sent["run_id"], [])  # no model call at all
    assert llm.requests == []
    assert run_of(client, tokens, sent["run_id"])["status"] == "completed"
    answer = [m for m in messages(client, tokens, conversation) if m["source"] == "agent"][-1]["text"]
    assert "bolsa de tokens tiene 500 disponibles" in answer and "2.000" in answer


def test_agent_requires_a_budget_when_configured(chat, monkeypatch):
    services, client, tokens, project, conversation, _, _ = chat
    monkeypatch.setenv("AGENT_REQUIRE_BUDGET", "true")
    sent = send(client, tokens, conversation, "Diseña una malla de 40 x 30 m")
    llm = step(services, sent["run_id"], [])
    assert llm.requests == []
    answer = [m for m in messages(client, tokens, conversation) if m["source"] == "agent"][-1]["text"]
    assert "no tiene una bolsa de tokens asignada" in answer


def test_agent_with_budget_left_runs_and_debits_its_usage(chat):
    services, client, tokens, project, conversation, _, admin_actor = chat
    budget = _budget_for(services, admin_actor, client, tokens, total=100_000)
    sent = send(client, tokens, conversation, "¿Qué falta?")
    step(services, sent["run_id"], [("respond_to_user", {"text": "Falta todo.", "waits_for": "nothing"})])
    with services.store.transaction() as db:
        used = db.one("budget", id=budget["id"])["used_tokens"]
        ledger = db.many("budget_usage", budget_id=budget["id"], limit=None)
    assert used > 0 and sum(row["total_tokens"] for row in ledger) == used
    assert {row["action"] for row in ledger} == {"grounding_design_agent"}
