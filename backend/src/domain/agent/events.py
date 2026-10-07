"""Progress notifications an agent run publishes for polling.

Events describe what the agent does, with which project data and with what result.
They never carry model reasoning, prompts or secrets.
"""

from enum import StrEnum


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    TOOL_CALLED = "tool.called"
    ARTIFACT_VERSION_CREATED = "artifact.version_created"
    CALCULATION_QUEUED = "calculation.queued"
    CALCULATION_COMPLETED = "calculation.completed"
    CALCULATION_FAILED = "calculation.failed"
    QUESTION_ASKED = "question.asked"
    MESSAGE_RECEIVED = "message.received"
    RUN_WAITING_USER = "run.waiting_user"
    RUN_WAITING_CALCULATION = "run.waiting_calculation"
    RUN_RESUMED = "run.resumed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class EventLevel(StrEnum):
    INFO = "info"
    PROGRESS = "progress"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


# Milestones are mirrored into the conversation as `notification` messages. The final
# answer and questions are already agent messages, and artifact changes get their own
# structured `artifact.updated` message, so they are not mirrored.
MIRRORED = frozenset({
    EventType.PLAN_CREATED,
    EventType.CALCULATION_COMPLETED,
    EventType.CALCULATION_FAILED,
    EventType.RUN_FAILED,
    EventType.RUN_CANCELLED,
})

TITLE_MAX = 200
# `payload.kind` of the chat message that tells the client to reload the artifact.
ARTIFACT_UPDATED = "artifact.updated"
