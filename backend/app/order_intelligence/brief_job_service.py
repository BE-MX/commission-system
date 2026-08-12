"""订单经营 AI 简报后台任务服务。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.order_intelligence import service as analysis_service
from app.order_intelligence.models import OrderIntelligenceBriefJob


logger = logging.getLogger("order_intelligence.brief_job")
ACTIVE_STATUSES = ("queued", "running")
STALE_AFTER = timedelta(minutes=30)


class BriefJobNotFoundError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now()


def _active_key(owner_user_id: int) -> str:
    return f"user:{owner_user_id}"


def _scope_snapshot(scope: analysis_service.AnalysisScope) -> dict:
    return {
        "mode": scope.mode,
        "user_id": scope.user_id,
        "team": scope.team,
        "can_read_all": scope.can_read_all,
    }


def _scope_from_snapshot(snapshot: dict) -> analysis_service.AnalysisScope:
    return analysis_service.AnalysisScope(
        mode=snapshot.get("mode") or "self",
        user_id=snapshot.get("user_id") or None,
        team=snapshot.get("team") or None,
        can_read_all=bool(snapshot.get("can_read_all")),
    )


def _expire_stale_jobs(db: Session, owner_user_id: int) -> None:
    cutoff = _now() - STALE_AFTER
    rows = db.query(OrderIntelligenceBriefJob).filter(
        OrderIntelligenceBriefJob.owner_user_id == owner_user_id,
        OrderIntelligenceBriefJob.status.in_(ACTIVE_STATUSES),
        OrderIntelligenceBriefJob.updated_at < cutoff,
    ).with_for_update().all()
    if not rows:
        return
    now = _now()
    for row in rows:
        row.status = "failed"
        row.active_key = None
        row.error_message = "任务运行超过 30 分钟已自动结束，请重新生成"
        row.finished_at = now
        row.updated_at = now
    db.commit()


def get_active_job(db: Session, owner_user_id: int) -> OrderIntelligenceBriefJob | None:
    _expire_stale_jobs(db, owner_user_id)
    return db.query(OrderIntelligenceBriefJob).filter(
        OrderIntelligenceBriefJob.owner_user_id == owner_user_id,
        OrderIntelligenceBriefJob.status.in_(ACTIVE_STATUSES),
    ).order_by(OrderIntelligenceBriefJob.id.desc()).first()


def get_latest_job(db: Session, owner_user_id: int) -> OrderIntelligenceBriefJob | None:
    _expire_stale_jobs(db, owner_user_id)
    return db.query(OrderIntelligenceBriefJob).filter(
        OrderIntelligenceBriefJob.owner_user_id == owner_user_id,
    ).order_by(OrderIntelligenceBriefJob.id.desc()).first()


def get_job(db: Session, owner_user_id: int, job_id: int) -> OrderIntelligenceBriefJob:
    _expire_stale_jobs(db, owner_user_id)
    row = db.query(OrderIntelligenceBriefJob).filter(
        OrderIntelligenceBriefJob.id == job_id,
        OrderIntelligenceBriefJob.owner_user_id == owner_user_id,
    ).first()
    if row is None:
        raise BriefJobNotFoundError("简报任务不存在")
    return row


def prepare_job(
    db: Session,
    owner_user_id: int,
    scope: analysis_service.AnalysisScope,
    date_from,
    date_to,
    focus: str,
) -> tuple[OrderIntelligenceBriefJob, bool]:
    """原子创建用户级活动任务；并发提交命中唯一键时返回已有任务。"""
    active = get_active_job(db, owner_user_id)
    if active is not None:
        return active, False
    row = OrderIntelligenceBriefJob(
        owner_user_id=owner_user_id,
        status="queued",
        active_key=_active_key(owner_user_id),
        date_from=date_from,
        date_to=date_to,
        focus=focus,
        scope_snapshot=_scope_snapshot(scope),
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row, True
    except IntegrityError:
        db.rollback()
        # 另一请求已抢先创建活动任务，返回同一任务作为幂等响应。
        active = get_active_job(db, owner_user_id)
        if active is None:
            raise
        return active, False


def serialize_job(row: OrderIntelligenceBriefJob) -> dict:
    return {
        "job_id": row.id,
        "status": row.status,
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "focus": row.focus,
        "content": row.content or "",
        "source": row.source or "",
        "evidence": row.evidence,
        "error_message": row.error_message or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def execute_job(db: Session, job_id: int) -> None:
    row = db.query(OrderIntelligenceBriefJob).filter(
        OrderIntelligenceBriefJob.id == job_id,
    ).with_for_update().first()
    if row is None or row.status != "queued":
        return
    row.status = "running"
    row.started_at = _now()
    row.updated_at = row.started_at
    db.commit()

    try:
        result = analysis_service.build_ai_brief(
            db=db,
            scope=_scope_from_snapshot(row.scope_snapshot or {}),
            date_from=row.date_from,
            date_to=row.date_to,
            focus=row.focus,
            caller_user_id=row.owner_user_id,
        )
        db.expire_all()
        current = db.query(OrderIntelligenceBriefJob).filter(
            OrderIntelligenceBriefJob.id == job_id,
        ).with_for_update().first()
        # 任务如果已被超时机制终止，迟到结果不得覆盖终态。
        if current is None or current.status != "running":
            db.rollback()
            return
        current.status = "succeeded"
        current.active_key = None
        current.content = result.get("content") or ""
        current.source = result.get("source") or "rules"
        current.evidence = json.loads(json.dumps(result.get("evidence"), default=str))
        current.error_message = None
        current.finished_at = _now()
        current.updated_at = current.finished_at
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.query(OrderIntelligenceBriefJob).filter(
            OrderIntelligenceBriefJob.id == job_id,
            OrderIntelligenceBriefJob.status.in_(ACTIVE_STATUSES),
        ).with_for_update().first()
        if failed is not None:
            failed.status = "failed"
            failed.active_key = None
            failed.error_message = f"简报生成失败：{type(exc).__name__}"
            failed.finished_at = _now()
            failed.updated_at = failed.finished_at
            db.commit()
        logger.exception("order intelligence brief background job failed: id=%s", job_id)
        print(
            f"order intelligence brief background job failed: id={job_id} {type(exc).__name__}",
            flush=True,
        )


def run_job_in_background(job_id: int) -> None:
    """FastAPI 后台任务入口，请求 session 结束后使用独立 Session。"""
    with SessionLocal() as db:
        execute_job(db, job_id)
