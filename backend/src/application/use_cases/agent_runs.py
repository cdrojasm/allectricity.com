"""Lifecycle of grounding design agent runs: chat trigger, events, cancellation, steps.

The store is the transactional record store used across the backend (`one`, `many`,
`ordered`, `add`, `change`). Write transactions are serialized by the store, which keeps
the per-conversation event sequence dense and the single-active-run rule race free.
"""

from dataclasses import dataclass
import re
from time import time
from uuid import uuid4

from src.domain.agent.events import ARTIFACT_UPDATED, MIRRORED, TITLE_MAX, EventLevel, EventType
from src.domain.agent.run import (
    ACTIVE, DEFAULT_MODE, RUNNABLE, TERMINAL, AgentMode, InvalidTransition, RunStatus,
    cancellation_target, poll_after_ms, transition,
)
from src.domain.identity import ServiceError

UNAVAILABLE_TEXT = ("Recibí tu solicitud, pero el agente de diseño todavía no está disponible "
                    "en este entorno. Tus mensajes quedan guardados en la conversación.")
FAILED_TEXT = "No pude completar la solicitud por un error interno. Puedes intentarlo de nuevo."
RUN_FIELDS = ("id", "conversation_id", "status", "mode", "artifact_id", "base_version",
              "current_step", "plan", "pending_question", "error", "created_at", "updated_at",
              "finished_at")


def message_order(message: dict) -> tuple:
    """Chat order: seconds, then milliseconds (messages of one run share a second), then id."""
    return message["created_at"], message.get("created_ms") or 0, message["id"]


def now_ms() -> int:
    return int(time() * 1000)


def public_run(run: dict | None) -> dict | None:
    return {field: run[field] for field in RUN_FIELDS} if run else None


@dataclass(frozen=True)
class StepOutcome:
    """What a worker step ends with: an answer, a message that waits for the user, or a
    message that waits for the potential calculation `calculation_id` (queued by the step)."""
    text: str
    wait_for_user: bool = False
    calculation_id: str | None = None


