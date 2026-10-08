from time import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from src.application.use_cases.agent_runs import AgentRuns, message_order, now_ms
from src.domain.agent.run import TERMINAL
from src.infrastructure.entrypoint.worker.tasks import enqueue_agent_step, resolve_chat_message
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1", tags=["chat"])


def owned_project(db, project_id, actor):
    project = db.one("projects", id=project_id)
    if not project or (not actor.privileged and project["owner_id"] != actor.user_id):
        raise HTTPException(404, "Project not found")
    return project


def queue_run_step(store, run_id: str) -> None:
    """Enqueue the next agent step after commit; a broker failure closes the run."""
    try:
        enqueue_agent_step(run_id)
    except Exception as exc:
        AgentRuns(store).fail(run_id, f"Unable to queue agent step: {exc}")
        raise HTTPException(503, "Unable to queue the agent") from exc


class ConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ContentRequest(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)


class MessageRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    type: str = Field(default="text", pattern="^(text|image|audio|file)$")
    contents: list[ContentRequest] = Field(default_factory=list, max_length=10)


@router.post("/projects/{project_id}/conversations", status_code=201)
def create_conversation(project_id: str, payload: ConversationRequest, request: Request, actor=Depends(require())):
    now, conversation_id = int(time()), str(uuid4())
    with request.app.state.services.store.transaction(write=True) as db:
        owned_project(db, project_id, actor)
        result = {"id": conversation_id, "project_id": project_id, "created_by": actor.user_id,
                  "title": payload.title, "created_at": now, "updated_at": now}
        db.add("conversations", **result)
    return result


@router.get("/projects/{project_id}/conversations")
def list_conversations(project_id: str, request: Request, actor=Depends(require())):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        return sorted(db.many("conversations", project_id=project_id, limit=500),
                      key=lambda row: (row["updated_at"], row["created_at"], row["id"]), reverse=True)


@router.get("/projects/{project_id}/memory")
def project_memory(project_id: str, request: Request, actor=Depends(require())):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        memory = db.one("project_context_memory", project_id=project_id)
        return memory or {"project_id": project_id, "summary": "", "items": [], "updated_at": None}


@router.get("/projects/{project_id}/files")
def project_files(project_id: str, request: Request, actor=Depends(require())):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        uploads = db.many("file_uploads", project_id=project_id, owner_id=actor.user_id, limit=1000)
        return [{"upload_id": u["id"], "filename": u["filename"], "mime_type": u["expected_mime"],
                 "status": u["status"], "ocr_confidence": u.get("ocr_confidence"),
                 "ocr_needs_review": u.get("ocr_needs_review", False),
                 "attempt_count": u.get("attempt_count", 0), "last_error": u.get("last_error"),
                 "created_at": u["created_at"], "updated_at": u["updated_at"]} for u in uploads]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def create_message(conversation_id: str, payload: MessageRequest, request: Request, actor=Depends(require())):
    """Store a user message and hand it to the grounding design agent."""
    now, message_id = int(time()), str(uuid4())
    store = request.app.state.services.store
    with store.transaction(write=True) as db:
        conversation = db.one("conversations", id=conversation_id)
        if not conversation:
            raise HTTPException(404, "Conversation not found")
        owned_project(db, conversation["project_id"], actor)
        uploads = []
        for ref in payload.contents:
            upload = db.one("file_uploads", id=ref.upload_id, owner_id=actor.user_id,
                            project_id=conversation["project_id"], status="available")
            if not upload:
                raise HTTPException(409, "Attachment must be available in this project")
            uploads.append(upload)
        expected_type = "text" if not uploads else ("image" if all(u["expected_mime"].startswith("image/") for u in uploads) else "file")
        if uploads and payload.type != expected_type:
            raise HTTPException(422, "Message type must match its attachments")
        if not uploads and payload.type != "text":
            raise HTTPException(422, "Image, audio and file messages require uploaded content")
        row = {"id": message_id, "conversation_id": conversation_id, "source": "user", "text": payload.text,
               "type": expected_type, "generated_at": now, "created_at": now, "updated_at": now, "status": "pending",
               "task_id": None, "run_id": None, "created_ms": max(now_ms(), now * 1000)}
        db.add("chat_messages", **row)
        for upload in uploads:
            db.add("message_contents", id=str(uuid4()), message_id=message_id,
                   format="image" if upload["expected_mime"].startswith("image/") else "file",
                   upload_id=upload["id"], filename=upload["filename"], mime_type=upload["expected_mime"], created_at=now)
        db.change("conversations", conversation_id, updated_at=now)
        contents = db.many("message_contents", message_id=message_id)
        run, dispatch = AgentRuns(store).submit_message(db, conversation, message_id, actor.user_id)
        row["run_id"] = run["id"]
    # Dispatch only after the database transaction has committed.
    if dispatch:
        queue_run_step(store, run["id"])
    return {**row, "contents": contents}


