"""Read models; no caller can enlarge its authorized roster via filters."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException

from app.battle_report.access import is_admin, load_report, select_members, visible_members
from app.battle_report.models import BattleReportAudit
from app.battle_report.statistics import money, overview, source_orders, summarize
from app.core.time import beijing_now


def context(db, report_id, user, *, details=False, team=None, member_id=None):
    report, members, own = load_report(db, report_id, user)
    visible = select_members(visible_members(report, members, own, user, details=details),
                             team=team, member_id=member_id)
    now = beijing_now()
    orders, issues = source_orders(db, report, visible, now)
    detail_ids = {m.id for m in visible_members(report, members, own, user, details=True)}
    return report, visible, orders, issues, now, detail_ids


def get_overview(db, report_id, user, team=None):
    report, members, orders, issues, now, detail_ids = context(db, report_id, user, team=team)
    return overview(report, members, orders, issues, now, detail_ids)


def get_daily(db, report_id, user, start=None, team=None):
    report, members, orders, issues, now, detail_ids = context(db, report_id, user, team=team)
    start = start or max(report.start_date, min(report.end_date, now.date()) - timedelta(days=6))
    if not report.start_date <= start <= report.end_date:
        raise HTTPException(422, "日期必须位于战报周期内")
    days = [start + timedelta(days=i) for i in range(min(7, (report.end_date - start).days + 1))]
    rows = []
    for member in members:
        cells = []
        for day in days:
            selected = [o for o in orders if o["account_date"] == day.isoformat() and o["member_id"] == member.id]
            metrics = summarize([member], selected, issues)
            cells.append({"date": day.isoformat(), "gmv": metrics["gmv"], "order_count": metrics["order_count"],
                          "state": "future" if day > now.date() else "ok" if metrics["data_complete"] else "incomplete"})
        rows.append({"member_id": member.id, "user_name": member.user_name, "team": member.team,
                     "can_view_orders": member.id in detail_ids, "cells": cells,
                     "subtotal": money(sum((Decimal(c["gmv"]) for c in cells), Decimal(0)))})
    return {"dates": [d.isoformat() for d in days], "rows": rows, "calculated_at": now.isoformat(),
            "issue_count": len(issues)}


def list_orders(db, report_id, user, *, team=None, member_id=None, day=None, page=1, page_size=20,
                sort="date", keyword=None):
    report, members, orders, issues, now, _ = context(db, report_id, user, details=True, team=team, member_id=member_id)
    if day and not report.start_date <= day <= min(report.end_date, now.date()):
        raise HTTPException(422, "请选择周期内已到达的日期")
    selected = [o for o in orders if day is None or o["account_date"] == day.isoformat()]
    if keyword:
        term = keyword.strip().casefold()
        selected = [o for o in selected if term in o["order_no"].casefold() or term in o["company_name"].casefold()]
    selected.sort(key=lambda o: (Decimal(o["included_usd"]), o["order_id"]) if sort == "amount"
                  else (o["account_date"], o["order_id"]), reverse=True)
    start = (page - 1) * page_size
    return {"items": selected[start:start + page_size], "total": len(selected), "page": page,
            "page_size": page_size, "gmv": money(sum((Decimal(o["included_usd"]) for o in selected), Decimal(0))),
            "issues": issues, "data_complete": not issues, "calculated_at": now.isoformat()}


def order_detail(db, report_id, order_id, user):
    _, _, orders, _, _, _ = context(db, report_id, user, details=True)
    item = next((o for o in orders if o["order_id"] == order_id), None)
    if item is None:
        raise HTTPException(404, "订单不存在或不在可查看的战报范围内")
    return {**item, "included_percent": 100, "reason": "有效订单 · 核算日期在战报周期内 · 参与业务员"}


def list_audits(db, report_id, user, page=1, page_size=20):
    if not is_admin(user):
        raise HTTPException(403, "需要战报管理权限")
    load_report(db, report_id, user)
    query = db.query(BattleReportAudit).filter_by(report_id=report_id)
    total = query.count()
    items = query.order_by(BattleReportAudit.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return {"total": total, "items": [{"id": a.id, "action": a.action, "actor_id": a.actor_id,
            "before": a.before, "after": a.after, "reason": a.reason, "created_at": a.created_at.isoformat()}
            for a in items]}
