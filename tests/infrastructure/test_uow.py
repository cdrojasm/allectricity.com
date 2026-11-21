import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet

from src.application.ports.prompt_catalog import PromptSnapshot
from src.application.use_cases.identity import now
from src.infrastructure.agents import runtime, telemetry, uow
from src.infrastructure.agents.phoenix_prompt_catalog import PhoenixPromptCatalog
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings

PASSWORD = "Correct-Horse-9-Battery"


class FakeClient:
    """OpenAI-compatible client: scripted chat responses (text or one tool call each) and Responses calls."""

    def __init__(self, script=None):
        self.script, self.requests, self.responses_requests = list(script or ["hola"]), [], []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.responses = SimpleNamespace(create=self._respond)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        step = self.script.pop(0)
        number = len(self.requests)
        if isinstance(step, tuple):
            name, arguments = step
            call = SimpleNamespace(id=f"call{number}", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
            message = SimpleNamespace(content=None, tool_calls=[call], model_dump=lambda **_: {
                "role": "assistant", "tool_calls": [{"id": call.id, "type": "function", "function": {
                    "name": name, "arguments": call.function.arguments}}]})
        else:
            message = SimpleNamespace(content=step, tool_calls=None)
        return SimpleNamespace(id=f"gen-{number}", model="openai/gpt-4.1",
                               choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))

    def _respond(self, **kwargs):
        self.responses_requests.append(kwargs)
        return SimpleNamespace(id="resp-1", model="openai/gpt-4.1", output_text="[]", output=[],
                               usage=SimpleNamespace(input_tokens=50, output_tokens=10))


def prompt(model=None, parameters=None, content="Eres un redactor."):
    return PromptSnapshot(name="spat-study-writer", version="v7", messages=[{"role": "system", "content": content}],
                          model_name=model, parameters=parameters or {})


