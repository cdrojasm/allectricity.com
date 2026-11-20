"""Traces to Arize Phoenix: OpenTelemetry + OpenInference, configured once per process.

Every OpenAI-client call (OpenRouter) becomes an LLM span automatically; a UnitOfWork adds the parent span with
its application id, the user, the project and the entity. Tracing never breaks a request: without
PHOENIX_ENDPOINT, without the packages (mail worker) or if Phoenix is down, spans are simply not exported.

Variables: PHOENIX_ENDPOINT (or PHOENIX_COLLECTOR_ENDPOINT), PHOENIX_API_KEY, PHOENIX_PROJECT_NAME (default
"terra"), PHOENIX_TRACING=false to switch it off.
"""

import json
import logging
import os
from contextlib import contextmanager, nullcontext
from threading import Lock

logger = logging.getLogger(__name__)
_lock = Lock()
_state = {"configured": False, "enabled": False}
MAX_ATTRIBUTE_CHARS = 4000


def setup(service: str) -> bool:
    """Register the tracer provider and the OpenAI instrumentation; idempotent and failure-proof."""
    with _lock:
        if _state["configured"]:
            return _state["enabled"]
        _state["configured"] = True
        if os.getenv("PHOENIX_TRACING", "true").lower() in {"0", "false", "no"}:
            return False
        endpoint = (os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("PHOENIX_ENDPOINT") or "").strip()
        if not endpoint:
            return False
        from importlib.util import find_spec

        if find_spec("phoenix") is None or find_spec("phoenix.otel") is None:
            return False  # workers without LLM calls (mail/billing) do not install the tracing packages
        try:
            from phoenix.otel import register

            # A private provider: only units of work and the OpenAI (OpenRouter) calls are exported. A global one
            # would also pick up the spans FastAPI emits by itself (every request, health checks included).
            options = {"project_name": os.getenv("PHOENIX_PROJECT_NAME", "terra"),
                       "endpoint": endpoint.rstrip("/") + "/v1/traces", "batch": True,
                       "auto_instrument": True, "set_global_tracer_provider": False}
            if api_key := os.getenv("PHOENIX_API_KEY"):
                options["api_key"] = api_key
            _state["provider"] = register(**options)
            _state["enabled"] = True
            logger.info("Phoenix tracing enabled for %s", service)
        except Exception:
            logger.warning("Phoenix tracing disabled for %s", service, exc_info=True)
        return _state["enabled"]


def flush():
    provider = _state.get("provider")
    if provider is None:
        return
    try:
        provider.force_flush(timeout_millis=5000)
    except Exception:
        logger.debug("Could not flush traces", exc_info=True)


def _tracer():
    from opentelemetry import trace

    provider = _state.get("provider")
    return provider.get_tracer("terra.uow") if provider is not None else trace.get_tracer("terra.uow")


def _clip(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_ATTRIBUTE_CHARS else text[:MAX_ATTRIBUTE_CHARS] + "…"


@contextmanager
def span(name: str, kind: str, attributes: dict | None = None, *, session_id=None, user_id=None,
         metadata: dict | None = None, tags: list[str] | None = None, input_value=None):
    """A span of OpenInference `kind` (CHAIN, AGENT, TOOL) whose context (session, user, metadata, tags) is
    inherited by every span opened inside it, including the instrumented LLM calls."""
    try:
        from openinference.instrumentation import using_attributes
    except ImportError:
        yield None
        return
    context = {key: value for key, value in {
        "session_id": session_id, "user_id": user_id, "metadata": metadata, "tags": tags}.items() if value}
    tracer = _tracer()
    with (using_attributes(**context) if context else nullcontext()):
        values = {"openinference.span.kind": kind, **{k: v for k, v in (attributes or {}).items() if v is not None}}
        if session_id:
            values["session.id"] = session_id
        if user_id:
            values["user.id"] = user_id
        if metadata:
            values["metadata"] = _clip(metadata)
        if tags:
            values["tag.tags"] = list(tags)
        if input_value is not None:
            values["input.value"] = _clip(input_value)
        # start_as_current_span records the exception and marks the span as an error on its own.
        with tracer.start_as_current_span(name, attributes=values) as current:
            yield current


def set_output(current, value):
    if current is not None:
        try:
            current.set_attribute("output.value", _clip(value))
        except Exception:
            logger.debug("Could not record span output", exc_info=True)
