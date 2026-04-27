"""设计预约 — 状态机"""

from enum import Enum
from typing import Tuple


class RequestStatus(str, Enum):
    pending_audit = "pending_audit"
    pending_design = "pending_design"
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"


class OperatorRole(str, Enum):
    salesperson = "salesperson"
    supervisor = "supervisor"
    design_staff = "design_staff"


# (from_status, action, role) -> to_status
TRANSITIONS: dict[Tuple[RequestStatus, str, OperatorRole], RequestStatus] = {
    # pending_audit
    (RequestStatus.pending_audit, "approve", OperatorRole.supervisor): RequestStatus.pending_design,
    (RequestStatus.pending_audit, "reject", OperatorRole.supervisor): RequestStatus.rejected,
    (RequestStatus.pending_audit, "cancel", OperatorRole.salesperson): RequestStatus.cancelled,
    (RequestStatus.pending_audit, "cancel", OperatorRole.supervisor): RequestStatus.cancelled,
    # pending_design
    (RequestStatus.pending_design, "confirm", OperatorRole.design_staff): RequestStatus.scheduled,
    (RequestStatus.pending_design, "cancel", OperatorRole.salesperson): RequestStatus.cancelled,
    (RequestStatus.pending_design, "cancel", OperatorRole.supervisor): RequestStatus.cancelled,
    (RequestStatus.pending_design, "cancel", OperatorRole.design_staff): RequestStatus.cancelled,
    # scheduled
    (RequestStatus.scheduled, "start", OperatorRole.design_staff): RequestStatus.in_progress,
    (RequestStatus.scheduled, "cancel", OperatorRole.salesperson): RequestStatus.cancelled,
    (RequestStatus.scheduled, "cancel", OperatorRole.supervisor): RequestStatus.cancelled,
    (RequestStatus.scheduled, "cancel", OperatorRole.design_staff): RequestStatus.cancelled,
    # in_progress
    (RequestStatus.in_progress, "complete", OperatorRole.design_staff): RequestStatus.completed,
    (RequestStatus.in_progress, "cancel", OperatorRole.supervisor): RequestStatus.cancelled,
    (RequestStatus.in_progress, "cancel", OperatorRole.design_staff): RequestStatus.cancelled,
}


def transition(current_status: RequestStatus, action: str, role: OperatorRole) -> RequestStatus:
    """执行状态转换，非法操作抛出 ValueError"""
    key = (current_status, action, role)
    if key not in TRANSITIONS:
        raise ValueError(
            f"非法操作：状态 {current_status.value} 下 {role.value} 不能执行 {action}"
        )
    return TRANSITIONS[key]