@pytest.fixture
def store(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'uow.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    config = Path("backend/alembic.ini") if Path("backend/alembic.ini").exists() else Path("alembic.ini")
    command.upgrade(Config(str(config)), "head")
    services = build_services(Settings(database_url=db_url, jwt_secret="test-only-secret-" * 4,
                                       mail_key=Fernet.generate_key().decode(), environment="test"))
    admin = services.admin.bootstrap("admin@example.com", PASSWORD, "Admin")
    services.store.user_id = admin["id"]
    yield services.store
    services.store.engine.dispose()


def add_budget(store, total, used=0):
    with store.transaction(write=True) as db:
        return db.add("budget", id=f"b-{total}-{used}", user_id=store.user_id, name="Plan", total_tokens=total,
                      used_tokens=used, active=True, created_at=now())


def ledger(store):
    with store.transaction() as db:
        return db.many("budget_usage", limit=None)


@pytest.fixture
def spans(monkeypatch):
    """Capture spans in memory instead of exporting them to Phoenix."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter, provider = InMemorySpanExporter(), TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", lambda *args, **kwargs: provider.get_tracer(*args[:1]))
    return exporter


def test_every_application_has_a_seed():
    for application, seed in uow.APPLICATIONS.items():
        assert runtime.read_prompt_seed(seed).strip(), application
    with pytest.raises(ValueError):
        uow.UnitOfWork("spat-unknown")


def test_phoenix_supplies_prompt_model_and_sampling_but_not_structure():
    client = FakeClient()
    work = uow.UnitOfWork("spat-study-writer", client=client,
                          prompt=prompt(model="anthropic/claude-sonnet-4", parameters={"temperature": 0.9}))
    work.complete([{"role": "user", "content": "Resume"}], temperature=0.2, response_format={"type": "json_object"})
    sent = client.requests[0]
    assert sent["model"] == "anthropic/claude-sonnet-4"
    assert sent["temperature"] == 0.9  # tuned in Phoenix
    assert sent["response_format"] == {"type": "json_object"}  # structure stays in the code
    assert sent["messages"] == [{"role": "system", "content": "Eres un redactor."},
                                {"role": "user", "content": "Resume"}]


def test_model_falls_back_to_openrouter_model_and_bare_names_get_a_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1")
    assert uow.UnitOfWork("spat-study-writer", prompt=prompt()).model == "openai/gpt-4.1"
    assert uow.UnitOfWork("spat-study-writer", prompt=prompt(model="gpt-5-nano")).model == "openai/gpt-5-nano"


def test_phoenix_catalog_keeps_only_tunable_parameters():
    class Version:
        id = "ver-3"
        _model_name = "openai/gpt-4.1"

        def format(self, sdk):
            return SimpleNamespace(messages=[{"role": "system", "content": "x"}], kwargs={
                "model": "openai/gpt-4.1", "temperature": 0.3, "max_tokens": 900, "tools": [{"type": "function"}]})

    phoenix = SimpleNamespace(prompts=SimpleNamespace(get=lambda **_: Version()))
    snapshot = PhoenixPromptCatalog(client=phoenix).load("spat-study-writer", tag="production")
    assert snapshot.model_name == "openai/gpt-4.1" and snapshot.version == "ver-3"
    assert snapshot.parameters == {"temperature": 0.3, "max_tokens": 900}


def test_seed_is_used_while_phoenix_is_down_and_a_version_can_be_pinned(monkeypatch):
    calls = []

    class Down:
        def load(self, name, *, tag=None, version_id=None):
            calls.append((name, tag, version_id))
            raise ConnectionError("phoenix down")

    monkeypatch.setenv("DOCUMENT_EXTRACTOR_PROMPT_VERSION", "pinned-1")
    snapshot = uow.load_prompt("spat-document-extractor", catalog=Down())
    assert calls == [("spat-document-extractor", "production", "pinned-1")]
    assert snapshot.version == "local" and snapshot.messages[0]["content"] == runtime.read_prompt_seed(
        "document-extractor.md")


def test_the_model_of_one_application_can_be_chosen_by_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1")
    context = uow.WorkContext(user_id="u-1")
    work = uow.UnitOfWork("spat-study-writer", context, client=object(), prompt=prompt(model="openai/gpt-4.1-mini"))
    assert work.model == "openai/gpt-4.1-mini"  # Phoenix version
    monkeypatch.setenv("STUDY_WRITER_MODEL", "anthropic/claude-sonnet-4")
    assert work.model == "anthropic/claude-sonnet-4"  # environment wins
    other = uow.UnitOfWork("spat-plan-vision", context, client=object(), prompt=prompt())
    assert other.model == "openai/gpt-4.1"  # untouched applications keep their default


def test_each_response_is_charged_once_to_the_user_under_the_application(store):
    budget = add_budget(store, 100_000)
    context = uow.WorkContext(user_id=store.user_id, project_id="p-1", entity="study:1")
    work = uow.UnitOfWork("spat-study-writer", context, client=FakeClient(["uno", "dos"]), prompt=prompt(), store=store)
    work.complete([{"role": "user", "content": "a"}])
    work.complete([{"role": "user", "content": "b"}])
    work._account(SimpleNamespace(id="gen-1", model="openai/gpt-4.1",  # a redelivered response
                                  usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20)))
    rows = ledger(store)
    assert [(row["action"], row["total_tokens"], row["project_id"]) for row in rows] == [
        ("spat-study-writer", 120, "p-1"), ("spat-study-writer", 120, "p-1")]
    assert {row["idempotency_key"] for row in rows} == {"spat-study-writer:gen-1", "spat-study-writer:gen-2"}
    with store.transaction() as db:
        assert db.one("budget", id=budget["id"])["used_tokens"] == 240
    assert work.tokens == {"input": 300, "output": 60, "calls": 3}


def test_calls_without_a_user_are_not_charged(store):
    add_budget(store, 100_000)
    uow.UnitOfWork("spat-study-writer", client=FakeClient(), prompt=prompt(), store=store).complete(
        [{"role": "user", "content": "a"}])
    assert ledger(store) == []


def test_budget_policy_blocks_before_calling_the_model(store, monkeypatch):
    context = uow.WorkContext(user_id=store.user_id)
    work = uow.UnitOfWork("spat-study-writer", context, client=FakeClient(), prompt=prompt(), store=store)
    work.require_capacity()  # no budget and not required: allowed
    monkeypatch.setenv("AGENT_REQUIRE_BUDGET", "true")
    with pytest.raises(uow.BudgetUnavailable) as missing:
        work.require_capacity()
    assert "no tiene una bolsa" in missing.value.message
    add_budget(store, 10_000, used=9_500)
    with pytest.raises(uow.BudgetUnavailable) as low:
        work.require_capacity()
    assert "quedan 500" in low.value.message and "2.000" in low.value.message


def test_tool_loop_charges_every_round_and_traces_tools_under_the_agent(store, spans):
    add_budget(store, 100_000)
    client = FakeClient([("lookup", {"q": "varilla"}), ("submit", {"answer": "ok"})])
    context = uow.WorkContext(user_id=store.user_id, project_id="p-1", session_id="conv-1", entity="agent_run:9")
    work = uow.UnitOfWork("spat-agent-orchestrator", context, client=client, store=store,
                          prompt=PromptSnapshot(name="spat-agent-orchestrator", version="v2",
                                                messages=[{"role": "system", "content": "orquestador"}]))
    usage = runtime.new_usage()
    with uow.scope("spat-agent-step", context):
        result = work.run_tools([{"role": "user", "content": "Diseña"}],
                                [runtime.tool("lookup", "", {"q": {"type": "string"}}, ["q"]),
                                 runtime.tool("submit", "", {"answer": {"type": "string"}}, ["answer"])],
                                {"lookup": lambda args: {"found": args["q"]}}, "submit",
                                lambda args: (True, {"ok": True}), usage)
    assert result == {"answer": "ok"}
    assert [row["action"] for row in ledger(store)] == ["spat-agent-orchestrator"] * 2
    assert client.requests[0]["messages"][0] == {"role": "system", "content": "orquestador"}

    by_name = {span.name: span for span in spans.get_finished_spans()}
    step, agent, tool = by_name["spat-agent-step"], by_name["spat-agent-orchestrator"], by_name["lookup"]
    assert agent.parent.span_id == step.context.span_id and tool.parent.span_id == agent.context.span_id
    assert agent.attributes["openinference.span.kind"] == "AGENT" and tool.attributes["openinference.span.kind"] == "TOOL"
    assert agent.attributes["user.id"] == store.user_id and agent.attributes["session.id"] == "conv-1"
    metadata = json.loads(agent.attributes["metadata"])
    assert metadata == {"application": "spat-agent-orchestrator", "project_id": "p-1", "entity": "agent_run:9",
                        "prompt_version": "v2"}
    assert "spat-agent-orchestrator" in agent.attributes["tag.tags"]


def test_responses_api_uses_the_prompt_as_instructions_and_is_charged(store):
    add_budget(store, 100_000)
    client = FakeClient()
    work = uow.UnitOfWork("spat-material-search", uow.WorkContext(user_id=store.user_id), client=client,
                          store=store, prompt=uow.seed_prompt("spat-material-search"))
    work.respond("Máximo de resultados: 3. Solicitud: varilla", tools=[{"type": "openrouter:web_search"}])
    sent = client.responses_requests[0]
    assert sent["instructions"] == runtime.read_prompt_seed("material-search.md")
    assert sent["tools"] == [{"type": "openrouter:web_search"}]
    assert [(row["action"], row["total_tokens"]) for row in ledger(store)] == [("spat-material-search", 60)]


def test_phoenix_reasoning_effort_reaches_both_apis_in_their_own_spelling(store):
    add_budget(store, 100_000)
    client = FakeClient(["ok"])
    tuned = prompt(model="openai/gpt-6.2-sol", parameters={"reasoning_effort": "medium", "max_tokens": 900})
    work = uow.UnitOfWork("spat-study-writer", uow.WorkContext(user_id=store.user_id), client=client,
                          store=store, prompt=tuned)
    work.complete([{"role": "user", "content": "a"}])
    assert client.requests[0]["reasoning_effort"] == "medium" and client.requests[0]["max_tokens"] == 900
    work.respond("b")
    sent = client.responses_requests[0]
    assert sent["reasoning"] == {"effort": "medium"} and sent["max_output_tokens"] == 900
    assert "reasoning_effort" not in sent and "max_tokens" not in sent


def test_tracing_setup_is_a_no_op_without_phoenix(monkeypatch):
    monkeypatch.setattr(telemetry, "_state", {"configured": False, "enabled": False})
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    assert telemetry.setup("test") is False
