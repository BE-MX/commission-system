"""四指标统计口径与工作日时间进度。

- GMV：VALID_ORDER_SQL 有效订单 amount_usd，按 account_date 入账，归属订单业务员。
- 新签客户数：期内 resolve_order_role=new_sign 订单去重客户数（新成交标记/人工裁定，裁定优先）。
- 复购客户数/金额：期内 resolve_order_role=repeat 订单去重客户数与 amount_usd 合计，归属下单业务员。
- 时间进度：工作日口径（周一至周五），已过工作日 / 期内工作日总数。
"""
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import bindparam, text

from app.battle_report.award_statistics import NEW_DEAL_FIELD
from app.battle_report.order_decisions import decision_index, resolve_order_role
from app.core.config import get_settings
from app.dingtalk.gmv_daily_service import VALID_ORDER_SQL
from app.perf_goal.models import METRICS

CENT = Decimal("0.01")
ZERO = Decimal(0)
logger = logging.getLogger(__name__)

METRIC_UNITS = {"gmv": "USD", "new_sign": "个", "repeat_customers": "个", "repeat_amount": "USD"}


def period_bounds(period_type: str, year: int, quarter: int | None = None, month: int | None = None) -> tuple[date, date]:
    if period_type == "year":
        return date(year, 1, 1), date(year, 12, 31)
    if period_type == "quarter":
        if quarter not in (1, 2, 3, 4):
            raise ValueError("季度统计必须提供 1-4 的季度")
        first_month = (quarter - 1) * 3 + 1
        start = date(year, first_month, 1)
        end_month = first_month + 2
        return start, date(year, end_month, month_days(year, end_month))
    if period_type == "month":
        if month is None or not 1 <= month <= 12:
            raise ValueError("月度统计必须提供 1-12 的月份")
        return date(year, month, 1), date(year, month, month_days(year, month))
    raise ValueError("period_type 必须是 year/quarter/month")


