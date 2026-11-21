"""Unit of work (UoW): every LLM call of the platform goes through one, named after its application.

    work = UnitOfWork("spat-study-writer", WorkContext(user_id=..., project_id=..., entity="study:42"))
    response = work.complete([{"role": "user", "content": "..."}])

- Configuration from Arize Phoenix: the application id is the name of its prompt. The prompt version tagged
  PHOENIX_PROMPT_TAG supplies the system messages, the model and the sampling parameters; while Phoenix is
  unreachable the checked-in seed (prompts/phoenix/<file>) and OPENROUTER_MODEL are used. A version can be pinned
  with <APPLICATION>_PROMPT_VERSION (e.g. DOCUMENT_EXTRACTOR_PROMPT_VERSION for spat-document-extractor).
  The model of one application can be forced with <APPLICATION>_MODEL (e.g. STUDY_WRITER_MODEL), which wins over
  Phoenix; precedence: <APPLICATION>_MODEL > Phoenix version > OPENROUTER_MODEL.
- Telemetry: each call opens a span named after the application carrying user, project, session and entity;
  units opened inside it (subagents, tools) nest under it and inherit that context.
- Billing: each model response is debited from the user's token budget under the application id.
"""

import logging
import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property, lru_cache
from uuid import uuid4

from src.application.ports.prompt_catalog import PromptSnapshot
from src.infrastructure.agents import llm_provider, runtime, telemetry

logger = logging.getLogger(__name__)

# Application id (Phoenix prompt name) → checked-in seed in prompts/phoenix/.
APPLICATIONS = {
    "spat-agent-orchestrator": "agent-orchestrator.md",
    "spat-agent-grid-designer": "agent-grid-designer.md",
    "spat-agent-soil-modeler": "agent-soil-modeler.md",
    "spat-agent-safety-analyst": "agent-safety-analyst.md",
    "spat-document-extractor": "document-extractor.md",
    "spat-document-consolidator": "document-consolidator.md",
    "spat-study-writer": "study-writer.md",
    "spat-plan-vision": "plan-vision.md",
    "spat-material-assistant": "material-assistant.md",
    "spat-material-search": "material-search.md",
    "spat-material-extractor": "material-extractor.md",
}


@dataclass(frozen=True)
class WorkContext:
    """Who and what a unit of work runs for; inherited by the spans of nested units."""

    user_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None  # groups the traces of one run, job or conversation
    entity: str | None = None  # the object being worked on, e.g. "study:<id>", "upload:<id>"


class BudgetUnavailable(RuntimeError):
    """The user's token budget cannot pay for an LLM call (see Budgets.llm_block)."""

    def __init__(self, block: dict):
        super().__init__(block.get("reason", "budget_unavailable"))
        self.block = block

    @property
    def message(self) -> str:
        if self.block.get("budgets"):
            return (f"No tienes tokens suficientes: quedan {self.block.get('remaining', 0):,} y se necesitan al menos "
                    f"{self.block.get('minimum', 0):,} para usar el asistente.").replace(",", ".")
        return "Tu cuenta no tiene una bolsa de tokens activa para usar el asistente."


def version_variable(application: str) -> str:
    return application.removeprefix("spat-").upper().replace("-", "_") + "_PROMPT_VERSION"


def model_variable(application: str) -> str:
    """<APPLICATION>_MODEL, e.g. STUDY_WRITER_MODEL for spat-study-writer: an OpenRouter id that wins over Phoenix."""
    return application.removeprefix("spat-").upper().replace("-", "_") + "_MODEL"


def load_prompt(application: str, catalog=None) -> PromptSnapshot:
    """The application's prompt from Phoenix, or its checked-in seed when Phoenix is unavailable."""
    try:
        catalog = catalog or runtime.clients()[0]
        return catalog.load(application, tag=os.getenv("PHOENIX_PROMPT_TAG", "production"),
                            version_id=os.getenv(version_variable(application)) or None)
    except Exception:
        logger.warning("Could not load prompt %s from Phoenix; using the checked-in seed", application,
                       exc_info=True)
        return seed_prompt(application)


def seed_prompt(application: str) -> PromptSnapshot:
    return PromptSnapshot(name=application, version="local", messages=[
        {"role": "system", "content": runtime.read_prompt_seed(APPLICATIONS[application])}])


@lru_cache
def _default_store():
    from src.infrastructure.persistence.identity_store import SQLIdentityStore

    return SQLIdentityStore(os.environ["DATABASE_URL"])


def budget_block(user_id: str | None, store=None) -> dict | None:
    """Budgets.llm_block for `user_id`; None when there is no user or no database (offline evaluation)."""
    if not user_id:
        return None
    if store is None:
        if not os.getenv("DATABASE_URL"):
            return None
        store = _default_store()
    try:
        from src.application.use_cases.budgets import Budgets

        return Budgets(store).llm_block(user_id)
    except Exception:
        logger.exception("Could not read the token budget of user %s", user_id)
        return None


@contextmanager
def scope(name: str, context: WorkContext | None = None, **attributes):
    """A parent span grouping several units of work (an agent step, a document ingestion)."""
    context = context or WorkContext()
    with telemetry.span(name, "CHAIN", attributes, session_id=context.session_id, user_id=context.user_id,
                        metadata=_metadata(name, context), tags=[name]) as current:
        yield current


def _metadata(application, context, **extra) -> dict:
    return {key: value for key, value in {"application": application, "project_id": context.project_id,
                                          "entity": context.entity, **extra}.items() if value}


