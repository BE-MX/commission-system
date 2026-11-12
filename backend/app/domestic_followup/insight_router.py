"""客户跟进 AI 建议端点。"""
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import insight_generation, insight_jobs, insight_service
from app.domestic_followup.insight_schemas import InsightAdoptIn, InsightFeedbackIn, InsightRefreshIn, InsightTaskIn

router = APIRouter()
_require_read = require_permission("domestic_followup:read")
_require_write = require_permission("domestic_followup:write")


@contextmanager
def _errors():
    try:
        yield
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/insights")
def get_insights(user_id: int | None = None, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(insight_service.get(db, user, user_id=user_id))


@router.post("/insights/refresh")
def refresh_insights(payload: InsightRefreshIn, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        result = insight_service.refresh(db, user, user_id=payload.user_id)
        db.commit()
    if result["started"]:
        insight_jobs.submit_snapshots(result["snapshot_ids"])
    return ok(result, message="已开始重新生成")


@router.post("/insights/{insight_id}/feedback")
def feedback(insight_id: int, payload: InsightFeedbackIn, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(insight_service.feedback(db, user, insight_id, payload.feedback), message="反馈已记录")


@router.get("/insights/jobs/{snapshot_id}")
def refresh_status(snapshot_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(insight_service.refresh_status(db, user, snapshot_id))


@router.post("/insights/{insight_id}/adopt")
def adopt(insight_id: int, payload: InsightAdoptIn, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(insight_service.adopt(db, user, insight_id, payload.note), message="已标记采纳")


@router.post("/insights/{insight_id}/to-task")
def to_task(insight_id: int, payload: InsightTaskIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors():
        return ok(insight_service.to_task(db, user, insight_id, payload.due_date, payload.content),
                  message="已生成约定跟进")
