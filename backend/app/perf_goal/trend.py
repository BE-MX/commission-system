"""看板查询：汇总卡、累积趋势、战队榜、排名与指标明细。"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import beijing_today
from app.perf_goal import access, statistics as stats, targets
from app.perf_goal.config_store import load_config, order_decision_rules
from app.perf_goal.models import METRICS, PerfGoal, PerfGoalPeriod, PerfGoalTeamOverride
from app.perf_goal.teams import all_people, roster

ZERO = Decimal(0)
logger = logging.getLogger(__name__)
COUNT_METRICS = {"new_sign", "repeat_customers"}
SORT_FIELDS = {f"{m}_rate" for m in METRICS} | {f"{m}_achieved" for m in METRICS} | {"delta_pp"}


def _as_of() -> date:
    return beijing_today()


def _period_params(period_type: str, year: int | None, quarter: int | None, month: int | None,
                   period) -> tuple[int, int | None, int | None]:
    if period_type not in ("year", "quarter", "month"):
        raise HTTPException(422, "period_type 必须是 year/quarter/month")
    today = _as_of()
    year = year or (period.year if period else today.year)
    if period_type == "quarter":
        quarter = quarter or ((today.month - 1) // 3 + 1)
        if quarter not in (1, 2, 3, 4):
            raise HTTPException(422, "quarter 必须是 1-4")
    if period_type == "month":
        month = month or today.month
        if not 1 <= month <= 12:
            raise HTTPException(422, "month 必须是 1-12")
        quarter = quarter or ((month - 1) // 3 + 1)
    return year, quarter, month


def _slot(period_type: str, quarter: int | None, month: int | None):
    if period_type == "year":
        return "year", None, None
    if period_type == "quarter":
        return "quarter", quarter, None
    return "month", quarter, month


def _goals_index(db: Session, period_id: int) -> dict[tuple, Decimal]:
    rows = db.query(PerfGoal).filter(PerfGoal.period_id == period_id).all()
    return {(r.user_id, r.metric, r.granularity, r.quarter, r.month): Decimal(r.target_value) for r in rows}


def _listed_user_ids(db: Session, period_id: int) -> set[int]:
    rows = (db.query(PerfGoal.user_id)
            .filter(PerfGoal.period_id == period_id, PerfGoal.granularity == "year").distinct().all())
    return {row[0] for row in rows}


def _team_target_index(db: Session, period_id: int, roster_data: dict) -> dict[tuple, Decimal]:
    config = load_config(db)
    default_factor = Decimal(str(config.get("default_factor") or "1"))
    auto_index = targets._team_auto_index(db, period_id, roster_data)
    stored = {(r.department_id, r.metric, r.granularity, r.quarter, r.month): r
              for r in db.query(PerfGoalTeamOverride).filter(PerfGoalTeamOverride.period_id == period_id).all()}
    index: dict[tuple, Decimal] = {}
    for key in set(auto_index) | set(stored):
        row = stored.get(key)
        if row is not None and row.override_value is not None:
            index[key] = Decimal(row.override_value)
        elif row is not None:
            index[key] = Decimal(row.auto_value or 0) * Decimal(row.factor)
        else:
            index[key] = auto_index[key] * default_factor
    return index


def _person_entry(roster_data: dict, user_id: int) -> dict | None:
    return next((p for p in all_people(roster_data) if p["user_id"] == user_id), None)


def _scope_people(user: dict, roster_data: dict, scope: str, scope_id: int | None,
                  listed: set[int]) -> list[dict]:
    people = all_people(roster_data)
    if scope == "company":
        access.require_company_visible(user, roster_data)
        return [p for p in people if p["user_id"] in listed]
    if scope == "team":
        if scope_id is None:
            raise HTTPException(422, "scope_id（战队 department_id）必填")
        access.require_team_visible(user, roster_data, scope_id)
        team = next((t for t in roster_data["teams"] if t["department_id"] == scope_id), None)
        if team is None:
            raise HTTPException(404, "战队不存在")
        return [p for p in people if p["department_id"] == scope_id]
    if scope == "person":
        if scope_id is None:
            raise HTTPException(422, "scope_id（方舟用户ID）必填")
        access.require_person_visible(user, roster_data, scope_id)
        person = _person_entry(roster_data, scope_id)
        if person is None:
            raise HTTPException(404, "该业务员不在绩效名单（未绑定 OKKI 账号）")
        return [person]
    raise HTTPException(422, "scope 必须是 company/team/person")


def _facts(db: Session, people: list[dict], start: date, end: date, department_id=None):
    from app.battle_report.order_decisions import decision_index
    from app.sales_return.sources import source_role
    rules = order_decision_rules(db)
    okki_ids = [p["okki_user_id"] for p in people if p.get("okki_user_id") and not p.get("historical_return_owner")]
    facts, issues = stats.fetch_order_facts(db, okki_ids, start, end, rules)
    try:
        decisions = decision_index(rules)
    except (TypeError, ValueError):
        logger.warning("Invalid performance order rulings for historical return adjustments")
        print("[perf-goal] Invalid order rulings; return classification pending", flush=True)
        decisions = {}  # fetch_order_facts already reports the invalid rules.

    def resolved_returns(rows):
        for row in rows:
            if row.get("original_order"):
                row["role"], issue = source_role(row["original_order"], decisions)
                if issue and issue not in issues:
                    issues.append(issue)
        return rows

    historical = [p["okki_user_id"] for p in people if p.get("historical_return_owner")]
    if department_id is not None:
        from app.sales_return.gmv import department_adjustments
        facts = [f for f in facts if f.get("source_type") != "sales_return"]
        department_facts, department_issues = department_adjustments(db, start, end, department_id)
        facts.extend(resolved_returns(department_facts))
        issues.extend(department_issues)
    elif historical:
        from app.sales_return.gmv import adjustments
        facts.extend(resolved_returns(adjustments(db, start, end, historical)))
        issues.append("历史归属待分配：退货调整已保留在公司净 GMV；请核对原团队与人员映射")
    return facts, issues


def _historical_people(db, people, roster_data, scope, start, end, scope_id=None):
    if scope not in {"company", "team"}:
        return people
    from app.sales_return.gmv import adjustments, department_adjustments
    known = {p["okki_user_id"] for p in people}
    if scope == "company":
        returns = adjustments(db, start, end)
    else:
        returns, _ = department_adjustments(db, start, end, scope_id)
    owners = {f["owner"] for f in returns} - known
    return people + [{"okki_user_id": uid, "user_id": None, "department_id": None,
                      "name": f"历史归属待分配 ({uid})", "historical_return_owner": True} for uid in sorted(owners)]


def _num(metric: str, value) -> float | int:
    if metric in COUNT_METRICS:
        return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return float(Decimal(value).quantize(Decimal("0.01")))


def _target_for(db: Session, period, goals: dict[tuple, Decimal], team_targets: dict[tuple, Decimal],
                scope: str, scope_id: int | None, metric: str, granularity: str,
                quarter: int | None, month: int | None, people: list[dict],
                listed: set[int]) -> Decimal | None:
    if period is None:
        return None
    if scope == "person":
        return goals.get((scope_id, metric, granularity, quarter, month))
    if scope == "team":
        return team_targets.get((scope_id, metric, granularity, quarter, month))
    values = [goals[(p["user_id"], metric, granularity, quarter, month)]
              for p in people if p["user_id"] in listed
              and (p["user_id"], metric, granularity, quarter, month) in goals]
    return sum(values, ZERO) if values else None


def _prev_targets(db: Session, current_period, scope: str, scope_id: int | None,
                  period_type: str, prev_year: int, prev_quarter: int | None, prev_month: int | None,
                  people: list[dict], roster_data: dict) -> dict[str, Decimal | None]:
    period = current_period
    if period is None or period.year != prev_year:
        period = (db.query(PerfGoalPeriod)
                  .filter(PerfGoalPeriod.year == prev_year)
                  .order_by((PerfGoalPeriod.status == "active").desc(),
                            PerfGoalPeriod.id.desc()).first())
    if period is None:
        return {m: None for m in METRICS}
    granularity, quarter, month = _slot(period_type, prev_quarter, prev_month)
    goals = _goals_index(db, period.id)
    team_targets = _team_target_index(db, period.id, roster_data) if scope == "team" else {}
    listed = _listed_user_ids(db, period.id)
    return {m: _target_for(db, period, goals, team_targets, scope, scope_id, m,
                           granularity, quarter, month, people, listed) for m in METRICS}


def _metric_view(metric: str, target: Decimal | None, achieved, time_progress: float,
                 prev_rate: float | None) -> dict:
    rate = stats.rate_of(achieved, target)
    return {"target": None if target is None else _num(metric, target),
            "achieved": _num(metric, achieved),
            "rate": rate,
            "delta_pp": stats.delta_pp(rate, time_progress),
            "prev_rate": prev_rate,
            "unit": stats.METRIC_UNITS[metric]}


def _warnings(people: list[dict], goals: dict[tuple, Decimal], granularity: str,
              quarter: int | None, month: int | None, totals: dict[str, dict],
              start: date, end: date, as_of: date) -> list[dict]:
    elapsed = stats.workdays_between(start, min(as_of, end))
    remaining = stats.workdays_between(start, end) - elapsed
    rows = []
    for person in people:
        if person["user_id"] is None:
            continue
        achieved = stats.owner_total(totals, person["okki_user_id"])
        for metric in METRICS:
            target = goals.get((person["user_id"], metric, granularity, quarter, month))
            projected = stats.projected_rate(achieved[metric], target, elapsed, remaining)
            if projected is None or projected >= 0.8:
                continue
            gap = Decimal(target) - Decimal(str(achieved[metric]))
            rows.append({"user_id": person["user_id"], "name": person["name"], "metric": metric,
                         "gap": _num(metric, gap if gap > 0 else ZERO),
                         "projected_rate": projected,
                         "text": (f"{person['name']} 的{metric}按当前日均速率外推期末约完成 "
                                  f"{round(projected * 100, 1)}%，缺口 {_num(metric, gap if gap > 0 else ZERO)}"
                                  f"{stats.METRIC_UNITS[metric]}")})
    rows.sort(key=lambda row: row["projected_rate"])
    return rows[:20]


def overview(db: Session, user: dict, scope: str, scope_id: int | None,
             period_type: str, year: int | None, quarter: int | None, month: int | None) -> dict:
    period = targets.get_active_period(db)
    year, quarter, month = _period_params(period_type, year, quarter, month, period)
    roster_data = roster(db, period.id if period else None)
    listed = _listed_user_ids(db, period.id) if period else set()
    people = _scope_people(user, roster_data, scope, scope_id, listed)
    start, end = stats.period_bounds(period_type, year, quarter, month)
    people = _historical_people(db, people, roster_data, scope, start, end, scope_id)
    as_of = min(_as_of(), end)
    facts, _issues = _facts(db, people, start, as_of, scope_id if scope == "team" else None)
    totals = stats.aggregate(facts)
    time_progress = stats.workday_time_progress(start, end, _as_of())
    granularity, slot_quarter, slot_month = _slot(period_type, quarter, month)
    goals = _goals_index(db, period.id) if period else {}
    team_targets = _team_target_index(db, period.id, roster_data) if period and scope == "team" else {}
    prev_year, prev_quarter, prev_month = stats.prev_period(period_type, year, quarter, month)
    prev_start, prev_end = stats.period_bounds(period_type, prev_year, prev_quarter, prev_month)
    people = _historical_people(db, people, roster_data, scope, prev_start, prev_end, scope_id)
    prev_facts, _ = _facts(db, people, prev_start, prev_end, scope_id if scope == "team" else None)
    prev_totals = stats.aggregate(prev_facts)
    prev_granularity, pq, pm = _slot(period_type, prev_quarter, prev_month)
    prev_target_map = _prev_targets(db, period, scope, scope_id, period_type,
                                    prev_year, prev_quarter, prev_month, people, roster_data)
    metrics = {}
    for metric in METRICS:
        achieved = stats.sum_totals(totals, [p["okki_user_id"] for p in people])[metric]
        prev_achieved = stats.sum_totals(prev_totals, [p["okki_user_id"] for p in people])[metric]
        target = _target_for(db, period, goals, team_targets, scope, scope_id, metric,
                             granularity, slot_quarter, slot_month, people, listed)
        metrics[metric] = _metric_view(metric, target, achieved, time_progress,
                                       stats.rate_of(prev_achieved, prev_target_map.get(metric)))
    warnings = _warnings(people if scope != "company" else people, goals, granularity,
                         slot_quarter, slot_month, totals, start, end, _as_of())
    return {"as_of": as_of.isoformat(),
            "period_label": stats.period_label(period_type, year, quarter, month),
            "time_progress": time_progress,
            "metrics": metrics,
            "data_issues": _issues,
            "historical_return_owners": [p["okki_user_id"] for p in people if p.get("historical_return_owner")],
            "warnings": warnings}


def _trend_slots(period_type: str, start: date, end: date) -> list[tuple[str, date, date]]:
    """(label, slot_start, slot_end)：年度=月，季度=周（周一至周日），月度=日。"""
    slots = []
    if period_type == "year":
        for month in range(1, 13):
            slot_start = date(start.year, month, 1)
            slot_end = date(start.year, month, stats.month_days(start.year, month))
            slots.append((f"{start.year}-{month:02d}", slot_start, min(slot_end, end)))
    elif period_type == "quarter":
        day = start
        while day <= end:
            slot_end = min(day + timedelta(days=6 - day.weekday()), end)
            slots.append((day.isoformat(), day, slot_end))
            day = slot_end + timedelta(days=1)
    else:
        day = start
        while day <= end:
            slots.append((day.isoformat(), day, day))
            day += timedelta(days=1)
    return slots


def _count_upto(facts: list[dict], okki_id: str, role: str, upto: date) -> int:
    return len({f["company_id"] for f in facts
                if f.get("source_type") != "sales_return" and f["owner"] == okki_id and f["role"] == role and f["day"] <= upto})


def _amount_between(facts: list[dict], okki_id: str, role: str | None,
                    start: date, end: date) -> Decimal:
    return sum((f["amount"] for f in facts
                if f["owner"] == okki_id and f["day"] >= start and f["day"] <= end
                and (role is None or f["role"] == role)), ZERO)


def _count_between(facts: list[dict], okki_id: str, role: str, start: date, end: date) -> int:
    return len({f["company_id"] for f in facts
                if f.get("source_type") != "sales_return" and f["owner"] == okki_id and f["role"] == role
                and f["day"] >= start and f["day"] <= end})


def trend(db: Session, user: dict, scope: str, scope_id: int | None, metric: str,
          period_type: str, year: int | None, quarter: int | None, month: int | None) -> dict:
    if metric not in METRICS:
        raise HTTPException(422, f"metric 必须是 {'/'.join(METRICS)}")
    period = targets.get_active_period(db)
    year, quarter, month = _period_params(period_type, year, quarter, month, period)
    roster_data = roster(db, period.id if period else None)
    listed = _listed_user_ids(db, period.id) if period else set()
    people = _scope_people(user, roster_data, scope, scope_id, listed)
    start, end = stats.period_bounds(period_type, year, quarter, month)
    people = _historical_people(db, people, roster_data, scope, start, end, scope_id)
    as_of = min(_as_of(), end)
    facts, _ = _facts(db, people, start, end, scope_id if scope == "team" else None)
    granularity, slot_quarter, slot_month = _slot(period_type, quarter, month)
    goals = _goals_index(db, period.id) if period else {}
    team_targets = _team_target_index(db, period.id, roster_data) if period and scope == "team" else {}
    target = _target_for(db, period, goals, team_targets, scope, scope_id, metric,
                         granularity, slot_quarter, slot_month, people, listed)
    slots = _trend_slots(period_type, start, end)
    okki_ids = [p["okki_user_id"] for p in people]
    role = None if metric == "gmv" else ("new_sign" if metric == "new_sign" else "repeat")

    # 年度视图优先按月度拆分目标铺设计划线；无拆分则线性。
    plan_cumulative: list[float | None] | None = None
    if period is not None and period_type == "year" and target is not None:
        monthly = []
        for m_index in range(1, 13):
            q_index = (m_index - 1) // 3 + 1
            month_target = _target_for(db, period, goals, team_targets, scope, scope_id, metric,
                                       "month", q_index, m_index, people, listed)
            monthly.append(month_target)
        if any(value is not None for value in monthly):
            plan_cumulative = []
            running = ZERO
            for value in monthly:
                running += value or ZERO
                plan_cumulative.append(_num(metric, running))

    labels, cumulative_actual, plan, time_progress_line, period_actual = [], [], [], [], []
    for index, (label, slot_start, slot_end) in enumerate(slots):
        labels.append(label)
        if slot_start > as_of:
            cumulative_actual.append(None)
            period_actual.append(None)
            plan.append(None)
            time_progress_line.append(None)
            continue
        if metric in COUNT_METRICS:
            slot_value = sum(_count_between(facts, uid, role, slot_start, slot_end) for uid in okki_ids)
            cumulative = sum(_count_upto(facts, uid, role, slot_end) for uid in okki_ids)
        else:
            slot_value = sum((_amount_between(facts, uid, role, slot_start, slot_end) for uid in okki_ids), ZERO)
            cumulative = sum((_amount_between(facts, uid, role, start, slot_end) for uid in okki_ids), ZERO)
        cumulative_actual.append(_num(metric, cumulative))
        period_actual.append(_num(metric, slot_value))
        if target is None:
            plan.append(None)
            time_progress_line.append(None)
        else:
            if plan_cumulative is not None:
                plan.append(plan_cumulative[index])
            else:
                plan.append(_num(metric, Decimal(target) * (index + 1) / len(slots)))
            time_progress_line.append(_num(metric, Decimal(target) * Decimal(
                str(stats.workday_time_progress(start, end, slot_end)))))
    return {"labels": labels, "cumulative_actual": cumulative_actual, "plan": plan,
            "time_progress_line": time_progress_line, "period_actual": period_actual}


def teams_board(db: Session, user: dict, period_type: str, year: int | None,
                quarter: int | None, month: int | None) -> dict:
    period = targets.get_active_period(db)
    year, quarter, month = _period_params(period_type, year, quarter, month, period)
    roster_data = roster(db, period.id if period else None)
    access.require_board_visible(user, roster_data)
    kind, scope_department = access.visible_scope(user, roster_data)
    listed = _listed_user_ids(db, period.id) if period else set()
    start, end = stats.period_bounds(period_type, year, quarter, month)
    as_of = min(_as_of(), end)
    granularity, slot_quarter, slot_month = _slot(period_type, quarter, month)
    goals = _goals_index(db, period.id) if period else {}
    team_targets = _team_target_index(db, period.id, roster_data) if period else {}
    rows = []
    for team in roster_data["teams"]:
        if kind == "team" and team["department_id"] != scope_department:
            continue
        members = _historical_people(db, team["members"], roster_data, "team", start, as_of, team["department_id"])
        okki_ids = [m["okki_user_id"] for m in members]
        facts, _ = _facts(db, members, start, as_of, team["department_id"])
        totals = stats.aggregate(facts)
        metrics = {}
        for metric in METRICS:
            achieved = stats.sum_totals(totals, okki_ids)[metric]
            target = team_targets.get((team["department_id"], metric, granularity, slot_quarter, slot_month))
            metrics[metric] = {"target": None if target is None else _num(metric, target),
                               "achieved": _num(metric, achieved),
                               "rate": stats.rate_of(achieved, target)}
        unlisted = [m for m in members if m["user_id"] not in listed]
        included_unlisted = any(
            stats.owner_total(totals, m["okki_user_id"])["gmv"] != 0 for m in unlisted if m["okki_user_id"])
        member_rows = []
        for member in members:
            achieved_gmv = stats.owner_total(totals, member["okki_user_id"])["gmv"]
            member_target = (goals.get((member["user_id"], "gmv", granularity, slot_quarter, slot_month))
                             if member["user_id"] is not None else None)
            member_rows.append({"user_id": member["user_id"], "name": member["name"],
                                "is_captain": member.get("is_captain", False),
                                "historical_return_owner": bool(member.get("historical_return_owner")),
                                "listed": member["user_id"] in listed if member["user_id"] is not None else False,
                                "gmv_rate": stats.rate_of(achieved_gmv, member_target)})
        rows.append({"department_id": team["department_id"], "team_name": team["name"],
                     "captain_name": team["captain_name"], "member_count": len(team["members"]),
                     "metrics": metrics, "overall_rate": metrics["gmv"]["rate"],
                     "included_unlisted": included_unlisted, "members": member_rows})
    return {"rows": rows}


def ranking(db: Session, user: dict, period_type: str, year: int | None, quarter: int | None,
            month: int | None, sort: str, order: str) -> dict:
    if sort not in SORT_FIELDS:
        raise HTTPException(422, f"sort 必须是 {'/'.join(sorted(SORT_FIELDS))}")
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order 必须是 asc/desc")
    period = targets.get_active_period(db)
    year, quarter, month = _period_params(period_type, year, quarter, month, period)
    roster_data = roster(db, period.id if period else None)
    access.require_board_visible(user, roster_data)
    kind, scope_department = access.visible_scope(user, roster_data)
    listed = _listed_user_ids(db, period.id) if period else set()
    people = all_people(roster_data)
    if kind == "team":
        people = [p for p in people if p["department_id"] == scope_department]
    start, end = stats.period_bounds(period_type, year, quarter, month)
    as_of = min(_as_of(), end)
    time_progress = stats.workday_time_progress(start, end, _as_of())
    granularity, slot_quarter, slot_month = _slot(period_type, quarter, month)
    goals = _goals_index(db, period.id) if period else {}
    facts, _ = _facts(db, people, start, as_of)
    totals = stats.aggregate(facts)
    rows = []
    for person in people:
        achieved = stats.owner_total(totals, person["okki_user_id"])
        metric_views = {}
        for metric in METRICS:
            target = (goals.get((person["user_id"], metric, granularity, slot_quarter, slot_month))
                      if person["user_id"] is not None else None)
            metric_views[metric] = {"target": None if target is None else _num(metric, target),
                                    "achieved": _num(metric, achieved[metric]),
                                    "rate": stats.rate_of(achieved[metric], target)}
        gmv_rate = metric_views["gmv"]["rate"]
        delta = stats.delta_pp(gmv_rate, time_progress)
        rows.append({"rank": None, "user_id": person["user_id"], "name": person["name"],
                     "team_name": person["team_name"], "is_captain": person["is_captain"],
                     "listed": person["user_id"] in listed if person["user_id"] is not None else False,
                     **{m: metric_views[m] for m in METRICS},
                     "delta_pp": delta, "status": stats.status_for(gmv_rate, delta)})

    def sort_key(row):
        if sort == "delta_pp":
            value = row["delta_pp"]
        else:
            field, _, kind_name = sort.rpartition("_")
            value = row[field][kind_name]
        # 空值永远排最后；desc 通过取负实现，避免 reverse 把空值带到最前
        return (value is None, value if order == "asc" or value is None else -value)

    rows.sort(key=sort_key)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return {"rows": rows}


def metric_orders(db: Session, user: dict, metric: str, user_id: int | None,
                  department_id: int | None, date_from: date | None, date_to: date | None,
                  page: int, page_size: int, listed_only: bool = False) -> dict:
    if metric not in METRICS:
        raise HTTPException(422, f"metric 必须是 {'/'.join(METRICS)}")
    period = targets.get_active_period(db)
    roster_data = roster(db, period.id if period else None)
    people = all_people(roster_data)
    detail_scope, detail_department = "person", None
    if user_id is not None:
        access.require_person_visible(user, roster_data, user_id)
        people = [p for p in people if p["user_id"] == user_id]
        if not people:
            raise HTTPException(404, "该业务员不在绩效名单（未绑定 OKKI 账号）")
    elif department_id is not None:
        detail_scope, detail_department = "team", department_id
        access.require_team_visible(user, roster_data, department_id)
        people = [p for p in people if p["department_id"] == department_id]
        if not people:
            raise HTTPException(404, "战队不存在")
    else:
        kind, scope_id = access.visible_scope(user, roster_data)
        if kind == "self":
            people = [p for p in people if p["user_id"] == scope_id]
        elif kind == "team":
            people = [p for p in people if p["department_id"] == scope_id]
            detail_scope, detail_department = "team", scope_id
        elif kind == "all":
            detail_scope = "company"
    if listed_only:
        listed = _listed_user_ids(db, period.id) if period else set()
        people = [person for person in people if person["user_id"] in listed]
    year = period.year if period else _as_of().year
    start = date_from or date(year, 1, 1)
    end = date_to or min(_as_of(), date(year, 12, 31))
    if end < start:
        raise HTTPException(422, "date_to 不得早于 date_from")
    people = _historical_people(db, people, roster_data, detail_scope, start, end, detail_department)
    facts, _ = _facts(db, people, start, end, detail_department)
    if metric == "new_sign":
        facts = [f for f in facts if f["role"] == "new_sign"]
    elif metric in ("repeat_customers", "repeat_amount"):
        facts = [f for f in facts if f["role"] == "repeat"]
    names = {p["okki_user_id"]: p for p in people}
    facts.sort(key=lambda f: (f["day"], f["order_id"]), reverse=True)
    total = len(facts)
    window = facts[(page - 1) * page_size: page * page_size]
    items = [{"order_id": f["order_id"], "order_no": f["order_no"],
              "fact_key": f.get("fact_key", f["order_id"]), "source_type": f.get("source_type", "okki"),
              "return_id": f.get("return_id"),
              "customer_name": f["customer_name"], "country": f["country"],
              "amount_usd": float(f["amount"]), "account_date": f["day"].isoformat(),
              "owner_user_id": names.get(f["owner"], {}).get("user_id"),
              "owner_name": names.get(f["owner"], {}).get("name", f["owner"]),
              "flags": f["flags"]} for f in window]
    summary = {"order_count": sum(f.get("source_type") != "sales_return" for f in facts),
               "adjustment_count": sum(f.get("source_type") == "sales_return" for f in facts),
               "amount_usd": float(sum((f["amount"] for f in facts), ZERO).quantize(Decimal("0.01"))),
               "customer_count": len({f["company_id"] for f in facts if f.get("source_type") != "sales_return"})}
    return {"total": total, "page": page, "page_size": page_size, "items": items, "summary": summary}
