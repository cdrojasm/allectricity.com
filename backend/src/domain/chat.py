"""Domain entities used to refine project artifacts through chat."""

from dataclasses import dataclass
from enum import StrEnum


class MessageSource(StrEnum):
    AGENT = "agent"
    USER = "user"
    NOTIFICATION = "notification"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"


@dataclass(frozen=True)
class Conversation:
    id: str
    project_id: str
    created_by: str
    title: str | None
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    source: MessageSource
    text: str
    type: MessageType
    generated_at: int
    created_at: int
    updated_at: int
    status: str


@dataclass(frozen=True)
class MessageContent:
    id: str
    message_id: str
    format: str
    upload_id: str
    filename: str
    mime_type: str
    created_at: int
