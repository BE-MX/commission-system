"""绩效目标管理 API（/api/perf-goals）。"""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.core.time import BEIJING_TIMEZONE, beijing_now_aware
from app.auth.models import ArkUser
from app.perf_goal import access, config_store, delivery, targets, teams as teams_service, trend
from app.perf_goal.dingtalk_worknotice import worknotice_configured
from app.perf_goal.models import PerfReport, PerfReportDelivery
from app.perf_goal.schemas import (ConfigUpdate, GoalsUpdate, PeriodInput, SplitInput,
                                   TeamGoalsUpdate)

router = APIRouter()
_require_read = require_any_permission("perf_goal:read", "perf_goal:admin")
_require_roster = require_any_permission("perf_goal:read", "perf_goal:write", "perf_goal:admin")
_require_write = require_any_permission("perf_goal:write", "perf_goal:admin")
_require_admin = require_permission("perf_goal:admin")

Granularity = Literal["year", "quarter", "month"]
Scope = Literal["company", "team", "person"]
Metric = Literal["gmv", "new_sign", "repeat_customers", "repeat_amount"]
REPORT_CRON = "0 9 1,10,20 * *"


def _active_period_id(db: Session) -> int | None:
    period = targets.get_active_period(db)
    return period.id if period else None


# ── 名单与批次 ──────────────────────────────────────────────
@router.get("/roster")
def get_roster(db: Session = Depends(get_db), user=Depends(_require_roster)):
    return ok(teams_service.roster(db, _active_period_id(db)))


