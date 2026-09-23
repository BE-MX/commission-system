"""Admin-only configuration and immutable full-roster poster snapshots."""
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import HTTPException

from app.battle_report.access import load_report
from app.battle_report.models import BattleReportDelivery
from app.battle_report.pace import calendar_progress, work_dates
from app.battle_report.service import audit, bump_report, report_payload, require_admin, write_transaction
from app.battle_report.statistics import overview, source_orders
from app.core.config import get_settings
from app.core.time import beijing_now


def push_ready(settings=None):
    settings = settings or get_settings()
    url = urlparse(settings.BATTLE_REPORT_WEBHOOK_URL)
    public = urlparse(settings.BATTLE_REPORT_PUBLIC_BASE_URL)
    return (url.scheme == "https" and url.hostname == "oapi.dingtalk.com"
            and url.path == "/robot/send" and "access_token=" in url.query
            and public.scheme == "https" and bool(public.hostname)
            and not public.query and not public.fragment and not public.username)


def get_config(db, report_id, user):
    require_admin(user)
    report, _, _ = load_report(db, report_id, user)
    settings = get_settings()
    logs = db.query(BattleReportDelivery).filter_by(report_id=report_id).order_by(BattleReportDelivery.id.desc()).limit(10).all()
    return {"version": report.version, "work_dates": work_dates(report),
            "push_enabled": bool(report.poster_push_enabled), "push_ready": bool(push_ready(settings)),
            "group_name": settings.BATTLE_REPORT_GROUP_NAME, "send_times": ["13:00", "17:01"],
            "history": [{"id": row.id, "date": row.report_date.isoformat(), "slot": row.slot,
                         "deliveries": row.deliveries, "calculated_at": row.snapshot["calculated_at"]} for row in logs]}


def save_config(db, report_id, user, payload):
    require_admin(user)
    with write_transaction(db):
        report, _, _ = load_report(db, report_id, user, lock=True)
        if report.status == "archived":
            raise HTTPException(409, "归档战报不可修改海报设置")
        if any(not report.start_date <= d <= report.end_date for d in payload.work_dates):
            raise HTTPException(422, "计时工作日必须位于战报周期内")
        if payload.push_enabled and (not push_ready() or report.visibility != "activity"):
            raise HTTPException(422, "请先配置战报专用群机器人和公网地址，并将战报可见范围设为全活动")
        before = {"work_dates": work_dates(report), "push_enabled": bool(report.poster_push_enabled)}
        dates = [d.isoformat() for d in payload.work_dates]
        bump_report(db, report, payload.version, work_dates=dates, poster_push_enabled=payload.push_enabled)
        audit(db, report, user, "poster_config", before,
              {"work_dates": dates, "push_enabled": payload.push_enabled}, "配置海报计时及群推送")
    return get_config(db, report_id, user)


def build_snapshot(db, report, members, now=None):
    now = now or beijing_now()
    if calendar_progress(report, now) is None:
        raise HTTPException(422, "请先在海报设置中配置周期内的计时工作日")
    orders, issues = source_orders(db, report, members, now)
    data = overview(report, members, orders, issues, now, set())
    if issues or not members or data["summary"]["progress_percent"] is None:
        raise HTTPException(422, "所有参与人填写有效目标且订单异常处理完毕后，才能生成海报")
    # Sort using exact money ratios, not rounded display percentages. Python's stable
    # sort preserves roster ID order for equal personal completion; ranks are consecutive.
    for key in ("teams", "people"):
        data[key].sort(key=lambda r: Decimal(r["gmv"]) / Decimal(r["target"]), reverse=True)
        for index, row in enumerate(data[key], 1):
            row["rank"] = index
    data["report"] = report_payload(report, now)
    data["art_version"] = 1
    return data


def preview_snapshot(db, report_id, user):
    require_admin(user)
    report, members, _ = load_report(db, report_id, user)
    return build_snapshot(db, report, members)