class AgentRuns:
    def __init__(self, store, clock=time):
        self.store = store
        self.clock = clock

    def now(self) -> int:
        return int(self.clock())

    # Conversation memory -------------------------------------------------------------

    def ensure_state(self, db, conversation: dict) -> dict:
        state = db.one("agent_conversation_state", id=conversation["id"])
        if state:
            return state
        return db.add("agent_conversation_state", id=conversation["id"],
                      project_id=conversation["project_id"], artifact_id=None,
                      mode=DEFAULT_MODE.value, summary="", assumptions=[], open_questions=[],
                      decisions=[], last_event_seq=0, updated_at=self.now())

    def update_state(self, db, conversation: dict, *, mode: str | None = None,
                     artifact_id: str | None = None) -> dict:
        state = self.ensure_state(db, conversation)
        changes = {}
        if mode is not None:
            changes["mode"] = AgentMode(mode).value
        if artifact_id is not None and artifact_id != state["artifact_id"]:
            if self.active_run(db, conversation["id"]):
                raise ServiceError(409, "Cannot change the artifact while the agent is working")
            if not db.designs.exists(conversation["project_id"], artifact_id):
                raise ServiceError(404, "Artifact not found")
            changes["artifact_id"] = artifact_id
        if changes:
            changes["updated_at"] = self.now()
            db.change("agent_conversation_state", conversation["id"], **changes)
            state = {**state, **changes}
        return state

    # Runs and events ------------------------------------------------------------------

    def active_run(self, db, conversation_id: str) -> dict | None:
        runs = db.many("agent_runs", conversation_id=conversation_id, limit=None)
        return next((run for run in runs if run["status"] in ACTIVE), None)

    def latest_run(self, db, conversation_id: str) -> dict | None:
        runs = db.many("agent_runs", conversation_id=conversation_id, limit=None)
        return max(runs, key=lambda run: (run["created_at"], run["id"]), default=None)

    def submit_message(self, db, conversation: dict, message_id: str, actor_id: str) -> tuple[dict, bool]:
        """Attach a new user message to the agent. Returns (run, step must be queued).

        Without an active run a new one starts. A run waiting for the user resumes. A
        working run receives the message in its inbox and reads it at its next checkpoint.
        """
        state = self.ensure_state(db, conversation)
        now = self.now()
        message = db.one("chat_messages", id=message_id)
        optimize_request = bool(
            state["mode"] == AgentMode.AUTONOMO.value
            and re.search(r"optimiza el diseño hasta que cumpla", (message or {}).get("text", ""), re.IGNORECASE)
        )
        run = self.active_run(db, conversation["id"])
        if run is None:
            artifact_id = state["artifact_id"]
            pending_calculation_id = None
            if optimize_request and artifact_id:
                latest_artifact = db.designs.latest(conversation["project_id"], artifact_id)
                if latest_artifact:
                    completed = [row for row in db.many(
                        "calculos_potencial_tierras", project_id=conversation["project_id"],
                        artifact_id=artifact_id, artifact_version=latest_artifact["version"], limit=1000,
                    ) if row["status"] == "completed"]
                    if completed:
                        pending_calculation_id = max(completed, key=lambda row: (row["updated_at"], row["id"]))["id"]
            run = db.add("agent_runs", id=str(uuid4()), conversation_id=conversation["id"],
                         project_id=conversation["project_id"], trigger_message_id=message_id,
                         artifact_id=artifact_id, base_version=None, mode=state["mode"],
                         status=RunStatus.QUEUED.value, plan=[], current_step=None,
                         draft_snapshot=None, pending_calculation_id=pending_calculation_id, pending_question=None,
                         inbox=[], usage={"steps": 0}, error=None, created_by=actor_id,
                         created_at=now, updated_at=now, finished_at=None)
            db.change("chat_messages", message_id, run_id=run["id"])
            return run, True
        changes = {"inbox": [*run["inbox"], message_id], "updated_at": now}
        resume = run["status"] == RunStatus.WAITING_USER
        if resume:
            changes["status"] = transition(run["status"], RunStatus.QUEUED).value
            changes["pending_question"] = None
        db.change("agent_runs", run["id"], **changes)
        db.change("chat_messages", message_id, run_id=run["id"])
        run = {**run, **changes}
        self.emit(db, run, EventType.MESSAGE_RECEIVED, "Mensaje recibido; lo tendré en cuenta",
                  payload={"message_id": message_id})
        return run, resume

    def emit(self, db, run: dict, event_type: EventType, title: str, *,
             level: EventLevel = EventLevel.INFO, detail: str | None = None,
             payload: dict | None = None) -> dict:
        state = db.one("agent_conversation_state", id=run["conversation_id"])
        seq = state["last_event_seq"] + 1
        now = self.now()
        db.change("agent_conversation_state", state["id"], last_event_seq=seq)
        event = db.add("agent_events", id=str(uuid4()), conversation_id=run["conversation_id"],
                       run_id=run["id"], seq=seq, type=EventType(event_type).value,
                       level=EventLevel(level).value, title=title[:TITLE_MAX], detail=detail,
                       payload=payload or {}, created_at=now)
        if event_type in MIRRORED:
            self._post(db, run, "notification", title if not detail else f"{title}\n{detail}")
        return event

    def events(self, conversation_id: str, after: int | None, limit: int) -> dict:
        with self.store.transaction() as db:
            state = db.one("agent_conversation_state", id=conversation_id)
            last = state["last_event_seq"] if state else 0
            start = max(0, last - limit) if after is None else after
            events = db.ordered("agent_events", "seq", after=start, limit=limit,
                                conversation_id=conversation_id)
            run = self.active_run(db, conversation_id)
        return {"events": events, "next_after": events[-1]["seq"] if events else start,
                "active_run": public_run(run),
                "poll_after_ms": poll_after_ms(run["status"] if run else None)}

    def cancel(self, run_id: str) -> dict:
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run:
                raise ServiceError(404, "Agent run not found")
            try:
                target = cancellation_target(run["status"])
            except InvalidTransition as exc:
                raise ServiceError(409, f"Agent run is already {run['status']}") from exc
            if target == RunStatus.CANCELLED:
                return public_run(self._finish_cancelled(db, run))
            if run["status"] != RunStatus.CANCELLING:
                run = self._change(db, run, status=RunStatus.CANCELLING.value)
            return public_run(run)

    # Worker steps ------------------------------------------------------------------

    def begin_step(self, run_id: str) -> dict | None:
        """Claim a run for a worker step; None when there is nothing to do."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run:
                return None
            if run["status"] == RunStatus.CANCELLING:
                self._finish_cancelled(db, run)
                return None
            if run["status"] not in RUNNABLE:
                return None
            first = run["usage"].get("steps", 0) == 0
            changes = {"usage": {**run["usage"], "steps": run["usage"].get("steps", 0) + 1}}
            if run["status"] == RunStatus.QUEUED:
                changes["status"] = transition(run["status"], RunStatus.RUNNING).value
            run = self._change(db, run, **changes)
            self._set_messages(db, run, "processing", only={"pending"})
            if first:
                self.emit(db, run, EventType.RUN_STARTED, "Empecé a trabajar en tu solicitud",
                          level=EventLevel.PROGRESS)
            else:
                self.emit(db, run, EventType.RUN_RESUMED, "Retomé el trabajo", level=EventLevel.PROGRESS)
            return run

    def complete(self, run_id: str, text: str) -> dict | None:
        """Post the final answer and close the run (or honour a pending cancellation)."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run or run["status"] in TERMINAL:
                return None
            if run["status"] == RunStatus.CANCELLING:
                return self._finish_cancelled(db, run)
            message = self._post(db, run, "agent", text)
            self._set_messages(db, run, "completed", only={"pending", "processing"})
            run = self._change(db, run, status=transition(run["status"], RunStatus.COMPLETED).value,
                               pending_calculation_id=None, finished_at=self.now())
            self.emit(db, run, EventType.RUN_COMPLETED, "Terminé", level=EventLevel.SUCCESS,
                      payload={"message_id": message["id"]})
            return run

    def fail(self, run_id: str, error: str) -> dict | None:
        """Close a run after an unrecoverable error; `error` is never shown to the user."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run or run["status"] in TERMINAL:
                return None
            if run["status"] == RunStatus.CANCELLING:
                return self._finish_cancelled(db, run)
            self._post(db, run, "agent", FAILED_TEXT)
            self._set_messages(db, run, "failed", only={"pending", "processing"})
            run = self._change(db, run, status=transition(run["status"], RunStatus.FAILED).value,
                               error=error[:4000], finished_at=self.now())
            self.emit(db, run, EventType.RUN_FAILED, "No pude completar la solicitud", level=EventLevel.ERROR)
            return run

    def await_user(self, run_id: str, text: str) -> dict | None:
        """Post a question and suspend until the user replies."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run or run["status"] in TERMINAL:
                return None
            if run["status"] == RunStatus.CANCELLING:
                return self._finish_cancelled(db, run)
            message = self._post(db, run, "agent", text)
            self._set_messages(db, run, "completed", only={"pending", "processing"})
            self.emit(db, run, EventType.QUESTION_ASKED, "Necesito información para continuar",
                      payload={"message_id": message["id"]})
            run = self._change(db, run, status=transition(run["status"], RunStatus.WAITING_USER).value,
                               pending_question={"kind": "question", "message_id": message["id"]}, inbox=[],
                               pending_calculation_id=None)
            self.emit(db, run, EventType.RUN_WAITING_USER, "Esperando tu respuesta",
                      payload={"message_id": message["id"]})
            return run

    def await_calculation(self, run_id: str, text: str, calculation_id: str) -> dict | None:
        """Post the step's message and suspend until the calculation finishes (no worker is held)."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run or run["status"] in TERMINAL:
                return None
            if run["status"] == RunStatus.CANCELLING:
                run = self._change(db, run, pending_calculation_id=calculation_id)
                return self._finish_cancelled(db, run)
            self._post(db, run, "agent", text)
            self._set_messages(db, run, "completed", only={"pending", "processing"})
            run = self._change(db, run, status=transition(run["status"], RunStatus.WAITING_CALCULATION).value,
                               pending_calculation_id=calculation_id, inbox=[])
            self.emit(db, run, EventType.RUN_WAITING_CALCULATION, "Calculando la seguridad de la malla",
                      level=EventLevel.PROGRESS, payload={"calculation_id": calculation_id})
            return run

    def calculation_finished(self, calculation_id: str) -> str | None:
        """Called by the calculation worker: resume the run waiting for it. Returns its id."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", pending_calculation_id=calculation_id, status=RunStatus.WAITING_CALCULATION.value)
            calculation = db.one("calculos_potencial_tierras", id=calculation_id)
            if not run or not calculation or calculation["status"] in {"pending", "running"}:
                return None
            if calculation["status"] == "completed":
                self.emit(db, run, EventType.CALCULATION_COMPLETED, "Cálculo de seguridad terminado",
                          level=EventLevel.SUCCESS, payload={"calculation_id": calculation_id})
            else:
                self.emit(db, run, EventType.CALCULATION_FAILED, "El cálculo de seguridad no se completó",
                          level=EventLevel.ERROR, detail=calculation.get("error"),
                          payload={"calculation_id": calculation_id, "status": calculation["status"]})
            self._change(db, run, status=transition(run["status"], RunStatus.QUEUED).value)
            return run["id"]

    def save_workspace(self, run_id: str, **changes) -> None:
        """Persist draft-related fields (`draft_snapshot`, `base_version`, `artifact_id`...)."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if run and run["status"] not in TERMINAL:
                self._change(db, run, **changes)

    def apply_changes(self, run_id: str, change: dict) -> dict:
        """Create the artifact version for a validated change set and announce it.

        `change`: summary, artifact_id (None creates the artifact), base_version, snapshot,
        provenance, diff, unconfirmed_critical, missing_for_calculation. The structured
        `artifact.updated` message tells the client to reload the artifact.
        """
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            snapshot = change["snapshot"]
            origin = {"kind": "agent", "run_id": run_id, "summary": change["summary"],
                      "provenance": change["provenance"], "draft": change.get("draft", False),
                      "draft_watermark": change.get("draft_watermark")}
            if change.get("restored_from") is not None:
                origin["restored_from"] = change["restored_from"]
            if change.get("artifact_id"):
                row = db.designs.append_version(run["project_id"], change["artifact_id"], snapshot["name"], snapshot,
                                                run["created_by"], origin, expected_version=change["base_version"])
            else:
                row = db.designs.create(run["project_id"], snapshot["name"], snapshot, run["created_by"], origin)
            conversation = db.one("conversations", id=run["conversation_id"])
            self.ensure_state(db, conversation)
            db.change("agent_conversation_state", run["conversation_id"], artifact_id=row["artifact_id"],
                      updated_at=self.now())
            run = self._change(db, run, artifact_id=row["artifact_id"], base_version=row["version"],
                               draft_snapshot=None)
            payload = {"kind": ARTIFACT_UPDATED, "artifact_id": row["artifact_id"], "version": row["version"],
                       "previous_version": change.get("base_version"), "name": row["name"],
                       "summary": change["summary"], "changes": change["diff"],
                       "unconfirmed_critical": change["unconfirmed_critical"],
                       "missing_for_calculation": change["missing_for_calculation"],
                       "draft": change.get("draft", False),
                       "draft_watermark": change.get("draft_watermark")}
            created = "Se creó" if change.get("base_version") is None else "Se editó"
            self._post(db, run, "notification", f"{created} el artefacto «{row['name']}» (versión {row['version']}): "
                       f"{change['summary']}", payload=payload)
            self.emit(db, run, EventType.ARTIFACT_VERSION_CREATED, f"Versión {row['version']} de «{row['name']}»",
                      level=EventLevel.SUCCESS, payload={"artifact_id": row["artifact_id"], "version": row["version"]})
            return row

    def progress(self, run_id: str, event_type: EventType, title: str, **kwargs) -> None:
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if run and run["status"] not in TERMINAL:
                self.emit(db, run, event_type, title, **kwargs)

    def add_usage(self, run_id: str, usage: dict) -> None:
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run:
                return
            total = dict(run["usage"])
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total[key] = total.get(key, 0) + value
            self._change(db, run, usage=total)

    def set_usage_fields(self, run_id: str, **fields) -> None:
        """Persist structured per-run state alongside numeric usage totals."""
        with self.store.transaction(write=True) as db:
            run = db.one("agent_runs", id=run_id)
            if not run:
                return
            usage = {**(run.get("usage") or {}), **fields}
            self._change(db, run, usage=usage)

    def cancelling(self, run_id: str) -> bool:
        with self.store.transaction() as db:
            run = db.one("agent_runs", id=run_id)
        return not run or run["status"] in TERMINAL | {RunStatus.CANCELLING}

    # Helpers --------------------------------------------------------------------------

    def _change(self, db, run: dict, **changes) -> dict:
        changes["updated_at"] = self.now()
        db.change("agent_runs", run["id"], **changes)
        return {**run, **changes}

    def _post(self, db, run: dict, source: str, text: str, payload: dict | None = None) -> dict:
        now = self.now()
        message = db.add("chat_messages", id=str(uuid4()), conversation_id=run["conversation_id"],
                         source=source, text=text, type="text", generated_at=now, created_at=now,
                         updated_at=now, status="completed", task_id=None, run_id=run["id"], payload=payload,
                         created_ms=max(now_ms(), now * 1000))
        db.change("conversations", run["conversation_id"], updated_at=now)
        return message

    def _set_messages(self, db, run: dict, status: str, *, only: set[str]) -> None:
        now = self.now()
        for message_id in [run["trigger_message_id"], *run["inbox"]]:
            message = db.one("chat_messages", id=message_id)
            if message and message["status"] in only:
                db.change("chat_messages", message_id, status=status, updated_at=now)

    def _finish_cancelled(self, db, run: dict) -> dict:
        calculation_id = run.get("pending_calculation_id")
        if calculation_id:
            calculation = db.one("calculos_potencial_tierras", id=calculation_id)
            if calculation and calculation["status"] in {"pending", "running"}:
                db.change("calculos_potencial_tierras", calculation_id, status="cancelled",
                          updated_at=self.now())
        self._set_messages(db, run, "cancelled", only={"pending", "processing"})
        run = self._change(db, run, status=transition(run["status"], RunStatus.CANCELLED).value,
                           pending_question=None, finished_at=self.now())
        self.emit(db, run, EventType.RUN_CANCELLED, "Solicitud cancelada", level=EventLevel.WARNING)
        return run


def run_step(store, run_id: str, agent=None, dispatch_calculation=None) -> None:
    """One worker step. `agent(run, runs)` returns a StepOutcome (or the answer text);
    None means the agent is not available in this environment. `dispatch_calculation(id)`
    queues the calculation worker, only after the run is suspended so it cannot be missed."""
    runs = AgentRuns(store)
    run = runs.begin_step(run_id)
    if run is None:
        return
    try:
        outcome = StepOutcome(UNAVAILABLE_TEXT) if agent is None else agent(run, runs)
    except Exception as exc:
        runs.fail(run_id, f"{type(exc).__name__}: {exc}")
        raise
    if isinstance(outcome, str):
        outcome = StepOutcome(outcome)
    if outcome.calculation_id:
        if runs.await_calculation(run_id, outcome.text, outcome.calculation_id) is None:
            return
        try:
            dispatch_calculation(outcome.calculation_id)
        except Exception as exc:
            from src.application.use_cases.potential_calculations import mark_dispatch_failed

            mark_dispatch_failed(store, outcome.calculation_id)
            if runs.calculation_finished(outcome.calculation_id):
                runs.fail(run_id, f"Unable to queue the calculation: {exc}")
    elif outcome.wait_for_user:
        runs.await_user(run_id, outcome.text)
    else:
        runs.complete(run_id, outcome.text)