def _authorized_messages(conversation_id, request, actor):
    with request.app.state.services.store.transaction() as db:
        conversation = db.one("conversations", id=conversation_id)
        if not conversation:
            raise HTTPException(404, "Conversation not found")
        owned_project(db, conversation["project_id"], actor)
        messages = db.many("chat_messages", conversation_id=conversation_id, limit=5000)
        for message in messages:
            message["contents"] = db.many("message_contents", message_id=message["id"])
        return sorted(messages, key=message_order)


@router.get("/conversations/{conversation_id}/messages/first")
def first_messages(conversation_id: str, request: Request, limit: int = 50, actor=Depends(require())):
    if limit < 1 or limit > 100:
        raise HTTPException(422, "limit must be between 1 and 100")
    messages = _authorized_messages(conversation_id, request, actor)
    return messages[-limit:]


@router.get("/conversations/{conversation_id}/messages/cursor")
def cursor_messages(conversation_id: str, request: Request, before: str, limit: int = 30, actor=Depends(require())):
    if limit < 1 or limit > 100:
        raise HTTPException(422, "limit must be between 1 and 100")
    messages = _authorized_messages(conversation_id, request, actor)
    cursor = next((m for m in messages if m["id"] == before), None)
    if cursor is None:
        raise HTTPException(404, "Message cursor not found")
    older = [m for m in messages if message_order(m) < message_order(cursor)]
    return older[-limit:]


@router.get("/conversations/{conversation_id}/messages/since")
def messages_since(conversation_id: str, request: Request, after: str, limit: int = 100, actor=Depends(require())):
    """Messages newer than the `after` message, oldest first, for incremental polling."""
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    with request.app.state.services.store.transaction() as db:
        conversation = db.one("conversations", id=conversation_id)
        if not conversation:
            raise HTTPException(404, "Conversation not found")
        owned_project(db, conversation["project_id"], actor)
        cursor = db.one("chat_messages", id=after, conversation_id=conversation_id)
        if cursor is None:
            raise HTTPException(404, "Message cursor not found")
        # created_at has one-second resolution: fetch from the cursor's second and order precisely.
        candidates = db.ordered("chat_messages", "created_at", after=cursor["created_at"] - 1,
                                conversation_id=conversation_id)
        newer = sorted((m for m in candidates if message_order(m) > message_order(cursor)), key=message_order)[:limit]
        for message in newer:
            message["contents"] = db.many("message_contents", message_id=message["id"])
        return newer


@router.post("/messages/{message_id}/cancel", status_code=202)
def cancel_message(message_id: str, request: Request, actor=Depends(require())):
    """Cancel the agent run handling this message (legacy messages revoke their task)."""
    store = request.app.state.services.store
    with store.transaction() as db:
        message = db.one("chat_messages", id=message_id)
        if not message:
            raise HTTPException(404, "Message not found")
        conversation = db.one("conversations", id=message["conversation_id"])
        owned_project(db, conversation["project_id"], actor)
        run = db.one("agent_runs", id=message["run_id"]) if message.get("run_id") else None
        task_id = message["task_id"]
    if run is not None:
        if run["status"] in TERMINAL:
            return {"message_id": message_id, "status": message["status"], "cancelled": False}
        cancelled = AgentRuns(store).cancel(run["id"])
        return {"message_id": message_id, "status": message["status"], "cancelled": True,
                "run": cancelled}
    if message["status"] == "completed":
        return {"message_id": message_id, "status": message["status"], "cancelled": False}
    if task_id:
        resolve_chat_message.app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    return {"message_id": message_id, "status": message["status"], "cancelled": bool(task_id)}
