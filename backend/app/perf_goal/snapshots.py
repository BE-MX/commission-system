"""统计快照：看板日更与报告生成前的冻结点。"""
from datetime import date

from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.perf_goal import statistics as stats, trend
from app.perf_goal.models import METRICS, PerfSnapshot
from app.perf_goal.teams import all_people, roster


def _scope_people(roster_data: dict, scope: str, scope_id: str, listed: set[int]) -> list[dict]:
    people = all_people(roster_data)
    if scope == "company":
        return [p for p in people if p["user_id"] in listed]
    if scope == "team":
        department_id = int(scope_id)
        return [p for p in people if p["department_id"] == department_id]
    user_id = int(scope_id)
    return [p for p in people if p["user_id"] == user_id]


def _scope_name(roster_data: dict, scope: str, scope_id: str) -> str:
    if scope == "company":
        return "公司整体"
    if scope == "team":
        team = next((t for t in roster_data["teams"] if t["department_id"] == int(scope_id)), None)
        return team["name"] if team else scope_id
    person = next((p for p in all_people(roster_data) if p["user_id"] == int(scope_id)), None)
    return person["name"] if person else scope_id


def build_payload(db: Session, period, scope: str, scope_id: str, as_of: date) -> dict:
    """Year-granularity frozen facts for one scope; every number the AI may quote lives here."""
    roster_data = roster(db, period.id)
    listed = trend._listed_user_ids(db, period.id)
    people = _scope_people(roster_data, scope, scope_id, listed)
    year = period.year
    start, end = date(year, 1, 1), date(year, 12, 31)
    capped = min(as_of, end)
    facts, issues = trend._facts(db, people, start, capped)
    totals = stats.aggregate(facts)
    time_progress = stats.workday_time_progress(start, end, as_of)
    goals = trend._goals_index(db, period.id)
    team_targets = trend._team_target_index(db, period.id, roster_data) if scope == "team" else {}
    scope_key: int | None = None if scope == "company" else int(scope_id)
    metrics = {}
    for metric in METRICS:
        achieved = stats.sum_totals(totals, [p["okki_user_id"] for p in people])[metric]
        target = trend._target_for(db, period, goals, team_targets, scope, scope_key, metric,
                                   "year", None, None, people, listed)
        rate = stats.rate_of(achieved, target)
        metrics[metric] = {"target": None if target is None else trend._num(metric, target),
                           "achieved": trend._num(metric, achieved), "rate": rate,
                           "delta_pp": stats.delta_pp(rate, time_progress),
                           "unit": stats.METRIC_UNITS[metric]}
    people_rows = []
    for person in people:
        achieved = stats.owner_total(totals, person["okki_user_id"])
        person_metrics = {}
        for metric in METRICS:
            target = goals.get((person["user_id"], metric, "year", None, None)) if person["user_id"] else None
            person_metrics[metric] = {"target": None if target is None else trend._num(metric, target),
                                      "achieved": trend._num(metric, achieved[metric]),
                                      "rate": stats.rate_of(achieved[metric], target)}
        gmv_rate = person_metrics["gmv"]["rate"]
        delta = stats.delta_pp(gmv_rate, time_progress)
        people_rows.append({"user_id": person["user_id"], "name": person["name"],
                            "team_name": person["team_name"], "is_captain": person["is_captain"],
                            "listed": person["user_id"] in listed if person["user_id"] else False,
                            "metrics": person_metrics, "delta_pp": delta,
                            "status": stats.status_for(gmv_rate, delta)})
    people_rows.sort(key=lambda row: (row["metrics"]["gmv"]["rate"] is None,
                                      -(row["metrics"]["gmv"]["rate"] or 0)))
    elapsed = stats.workdays_between(start, capped)
    remaining = stats.workdays_between(start, end) - elapsed
    warnings = trend._warnings(people, goals, "year", None, None, totals, start, end, as_of)
    unlisted = [p for p in people if p["user_id"] not in listed]
    included_unlisted = scope == "team" and any(
        stats.owner_total(totals, p["okki_user_id"])["gmv"] > 0 for p in unlisted if p["okki_user_id"])
    return {"as_of": as_of.isoformat(), "year": year,
            "period_label": stats.period_label("year", year, None, None),
            "scope": scope, "scope_id": scope_id,
            "scope_name": _scope_name(roster_data, scope, scope_id),
            "time_progress": time_progress, "elapsed_workdays": elapsed,
            "remaining_workdays": remaining, "metrics": metrics,
            "people": people_rows, "warnings": warnings,
            "included_unlisted": included_unlisted,
            "issue_count": len(issues),
            "frozen_at": beijing_now().isoformat()}


def upsert_snapshot(db: Session, period, scope: str, scope_id: str, as_of: date) -> PerfSnapshot:
    payload = build_payload(db, period, scope, scope_id, as_of)
    row = (db.query(PerfSnapshot)
           .filter_by(period_type="year", year=period.year, quarter=None, month=None,
                      scope=scope, scope_id=str(scope_id)).first())
    if row is None:
        row = PerfSnapshot(period_type="year", year=period.year, quarter=None, month=None,
                           scope=scope, scope_id=str(scope_id))
        db.add(row)
    row.as_of = as_of
    row.payload = payload
    row.created_at = beijing_now()
    db.flush()
    return row


def refresh_year_snapshots(db: Session, period, as_of: date | None = None) -> dict[str, int]:
    """刷新 company/team/person 三级 year 口径快照；返回各级数量。"""
    as_of = as_of or beijing_today()
    roster_data = roster(db, period.id)
    listed = trend._listed_user_ids(db, period.id)
    counts = {"company": 0, "team": 0, "person": 0}
    upsert_snapshot(db, period, "company", "company", as_of)
    counts["company"] = 1
    for team in roster_data["teams"]:
        upsert_snapshot(db, period, "team", str(team["department_id"]), as_of)
        counts["team"] += 1
    for person in all_people(roster_data):
        if person["user_id"] in listed:
            upsert_snapshot(db, period, "person", str(person["user_id"]), as_of)
            counts["person"] += 1
    db.commit()
    return counts


def get_year_snapshot(db: Session, year: int, scope: str, scope_id: str) -> PerfSnapshot | None:
    return (db.query(PerfSnapshot)
            .filter_by(period_type="year", year=year, quarter=None, month=None,
                       scope=scope, scope_id=str(scope_id)).first())
