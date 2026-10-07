"""Grounding design agent: progress polling, ready-message stream, cancellation and memory.

Progress is read by polling `agent-events`. `agent-stream` is a Server-Sent Events
stream that only announces agent messages once they are ready (answer or question) and
closes when the run stops working. Browsers must read it with `fetch`, since
`EventSource` cannot send the bearer token.
"""

import asyncio
import json
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.application.use_cases.agent_runs import AgentRuns, message_order, public_run
from src.domain.agent.run import RunStatus, TERMINAL
from src.infrastructure.entrypoint.api.chat_routes import owned_project
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1", tags=["agent"])
STREAM_POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
# The stream stops when the run no longer produces messages without a new user message.
STREAM_STOP = TERMINAL | {RunStatus.WAITING_USER}


class AgentStateRequest(BaseModel):
    mode: str | None = Field(default=None, pattern="^(consulta|asistido|autonomo)$")
    artifact_id: str | None = Field(default=None, min_length=36, max_length=36)


def runs(request: Request) -> AgentRuns:
    return AgentRuns(request.app.state.services.store)


def _owned_conversation(db, conversation_id, actor):
    conversation = db.one("conversations", id=conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    owned_project(db, conversation["project_id"], actor)
    return conversation


def _owned_run(db, run_id, actor):
    run = db.one("agent_runs", id=run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    owned_project(db, run["project_id"], actor)
    return run


@router.get("/conversations/{conversation_id}/agent-events")
def agent_events(conversation_id: str, request: Request, after: int | None = None, limit: int = 100,
                 actor=Depends(require())):
    if limit < 1 or limit > 500:
        raise HTTPException(422, "limit must be between 1 and 500")
    if after is not None and after < 0:
        raise HTTPException(422, "after must be zero or positive")
    with request.app.state.services.store.transaction() as db:
        _owned_conversation(db, conversation_id, actor)
    return runs(request).events(conversation_id, after, limit)


@router.get("/conversations/{conversation_id}/agent-state")
def get_agent_state(conversation_id: str, request: Request, actor=Depends(require())):
    service = runs(request)
    with request.app.state.services.store.transaction(write=True) as db:
        conversation = _owned_conversation(db, conversation_id, actor)
        return service.ensure_state(db, conversation)


@router.put("/conversations/{conversation_id}/agent-state")
def put_agent_state(conversation_id: str, payload: AgentStateRequest, request: Request,
                    actor=Depends(require("designs:write"))):
    service = runs(request)
    with request.app.state.services.store.transaction(write=True) as db:
        conversation = _owned_conversation(db, conversation_id, actor)
        return service.update_state(db, conversation, mode=payload.mode, artifact_id=payload.artifact_id)


@router.get("/agent-runs/{run_id}")
def get_agent_run(run_id: str, request: Request, actor=Depends(require())):
    with request.app.state.services.store.transaction() as db:
        return public_run(_owned_run(db, run_id, actor))


@router.post("/agent-runs/{run_id}/cancel", status_code=202)
def cancel_agent_run(run_id: str, request: Request, actor=Depends(require())):
    with request.app.state.services.store.transaction() as db:
        _owned_run(db, run_id, actor)
    return runs(request).cancel(run_id)


def _sse(event: str, data: dict, event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/conversations/{conversation_id}/agent-stream")
async def agent_stream(conversation_id: str, request: Request, run_id: str | None = None,
                       wait: int = 300, actor=Depends(require())):
    """Emit `message.ready` for each agent message of the run, then `run.idle` and close.

    Without `run_id` it follows the active run, or the latest one. A `Last-Event-ID`
    header (a message id) skips messages already received. After `wait` seconds the
    stream sends `timeout` and closes; the client reconnects with `Last-Event-ID`.
    """
    if wait < 1 or wait > 300:
        raise HTTPException(422, "wait must be between 1 and 300 seconds")
    store, service = request.app.state.services.store, runs(request)

    def resolve():
        with store.transaction() as db:
            _owned_conversation(db, conversation_id, actor)
            if run_id:
                run = _owned_run(db, run_id, actor)
                if run["conversation_id"] != conversation_id:
                    raise HTTPException(404, "Agent run not found")
                return run
            return service.active_run(db, conversation_id) or service.latest_run(db, conversation_id)

    def snapshot(current_id):
        with store.transaction() as db:
            run = db.one("agent_runs", id=current_id)
            messages = db.many("chat_messages", run_id=current_id, source="agent", limit=None)
        return run, sorted(messages, key=message_order)

    run = await run_in_threadpool(resolve)
    if run is None:
        raise HTTPException(404, "The conversation has no agent runs")
    sent = {request.headers.get("last-event-id")} if request.headers.get("last-event-id") else set()

    async def stream():
        started = last_beat = monotonic()
        skip_until = next(iter(sent), None)
        while True:
            current, messages = await run_in_threadpool(snapshot, run["id"])
            if skip_until and any(m["id"] == skip_until for m in messages):
                for message in messages:
                    sent.add(message["id"])
                    if message["id"] == skip_until:
                        break
                skip_until = None
            for message in messages:
                if message["id"] not in sent:
                    sent.add(message["id"])
                    yield _sse("message.ready", message, message["id"])
            if current["status"] in STREAM_STOP:
                yield _sse("run.idle", {"run_id": current["id"], "status": current["status"]})
                return
            if await request.is_disconnected():
                return
            if monotonic() - started >= wait:
                yield _sse("timeout", {"run_id": current["id"], "status": current["status"]})
                return
            if monotonic() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = monotonic()
                yield ": ping\n\n"
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
