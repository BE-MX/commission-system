"""目标批次、人员目标、拆分与战队目标汇总；全部写操作留痕。"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.perf_goal.access import actor_id
from app.perf_goal.config_store import load_config
from app.perf_goal.models import (GRANULARITIES, METRICS, PerfGoal, PerfGoalAudit,
                                  PerfGoalPeriod, PerfGoalTeamOverride)
from app.perf_goal.teams import roster

CENT = Decimal("0.01")
COUNT_METRICS = {"new_sign", "repeat_customers"}


def _quantize(metric: str, value: Decimal) -> Decimal:
    if metric in COUNT_METRICS:
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def get_period(db: Session, period_id: int) -> PerfGoalPeriod:
    period = db.get(PerfGoalPeriod, period_id)
    if period is None:
        raise HTTPException(404, "目标批次不存在")
    return period


def get_active_period(db: Session) -> PerfGoalPeriod | None:
    return (db.query(PerfGoalPeriod).filter(PerfGoalPeriod.status == "active")
            .order_by(PerfGoalPeriod.year.desc(), PerfGoalPeriod.id.desc()).first())


def _period_json(period: PerfGoalPeriod) -> dict:
    return {"id": period.id, "year": period.year, "name": period.name, "status": period.status,
            "version": period.version, "published_by": period.published_by,
            "published_at": period.published_at.isoformat() if period.published_at else None}


def list_periods(db: Session) -> list[dict]:
    rows = db.query(PerfGoalPeriod).order_by(PerfGoalPeriod.year.desc(), PerfGoalPeriod.id.desc()).all()
    return [_period_json(row) for row in rows]


def create_period(db: Session, user: dict, payload) -> dict:
    exists = (db.query(PerfGoalPeriod)
              .filter(PerfGoalPeriod.year == payload.year, PerfGoalPeriod.name == payload.name).first())
    if exists is not None:
        raise HTTPException(409, "同年度同名目标批次已存在")
    uid = actor_id(user)
    period = PerfGoalPeriod(year=payload.year, name=payload.name, status="draft", created_by=uid)
    db.add(period)
    db.commit()
    db.refresh(period)
    return _period_json(period)


def activate_period(db: Session, user: dict, period_id: int) -> dict:
    period = get_period(db, period_id)
    uid = actor_id(user)
    now = beijing_now()
    for other in db.query(PerfGoalPeriod).filter(PerfGoalPeriod.status == "active",
                                                 PerfGoalPeriod.id != period.id).all():
        other.status = "archived"
        other.updated_at = now
    period.status = "active"
    period.published_by = uid
    period.published_at = now
    period.updated_at = now
    db.commit()
    return _period_json(period)


def _user_names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(user_ids)).all()
    return {row.id: row.real_name for row in rows}


def _slot_field(metric: str, granularity: str, quarter: int | None, month: int | None) -> str:
    if granularity == "month":
        return f"{metric}:month:{month}"
    if granularity == "quarter":
        return f"{metric}:quarter:{quarter}"
    return f"{metric}:year"


def _goal_key(row) -> tuple:
    return (row.user_id, row.metric, row.granularity, row.quarter, row.month)


def _existing_goals(db: Session, period_id: int) -> dict[tuple, PerfGoal]:
    rows = db.query(PerfGoal).filter(PerfGoal.period_id == period_id).all()
    return {(r.user_id, r.metric, r.granularity, r.quarter, r.month): r for r in rows}


def _mark_team_stale(db: Session, period_id: int, roster_data: dict,
                     changes: list[tuple[int, str, str, int | None, int | None]]) -> None:
    team_by_user = {}
    for team in roster_data["teams"]:
        for member in team["members"]:
            if member["user_id"] is not None:
                team_by_user.setdefault(member["user_id"], []).append(team["department_id"])
    for user_id, metric, granularity, quarter, month in changes:
        for department_id in team_by_user.get(user_id, []):
            (db.query(PerfGoalTeamOverride)
             .filter(PerfGoalTeamOverride.period_id == period_id,
                     PerfGoalTeamOverride.department_id == department_id,
                     PerfGoalTeamOverride.metric == metric,
                     PerfGoalTeamOverride.granularity == granularity,
                     PerfGoalTeamOverride.quarter.is_(quarter) if quarter is None
                     else PerfGoalTeamOverride.quarter == quarter,
                     PerfGoalTeamOverride.month.is_(month) if month is None
                     else PerfGoalTeamOverride.month == month)
             .update({"stale": True}, synchronize_session=False))


def _audit(db: Session, period_id: int, object_type: str, object_ref: str, object_label: str,
           field: str, old_value, new_value, operator: tuple[int, str], reason: str) -> None:
    db.add(PerfGoalAudit(period_id=period_id, object_type=object_type, object_ref=object_ref,
                         object_label=object_label, field=field,
                         old_value=None if old_value is None else str(old_value),
                         new_value=None if new_value is None else str(new_value),
                         created_by=operator[0], operator_name=operator[1],
                         reason=reason or "", created_at=beijing_now()))


def _operator(db: Session, user: dict) -> tuple[int, str]:
    uid = actor_id(user)
    row = db.get(ArkUser, uid)
    return uid, (row.real_name if row else user.get("name") or str(uid))


def _goal_json(row: PerfGoal, names: dict[int, str]) -> dict:
    return {"user_id": row.user_id, "user_name": names.get(row.user_id, str(row.user_id)),
            "metric": row.metric, "granularity": row.granularity, "quarter": row.quarter,
            "month": row.month, "target_value": float(row.target_value)}


def list_goals(db: Session, period_id: int, granularity: str | None) -> dict:
    get_period(db, period_id)
    query = db.query(PerfGoal).filter(PerfGoal.period_id == period_id)
    if granularity:
        if granularity not in GRANULARITIES:
            raise HTTPException(422, "granularity 必须是 year/quarter/month")
        query = query.filter(PerfGoal.granularity == granularity)
    rows = query.order_by(PerfGoal.user_id, PerfGoal.metric, PerfGoal.id).all()
    names = _user_names(db, {row.user_id for row in rows})
    return {"rows": [_goal_json(row, names) for row in rows]}


def save_goals(db: Session, period_id: int, user: dict, payload) -> dict:
    period = get_period(db, period_id)
    if period.status == "archived":
        raise HTTPException(409, "已归档批次不允许修改")
    existing = _existing_goals(db, period_id)
    names = _user_names(db, {row.user_id for row in payload.rows})
    operator = _operator(db, user)
    roster_data = roster(db, period_id)
    now = beijing_now()
    audits = 0
    changes = []
    for row in payload.rows:
        if row.user_id not in names:
            raise HTTPException(422, f"用户 {row.user_id} 不存在")
        key = _goal_key(row)
        target = _quantize(row.metric, Decimal(str(row.target_value)))
        field = _slot_field(row.metric, row.granularity, row.quarter, row.month)
        label = names.get(row.user_id, str(row.user_id))
        current = existing.get(key)
        if current is None:
            db.add(PerfGoal(period_id=period_id, user_id=row.user_id, metric=row.metric,
                            granularity=row.granularity, quarter=row.quarter, month=row.month,
                            target_value=target, updated_by=operator[0], updated_at=now))
            _audit(db, period_id, "person_goal", str(row.user_id), label, field,
                   None, _fmt(target), operator, payload.reason)
            audits += 1
            changes.append((row.user_id, row.metric, row.granularity, row.quarter, row.month))
        elif Decimal(current.target_value) != target:
            _audit(db, period_id, "person_goal", str(row.user_id), label, field,
                   _fmt(Decimal(current.target_value)), _fmt(target), operator, payload.reason)
            current.target_value = target
            current.updated_by = operator[0]
            current.updated_at = now
            audits += 1
            changes.append((row.user_id, row.metric, row.granularity, row.quarter, row.month))
    period.version += 1
    period.updated_at = now
    _mark_team_stale(db, period_id, roster_data, changes)
    db.commit()
    return {"version": period.version, "audit_count": audits}


def _split_slots(source_value: Decimal, weights: list[Decimal], metric: str) -> list[Decimal]:
    total_weight = sum(weights)
    slots = [_quantize(metric, source_value * w / total_weight) for w in weights]
    slots[-1] = source_value - sum(slots[:-1])
    return slots


def split_goals(db: Session, period_id: int, user: dict, payload) -> dict:
    period = get_period(db, period_id)
    existing = _existing_goals(db, period_id)
    weights = [Decimal(str(w)) for w in payload.weights]
    previews = []
    if payload.source == "year":
        source_rows = [row for key, row in existing.items()
                       if key[1] == payload.metric and key[2] == "year"
                       and (payload.user_ids is None or key[0] in set(payload.user_ids))]
        names = _user_names(db, {row.user_id for row in source_rows})
        for source in sorted(source_rows, key=lambda r: r.user_id):
            entries = []
            for index, value in enumerate(_split_slots(Decimal(source.target_value), weights, payload.metric), 1):
                current = existing.get((source.user_id, payload.metric, "quarter", index, None))
                entries.append({"quarter": index, "month": None,
                                "old_value": None if current is None else float(current.target_value),
                                "new_value": float(value)})
            previews.append({"user_id": source.user_id,
                             "user_name": names.get(source.user_id, str(source.user_id)),
                             "entries": entries})
    else:
        source_rows = [row for key, row in existing.items()
                       if key[1] == payload.metric and key[2] == "quarter"
                       and (payload.user_ids is None or key[0] in set(payload.user_ids))]
        names = _user_names(db, {row.user_id for row in source_rows})
        for source in sorted(source_rows, key=lambda r: (r.user_id, r.quarter)):
            entries = []
            for offset, value in enumerate(_split_slots(Decimal(source.target_value), weights, payload.metric)):
                month = (source.quarter - 1) * 3 + offset + 1
                current = existing.get((source.user_id, payload.metric, "month", source.quarter, month))
                entries.append({"quarter": source.quarter, "month": month,
                                "old_value": None if current is None else float(current.target_value),
                                "new_value": float(value)})
            previews.append({"user_id": source.user_id,
                             "user_name": names.get(source.user_id, str(source.user_id)),
                             "entries": entries})
    if not payload.apply:
        return {"preview": previews, "applied": False}
    if period.status == "archived":
        raise HTTPException(409, "已归档批次不允许修改")
    operator = _operator(db, user)
    roster_data = roster(db, period_id)
    now = beijing_now()
    granularity = payload.target
    for person in previews:
        for entry in person["entries"]:
            key = (person["user_id"], payload.metric, granularity, entry["quarter"], entry["month"])
            target = _quantize(payload.metric, Decimal(str(entry["new_value"])))
            field = _slot_field(payload.metric, granularity, entry["quarter"], entry["month"])
            current = existing.get(key)
            if current is None:
                db.add(PerfGoal(period_id=period_id, user_id=person["user_id"], metric=payload.metric,
                                granularity=granularity, quarter=entry["quarter"], month=entry["month"],
                                target_value=target, updated_by=operator[0], updated_at=now))
                _audit(db, period_id, "person_goal", str(person["user_id"]), person["user_name"],
                       field, None, _fmt(target), operator, "目标拆分")
            elif Decimal(current.target_value) != target:
                _audit(db, period_id, "person_goal", str(person["user_id"]), person["user_name"],
                       field, _fmt(Decimal(current.target_value)), _fmt(target), operator, "目标拆分")
                current.target_value = target
                current.updated_by = operator[0]
                current.updated_at = now
    period.version += 1
    period.updated_at = now
    changes = [(p["user_id"], payload.metric, granularity, e["quarter"], e["month"])
               for p in previews for e in p["entries"]]
    _mark_team_stale(db, period_id, roster_data, changes)
    db.commit()
    return {"preview": previews, "applied": True}


def _team_auto_index(db: Session, period_id: int, roster_data: dict) -> dict[tuple, Decimal]:
    team_by_user = {}
    for team in roster_data["teams"]:
        for member in team["members"]:
            if member["user_id"] is not None:
                team_by_user[member["user_id"]] = team["department_id"]
    index: dict[tuple, Decimal] = {}
    for row in db.query(PerfGoal).filter(PerfGoal.period_id == period_id).all():
        department_id = team_by_user.get(row.user_id)
        if department_id is None:
            continue
        key = (department_id, row.metric, row.granularity, row.quarter, row.month)
        index[key] = index.get(key, Decimal(0)) + Decimal(row.target_value)
    return index


def _slots_for_granularity(db: Session, period_id: int, granularity: str,
                           auto_index: dict[tuple, Decimal], stored: list) -> list[tuple[int | None, int | None]]:
    if granularity == "year":
        return [(None, None)]
    slots = set()
    if granularity == "quarter":
        for key in auto_index:
            if key[2] == "quarter":
                slots.add(key[3])
        for row in stored:
            if row.granularity == "quarter":
                slots.add(row.quarter)
        return sorted((q, None) for q in slots)
    for key in auto_index:
        if key[2] == "month":
            slots.add((key[3], key[4]))
    for row in stored:
        if row.granularity == "month":
            slots.add((row.quarter, row.month))
    return sorted(slots)


def list_team_goals(db: Session, period_id: int, granularity: str | None) -> dict:
    get_period(db, period_id)
    roster_data = roster(db, period_id)
    config = load_config(db)
    default_factor = Decimal(str(config.get("default_factor") or "1"))
    auto_index = _team_auto_index(db, period_id, roster_data)
    stored_rows = db.query(PerfGoalTeamOverride).filter(PerfGoalTeamOverride.period_id == period_id).all()
    stored = {(r.department_id, r.metric, r.granularity, r.quarter, r.month): r for r in stored_rows}
    names = _user_names(db, {row.updated_by for row in stored_rows if row.updated_by})
    rows = []
    for team in roster_data["teams"]:
        for metric in METRICS:
            for granularity_item in ([granularity] if granularity else GRANULARITIES):
                member_count = len(team["members"])
                for quarter, month in _slots_for_granularity(db, period_id, granularity_item,
                                                             auto_index, stored_rows):
                    key = (team["department_id"], metric, granularity_item, quarter, month)
                    auto = auto_index.get(key)
                    row = stored.get(key)
                    if auto is None and row is None:
                        continue
                    factor = Decimal(row.factor) if row is not None else default_factor
                    override = Decimal(row.override_value) if row is not None and row.override_value is not None else None
                    auto_value = auto if auto is not None else Decimal(0)
                    effective = override if override is not None else _quantize(metric, auto_value * factor)
                    stale = bool(row.stale) if row is not None else False
                    if row is not None and auto is not None and Decimal(row.auto_value or 0) != auto:
                        stale = True
                    rows.append({"department_id": team["department_id"], "team_name": team["name"],
                                 "captain_name": team["captain_name"], "member_count": member_count,
                                 "metric": metric, "granularity": granularity_item,
                                 "quarter": quarter, "month": month,
                                 "auto_value": float(_quantize(metric, auto_value)),
                                 "factor": float(factor),
                                 "override_value": None if override is None else float(override),
                                 "effective_value": float(effective),
                                 "stale": stale,
                                 "updated_by": row.updated_by if row is not None else None,
                                 "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None})
    return {"rows": rows}


def save_team_goals(db: Session, period_id: int, user: dict, payload) -> dict:
    period = get_period(db, period_id)
    if period.status == "archived":
        raise HTTPException(409, "已归档批次不允许修改")
    roster_data = roster(db, period_id)
    team_ids = {team["department_id"] for team in roster_data["teams"]}
    auto_index = _team_auto_index(db, period_id, roster_data)
    stored = {(r.department_id, r.metric, r.granularity, r.quarter, r.month): r
              for r in db.query(PerfGoalTeamOverride).filter(PerfGoalTeamOverride.period_id == period_id).all()}
    team_names = {team["department_id"]: team["name"] for team in roster_data["teams"]}
    operator = _operator(db, user)
    now = beijing_now()
    audits = 0
    for row in payload.rows:
        if row.department_id not in team_ids:
            raise HTTPException(422, f"战队 {row.department_id} 不存在")
        key = (row.department_id, row.metric, row.granularity, row.quarter, row.month)
        auto = auto_index.get(key, Decimal(0))
        current = stored.get(key)
        if current is None:
            current = PerfGoalTeamOverride(period_id=period_id, department_id=row.department_id,
                                           metric=row.metric, granularity=row.granularity,
                                           quarter=row.quarter, month=row.month, factor=1)
            db.add(current)
            db.flush()
            stored[key] = current
        label = team_names[row.department_id]
        if row.factor is not None and Decimal(current.factor) != Decimal(str(row.factor)):
            _audit(db, period_id, "team_goal", str(row.department_id), label,
                   f"factor:{row.granularity}", _fmt(Decimal(current.factor)),
                   format(Decimal(str(row.factor)), "f"), operator, payload.reason)
            current.factor = Decimal(str(row.factor))
            audits += 1
        new_override = None if row.clear_override else (
            _quantize(row.metric, Decimal(str(row.override_value))) if row.override_value is not None
            else (Decimal(current.override_value) if current.override_value is not None else None))
        old_override = Decimal(current.override_value) if current.override_value is not None else None
        if new_override != old_override:
            _audit(db, period_id, "team_goal", str(row.department_id), label,
                   _slot_field(row.metric, row.granularity, row.quarter, row.month),
                   _fmt(old_override), _fmt(new_override), operator, payload.reason)
            audits += 1
        current.override_value = new_override
        current.auto_value = _quantize(row.metric, auto)
        current.effective_value = (new_override if new_override is not None
                                   else _quantize(row.metric, auto * Decimal(current.factor)))
        current.stale = False
        current.updated_by = operator[0]
        current.updated_at = now
    db.commit()
    return {"version": period.version, "audit_count": audits}


def recalc_team_goals(db: Session, period_id: int, user: dict) -> dict:
    get_period(db, period_id)
    roster_data = roster(db, period_id)
    auto_index = _team_auto_index(db, period_id, roster_data)
    stored = {(r.department_id, r.metric, r.granularity, r.quarter, r.month): r
              for r in db.query(PerfGoalTeamOverride).filter(PerfGoalTeamOverride.period_id == period_id).all()}
    operator = _operator(db, user)
    now = beijing_now()
    updated = 0
    keys = set(auto_index) | set(stored)
    team_ids = {team["department_id"] for team in roster_data["teams"]}
    for key in sorted(keys, key=str):
        if key[0] not in team_ids:
            continue
        auto = _quantize(key[1], auto_index.get(key, Decimal(0)))
        row = stored.get(key)
        if row is None:
            row = PerfGoalTeamOverride(period_id=period_id, department_id=key[0], metric=key[1],
                                       granularity=key[2], quarter=key[3], month=key[4], factor=1)
            db.add(row)
            db.flush()
            stored[key] = row
        if row.auto_value is not None and Decimal(row.auto_value) != auto:
            team_name = next((t["name"] for t in roster_data["teams"] if t["department_id"] == key[0]), str(key[0]))
            _audit(db, period_id, "team_goal", str(key[0]), team_name, "auto_recalc",
                   _fmt(Decimal(row.auto_value)), _fmt(auto), operator, "一键重算")
        row.auto_value = auto
        override = Decimal(row.override_value) if row.override_value is not None else None
        row.effective_value = override if override is not None else _quantize(key[1], auto * Decimal(row.factor))
        row.stale = False
        row.updated_by = operator[0]
        row.updated_at = now
        updated += 1
    db.commit()
    return {"updated": updated}


def list_audits(db: Session, period_id: int) -> list[dict]:
    get_period(db, period_id)
    rows = (db.query(PerfGoalAudit).filter(PerfGoalAudit.period_id == period_id)
            .order_by(PerfGoalAudit.id.desc()).limit(500).all())
    return [{"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None,
             "operator_name": row.operator_name, "object_type": row.object_type,
             "object_label": row.object_label, "field": row.field,
             "old_value": row.old_value, "new_value": row.new_value, "reason": row.reason}
            for row in rows]