class UnitOfWork:
    def __init__(self, application: str, context: WorkContext | None = None, *, client=None, prompt=None,
                 store=None, charge: bool = True):
        if application not in APPLICATIONS:
            raise ValueError(f"Unknown LLM application {application!r}; register it in uow.APPLICATIONS")
        self.application = application
        self.context = context or WorkContext()
        self._client, self._prompt, self._store, self._charge = client, prompt, store, charge
        self.tokens = {"input": 0, "output": 0, "calls": 0}

    # Configuration (Phoenix) ------------------------------------------------------------------------
    @cached_property
    def prompt(self) -> PromptSnapshot:
        return self._prompt if self._prompt is not None else load_prompt(self.application)

    @property
    def system_messages(self) -> list[dict]:
        return deepcopy(list(self.prompt.messages))

    @property
    def model(self) -> str:
        # Environment (per application) > Phoenix prompt version > OPENROUTER_MODEL.
        return llm_provider.model(os.getenv(model_variable(self.application)),
                                  getattr(self.prompt, "model_name", None))

    @property
    def parameters(self) -> dict:
        return dict(getattr(self.prompt, "parameters", None) or {})

    @property
    def version(self) -> str:
        return str(getattr(self.prompt, "version", "") or "")

    @property
    def client(self):
        return self._client if self._client is not None else runtime.clients()[1]

    @property
    def store(self):
        if self._store is not None:
            return self._store
        return _default_store() if os.getenv("DATABASE_URL") else None

    # Budget -----------------------------------------------------------------------------------------
    def require_capacity(self) -> None:
        """Raise BudgetUnavailable when the user may not start an LLM call (call it before a user action)."""
        block = budget_block(self.context.user_id, self._store)
        if block is not None:
            raise BudgetUnavailable(block)

    def _account(self, response) -> None:
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None) or 0)
        self.tokens["input"] += tokens_in
        self.tokens["output"] += tokens_out
        self.tokens["calls"] += 1
        if not (self._charge and self.context.user_id and tokens_in + tokens_out > 0):
            return
        store = self.store
        if store is None:
            return
        try:
            from src.application.use_cases.budgets import Budgets

            # The provider's response id makes a retried debit of the same response a no-op.
            key = f"{self.application}:{getattr(response, 'id', None) or uuid4()}"
            Budgets(store).consume_llm_usage(
                self.context.user_id, self.context.project_id, self.application, key,
                getattr(response, "model", None) or self.model, tokens_in, tokens_out)
        except Exception:
            logger.exception("Could not debit %s token usage for user %s", self.application, self.context.user_id)

    # Invocation -------------------------------------------------------------------------------------
    def _span(self, kind: str, input_value=None):
        return telemetry.span(
            self.application, kind, {"llm.model_name": self.model},
            session_id=self.context.session_id, user_id=self.context.user_id,
            metadata=_metadata(self.application, self.context, prompt_version=self.version),
            tags=[self.application], input_value=input_value)

    def _call_parameters(self, params: dict) -> dict:
        # Phoenix tunes sampling (temperature, max_tokens, ...); the code keeps structure (response_format, tools).
        return {**params, **self.parameters}

    def complete(self, messages: list[dict], **params):
        """One chat completion; `messages` follow the application's system messages."""
        with self._span("CHAIN", input_value=_last_text(messages)) as current:
            response = self.client.chat.completions.create(
                **self._call_parameters(params), model=self.model, messages=[*self.system_messages, *messages])
            self._account(response)
            choices = getattr(response, "choices", None) or []
            telemetry.set_output(current, getattr(choices[0].message, "content", "") if choices else "")
            return response

    def respond(self, input_text: str, **params):
        """One Responses API call (server-side tools such as openrouter:web_search); the system prompt goes
        as `instructions`."""
        instructions = "\n\n".join(str(message.get("content") or "") for message in self.system_messages
                                   if message.get("role") in {"system", "developer"})
        with self._span("CHAIN", input_value=input_text) as current:
            response = self.client.responses.create(
                **self._call_parameters(params), model=self.model, instructions=instructions or None,
                input=input_text)
            self._account(response)
            telemetry.set_output(current, getattr(response, "output_text", "") or "")
            return response

    def run_tools(self, messages: list[dict], tools, handlers, final_tool, finalize, usage, *, max_rounds=10,
                  max_tokens=None):
        """Bounded tool loop (runtime.run_tool_agent); every handler call is a TOOL span of this unit."""
        conversation = [*self.system_messages, *messages]
        with self._span("AGENT", input_value=_last_text(messages)) as current:
            result = runtime.run_tool_agent(
                self.client, self.model, conversation, tools, _traced(handlers), final_tool, finalize, usage,
                max_rounds=max_rounds, max_tokens=max_tokens, parameters=self.parameters,
                on_response=self._account)
            telemetry.set_output(current, result)
            return result


def _last_text(messages: list[dict]):
    """Text of the last message for the span input; images (base64) are left to the LLM span."""
    if not messages:
        return None
    content = messages[-1].get("content")
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict)) or "[multimodal]"
    return content


def _traced(handlers: dict) -> dict:
    def wrap(name, handler):
        def call(arguments):
            with telemetry.span(name, "TOOL", {"tool.name": name}, input_value=arguments) as current:
                result = handler(arguments)
                telemetry.set_output(current, result)
                return result
        return call

    return {name: wrap(name, handler) for name, handler in handlers.items()}
