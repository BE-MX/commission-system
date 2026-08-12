"""订单经营智能分析 API。"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.order_intelligence import service
from app.order_intelligence.schemas import AiBriefRequest

router = APIRouter()
READ_PERMISSION = "order_intelligence:read"


def _scope(db: Session, user: dict, user_id: str | None, team: str | None):
    return service.resolve_scope(db, user, user_id, team)


@router.get("/filters")
def filters(
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    return ok(service.get_filter_options(db, _scope(db, user, user_id, team)))


@router.get("/overview")
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_overview(db, _scope(db, user, user_id, team), start, end))


@router.get("/countries")
def countries(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_country_analysis(db, _scope(db, user, user_id, team), start, end))


@router.get("/people")
def people(
    dimension: Literal["team", "user"] = Query("user"),
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_people_analysis(db, _scope(db, user, user_id, team), start, end, dimension))


@router.get("/customers")
def customers(
    as_of: date | None = None,
    risk_status: Literal["upcoming", "overdue", "churn_risk"] | None = None,
    country: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    return ok(service.get_customer_actions(
        db, _scope(db, user, user_id, team), as_of or date.today(),
        page, page_size, risk_status, country,
    ))


@router.post("/ai-brief")
def ai_brief(
    body: AiBriefRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    scope = _scope(db, user, body.user_id, body.team)
    try:
        caller_id = int(user.get("sub"))
    except (TypeError, ValueError):
        caller_id = None
    return ok(service.build_ai_brief(
        db, scope, body.date_from, body.date_to, body.focus, caller_id,
    ))
