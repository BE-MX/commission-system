"""订单经营智能分析 API。"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.order_intelligence import brief_job_service, service
from app.order_intelligence.filtering import AnalysisFilters
from app.order_intelligence.schemas import AiBriefRequest

router = APIRouter()
READ_PERMISSION = "order_intelligence:read"


def _scope(db: Session, user: dict, user_id: str | None, team: str | None):
    return service.resolve_scope(db, user, user_id, team)


def _user_id(user: dict) -> int:
    try:
        value = int(user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
    if value <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误")
    return value


def _analysis_filters(
    countries: list[str] | None = Query(None),
    models: list[str] | None = Query(None),
    colors: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
) -> AnalysisFilters:
    try:
        return AnalysisFilters.build(countries, models, colors, sources)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/filters")
def filters(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_filter_options(db, _scope(db, user, user_id, team), start, end))


@router.get("/overview")
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    analysis_filters: AnalysisFilters = Depends(_analysis_filters),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_overview(
        db, _scope(db, user, user_id, team), start, end, analysis_filters,
    ))


@router.get("/countries")
def countries(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    analysis_filters: AnalysisFilters = Depends(_analysis_filters),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_country_analysis(
        db, _scope(db, user, user_id, team), start, end, analysis_filters,
    ))


@router.get("/people")
def people(
    dimension: Literal["team", "user"] = Query("user"),
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    analysis_filters: AnalysisFilters = Depends(_analysis_filters),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, date_to)
    return ok(service.get_people_analysis(
        db, _scope(db, user, user_id, team), start, end, dimension, analysis_filters,
    ))


@router.get("/customers")
def customers(
    date_from: date | None = None,
    as_of: date | None = None,
    risk_status: Literal["upcoming", "overdue", "churn_risk"] | None = None,
    country: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str | None = Query(None, max_length=64),
    team: str | None = Query(None, max_length=100),
    analysis_filters: AnalysisFilters = Depends(_analysis_filters),
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    start, end = service.normalize_window(date_from, as_of)
    return ok(service.get_customer_actions(
        db, _scope(db, user, user_id, team), end,
        page, page_size, risk_status, country, analysis_filters, start,
    ))


@router.get("/ai-brief/active")
def active_ai_brief(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    row = brief_job_service.get_active_job(db, _user_id(user))
    if row is not None and row.status == "queued":
        background_tasks.add_task(brief_job_service.run_job_in_background, row.id)
    return ok(brief_job_service.serialize_job(row) if row else None)


@router.get("/ai-brief/latest")
def latest_ai_brief(
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    row = brief_job_service.get_latest_job(db, _user_id(user))
    return ok(brief_job_service.serialize_job(row) if row else None)


@router.get("/ai-brief/{job_id}")
def ai_brief_status(
    job_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission(READ_PERMISSION)),
):
    try:
        row = brief_job_service.get_job(db, _user_id(user), job_id)
    except brief_job_service.BriefJobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ok(brief_job_service.serialize_job(row))


@router.post("/ai-brief", status_code=status.HTTP_202_ACCEPTED)
def ai_brief(
    body: AiBriefRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("order_intelligence:read")),
):
    scope = _scope(db, user, body.user_id, body.team)
    try:
        analysis_filters = AnalysisFilters.build(
            body.countries, body.models, body.colors, body.sources,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row, should_start = brief_job_service.prepare_job(
        db, _user_id(user), scope, body.date_from, body.date_to, body.focus, analysis_filters,
    )
    if should_start or row.status == "queued":
        background_tasks.add_task(brief_job_service.run_job_in_background, row.id)
    data = brief_job_service.serialize_job(row)
    data.update({"enqueued": should_start, "already_running": not should_start})
    # HTTP 202 表示任务已受理；统一响应信封仍使用业务成功码 200，
    # 以兼容前端公共拦截器的业务码约定。
    return ok(data)
