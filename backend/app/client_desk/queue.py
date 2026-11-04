"""Persist candidate allocations and protect user-initiated runs with a per-customer lock."""

import logging
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import func

from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp.access import live_actor
from .calendar import is_workday
from .models import ClientDeskState as State, ClientDeskSuggestion as Row
from .private_scope import user_id
from .rules import allocate, as_time, evaluate, REASONS, R1, R4, R5, R6
from . import sources

logger = logging.getLogger(__name__)


def actor_id(user):
    return int(user.id) if hasattr(user, "id") else user_id(user)


def active(db, uid):
    cfg = get_settings()
    if not cfg.CLIENT_DESK_ENABLED or uid not in cfg.CLIENT_DESK_PILOT_USER_IDS:
        raise HTTPException(403, "私海助理未启用")
    try:
        live_actor(db, uid, "client_desk:read")
    except PermissionError as exc:
        raise HTTPException(403, "私海助理访问权限已变更") from exc
    return cfg


def state_data(state):
    if isinstance(state, dict):
        return dict(state)
    return (
        {c.name: getattr(state, c.name) for c in State.__table__.columns}
        if state
        else {}
    )


def today_rows(db, uid, day):
    return db.query(Row).filter_by(user_id=uid, biz_date=day)


def linkage_fingerprint(source):
    """Only authorization/binding identity; normal new messages must not invalidate ITT."""
    from .pack import digest

    deps = (source.get("source_dependencies") or {}).get("wa")
    if deps is None:
        return None
    keys = [(d["account"], d["link"], d["version"], d["generation"]) for d in deps]
    return digest(sorted(keys, key=lambda k: (k[0], k[1])))


def effective_snooze(db, uid, cid, day):
    return (
        db.query(func.max(Row.snoozed_until))
        .filter(Row.user_id == uid, Row.company_id == cid, Row.snoozed_until > day)
        .scalar()
    )


def read_candidates(db, user, now):
    uid = actor_id(user)
    cfg = active(db, uid)
    states = {
        r.company_id: state_data(r) for r in db.query(State).filter_by(user_id=uid)
    }
    for cid, until in (
        db.query(Row.company_id, func.max(Row.snoozed_until))
        .filter(Row.user_id == uid, Row.snoozed_until > now.date())
        .group_by(Row.company_id)
    ):
        states.setdefault(cid, {})["snoozed_until"] = until
    material = sources.scan_inputs(db, uid, now)
    all_sources = {int(s["company_id"]): s for s in material}
    candidates = [
        evaluate(
            s,
            states.get(cid, {}),
            now,
            uid,
            cfg.CLIENT_DESK_RULES,
            cfg.CLIENT_DESK_CALENDAR,
        )
        for cid, s in all_sources.items()
    ]
    return (
        allocate(
            [c for c in candidates if c],
            min(40, cfg.CLIENT_DESK_RULES.get("quota", 40)),
        ),
        all_sources,
    )


