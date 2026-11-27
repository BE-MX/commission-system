"""AI 调用日志查询（SQL 聚合 + 提供商/费用状态筛选）"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.ai.models import AiCallLog
from app.core.list_sort import apply_list_sort


def _serialize_log_item(log: AiCallLog) -> dict:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "caller_module": log.caller_module,
        "caller_user_id": log.caller_user_id,
        "preset_id": log.preset_id,
        "preset_name": log.preset_name,
        "provider_id": log.provider_id,
        "provider_type": log.provider_type,
        "model": log.model,
        "tokens_prompt": log.tokens_prompt,
        "tokens_completion": log.tokens_completion,
        "tokens_used": log.tokens_used,
        "duration_ms": log.duration_ms,
        "status": log.status,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "cost_status": log.cost_status,
        "cost_amount": str(Decimal(log.cost_amount).quantize(Decimal("0.000001"))) if log.cost_amount is not None else None,
        "cost_currency": log.cost_currency,
        "error_code": log.error_code,
        "error_message": log.error_message,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


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
    provider_id: Optional[int] = None,
    cost_status: Optional[str] = None,
) -> dict:
    query = db.query(AiCallLog)
    if caller_module:
        query = query.filter(AiCallLog.caller_module == caller_module)
    if preset_id:
        query = query.filter(AiCallLog.preset_id == preset_id)
    if provider_id:
        query = query.filter(AiCallLog.provider_id == provider_id)
    if status:
        query = query.filter(AiCallLog.status == status)
    if cost_status:
        query = query.filter(AiCallLog.cost_status == cost_status)
    if date_from:
        query = query.filter(AiCallLog.created_at >= date_from)
    if date_to:
        query = query.filter(AiCallLog.created_at <= date_to)

    SORT_MAP = {
        "created_at": AiCallLog.created_at,
        "model": AiCallLog.model,
        "tokens_used": AiCallLog.tokens_used,
        "duration_ms": AiCallLog.duration_ms,
        "id": AiCallLog.id,
        "caller_module": AiCallLog.caller_module,
        "provider_type": AiCallLog.provider_type,
        "status": AiCallLog.status,
        "cost_amount": AiCallLog.cost_amount,
    }
    query = apply_list_sort(
        query,
        sort_field,
        sort_order,
        SORT_MAP,
        default=(AiCallLog.created_at.desc(),),
        tie_breakers=(AiCallLog.id.asc(),),
    )

    total = query.count()
    items = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # SQL 聚合替代旧版 .all() 全表拉内存求和
    agg = db.query(
        func.coalesce(func.sum(AiCallLog.tokens_used), 0).label("tokens_total"),
        func.coalesce(func.sum(case((AiCallLog.status == "success", 1), else_=0)), 0).label("success_count"),
        func.coalesce(func.sum(case((AiCallLog.status == "error", 1), else_=0)), 0).label("error_count"),
        func.coalesce(func.sum(case((AiCallLog.status == "timeout", 1), else_=0)), 0).label("timeout_count"),
        func.avg(AiCallLog.duration_ms).label("avg_duration_ms"),
    ).one()

    return {
        "total": total,
        "summary": {
            "tokens_total": int(agg.tokens_total or 0),
            "success_count": int(agg.success_count or 0),
            "error_count": int(agg.error_count or 0),
            "timeout_count": int(agg.timeout_count or 0),
            "avg_duration_ms": round(float(agg.avg_duration_ms)) if agg.avg_duration_ms is not None else 0,
        },
        "items": [_serialize_log_item(item) for item in items],
    }


def get_log(db: Session, log_id: int) -> AiCallLog:
    log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
    if not log:
        raise ValueError("日志不存在")
    return log
