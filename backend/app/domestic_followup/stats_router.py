"""客户跟进确定性统计端点。"""
from contextlib import contextmanager
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import stats_churn, stats_service

router = APIRouter()
_require_read = require_permission("domestic_followup:read")
_require_read_all = require_permission("domestic_followup:read_all")


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


def _period(range_key: str, date_from: date | None, date_to: date | None) -> dict:
    return {"range_key": range_key, "date_from": date_from, "date_to": date_to}


@router.get("/stats/personal")
def personal(range_key: str = Query("30", alias="range"), date_from: date | None = None,
             date_to: date | None = None, user_id: int | None = Query(None, ge=1),
             db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(stats_service.personal(db, user, **_period(range_key, date_from, date_to), user_id=user_id))


@router.get("/stats/team")
def team(range_key: str = Query("30", alias="range"), date_from: date | None = None,
         date_to: date | None = None, db: Session = Depends(get_db), user=Depends(_require_read_all)):
    with _errors():
        return ok(stats_service.team(db, user, **_period(range_key, date_from, date_to)))


@router.get("/stats/rhythm")
def rhythm(scope: str = Query("personal", pattern="^(personal|team)$"),
           range_key: str = Query("30", alias="range"), date_from: date | None = None,
           date_to: date | None = None, user_id: int | None = Query(None, ge=1),
           db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(stats_service.rhythm(db, user, scope=scope, **_period(range_key, date_from, date_to),
                                       user_id=user_id))


@router.get("/stats/missing-today")
def missing_today(db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(stats_service.missing_today(db, user))


@router.get("/stats/churn-map")
def churn_map(user_id: int | None = Query(None, ge=1), db: Session = Depends(get_db), user=Depends(_require_read)):
    """客户流失态势：当前快照，不随看板时间范围变化。业务员只拿自己的客户明细。"""
    with _errors():
        return ok(stats_churn.churn_map(db, user, user_id=user_id))


@router.get("/stats/drilldown")
def drilldown(kind: str = Query("records", pattern="^(records|overdue|signal|plans)$"),
              user_id: int | None = Query(None, ge=1), date_from: date | None = None,
              date_to: date | None = None, followup_date: date | None = None,
              result_code: str | None = Query(None, max_length=32), obstacle: str | None = Query(None, max_length=32),
              state_change: str | None = Query(None, max_length=64), quality: str | None = Query(None, max_length=32),
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(stats_service.drilldown(
            db, user, kind=kind, user_id=user_id, date_from=date_from, date_to=date_to,
            followup_date=followup_date, result_code=result_code, obstacle=obstacle,
            state_change=state_change, quality=quality, page=page, page_size=page_size,
        ))