def scan_pilots(db, users, now=None):
    """Use only each pilot's own minimal signal when resolving shared customers."""
    now = now or beijing_now()
    snapshots = {}
    owners = {}
    incomplete = False
    for user in users:
        uid = actor_id(user)
        try:
            cfg = active(db, uid)
            if uid not in cfg.CLIENT_DESK_NONWORKDAY_USER_IDS and not is_workday(
                now.date(), cfg.CLIENT_DESK_CALENDAR
            ):
                continue
            from .history_import import import_history

            import_history(db, uid)
            ranked, material = read_candidates(db, uid, now)
            snapshots[uid] = (ranked, material)
            for cid, source in material.items():
                owners.setdefault(cid, []).append(
                    (
                        uid,
                        source.get("own_last_outbound_at"),
                        source.get("outbound_coverage_complete", False),
                    )
                )
        except Exception as exc:
            db.rollback()
            incomplete = True
            logger.warning(
                "private desk pilot snapshot %s: %s", uid, type(exc).__name__
            )
            print(
                f"[CLIENT_DESK] pilot snapshot {uid}: {type(exc).__name__}", flush=True
            )
    for uid, (ranked, material) in snapshots.items():
        eligible = []
        for c in ranked:
            signals = owners[c.company_id]
            if len(signals) > 1:
                if incomplete or not all(s[2] for s in signals):
                    material[c.company_id]["arbitration"] = "coverage_unknown"
                else:
                    outbound = [(as_time(at), -owner) for owner, at, _ in signals if at]
                    if outbound and -max(outbound)[1] != uid:
                        material[c.company_id]["arbitration"] = "other_owner"
                        continue
            eligible.append(c)
        try:
            scan_user(
                db,
                uid,
                now,
                prepared=(
                    allocate(
                        eligible,
                        min(40, get_settings().CLIENT_DESK_RULES.get("quota", 40)),
                    ),
                    material,
                ),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("private desk pilot scan %s: %s", uid, type(exc).__name__)
            print(f"[CLIENT_DESK] pilot scan {uid}: {type(exc).__name__}", flush=True)


def scan_user(db, user, now=None, *, prepared=None):
    from .service import lock_state

    now = now or beijing_now()
    uid = actor_id(user)
    cfg = active(db, uid)
    if uid not in cfg.CLIENT_DESK_NONWORKDAY_USER_IDS and not is_workday(
        now.date(), cfg.CLIENT_DESK_CALENDAR
    ):
        return 0
    if prepared is None:
        from .history_import import import_history

        import_history(db, uid)
    candidates, material = prepared or read_candidates(db, uid, now)
    # Serialize the quota even when two invocations discover different new companies.
    from app.auth.models import ArkUser

    db.query(ArkUser.id).filter_by(id=uid).with_for_update().one()
    existing = {
        r.company_id: r
        for r in today_rows(db, uid, now.date()).filter_by(run_seq=0).with_for_update()
    }
    quota = min(40, cfg.CLIENT_DESK_RULES.get("quota", 40)) - sum(
        r.queue_eligible for r in existing.values()
    )
    for cid, source in material.items():
        with db.begin_nested():
            state = lock_state(db, uid, cid)
            state.last_touch_at = source.get("last_touch_at")
            state.last_touch_channel = source.get("last_touch_channel")
    for c in candidates:
        if c.company_id in existing:
            continue
        with db.begin_nested():
            eligible = c.disposition == "eligible" and quota > 0
            quota -= int(eligible)
            disposition = (
                "quota"
                if not eligible and c.disposition == "eligible"
                else c.disposition
            )
            source = material[c.company_id]
            db.add(
                Row(
                    user_id=uid,
                    company_id=c.company_id,
                    biz_date=now.date(),
                    run_seq=0,
                    rank_score=c.score,
                    rule_codes=c.codes,
                    rule_details=[REASONS[x] for x in c.codes],
                    rule_version=cfg.CLIENT_DESK_RULES.get("version", "desk_rules_v1"),
                    snapshot_at=now,
                    snapshot={
                        "rank_wait": c.wait,
                        "wa_linked": bool(source["conversations"]),
                        "linkage_fingerprint": linkage_fingerprint(source),
                        "grade": source.get("grade"),
                        "active_customer": bool(
                            source.get("order_count")
                            or source.get("last_touch_at")
                            and as_time(source["last_touch_at"])
                            >= now - timedelta(days=30)
                        ),
                        "coverage_gaps": source.get("coverage_gaps", []),
                        "arbitration": source.get("arbitration", "independent"),
                        "rules_config": cfg.CLIENT_DESK_RULES,
                        "calendar_version": cfg.CLIENT_DESK_CALENDAR.get(
                            "version", "CN-2025-2026"
                        ),
                    },
                    cohort=c.cohort,
                    queue_eligible=eligible,
                    display_eligible=c.cohort != "holdout" and c.codes != [R4],
                    disposition=disposition,
                    status="queued" if eligible else "rule_only",
                )
            )
    return len(candidates)


def enqueue_manual(db, user, company_id, client_request_id):
    from .service import lock_state
    from .private_scope import assert_company_access

    uid = actor_id(user)
    active(db, uid)
    assert_company_access(db, uid, company_id)
    now = beijing_now()
    lock_state(db, uid, int(company_id))
    existing = (
        db.query(Row)
        .filter_by(user_id=uid, client_request_id=client_request_id)
        .with_for_update()
        .first()
    )
    history = (
        today_rows(db, uid, now.date())
        .filter_by(company_id=int(company_id))
        .with_for_update()
        .all()
    )
    count = max([r.run_seq for r in history] + [0])
    if existing and existing.company_id != int(company_id):
        raise HTTPException(409, "请求键已用于其他客户")
    if not existing:
        if count >= 3:
            raise HTTPException(429, "今日重分析次数已用完")
        routine = next((r for r in history if not r.run_seq), None)
        count += 1
        existing = Row(
            user_id=uid,
            company_id=int(company_id),
            biz_date=now.date(),
            run_seq=count,
            client_request_id=client_request_id,
            rule_codes=(routine.rule_codes if routine else []),
            rank_score=routine.rank_score if routine else 0,
            cohort=routine.cohort if routine else "ineligible",
            display_eligible=routine.cohort != "holdout" if routine else True,
            status="queued",
            queue_eligible=True,
            disposition="manual",
            snapshot_at=now,
        )
        db.add(existing)
        db.flush()
    return {
        "suggestion_id": str(existing.id),
        "run_seq": existing.run_seq,
        "status": existing.status,
        "remaining": 3 - count,
    }


def visible_suggestion(db, row, source, state, now):
    if effective_snooze(db, row.user_id, row.company_id, now.date()):
        return None
    cfg = get_settings()
    s = state_data(state)
    current = evaluate(
        source, s, now, row.user_id, cfg.CLIENT_DESK_RULES, cfg.CLIENT_DESK_CALENDAR
    )
    codes = list(current.codes) if current else []
    strong = set(codes) - {R4, R5, R6}
    if row.cohort == "holdout" and not strong:
        return None
    if row.snoozed_until and row.snoozed_until > now.date():
        return None
    if row.cohort == "holdout":
        codes = [c for c in codes if c in strong]
    if (
        set(codes) <= {R4}
        and not row.run_seq
        and not row.done_at
        and not row.quality_feedback
    ):
        return None
    stale = row.status == "succeeded" and (
        row.source_dependencies
        != source.get("ai_source_dependencies", source.get("source_dependencies"))
        or (R1 in row.rule_codes) != (R1 in codes)
        or row.cohort == "holdout"
    )
    if row.priority == "skip" and not stale:
        return None
    data = {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "run_seq": row.run_seq,
        "status": row.status,
        "rule_codes": codes,
        "rank_score": current.score if current else 0,
        "quality_feedback": row.quality_feedback,
        "done_at": row.done_at,
        "done_source": row.done_source,
        "snoozed_until": row.snoozed_until,
        "disposition": row.disposition,
        "reason": "；".join(REASONS[c] for c in codes if c != R4),
        "needs_review": False,
        "cites": [],
    }
    if row.status == "succeeded" and not stale:
        data.update(
            {
                k: getattr(row, k)
                for k in (
                    "priority",
                    "reason",
                    "strategy",
                    "check_before_reply",
                    "talking_points",
                    "draft_message",
                    "cites",
                    "grade_hint",
                    "needs_review",
                )
            }
        )
    if stale:
        data.update(status="rule_only", disposition="source_changed")
    return data


def auto_done(db, user, now=None):
    from .service import lock_state

    now = now or beijing_now()
    uid = actor_id(user)
    active(db, uid)
    rows = (
        db.query(Row)
        .filter(
            Row.user_id == uid,
            Row.done_at.is_(None),
            Row.shown_at.is_not(None),
            Row.biz_date >= now.date() - timedelta(days=14),
        )
        .all()
    )
    by_company = {}
    for row in rows:
        by_company.setdefault(row.company_id, []).append(row.id)
    for cid, row_ids in by_company.items():
        try:
            with db.begin_nested():
                _complete_company(db, uid, cid, row_ids, now)
        except Exception as exc:
            if isinstance(exc, HTTPException) and exc.status_code == 404:
                continue
            logger.warning(
                "private desk automatic completion %s/%s: %s",
                uid,
                cid,
                type(exc).__name__,
            )
            print(
                f"[CLIENT_DESK] automatic completion {uid}/{cid}: {type(exc).__name__}",
                flush=True,
            )


def _complete_company(db, uid, cid, row_ids, now):
    from .service import lock_state

    source = sources.build_customer_sources(db, uid, cid, for_ai=False)
    outbound = [
        as_time(m["at"])
        for m in source.get("messages", [])
        if m.get("direction") == "outbound" and str(m.get("owner_user_id")) == str(uid)
    ]
    state = lock_state(db, uid, cid)
    for row in (
        db.query(Row)
        .filter(Row.id.in_(row_ids), Row.done_at.is_(None))
        .with_for_update()
    ):
        after = [
            at for at in outbound if (row.snapshot_at or row.created_at) < at <= now
        ]
        if after:
            row.done_at, row.done_source = min(after), "whatsapp"
            cooldowns = dict(state.rule_cooldowns or {})
            until = (row.done_at.date() + timedelta(days=7)).isoformat()
            cooldowns.update(
                {c: max(until, cooldowns.get(c, "")) for c in row.rule_codes}
            )
            state.rule_cooldowns = cooldowns
