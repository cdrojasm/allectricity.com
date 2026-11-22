import copy
import json
from types import SimpleNamespace

from src.application.ports.prompt_catalog import PromptSnapshot
from src.infrastructure.processing import document_agents
from src.infrastructure.processing.document_sources import DOCX_MIME, parse_document
from tests.infrastructure.test_knowledge_extraction import LLM_PAYLOAD, MEMORIA



def _prompt(messages=None):
    return PromptSnapshot(name="spat-document-extractor", version="test", messages=messages or [])


class ScriptedClient:
    """Cliente OpenAI simulado: cada respuesta es una llamada a submit_extraction."""

    def __init__(self, submissions):
        self.submissions, self.requests = list(submissions), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        payload = self.submissions.pop(0)
        call = SimpleNamespace(id=f"call{len(self.requests)}", function=SimpleNamespace(
            name="submit_extraction", arguments=json.dumps(payload)))
        message = SimpleNamespace(tool_calls=[call], model_dump=lambda **_: {
            "role": "assistant", "tool_calls": [{"id": call.id, "type": "function",
                                                 "function": {"name": call.function.name,
                                                              "arguments": call.function.arguments}}]})
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_extractor_gets_source_validation_feedback_before_finishing(monkeypatch):
    broken = copy.deepcopy(LLM_PAYLOAD)
    broken["evidence"][0]["finding_ids"].remove("a1")  # atributo sin evidencia
    client = ScriptedClient([broken, LLM_PAYLOAD])
    monkeypatch.setattr(document_agents, "_clients", lambda: (None, client))
    source = parse_document(MEMORIA, DOCX_MIME)
    prompts = {"extractor": _prompt([{"role": "system", "content": "x"}])}

    result = document_agents.run_llm_extraction(source, {}, "m.docx", prompts)

    assert result["payload"] == LLM_PAYLOAD and result["errors"] == []
    assert result["usage"]["submissions"] == 2
    feedback = json.loads(client.requests[1]["messages"][-1]["content"])
    assert feedback["accepted"] is False
    assert any(error.startswith("a1: missing_evidence") for error in feedback["errors"])


def test_a_numeric_schema_version_is_read_as_its_string(monkeypatch):
    numeric = copy.deepcopy(LLM_PAYLOAD)
    numeric["schema_version"] = float(LLM_PAYLOAD["schema_version"])  # what the models send
    client = ScriptedClient([numeric])
    monkeypatch.setattr(document_agents, "_clients", lambda: (None, client))
    source = parse_document(MEMORIA, DOCX_MIME)

    result = document_agents.run_llm_extraction(source, {}, "m.docx", {"extractor": _prompt()})

    assert result["errors"] == [] and result["payload"]["schema_version"] == LLM_PAYLOAD["schema_version"]
    assert result["usage"]["submissions"] == 1


def test_last_submission_is_kept_even_with_finding_level_problems(monkeypatch):
    broken = copy.deepcopy(LLM_PAYLOAD)
    broken["evidence"][0]["finding_ids"].remove("a1")
    client = ScriptedClient([broken] * document_agents.MAX_SUBMISSIONS)
    monkeypatch.setattr(document_agents, "_clients", lambda: (None, client))
    source = parse_document(MEMORIA, DOCX_MIME)
    prompts = {"extractor": _prompt()}

    result = document_agents.run_llm_extraction(source, {}, "m.docx", prompts)

    assert result["payload"] == broken and result["errors"] == []


def test_token_limit_stops_the_extractor_and_reports_its_usage(monkeypatch):
    broken = copy.deepcopy(LLM_PAYLOAD)
    broken["evidence"][0]["finding_ids"].remove("a1")
    client = ScriptedClient([broken] * document_agents.MAX_SUBMISSIONS)
    monkeypatch.setattr(document_agents, "_clients", lambda: (None, client))
    source = parse_document(MEMORIA, DOCX_MIME)
    prompts = {"extractor": _prompt()}

    result = document_agents.run_llm_extraction(source, {}, "m.docx", prompts, max_tokens=20)

    assert result["payload"] is None and "token limit" in result["errors"][0]
    assert len(client.requests) == 2 and result["usage"]["token_limit_exceeded"]
    assert result["usage"]["prompt_tokens"] + result["usage"]["completion_tokens"] == 30


def test_plain_text_answers_get_a_reminder_and_then_a_forced_tool_call(monkeypatch):
    client = ScriptedClient([LLM_PAYLOAD])
    replies = [None, None]  # dos respuestas de texto antes de la llamada a la herramienta
    original = client.create

    def create(**kwargs):
        if replies:
            replies.pop()
            client.requests.append(kwargs)
            message = SimpleNamespace(tool_calls=None, content="Aquí está mi análisis…")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
        return original(**kwargs)

    client.chat.completions.create = create
    monkeypatch.setattr(document_agents, "_clients", lambda: (None, client))
    source = parse_document(MEMORIA, DOCX_MIME)

    result = document_agents.run_llm_extraction(source, {}, "m.docx",
                                                {"extractor": _prompt()})

    assert result["payload"] == LLM_PAYLOAD
    assert client.requests[1]["tool_choice"] == "auto"
    assert client.requests[2]["tool_choice"]["function"]["name"] == "submit_extraction"