@router.get("/periods")
def list_periods(db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(targets.list_periods(db))


@router.post("/periods")
def create_period(payload: PeriodInput, db: Session = Depends(get_db), user=Depends(_require_write)):
    return ok(targets.create_period(db, user, payload))


@router.post("/periods/{period_id}/activate")
def activate_period(period_id: int, db: Session = Depends(get_db), user=Depends(_require_write)):
    return ok(targets.activate_period(db, user, period_id))


@router.get("/periods/active")
def active_period(db: Session = Depends(get_db), user=Depends(_require_read)):
    period = targets.get_active_period(db)
    return ok(targets._period_json(period) if period else None)


@router.get("/periods/{period_id}/goals")
def list_goals(period_id: int, granularity: Granularity | None = None,
               db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(targets.list_goals(db, period_id, granularity))


@router.put("/periods/{period_id}/goals")
def save_goals(period_id: int, payload: GoalsUpdate, db: Session = Depends(get_db),
               user=Depends(_require_write)):
    return ok(targets.save_goals(db, period_id, user, payload))


@router.post("/periods/{period_id}/split")
def split_goals(period_id: int, payload: SplitInput, db: Session = Depends(get_db),
                user=Depends(_require_write)):
    return ok(targets.split_goals(db, period_id, user, payload))


@router.get("/periods/{period_id}/team-goals")
def list_team_goals(period_id: int, granularity: Granularity | None = None,
                    db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(targets.list_team_goals(db, period_id, granularity))


@router.put("/periods/{period_id}/team-goals")
def save_team_goals(period_id: int, payload: TeamGoalsUpdate, db: Session = Depends(get_db),
                    user=Depends(_require_write)):
    return ok(targets.save_team_goals(db, period_id, user, payload))


@router.post("/periods/{period_id}/team-goals/recalc")
def recalc_team_goals(period_id: int, db: Session = Depends(get_db), user=Depends(_require_write)):
    return ok(targets.recalc_team_goals(db, period_id, user))


@router.get("/periods/{period_id}/audits")
def list_audits(period_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(targets.list_audits(db, period_id))


# ── 看板 ──────────────────────────────────────────────────
@router.get("/overview")
def overview(scope: Scope, scope_id: int | None = None, period_type: Granularity = "year",
             year: int | None = None, quarter: int | None = None, month: int | None = None,
             db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(trend.overview(db, user, scope, scope_id, period_type, year, quarter, month))


@router.get("/trend")
def cumulative_trend(scope: Scope, scope_id: int | None = None, metric: Metric = "gmv",
                     period_type: Granularity = "year", year: int | None = None,
                     quarter: int | None = None, month: int | None = None,
                     db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(trend.trend(db, user, scope, scope_id, metric, period_type, year, quarter, month))


@router.get("/teams")
def teams_board(period_type: Granularity = "year", year: int | None = None,
                quarter: int | None = None, month: int | None = None,
                db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(trend.teams_board(db, user, period_type, year, quarter, month))


@router.get("/ranking")
def ranking(period_type: Granularity = "year", year: int | None = None,
            quarter: int | None = None, month: int | None = None,
            sort: str = "gmv_rate", order: Literal["asc", "desc"] = "desc",
            db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(trend.ranking(db, user, period_type, year, quarter, month, sort, order))


@router.get("/metric-orders")
def metric_orders(metric: Metric, user_id: int | None = None, department_id: int | None = None,
                  date_from: date | None = None, date_to: date | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(trend.metric_orders(db, user, metric, user_id, department_id,
                                  date_from, date_to, page, page_size))


# ── 报告与推送 ─────────────────────────────────────────────
def _report_names(db: Session, reports: list[PerfReport]) -> tuple[dict, dict]:
    user_names = {row.id: row.real_name for row in db.query(ArkUser.id, ArkUser.real_name)
                  .filter(ArkUser.id.in_([r.user_id for r in reports if r.user_id] or [-1])).all()}
    try:
        roster_data = teams_service.roster(db, None)
        team_names = {team["department_id"]: team["name"] for team in roster_data["teams"]}
    except ValueError:
        team_names = {}
    return user_names, team_names


def _report_row(report: PerfReport, user_names: dict, team_names: dict) -> dict:
    return {"id": report.id, "slot": report.slot.isoformat(), "scope": report.scope,
            "user_id": report.user_id, "user_name": user_names.get(report.user_id),
            "department_id": report.department_id,
            "team_name": team_names.get(report.department_id),
            "status": report.status,
            "created_at": report.created_at.isoformat() if report.created_at else None}


@router.get("/reports")
def list_reports(slot: date | None = None, scope: Literal["person", "leader", "company"] | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db: Session = Depends(get_db), user=Depends(_require_read)):
    query = db.query(PerfReport)
    if slot is not None:
        query = query.filter(PerfReport.slot == slot)
    if scope is not None:
        query = query.filter(PerfReport.scope == scope)
    if not access.can_read_all(user):
        query = query.filter(PerfReport.user_id == access.actor_id(user))
    total = query.count()
    rows = (query.order_by(PerfReport.slot.desc(), PerfReport.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    user_names, team_names = _report_names(db, rows)
    return ok({"rows": [_report_row(row, user_names, team_names) for row in rows], "total": total})


def _load_report_visible(db: Session, report_id: int, user: dict) -> PerfReport:
    report = db.get(PerfReport, report_id)
    if report is None:
        raise HTTPException(404, "报告不存在")
    if access.can_read_all(user):
        return report
    if report.user_id == access.actor_id(user):
        return report
    roster_data = teams_service.roster(db, None)
    if (report.scope == "leader" and report.department_id is not None
            and access.captain_department(roster_data, access.actor_id(user)) == report.department_id):
        return report
    raise HTTPException(403, "无权查看该报告")


@router.get("/reports-schedule")
def reports_schedule(db: Session = Depends(get_db), user=Depends(_require_read)):
    now = beijing_now_aware()
    candidates = []
    for year, month in ((now.year, now.month),
                        (now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1)):
        for day in (1, 10, 20):
            candidates.append(datetime(year, month, day, 9, 0, tzinfo=BEIJING_TIMEZONE))
    next_run = next((slot for slot in candidates if slot > now), None)
    return ok({"cron": REPORT_CRON,
               "next_run_at": next_run.isoformat() if next_run else None,
               "recent_slots": delivery.slot_counts(db)})


@router.get("/reports/{report_id}")
def report_detail(report_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    report = _load_report_visible(db, report_id, user)
    deliveries = (db.query(PerfReportDelivery).filter(PerfReportDelivery.report_id == report.id)
                  .order_by(PerfReportDelivery.id).all())
    return ok({"id": report.id, "slot": report.slot.isoformat(), "scope": report.scope,
               "content_md": report.content_md, "content_json": report.content_json,
               "status": report.status, "error": report.error,
               "deliveries": [{"channel": row.channel, "destination": row.destination,
                               "status": row.status, "attempts": row.attempts,
                               "last_error": row.last_error,
                               "sent_at": row.sent_at.isoformat() if row.sent_at else None}
                              for row in deliveries]})


@router.post("/reports/{report_id}/resend")
def resend_report(report_id: int, db: Session = Depends(get_db), user=Depends(_require_admin)):
    report = db.get(PerfReport, report_id)
    if report is None:
        raise HTTPException(404, "报告不存在")
    if report.status != "generated" or not report.content_md:
        raise HTTPException(409, "报告尚未生成成功，无法补发")
    rows = (db.query(PerfReportDelivery).filter(PerfReportDelivery.report_id == report.id)
            .order_by(PerfReportDelivery.id).all())
    if not rows:
        raise HTTPException(409, "该报告没有投递记录")
    for row in rows:
        if row.status in ("failed", "pending"):
            row.status = "pending"
            row.attempts = 0
            row.last_error = None
    db.commit()
    recipient_row = db.get(ArkUser, report.user_id) if report.user_id else None
    recipient = {"ark_user_id": report.user_id,
                 "name": recipient_row.real_name if recipient_row else str(report.user_id),
                 "dingtalk_id": (recipient_row.dingtalk_id or "").strip() if recipient_row else "",
                 "phone": (recipient_row.phone or "").strip() if recipient_row else ""}
    if report.scope == "person":
        scope_name = recipient["name"]
    elif report.scope == "leader":
        scope_name = "战队"
    else:
        scope_name = "公司整体"
    for row in rows:
        if row.status in ("pending", "failed"):
            delivery.deliver_report(db, report, recipient, scope_name)
    return report_detail(report_id, db, user)


# ── 配置 ──────────────────────────────────────────────────
@router.get("/config")
def get_config(db: Session = Depends(get_db), user=Depends(_require_admin)):
    settings = get_settings()
    config = config_store.load_config(db)
    config["worknotice_enabled"] = worknotice_configured(settings)
    config["webhook_configured"] = bool(settings.PERF_REPORT_WEBHOOK_URL)
    return ok(config)


@router.put("/config")
def save_config(payload: ConfigUpdate, db: Session = Depends(get_db), user=Depends(_require_admin)):
    config = config_store.save_config(db, payload, access.actor_id(user))
    settings = get_settings()
    config["worknotice_enabled"] = worknotice_configured(settings)
    config["webhook_configured"] = bool(settings.PERF_REPORT_WEBHOOK_URL)
    return ok(config)
