"""Pure Agent Run state-transition rules."""

from app.agent_runtime.contracts import RunStatus, TERMINAL_RUN_STATUSES


class InvalidRunTransition(ValueError):
    pass


_ALLOWED = {
    RunStatus.QUEUED: {RunStatus.LEASED, RunStatus.CANCELLED},
    RunStatus.LEASED: {RunStatus.RUNNING, RunStatus.QUEUED, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.WAITING_INPUT,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.AMBIGUOUS,
    },
    RunStatus.WAITING_INPUT: {
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.AMBIGUOUS,
    },
}


def can_transition(current: str | RunStatus, target: str | RunStatus) -> bool:
    source = RunStatus(current)
    destination = RunStatus(target)
    return destination in _ALLOWED.get(source, set())


def require_transition(current: str | RunStatus, target: str | RunStatus) -> None:
    source = RunStatus(current)
    destination = RunStatus(target)
    if source in TERMINAL_RUN_STATUSES:
        raise InvalidRunTransition(f"终态任务不能从 {source.value} 迁移到 {destination.value}")
    if not can_transition(source, destination):
        raise InvalidRunTransition(f"不允许从 {source.value} 迁移到 {destination.value}")

