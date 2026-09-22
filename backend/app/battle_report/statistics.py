"""One Decimal-based order set feeds every battle-report view."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import bindparam, text

from app.core.config import get_settings
from app.dingtalk.gmv_daily_service import VALID_ORDER_SQL

CENT = Decimal("0.01")


def money(value):
    return format(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def source_orders(db, report, members, now):
    if not members or now.date() < report.start_date:
        return [], []
    schema = get_settings().BUSINESS_DB_NAME
    # Schema comes from validated Settings, never request input. Business mirror is read-only.
    statement = text(f"""
        SELECT o.order_id, o.order_no, o.user_id, o.account_date, o.amount_usd,
               o.status_name, o.company_id, COALESCE(c.company_name, '') AS company_name
        FROM `{schema}`.okki_orders o
        LEFT JOIN `{schema}`.customer_info c ON c.company_id = o.company_id
        WHERE o.user_id IN :user_ids AND {VALID_ORDER_SQL}
          AND ((o.account_date >= :start AND o.account_date <= :end) OR o.account_date IS NULL)
        ORDER BY o.account_date DESC, o.order_id
    """).bindparams(bindparam("user_ids", expanding=True))
    raw = db.execute(statement, {"user_ids": [m.okki_user_id for m in members],
                                "start": report.start_date, "end": min(report.end_date, now.date())}).mappings().all()
    return normalize_orders(raw, report, members, now.date())


def normalize_orders(raw, report, members, today):
    by_user = {m.okki_user_id: m for m in members}
    seen, conflicts, issues = {}, set(), []
    for row in raw:
        row = dict(row)
        member = by_user.get(str(row.get("user_id")))
        if member is None:
            continue
        key = str(row.get("order_id") or "")
        reason = None
        try:
            day = row.get("account_date")
            if isinstance(day, datetime):
                day = day.date()
            elif not isinstance(day, date):
                day = date.fromisoformat(str(day))
            amount = Decimal(str(row.get("amount_usd")))
            if not amount.is_finite() or amount < 0 or amount >= Decimal("100000000000000"):
                raise InvalidOperation
            amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        except (ValueError, TypeError, InvalidOperation):
            reason = "金额或核算日期异常（负金额需核对）"
        if not key:
            reason = "缺少稳定订单编号"
        if reason:
            issues.append({"member_id": member.id, "order_no": row.get("order_no"), "reason": reason})
            continue
        if not report.start_date <= day <= min(report.end_date, today):
            continue
        item = {"order_id": key, "order_no": row.get("order_no") or key,
                "account_date": day.isoformat(), "member_id": member.id,
                "user_name": member.user_name, "team": member.team,
                "company_name": row.get("company_name") or "", "status_name": row.get("status_name") or "有效订单",
                "amount_usd": money(amount), "included_usd": money(amount)}
        if key in seen and item != seen[key]:
            conflicts.add(key)
            for mid in {seen[key]["member_id"], member.id}:
                issues.append({"member_id": mid, "order_no": item["order_no"], "reason": "重复订单内容冲突"})
        seen[key] = item
    return [item for key, item in seen.items() if key not in conflicts], issues


def summarize(members, orders, issues):
    ids = {m.id for m in members}
    selected = [o for o in orders if o["member_id"] in ids]
    total = sum((Decimal(o["included_usd"]) for o in selected), Decimal(0))
    target = sum((m.target_usd or Decimal(0) for m in members), Decimal(0))
    filled = sum(m.target_usd is not None for m in members)
    complete = not any(i["member_id"] in ids for i in issues)
    rate = total / target * 100 if complete and target > 0 and filled == len(members) else None
    return {"gmv": money(total), "target": money(target), "order_count": len(selected),
            "filled": filled, "member_count": len(members), "data_complete": complete,
            "progress_percent": float(rate.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if rate is not None else None,
            "gap": money(max(target - total, 0)) if filled == len(members) else None,
            "excess": money(max(total - target, 0)) if filled == len(members) else None,
            "average_order": money(total / len(selected)) if selected else None}


def period_days(report):
    return [report.start_date + timedelta(days=i) for i in range((report.end_date - report.start_date).days + 1)]


def time_progress(report, now):
    start = datetime.combine(report.start_date, time.min)
    end = datetime.combine(report.end_date + timedelta(days=1), time.min)
    return round(min(100, max(0, (now - start).total_seconds() / (end - start).total_seconds() * 100)), 1)


def overview(report, members, orders, issues, now, detail_ids):
    people = [{"member_id": m.id, "user_name": m.user_name, "team": m.team,
               "target_usd": money(m.target_usd) if m.target_usd is not None else None,
               "can_view_orders": m.id in detail_ids, **summarize([m], orders, issues)} for m in members]
    teams = [{"team": team, **summarize([m for m in members if m.team == team], orders, issues)}
             for team in sorted({m.team for m in members})]
    daily = []
    for day in period_days(report):
        summary = summarize(members, [o for o in orders if o["account_date"] == day.isoformat()], issues)
        daily.append({"date": day.isoformat(), "gmv": summary["gmv"], "order_count": summary["order_count"],
                      "state": "future" if day > now.date() else "ok" if summary["data_complete"] else "incomplete"})
    return {"summary": summarize(members, orders, issues), "people": people, "teams": teams,
            "daily": daily, "time_progress": time_progress(report, now),
            "calculated_at": now.isoformat(), "source_synced_at": None,
            "issue_count": len(issues), "basis": "核算日期 · 订单 GMV · USD · 活动小组"}
