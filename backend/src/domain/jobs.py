"""Lifecycle of a background job: a slow request (LLM call, PDF rasterizing, numeric fit) the API
accepts with 202 and a worker finishes, so no API thread waits on it.

A job only moves forward. A late writer (a redelivered task, a stale reaper) can never overwrite a
terminal state, because each change is a compare-and-set from the allowed previous states.
"""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})
ACTIVE = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
}


class InvalidJobTransition(ValueError):
    def __init__(self, current: str, target: str):
        super().__init__(f"Job cannot go from {current} to {target}")
        self.current, self.target = current, target


def transition(current: str, target: str) -> JobStatus:
    current, target = JobStatus(current), JobStatus(target)
    if target not in TRANSITIONS[current]:
        raise InvalidJobTransition(current, target)
    return target


def sources(target: str) -> frozenset[JobStatus]:
    """States a job may be in for a change to `target` to be valid."""
    target = JobStatus(target)
    return frozenset(state for state, nexts in TRANSITIONS.items() if target in nexts)


class JobKind(StrEnum):
    MATERIAL_ASSISTANT = "material_assistant"
    STUDY_SECTION = "study_section"
    PLAN_PROPOSAL = "plan_proposal"
    PLAN_REVISION = "plan_revision"
    SOIL_FIT = "soil_fit"
    SOIL_FILE_FIT = "soil_file_fit"


# Each kind runs on the worker that has its dependencies (LLM client, pypdfium2/openpyxl, nothing extra).
QUEUES = {
    JobKind.MATERIAL_ASSISTANT: "agent",
    JobKind.STUDY_SECTION: "agent",
    JobKind.PLAN_PROPOSAL: "documents",
    JobKind.PLAN_REVISION: "documents",
    JobKind.SOIL_FIT: "calculations",
    JobKind.SOIL_FILE_FIT: "documents",
}

# A job not finished after this many seconds is considered lost (worker crash, broker loss).
STALE_AFTER_S = {JobStatus.QUEUED: 600, JobStatus.RUNNING: 300}


def poll_after_ms(status: str) -> int | None:
    return 1000 if status in ACTIVE else None
