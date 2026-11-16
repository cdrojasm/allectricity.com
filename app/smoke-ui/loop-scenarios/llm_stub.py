"""Scripted OpenAI-compatible LLM for forcing the autonomous-loop branches in local smoke tests.

Only for the local stack: it answers /v1/chat/completions with fixed tool calls so the cases that depend
on what the model proposes (P1-03 no valid change, P1-04 a worse iteration) become reproducible. The
solver, API, worker and UI stay real. Scenario from STUB_SCENARIO:

- invalid: the grid designer always proposes a burial depth the schema rejects.
- worse:   the grid designer widens the mesh to 10 × 10 m (always worse touch voltage than 5 × 6 m).

- p4:      scripts the orchestrator from a marker in the user's message (P4-02/P4-03 forced):
           ESCENARIO=negar ANCHO=<m> FRASE=«…»  saves the width and then answers with the negation;
           ESCENARIO=afirmar                    saves nothing and claims a saved version;
           ESCENARIO=invalido ANCHO=<m>         saves the width, tries a negative burial depth, claims it saved.

Any other agent that asks (orchestrator) gets a plain respond_to_user so the run never hangs.
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCENARIO = os.environ.get("STUB_SCENARIO", "worse")
CHANGES = {
    "invalid": [{"path": "geometry.burial_depth_m", "value": -1, "source_kind": "assumption",
                 "message_id": None, "note": "Escenario forzado: valor fuera de rango"}],
    "worse": [{"path": "geometry.conductor_spacing_x_m", "value": 10, "source_kind": "assumption",
               "message_id": None, "note": "Escenario forzado: retícula más abierta"},
              {"path": "geometry.conductor_spacing_y_m", "value": 10, "source_kind": "assumption",
               "message_id": None, "note": "Escenario forzado: retícula más abierta"}],
}


def tool_call(name: str, arguments: dict) -> dict:
    return {"id": f"call-{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def _p4_plan(messages: list) -> tuple[list, int]:
    """The scripted orchestrator calls for the last user message, and how many of them already ran."""
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    text = str(messages[last_user].get("content") or "") if last_user >= 0 else ""
    done = sum(1 for m in messages[last_user + 1:] if m.get("role") == "tool")
    found = re.match(r"\[mensaje ([^\]]+)\]", text)
    source = {"kind": "user", "ref": found.group(1) if found else None, "note": None}
    width = re.search(r"ANCHO=([\d.]+)", text)
    set_width = ("set_fields", {"reason": "Pedido del usuario", "changes": [
        {"path": "geometry.width_m", "value": float(width.group(1)) if width else 31.0, "source": source}]})
    if "ESCENARIO=negar" in text:
        phrase = re.search(r"FRASE=«([^»]+)»", text)
        plan = [set_width, ("apply_changes", {"summary": "Ancho pedido por el usuario"}),
                ("respond_to_user", {"text": phrase.group(1) if phrase else "No se realizaron cambios.",
                                     "waits_for": "nothing"})]
    elif "ESCENARIO=afirmar" in text:
        plan = [("respond_to_user", {"text": "Guardé la versión 99 del diseño.", "waits_for": "nothing"})]
    elif "ESCENARIO=invalido" in text:
        plan = [set_width, ("apply_changes", {"summary": "Ancho pedido por el usuario"}),
                ("set_fields", {"reason": "Pedido del usuario", "changes": [
                    {"path": "geometry.burial_depth_m", "value": -2, "source": source}]}),
                ("apply_changes", {"summary": "Profundidad pedida por el usuario"}),
                ("respond_to_user", {"text": "Guardé la profundidad de -2 m en una versión nueva.",
                                     "waits_for": "nothing"})]
    else:
        plan = [("respond_to_user", {"text": "Respuesta del LLM de prueba.", "waits_for": "nothing"})]
    return plan, done


def answer(request: dict) -> dict:
    tools = {tool["function"]["name"] for tool in request.get("tools") or []}
    if SCENARIO == "p4" and "respond_to_user" in tools:
        plan, done = _p4_plan(request.get("messages") or [])
        name, arguments = plan[min(done, len(plan) - 1)]
        calls = [tool_call(name, arguments)]
    elif "submit_grid_design" in tools and SCENARIO in CHANGES:
        calls = [tool_call("submit_grid_design", {"changes": CHANGES[SCENARIO],
                                                  "rationale": f"Escenario de prueba «{SCENARIO}»"})]
    elif "respond_to_user" in tools:
        calls = [tool_call("respond_to_user", {"text": "Respuesta del LLM de prueba.", "waits_for": "nothing"})]
    else:
        calls = []
    message = {"role": "assistant", "content": None if calls else "Respuesta del LLM de prueba."}
    if calls:
        message["tool_calls"] = calls
    print(json.dumps({"scenario": SCENARIO, "tools": sorted(tools), "answered": [c["function"]["name"] for c in calls]}),
          flush=True)
    return {"id": "stub", "object": "chat.completion", "created": 0, "model": request.get("model", "stub"),
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        payload = json.dumps(answer(body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    if SCENARIO not in {*CHANGES, "p4"}:
        sys.exit(f"STUB_SCENARIO must be one of {sorted({*CHANGES, 'p4'})}")
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