def month_days(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def prev_period(period_type: str, year: int, quarter: int | None, month: int | None):
    if period_type == "year":
        return year - 1, None, None
    if period_type == "quarter":
        return (year, quarter - 1, None) if quarter > 1 else (year - 1, 4, None)
    return (year, quarter, month - 1) if month > 1 else (year - 1, 4, 12)


def period_label(period_type: str, year: int, quarter: int | None, month: int | None) -> str:
    if period_type == "year":
        return f"{year} 年度"
    if period_type == "quarter":
        return f"{year} Q{quarter}"
    return f"{year}-{month:02d}"


def _is_workday(day: date) -> bool:
    return day.weekday() < 5


def workdays_between(start: date, end: date) -> int:
    if end < start:
        return 0
    days = (end - start).days + 1
    full_weeks, remainder = divmod(days, 7)
    count = full_weeks * 5
    for offset in range(days - remainder, days):
        if _is_workday(start + timedelta(days=offset)):
            count += 1
    return count


def workday_time_progress(start: date, end: date, as_of: date) -> float:
    """已过工作日 / 期内工作日总数；as_of 早于起点为 0，晚于终点为 1。"""
    total = workdays_between(start, end)
    if total <= 0:
        return 0.0
    elapsed = workdays_between(start, min(as_of, end))
    return round(elapsed / total, 4)


def fetch_order_facts(db, okki_user_ids: list[str], start: date, end: date,
                      decisions: dict | None = None) -> tuple[list[dict], list[str]]:
    """Read valid goods orders for the roster window; roles resolved with manual rulings first."""
    if not okki_user_ids or end < start:
        return [], []
    try:
        index = decision_index(decisions or {})
    except (ValueError, TypeError):
        logger.warning("Invalid perf-goal order decisions; GMV kept, new/repeat metrics degraded", exc_info=True)
        index = {}
    schema = get_settings().BUSINESS_DB_NAME
    # Schema comes from validated Settings, never request input. Business mirror is read-only.
    statement = text(f"""
        SELECT o.order_id, o.order_no, o.name AS order_name, o.user_id, o.company_id,
               COALESCE(c.company_name, '') AS company_name, COALESCE(c.country_name, '') AS country_name,
               o.account_date, o.amount_usd, o.custom_fields
        FROM `{schema}`.okki_orders o
        LEFT JOIN `{schema}`.customer_info c ON c.company_id = o.company_id
        WHERE o.user_id IN :user_ids AND {VALID_ORDER_SQL}
          AND o.account_date >= :start AND o.account_date <= :end
        ORDER BY o.account_date, o.order_id
    """).bindparams(bindparam("user_ids", expanding=True))
    raw = db.execute(statement, {"user_ids": [str(u) for u in okki_user_ids],
                                 "start": start, "end": end}).mappings().all()
    facts, issues, seen = [], [], {}
    for source in raw:
        row = dict(source)
        oid = str(row.get("order_id") or "")
        try:
            day = row.get("account_date")
            if isinstance(day, datetime):
                day = day.date()
            elif not isinstance(day, date):
                day = date.fromisoformat(str(day))
            amount = Decimal(str(row.get("amount_usd")))
            uid = str(row.get("user_id") or "")
            cid = str(row.get("company_id") or "")
            if not oid or not uid or not cid or not amount.is_finite() or amount < 0:
                raise ValueError
            amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        except (ValueError, TypeError, InvalidOperation):
            issues.append(f"订单 {row.get('order_id') or '未知'} 缺少有效客户、日期、美元金额或负责人")
            continue
        if not start <= day <= end:
            continue
        fields = row.get("custom_fields")
        try:
            fields = json.loads(fields) if isinstance(fields, str) else fields
        except (TypeError, ValueError, json.JSONDecodeError):
            fields = None
        mark = fields.get(NEW_DEAL_FIELD) if isinstance(fields, dict) else None
        role, issue = resolve_order_role(
            {"order_id": oid, "order_no": row.get("order_no"), "company_id": cid,
             "user_id": uid, "account_date": day}, mark, index)
        if issue:
            issues.append(issue)
        if oid in seen:
            if seen[oid] != (uid, cid, day, amount, role):
                issues.append(f"订单 {oid} 重复且事实冲突")
            continue
        seen[oid] = (uid, cid, day, amount, role)
        flags = []
        if role == "new_sign":
            flags.append("new_sign")
        elif role == "repeat":
            flags.append("repeat")
        if role != "pending" and oid in index:
            flags.append("manual_decision")
        facts.append({"order_id": oid, "order_no": row.get("order_no") or oid,
                      "order_name": row.get("order_name") or "", "owner": uid, "company_id": cid,
                      "customer_name": row.get("company_name") or "", "country": row.get("country_name") or "",
                      "day": day, "amount": amount, "role": role, "flags": flags})
    from app.sales_return.gmv import adjustments
    from app.sales_return.sources import source_role
    for adjustment in adjustments(db, start, end, okki_user_ids):
        if adjustment.get("original_order"):
            role, issue = source_role(adjustment["original_order"], index)
            adjustment["role"] = role
            if issue:
                issues.append(issue)
            elif adjustment["order_id"] in index:
                adjustment["flags"].append("manual_decision")
        facts.append(adjustment)
    return facts, issues


def aggregate(facts: list[dict]) -> dict[str, dict]:
    """Per-owner metric totals; count metrics dedupe customers within the window."""
    result: dict[str, dict] = {}
    for fact in facts:
        row = result.setdefault(fact["owner"], {"gmv": ZERO, "new_sign": set(),
                                                "repeat_customers": set(), "repeat_amount": ZERO})
        row["gmv"] += fact["amount"]
        if fact.get("source_type") == "sales_return":
            if fact["role"] == "repeat":
                row["repeat_amount"] += fact["amount"]
            continue
        if fact["role"] == "new_sign":
            row["new_sign"].add(fact["company_id"])
        elif fact["role"] == "repeat":
            row["repeat_customers"].add(fact["company_id"])
            row["repeat_amount"] += fact["amount"]
    return result


def sum_totals(totals: dict[str, dict], okki_user_ids: list[str]) -> dict:
    """Sum per-owner totals; distinct-customer counts sum per owner (同一客户被多人成交分别计入其名下)."""
    combined = {"gmv": ZERO, "new_sign": 0, "repeat_customers": 0, "repeat_amount": ZERO}
    for uid in okki_user_ids:
        row = totals.get(str(uid))
        if not row:
            continue
        combined["gmv"] += row["gmv"]
        combined["new_sign"] += len(row["new_sign"])
        combined["repeat_customers"] += len(row["repeat_customers"])
        combined["repeat_amount"] += row["repeat_amount"]
    return combined


def owner_total(totals: dict[str, dict], okki_user_id: str) -> dict:
    row = totals.get(str(okki_user_id)) or {}
    return {"gmv": row.get("gmv", ZERO), "new_sign": len(row.get("new_sign", set())),
            "repeat_customers": len(row.get("repeat_customers", set())), "repeat_amount": row.get("repeat_amount", ZERO)}


def rate_of(achieved: Decimal | int | None, target: Decimal | None) -> float | None:
    if target is None or target <= 0 or achieved is None:
        return None
    return round(float(Decimal(str(achieved)) / Decimal(str(target))), 4)


def delta_pp(rate: float | None, time_progress: float) -> float | None:
    if rate is None:
        return None
    return round((rate - time_progress) * 100, 2)


def status_for(rate: float | None, delta: float | None) -> str:
    if rate is None:
        return "no_target"
    if rate >= 1:
        return "completed"
    if delta is None or delta >= -5:
        return "on_track"
    if delta > -20:
        return "lagging"
    return "critical"


def projected_rate(achieved: Decimal | int, target: Decimal | None,
                   elapsed_workdays: int, remaining_workdays: int) -> float | None:
    """按当前日均速率外推期末完成率；目标缺失或尚未进入周期时为 None。"""
    if target is None or target <= 0 or elapsed_workdays <= 0:
        return None
    daily = Decimal(str(achieved)) / elapsed_workdays
    projected = Decimal(str(achieved)) + daily * remaining_workdays
    return round(float(projected / Decimal(str(target))), 4)
