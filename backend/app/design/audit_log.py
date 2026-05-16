"""设计预约 — 审计日志写入共享 helper

被 request_service / schedule_service / import_service 复用。
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.design.models import DesignAuditLog


def write_audit_log(
    db: Session,
    *,
    request_id: int,
    task_id: Optional[int] = None,
    operator_id: int,
    operator_name: str,
    operator_role: str,
    action: str,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    comment: Optional[str] = None,
    snapshot: Optional[dict] = None,
):
    """写入设计预约审计日志 (不提交,由调用方 commit)"""
    log = DesignAuditLog(
        request_id=request_id,
        task_id=task_id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role=operator_role,
        action=action,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        snapshot=snapshot,
    )
    db.add(log)
