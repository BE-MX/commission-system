"""Deterministic private-customer candidate evaluation, independent of ORM/model calls."""

from dataclasses import dataclass
from datetime import date, datetime
import hashlib

from .calendar import complete_days

R1 = "R1_UNREPLIED"
R2 = "R2_FOLLOWUP_DUE"
R3 = "R3_RECHECK_DUE"
R4 = "R4_NEW_ACTIVITY"
R5 = "R5_REPURCHASE"
R6 = "R6_LONG_SILENT"
R7 = "R7_AWAITING_CUSTOMER"
R8 = "R8_NEW_LEAD"
WEIGHTS = {R1: 6, R2: 4, R3: 3, R4: 0, R5: 3, R6: 2, R7: 4, R8: 3}
GRADE_FACTORS = dict(zip("SABCDE", (1.8, 1.5, 1.2, 1, 0.8, 0.6)))
REASONS = {
    R1: "客户的 WhatsApp 消息待回复",
    R2: "本人设置的跟进日期已到",
    R3: "有待确认事项到期",
    R4: "新增订单或背调资料",
    R5: "已超过历史复购间隔",
    R6: "方舟可见渠道已较久未联系",
    R7: "我方消息发出后，客户尚未回复",
    R8: "新建客户近期在方舟可见渠道没有接触记录",
}


def as_day(value):
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(value[:10]) if isinstance(value, str) else value


def as_time(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    return value


@dataclass
class Candidate:
    company_id: int
    codes: list
    score: float
    wait: float
    cohort: str
    disposition: str = "quota"


def evaluate(source, state, now, user_id, config=None, calendar=None):
    cfg = config or {}
    today = now.date()
    due = as_day(state.get("next_followup_date"))
    if as_day(state.get("snoozed_until") or today) > today:
        return None
    grade = source.get("grade")
    touch = as_day(source.get("last_touch_at"))
    conv = source.get("conversations") or []
    inbound = [
        as_time(c["last_at"])
        for c in conv
        if c.get("direction") == "inbound" and c.get("last_at")
    ]
    outbound = [
        as_day(c["last_at"])
        for c in conv
        if c.get("direction") == "outbound" and c.get("last_at")
    ]
    threshold = cfg.get("awaiting_days", {}).get(
        grade or "", 3 if grade in ("S", "A") else 5 if grade == "B" else 7
    )
    codes = []
    if inbound:
        codes.append(R1)
    if (
        outbound
        and complete_days(min(outbound), today, calendar, threshold + 1) > threshold
    ):
        codes.append(R7)
    if due and due <= today:
        codes.append(R2)
    check = as_day(state.get("recheck_date"))
    if (
        check
        and check <= today
        and state.get("recheck_condition")
        and (state.get("recheck_count") or 0) < 2
    ):
        codes.append(R3)
    created = as_day(source.get("created_at"))
    if (
        created
        and 0 <= (today - created).days <= 30
        and source.get("order_count") == 0
        and (not touch or complete_days(touch, today, calendar, 7) >= 7)
    ):
        codes.append(R8)
    days = sorted(map(as_day, source.get("order_days") or []))
    last = as_day(source.get("last_order_date"))
    if len(days) >= 3 and last and source.get("in_transit") is False:
        span = (days[-1] - days[0]).days
        if span > 0 and (today - last).days * 10 * (len(days) - 1) > 13 * span:
            codes.append(R5)
    silence = 15 if grade in ("S", "A") else 30 if grade == "B" else None
    if (
        conv
        and touch
        and silence
        and complete_days(touch, today, calendar, silence + 1) > silence
    ):
        codes.append(R6)
    activity = as_time(source.get("activity_at"))
    analyzed = as_time(state.get("last_analyzed_at"))
    if activity and (not analyzed or activity > analyzed):
        codes.append(R4)
    cooldowns = state.get("rule_cooldowns") or {}
    codes = [c for c in codes if not cooldowns.get(c) or as_day(cooldowns[c]) <= today]
    if not codes:
        return None
    seasonal = (today.month, today.day) >= (12, 20) or (today.month, today.day) <= (
        1,
        5,
    )
    weights = WEIGHTS | cfg.get("weights", {})
    score = sum(
        weights[c]
        * (cfg.get("season_factor", 0.5) if seasonal and c in (R5, R6) else 1)
        for c in codes
    )
    company_id = int(source["company_id"])
    experiment = cfg.get("experiment_version", "desk_holdout_v1")
    bucket = (
        int.from_bytes(
            hashlib.sha256(f"{experiment}:{user_id}:{company_id}".encode()).digest()[
                :8
            ],
            "big",
        )
        % 100
    )
    reminders = set(codes) - {R4}
    cohort = "ineligible"
    if reminders and reminders <= {R5, R6}:
        cohort = "holdout" if bucket < cfg.get("holdout_percent", 15) else "treatment"
    return Candidate(
        company_id,
        codes,
        round(score * GRADE_FACTORS.get(grade, 1), 4),
        (now - min(inbound)).total_seconds() if R1 in codes else 0,
        cohort,
    )


def allocate(candidates, quota=40):
    ranked = sorted(
        candidates, key=lambda c: (c.codes == [R4], -c.score, -c.wait, c.company_id)
    )
    for candidate in ranked:
        if candidate.cohort == "holdout":
            candidate.disposition = "holdout"
        elif quota > 0:
            candidate.disposition = "eligible"
            quota -= 1
        else:
            candidate.disposition = "quota"
    return ranked
