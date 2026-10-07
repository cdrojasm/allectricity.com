"""Lifecycle of one agent run, triggered by a chat message.

A run never blocks a worker while it waits: waiting for a calculation or for the user
only leaves it suspended in the database until something enqueues its next step.
"""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_CALCULATION = "waiting_calculation"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMode(StrEnum):
    CONSULTA = "consulta"
    ASISTIDO = "asistido"
    AUTONOMO = "autonomo"


DEFAULT_MODE = AgentMode.ASISTIDO
TERMINAL = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
ACTIVE = frozenset(RunStatus) - TERMINAL
# A worker step may only start from these states.
RUNNABLE = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})

TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.WAITING_USER, RunStatus.WAITING_CALCULATION, RunStatus.CANCELLING,
                        RunStatus.COMPLETED, RunStatus.FAILED},
    RunStatus.WAITING_USER: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.WAITING_CALCULATION: {RunStatus.QUEUED, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.CANCELLING: {RunStatus.CANCELLED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class InvalidTransition(ValueError):
    def __init__(self, current: str, target: str):
        super().__init__(f"Agent run cannot go from {current} to {target}")
        self.current, self.target = current, target


def transition(current: str, target: str) -> RunStatus:
    """Validate a status change and return the target status."""
    current, target = RunStatus(current), RunStatus(target)
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(current, target)
    return target


def cancellation_target(current: str) -> RunStatus:
    """A running step finishes its current work first; suspended runs stop at once."""
    current = RunStatus(current)
    if current in TERMINAL:
        raise InvalidTransition(current, RunStatus.CANCELLED)
    if current == RunStatus.CANCELLING:
        return RunStatus.CANCELLING
    return RunStatus.CANCELLING if current == RunStatus.RUNNING else RunStatus.CANCELLED


def poll_after_ms(status: str | None) -> int | None:
    """Suggested polling interval for the client; None means stop polling."""
    if status in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING}:
        return 1500
    if status == RunStatus.WAITING_CALCULATION:
        return 5000
    return None
