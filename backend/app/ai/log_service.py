"""AI 调用日志查询"""

from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiCallLog


def list_logs(
    db: Session,
    caller_module: Optional[str] = None,
    preset_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    sort_field: str = "created_at",
    sort_order: str = "desc",
) -> dict:
    from sqlalchemy import desc as _desc
    query = db.query(AiCallLog)
    if caller_module:
        query = query.filter(AiCallLog.caller_module == caller_module)
    if preset_id:
        query = query.filter(AiCallLog.preset_id == preset_id)
    if status:
        query = query.filter(AiCallLog.status == status)
    if date_from:
        query = query.filter(AiCallLog.created_at >= date_from)
    if date_to:
        query = query.filter(AiCallLog.created_at <= date_to)

    SORT_MAP = {
        "created_at": AiCallLog.created_at,
        "model": AiCallLog.model,
        "tokens_used": AiCallLog.tokens_used,
        "duration_ms": AiCallLog.duration_ms,
    }
    sort_col = SORT_MAP.get(sort_field, AiCallLog.created_at)
    order_fn = _desc if sort_order == "desc" else lambda c: c

    total = query.count()
    items = (
        query.order_by(order_fn(sort_col))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    summary = {
        "tokens_total": (
            db.query(AiCallLog)
            .filter(AiCallLog.tokens_used.isnot(None))
            .with_entities(AiCallLog.tokens_used)
            .all()
        ),
        "success_count": db.query(AiCallLog).filter(AiCallLog.status == "success").count(),
        "error_count": db.query(AiCallLog).filter(AiCallLog.status == "error").count(),
        "timeout_count": db.query(AiCallLog).filter(AiCallLog.status == "timeout").count(),
    }
    tokens_total = sum(x[0] for x in summary["tokens_total"] if x[0] is not None)
    avg_q = (
        db.query(AiCallLog)
        .filter(AiCallLog.duration_ms.isnot(None))
        .with_entities(AiCallLog.duration_ms)
        .all()
    )
    avg_duration = (
        round(sum(x[0] for x in avg_q) / len(avg_q)) if avg_q else 0
    )

    return {
        "total": total,
        "summary": {
            "tokens_total": tokens_total,
            "success_count": summary["success_count"],
            "error_count": summary["error_count"],
            "timeout_count": summary["timeout_count"],
            "avg_duration_ms": avg_duration,
        },
        "items": items,
    }


def get_log(db: Session, log_id: int) -> AiCallLog:
    log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
    if not log:
        raise ValueError("日志不存在")
    return log
