"""客户跟进统计：次数按记录作者，覆盖按当前负责人；所有数字可下钻核对。"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import collaboration_projection, config_service, followup_service, task_service, visibility
from app.domestic_followup.constants import NEGATIVE_RESULT_CODES, OPEN_ITEM_STATES, TRACKED_KINDS
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from app.domestic_followup.stats_coverage import coverage_for, responsible_customers
from app.domestic_followup.stats_quality import quality_stats


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _period(range_key: str = "30", date_from: date | None = None, date_to: date | None = None,
            *, today: date | None = None) -> dict:
    today = today or beijing_today()
    if range_key == "custom" or date_from or date_to:
        if not date_from or not date_to:
            raise ValueError("自定义范围需同时选择开始和结束日期")
        start, end = date_from, date_to
    elif range_key in ("w", "week"):
        start, end = today - timedelta(days=today.weekday()), today
    elif range_key in ("q", "quarter"):
        quarter_month = (today.month - 1) // 3 * 3 + 1
        start, end = today.replace(month=quarter_month, day=1), today
    elif range_key == "30":
        start, end = today - timedelta(days=29), today
    else:
        raise ValueError("不支持的时间范围")
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    if end > today:
        raise ValueError("统计结束日期不能晚于今天")
    if (end - start).days > 366:
        raise ValueError("单次统计范围不能超过 366 天")
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=(end - start).days)
    return {"start": start, "end": end, "previous_start": previous_start, "previous_end": previous_end,
            "today": today, "range": range_key}


def _records(db: Session, user_ids: list[int], start: date, end: date) -> list[DomesticFollowup]:
    if not user_ids:
        return []
    return (db.query(DomesticFollowup)
            .filter(DomesticFollowup.author_user_id.in_(user_ids), DomesticFollowup.status == "confirmed",
                    DomesticFollowup.followup_date >= start, DomesticFollowup.followup_date <= end)
            .order_by(DomesticFollowup.followup_date, DomesticFollowup.id).all())


def _roster(db: Session, config: dict, entries: list[dict]) -> list[ArkUser]:
    configured = config.get("stats_user_ids") or []
    query = db.query(ArkUser).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    if configured:
        query = query.filter(ArkUser.id.in_(configured))
    else:
        owners = {entry["owner_id"] for entry in entries}
        query = query.filter(ArkUser.id.in_(owners), ArkUser.id.in_(visibility.holder_ids("domestic_followup:write")))
    return query.order_by(ArkUser.real_name, ArkUser.id).all()


def _selected_users(db: Session, current_user: dict, users: list[ArkUser], user_id: int | None) -> list[ArkUser]:
    actor_id = visibility.uid(current_user)
    if not visibility.can_read_all(current_user):
        if user_id and user_id != actor_id:
            raise PermissionError("只能查看自己的跟进统计")
        actor = db.get(ArkUser, actor_id)
        if actor is None:
            raise LookupError("当前用户不存在")
        return [actor]
    if user_id:
        selected = next((user for user in users if user.id == user_id), None)
        if selected is None:
            raise LookupError("该业务员不在跟进统计名单中")
        return [selected]
    return users


def _is_workday(day: date, non_workdays: set[str]) -> bool:
    return day.weekday() != 6 and day.isoformat() not in non_workdays


def _daily(records: list[DomesticFollowup], start: date, end: date, non_workdays: set[str]) -> list[dict]:
    grouped = defaultdict(list)
    for row in records:
        grouped[row.followup_date].append(row)
    days = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        rows = grouped.get(day, [])
        days.append({
            "date": day.isoformat(), "count": len(rows), "reach": len({row.customer_id for row in rows}),
            "effective": sum(bool(row.result_code) and row.result_code not in NEGATIVE_RESULT_CODES for row in rows),
            "workday": _is_workday(day, non_workdays),
        })
    for index, row in enumerate(days):
        window = [candidate["count"] for candidate in days[max(0, index - 6):index + 1] if candidate["workday"]]
        row["moving_average"] = round(sum(window) / len(window), 2) if window else None
    return days


def _today_status(db: Session, user_id: int, today: date, non_workdays: set[str]) -> dict:
    rows = (db.query(DomesticFollowup.followup_date)
            .filter(DomesticFollowup.author_user_id == user_id, DomesticFollowup.status == "confirmed",
                    DomesticFollowup.followup_date <= today)
            .order_by(DomesticFollowup.followup_date.desc()).all())
    dates = [row[0] for row in rows]
    unique_dates = set(dates)
    today_count = dates.count(today)
    streak = 0
    if not today_count:
        day = today
        for _ in range(367):
            if not _is_workday(day, non_workdays):
                day -= timedelta(days=1)
                continue
            if day in unique_dates:
                break
            streak += 1
            day -= timedelta(days=1)
    return {"today_count": today_count, "last_submission_date": dates[0].isoformat() if dates else None,
            "missing_streak": streak}


def _result_counts(records: list[DomesticFollowup]) -> list[dict]:
    counts = defaultdict(int)
    for row in records:
        if row.result_code:
            counts[row.result_code] += 1
    return [{"name": name, "count": count, "effective": name not in NEGATIVE_RESULT_CODES}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _obstacle_counts(records: list[DomesticFollowup]) -> list[dict]:
    counts = defaultdict(int)
    for row in records:
        for obstacle in row.obstacles or []:
            counts[obstacle] += 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _person(db: Session, user: ArkUser, period: dict, config: dict, entries: list[dict]) -> dict:
    start, end, today = period["start"], period["end"], period["today"]
    records = _records(db, [user.id], start, end)
    previous = _records(db, [user.id], period["previous_start"], period["previous_end"])
    resulted = [row for row in records if row.result_code]
    previous_resulted = [row for row in previous if row.result_code]
    effective = sum(row.result_code not in NEGATIVE_RESULT_CODES for row in resulted)
    previous_effective = sum(row.result_code not in NEGATIVE_RESULT_CODES for row in previous_resulted)
    coverage = coverage_for(entries, user.id, config["frequency_days"], today)
    previous_coverage = coverage_for(entries, user.id, config["frequency_days"], period["previous_end"], previous=True)
    non_workdays = set(config.get("stats_non_workdays") or [])
    days = _daily(records, start, end, non_workdays)
    workdays = [row for row in days if row["workday"]]
    quality = quality_stats(db, user.id, records, start, end, today)
    return {
        "user": {"id": user.id, "real_name": user.real_name},
        "kpis": {
            "count": len(records), "reach": len({row.customer_id for row in records}),
            "effective_rate": _ratio(effective, len(resulted)),
            "overdue": coverage["overdue_count"], "owner_customers": coverage["owner_customer_count"],
            "previous_count": len(previous), "previous_reach": len({row.customer_id for row in previous}),
            "previous_effective_rate": _ratio(previous_effective, len(previous_resulted)),
            "previous_overdue": previous_coverage["overdue_count"],
        },
        "days": days,
        "rhythm_summary": {
            "average": round(sum(row["count"] for row in workdays) / len(workdays), 2) if workdays else None,
            "best": max((row["count"] for row in days), default=0),
            "gaps": sum(row["count"] == 0 and row["date"] != today.isoformat() for row in workdays),
        },
        "today": _today_status(db, user.id, today, non_workdays),
        "coverage": coverage["coverage"], "overdue_customers": coverage["overdue_customers"][:5],
        "ungraded_customers": coverage["ungraded_customers"],
        "results": _result_counts(records), "obstacles": _obstacle_counts(records),
        **quality,
    }


def _mean(values, digits=2):
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), digits) if present else None


def _team_average(people: list[dict]) -> dict:
    return {
        "count": _mean([person["kpis"]["count"] for person in people]),
        "reach": _mean([person["kpis"]["reach"] for person in people]),
        "effective_rate": _mean([person["kpis"]["effective_rate"] for person in people], 4),
        "daily_count": _mean([person["rhythm_summary"]["average"] for person in people]),
        "quality": {key: _mean([person["quality"][key]["value"] for person in people], 4)
                    for key in ("next_step", "commitment", "effective_progress")},
    }


def _base(db: Session, range_key: str, date_from: date | None, date_to: date | None) -> tuple[dict, dict, list[dict]]:
    period = _period(range_key, date_from, date_to)
    config = config_service.get_config(db)
    entries = responsible_customers(db, period["today"], period["previous_end"])
    return period, config, entries


def personal(db: Session, current_user: dict, *, range_key: str = "30", date_from: date | None = None,
             date_to: date | None = None, user_id: int | None = None) -> dict:
    period, config, entries = _base(db, range_key, date_from, date_to)
    roster = _roster(db, config, entries)
    users = _selected_users(db, current_user, roster, user_id)
    people = [_person(db, user, period, config, entries) for user in users]
    all_people = people if {user.id for user in users} == {user.id for user in roster} else [_person(db, user, period, config, entries) for user in roster]
    show_average = visibility.can_read_all(current_user) or len(roster) >= 4
    average = _team_average(all_people) if show_average and all_people else None
    if average:
        for person in people:
            for key, value in average["quality"].items():
                person["quality"][key]["team_average"] = value
    return {
        "period": {key: value.isoformat() if isinstance(value, date) else value
                   for key, value in period.items() if key != "today"},
        "today": period["today"].isoformat(), "can_read_all": visibility.can_read_all(current_user),
        "roster": [{"id": user.id, "real_name": user.real_name} for user in roster]
                  if visibility.can_read_all(current_user) else [],
        "people": people, "team_average": average,
        "missing": missing_today(db, current_user),
    }


def _signals(current: list[DomesticFollowup], previous: list[DomesticFollowup]) -> list[dict]:
    def counts(rows):
        result = defaultdict(set)
        for row in rows:
            for signal in row.state_changes or []:
                if row.customer_id:
                    result[signal].add(row.customer_id)
        return result
    now, before = counts(current), counts(previous)
    rows = [{"name": name, "count": len(now.get(name, set())), "previous_count": len(before.get(name, set()))}
            for name in set(now) | set(before)]
    rows = [row for row in rows if row["count"] != row["previous_count"]]
    rows.sort(key=lambda row: (-abs(row["count"] - row["previous_count"]), -row["count"], row["name"]))
    return rows[:6]


def _issues(db: Session, start: date, end: date) -> list[dict]:
    rows = (db.query(DomesticFollowupItem)
            .filter(DomesticFollowupItem.kind.in_(TRACKED_KINDS),
                    DomesticFollowupItem.status != "withdrawn",
                    DomesticFollowupItem.created_at >= datetime.combine(start, time.min),
                    DomesticFollowupItem.created_at < datetime.combine(end + timedelta(days=1), time.min)).all())
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.category or "其他"].append(row)
    result = []
    for category, items in grouped.items():
        durations = [(row.resolved_at - row.created_at).total_seconds() / 86400
                     for row in items if row.resolved_at and row.created_at]
        result.append({"category": category, "count": len(items),
                       "average_resolution_days": round(sum(durations) / len(durations), 1) if durations else None,
                       "open_count": sum(row.status in OPEN_ITEM_STATES for row in items)})
    return sorted(result, key=lambda row: (-row["count"], row["category"]))


def _coordination(db: Session) -> list[dict]:
    from app.domestic_followup.collaboration_models import FollowupResponsibility

    counts = {"no_progress": 0, "development_task_overdue": 0, "handoff_overdue": 0}
    rows = (db.query(DomesticCustomer, FollowupResponsibility)
            .join(FollowupResponsibility, FollowupResponsibility.customer_id == DomesticCustomer.id).all())
    for customer, responsibility in rows:
        handoff = collaboration_projection.pending_handoff(db, customer.id)
        reasons = collaboration_projection.coordination_reasons(db, customer, responsibility, handoff)
        for key in counts:
            counts[key] += key in reasons
    labels = {"no_progress": "30 天无有效推进的客户", "development_task_overdue": "开发待办逾期满 30 天",
              "handoff_overdue": f"交接待接收满 {collaboration_projection.pending_handoff_days(db)} 天"}
    return [{"key": key, "label": labels[key], "count": value} for key, value in counts.items()]


def team(db: Session, current_user: dict, *, range_key: str = "30", date_from: date | None = None,
         date_to: date | None = None) -> dict:
    if not visibility.can_read_all(current_user):
        raise PermissionError("需要全部客户跟进查看权限")
    period, config, entries = _base(db, range_key, date_from, date_to)
    roster = _roster(db, config, entries)
    ids = [user.id for user in roster]
    current = _records(db, ids, period["start"], period["end"])
    previous = _records(db, ids, period["previous_start"], period["previous_end"])
    people = [_person(db, user, period, config, entries) for user in roster]
    resulted = [row for row in current if row.result_code]
    previous_resulted = [row for row in previous if row.result_code]
    effective = sum(row.result_code not in NEGATIVE_RESULT_CODES for row in resulted)
    previous_effective = sum(row.result_code not in NEGATIVE_RESULT_CODES for row in previous_resulted)
    non_workdays = set(config.get("stats_non_workdays") or [])
    submitted = sum(person["today"]["today_count"] > 0 for person in people)
    return {
        "period": {key: value.isoformat() if isinstance(value, date) else value
                   for key, value in period.items() if key != "today"},
        "today": period["today"].isoformat(),
        "kpis": {
            "count": len(current), "reach": len({row.customer_id for row in current}),
            "effective_rate": _ratio(effective, len(resulted)),
            "overdue": sum(person["kpis"]["overdue"] for person in people),
            "today_submitted": submitted, "roster_count": len(roster),
            "previous_count": len(previous), "previous_reach": len({row.customer_id for row in previous}),
            "previous_effective_rate": _ratio(previous_effective, len(previous_resulted)),
            "previous_overdue": sum(person["kpis"]["previous_overdue"] for person in people),
        },
        "days": _daily(current, period["start"], period["end"], non_workdays),
        "people": [{"user": person["user"], "kpis": person["kpis"], "quality": person["quality"],
                    "days": person["days"]} for person in people],
        "missing": missing_today(db, current_user), "signals": _signals(current, previous),
        "obstacles": _obstacle_counts(current), "issues": _issues(db, period["start"], period["end"]),
        "coordination": _coordination(db),
    }


def missing_today(db: Session, current_user: dict) -> dict:
    today = beijing_today()
    config = config_service.get_config(db)
    non_workdays = set(config.get("stats_non_workdays") or [])
    applicable = _is_workday(today, non_workdays)
    entries = responsible_customers(db, today, today - timedelta(days=1))
    roster = _roster(db, config, entries)
    if not visibility.can_read_all(current_user):
        actor_id = visibility.uid(current_user)
        roster = [user for user in roster if user.id == actor_id]
        if not roster:
            actor = db.get(ArkUser, actor_id)
            roster = [actor] if actor else []
    statuses = [{"user": {"id": user.id, "real_name": user.real_name},
                 **_today_status(db, user.id, today, non_workdays)} for user in roster]
    missing = [row for row in statuses if not row["today_count"]]
    return {"applicable": applicable, "date": today.isoformat(), "generated_at": beijing_now().isoformat(),
            "submitted": len(statuses) - len(missing), "total": len(statuses),
            "users": [] if not applicable else missing,
            "self": statuses[0] if not visibility.can_read_all(current_user) and statuses else None}


def rhythm(db: Session, current_user: dict, *, scope: str = "personal", range_key: str = "30",
           date_from: date | None = None, date_to: date | None = None, user_id: int | None = None) -> dict:
    if scope == "team":
        data = team(db, current_user, range_key=range_key, date_from=date_from, date_to=date_to)
        return {"scope": scope, "days": data["days"], "people": data["people"]}
    data = personal(db, current_user, range_key=range_key, date_from=date_from, date_to=date_to, user_id=user_id)
    person = data["people"][0] if data["people"] else None
    return {"scope": scope, "days": person["days"] if person else [],
            "team_daily_average": (data["team_average"] or {}).get("daily_count")}


def drilldown(db: Session, current_user: dict, *, kind: str = "records", user_id: int | None = None,
              date_from: date | None = None, date_to: date | None = None, followup_date: date | None = None,
              result_code: str | None = None, obstacle: str | None = None, state_change: str | None = None,
              quality: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    actor_id = visibility.uid(current_user)
    if user_id and not visibility.can_read_all(current_user) and user_id != actor_id:
        raise PermissionError("只能查看自己的统计明细")
    if kind == "overdue":
        period, config, entries = _base(db, "custom", date_from or beijing_today(), date_to or beijing_today())
        roster = _roster(db, config, entries)
        users = _selected_users(db, current_user, roster, user_id)
        rows = []
        for user in users:
            coverage = coverage_for(entries, user.id, config["frequency_days"], period["today"])
            rows.extend({**row, "owner_name": user.real_name} for row in coverage["overdue_customers"])
        rows.sort(key=lambda row: (-row["overdue_days"], row["shop_name"]))
        total = len(rows)
        start = (page - 1) * page_size
        return {"kind": kind, "items": rows[start:start + page_size], "total": total, "page": page,
                "page_size": page_size}
    period, config, entries = _base(db, "30", date_from, date_to)
    users = _selected_users(db, current_user, _roster(db, config, entries), user_id)
    author_ids = [user.id for user in users]
    if kind == "plans":
        tasks = (db.query(DomesticFollowupTask).filter(
            DomesticFollowupTask.assignee_user_id.in_(author_ids), DomesticFollowupTask.task_type == "plan",
            DomesticFollowupTask.due_date >= period["start"], DomesticFollowupTask.due_date <= period["end"],
        ).order_by(DomesticFollowupTask.due_date.desc(), DomesticFollowupTask.id.desc()).all())
        start = (page - 1) * page_size
        items = [{"id": task.id, "customer_id": task.customer_id, "title": task.title,
                  "due_date": task.due_date.isoformat(), "status": task.status,
                  "snooze_count": task.snooze_count,
                  "on_time": bool(task.status == "done" and task.snooze_count == 0 and task.closed_at
                                  and task.closed_at.date() <= task.due_date)} for task in tasks[start:start + page_size]]
        return {"kind": kind, "items": items, "total": len(tasks), "page": page, "page_size": page_size}
    query = db.query(DomesticFollowup).filter(DomesticFollowup.status == "confirmed",
                                            DomesticFollowup.author_user_id.in_(author_ids))
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        query = query.filter(condition)
    if user_id:
        query = query.filter(DomesticFollowup.author_user_id == user_id)
    if followup_date:
        date_from = date_to = followup_date
    else:
        date_from, date_to = period["start"], period["end"]
    if date_from:
        query = query.filter(DomesticFollowup.followup_date >= date_from)
    if date_to:
        query = query.filter(DomesticFollowup.followup_date <= date_to)
    if result_code:
        query = query.filter(DomesticFollowup.result_code == result_code)
    rows = query.order_by(DomesticFollowup.followup_date.desc(), DomesticFollowup.id.desc()).all()
    if obstacle:
        rows = [row for row in rows if obstacle in (row.obstacles or [])]
    if state_change:
        rows = [row for row in rows if state_change in (row.state_changes or [])]
    if quality == "next_step":
        rows = [row for row in rows if row.next_date is not None]
    elif quality == "effective_progress":
        rows = [row for row in rows if row.result_code and row.effective_progress]
    if kind == "signal":
        customer_ids = sorted({row.customer_id for row in rows if row.customer_id})
        customers = (db.query(DomesticCustomer).filter(DomesticCustomer.id.in_(customer_ids))
                     .order_by(DomesticCustomer.shop_name).all()) if customer_ids else []
        total = len(customers)
        start = (page - 1) * page_size
        items = [{"customer_id": row.id, "shop_name": row.shop_name, "level": row.customer_level}
                 for row in customers[start:start + page_size]]
    else:
        total = len(rows)
        start = (page - 1) * page_size
        items = [followup_service.serialize(db, row) for row in rows[start:start + page_size]]
    return {"kind": kind, "items": items, "total": total, "page": page, "page_size": page_size}
