"""Versioned constants shared by Agent control-plane services and adapters."""

from enum import StrEnum


class RuntimeKind(StrEnum):
    DSH = "dsh"
    OPENCLAW = "openclaw"
    NATIVE = "native"


class ProfileMode(StrEnum):
    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"
    SHADOW = "shadow"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"


TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.AMBIGUOUS,
}

ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED,
    RunStatus.LEASED,
    RunStatus.RUNNING,
    RunStatus.WAITING_INPUT,
}


class ActorType(StrEnum):
    USER = "user"
    CONTROL_PLANE = "control_plane"
    RUNTIME = "runtime"
    MODEL = "model"
    TOOL = "tool"


class EventVisibility(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SECRET = "secret"


STANDARD_EVENT_TYPES = {
    "run.created",
    "run.claimed",
    "run.requeued",
    "run.started",
    "model.requested",
    "model.responded",
    "plan.updated",
    "tool.requested",
    "tool.succeeded",
    "tool.failed",
    "artifact.created",
    "artifact.validated",
    "user.feedback",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "run.ambiguous",
}


EVENT_SCHEMA_VERSION = 1
