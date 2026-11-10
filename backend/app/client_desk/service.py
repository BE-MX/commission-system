"""Transactional manual actions; AI fields are never included in a manual update."""

from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.client_desk.models import (
    ClientDeskState as State,
    ClientDeskFollowup as Followup,
    ClientDeskSuggestion as Suggestion,
)
from app.client_desk.private_scope import (
    assert_company_access,
    user_id,
    list_private_companies,
)
from app.client_desk.access import require_enabled, dependencies_valid


def atomic_insert(db, model, values, key_columns):
    if db.get_bind().dialect.name == "sqlite":
        stmt = (
            sqlite_insert(model)
            .values(**values)
            .on_conflict_do_nothing(index_elements=key_columns)
        )
    else:
        stmt = mysql_insert(model).values(**values)
        stmt = stmt.on_duplicate_key_update(
            **{key_columns[0]: getattr(stmt.inserted, key_columns[0])}
        )
    db.execute(stmt)


def lock_state(db, user_id, company_id):
    atomic_insert(
        db,
        State,
        {
            "user_id": int(user_id),
            "company_id": int(company_id),
            "status": "active",
            "manual_version": 0,
            "recheck_count": 0,
            "rule_cooldowns": {},
            "created_by": int(user_id),
        },
        ["user_id", "company_id"],
    )
    return (
        db.query(State)
        .filter_by(user_id=int(user_id), company_id=int(company_id))
        .populate_existing()
        .with_for_update()
        .one()
    )


def state_dto(row):
    return (
        {
            k: getattr(row, k)
            for k in (
                "remark",
                "next_followup_date",
                "next_followup_remark",
                "manual_version",
                "updated_at",
                "updated_by",
                "last_touch_at",
                "last_touch_channel",
            )
        }
        if row
        else {
            "remark": None,
            "next_followup_date": None,
            "next_followup_remark": None,
            "manual_version": 0,
        }
    )


def scoped(db, user, company_id, write=False):
    actor = require_enabled(db, user, write=write)
    assert_company_access(db, actor, company_id)
    return actor


def suggestion_for(db, user, suggestion_id, company_id=None):
    row = (
        db.query(Suggestion)
        .filter_by(id=int(suggestion_id), user_id=user_id(user))
        .first()
    )
    if row is None or (company_id is not None and row.company_id != int(company_id)):
        raise HTTPException(404, "建议不存在或不可访问")
    assert_company_access(db, user, row.company_id)
    return row


def patch_state(db, user, company_id, payload):
    scoped(db, user, company_id, True)
    row = lock_state(db, user_id(user), company_id)
    if row.manual_version != payload.expected_version:
        raise HTTPException(
            409, detail={"code": "STATE_CONFLICT", "latest": state_dto(row)}
        )
    for key in payload.model_fields_set - {"expected_version"}:
        setattr(row, key, getattr(payload, key))
    row.manual_version += 1
    row.updated_by = user_id(user)
    db.commit()
    return state_dto(row)


def seed_grade_dictionary(db):
    from app.system.models import SysDict

    for sort, code in enumerate("SABCDE"):
        atomic_insert(
            db,
            SysDict,
            {
                "type": "customer_grade",
                "code": code,
                "label": code,
                "sort": sort,
                "is_active": True,
            },
            ["type", "code"],
        )


def put_grade(db, user, company_id, payload):
    scoped(db, user, company_id, True)
    from app.invoice.models import CustomerProfile
    from app.invoice.customer_profile_service import save_customer_grade
    from app.client_desk.sources import grade_options

    if payload.grade is not None and payload.grade not in grade_options(db):
        raise HTTPException(422, "等级未在系统字典启用")
    if payload.suggestion_id:
        suggestion = suggestion_for(db, user, payload.suggestion_id, company_id)
        if not dependencies_valid(db, user, company_id, suggestion.source_dependencies):
            raise HTTPException(409, "来源授权已变更，请重新分析")
        if (
            not suggestion.grade_hint
            or suggestion.grade_hint.get("value") != payload.grade
        ):
            raise HTTPException(409, "分级建议已变更")
    atomic_insert(
        db,
        CustomerProfile,
        {"customer_id": str(company_id), "customer_grade": None, "delivery_version": 1},
        ["customer_id"],
    )
    profile = (
        db.query(CustomerProfile)
        .filter_by(customer_id=str(company_id))
        .populate_existing()
        .with_for_update()
        .one()
    )
    current = profile.customer_grade
    if current != payload.grade and current != payload.expected_grade:
        raise HTTPException(
            409,
            detail={
                "code": "GRADE_CONFLICT",
                "grade": current,
                "updated_by": profile.updated_by,
            },
        )
    save_customer_grade(db, company_id, payload.grade, user_id(user))
    db.commit()
    return {
        "grade": payload.grade,
        "updated_by": user_id(user),
        "updated_at": beijing_now(),
    }


def add_followup(db, user, company_id, payload):
    scoped(db, user, company_id, True)
    state = lock_state(db, user_id(user), company_id)
    previous = (
        db.query(Followup)
        .filter_by(user_id=user_id(user), client_request_id=payload.client_request_id)
        .first()
    )
    if previous:
        if previous.company_id != int(company_id):
            raise HTTPException(409, "请求键已用于另一客户")
        return followup_dto(previous, state)
    happened = to_beijing_naive(payload.happened_at)
    if happened > beijing_now():
        raise HTTPException(422, "发生时间不能晚于当前")
    suggestion = (
        suggestion_for(db, user, payload.suggestion_id, company_id)
        if payload.suggestion_id
        else None
    )
    row = Followup(
        user_id=user_id(user),
        company_id=int(company_id),
        channel=payload.channel,
        content=payload.content,
        happened_at=happened,
        suggestion_id=suggestion.id if suggestion else None,
        client_request_id=payload.client_request_id,
        created_by=user_id(user),
    )
    db.add(row)
    if "next_followup_date" in payload.model_fields_set:
        state.next_followup_date = payload.next_followup_date
        state.manual_version += 1
    if state.last_touch_at is None or happened > state.last_touch_at:
        state.last_touch_at = happened
        state.last_touch_channel = payload.channel
    if suggestion and suggestion.done_at is None:
        suggestion.done_at = happened
        suggestion.done_source = "manual_followup"
        set_cooldowns(state, suggestion, 7, happened.date())
    db.commit()
    return followup_dto(row, state)


def followup_dto(row, state):
    return {
        "event": {
            "id": str(row.id),
            "event_key": f"followup:{row.id}",
            "source": "followup",
            "occurred_at": row.happened_at,
            "channel": row.channel,
            "content": row.content,
            "author_id": str(row.user_id),
            "manual": True,
        },
        "personal_state": state_dto(state),
        "last_touch_at": state.last_touch_at,
    }


def set_cooldowns(state, suggestion, days, day=None):
    cooldowns = dict(state.rule_cooldowns or {})
    for code in suggestion.rule_codes or []:
        until = ((day or beijing_today()) + timedelta(days=days)).isoformat()
        cooldowns[code] = max(cooldowns.get(code, ""), until)
    state.rule_cooldowns = cooldowns


def feedback(db, user, suggestion_id, payload):
    require_enabled(db, user, True)
    suggestion = suggestion_for(db, user, suggestion_id)
    state = lock_state(db, user_id(user), suggestion.company_id)
    suggestion = (
        db.query(Suggestion)
        .filter_by(id=suggestion.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    now = beijing_now()
    if (
        payload.value in ("useful", "useless")
        and suggestion.quality_feedback == payload.value
    ):
        return {
            "quality_feedback": suggestion.quality_feedback,
            "done_at": suggestion.done_at,
            "done_source": suggestion.done_source,
            "snoozed_until": suggestion.snoozed_until,
            "next_followup_date": state.next_followup_date,
            "rule_cooldowns": state.rule_cooldowns,
        }
    if payload.value in ("useful", "useless"):
        suggestion.quality_feedback = payload.value
        suggestion.feedback_at = now
        if payload.value == "useless":
            set_cooldowns(state, suggestion, 14)
    elif payload.value == "done":
        if suggestion.done_at is None:
            suggestion.done_at = now
            suggestion.done_source = "manual"
        set_cooldowns(state, suggestion, 7, suggestion.done_at.date())
    else:
        if payload.date is None or payload.date <= beijing_today():
            raise HTTPException(422, "请选择未来日期")
        if suggestion.snoozed_until != payload.date:
            suggestion.snoozed_until = payload.date
            state.next_followup_date = payload.date
            state.manual_version += 1
    db.commit()
    return {
        "quality_feedback": suggestion.quality_feedback,
        "done_at": suggestion.done_at,
        "done_source": suggestion.done_source,
        "snoozed_until": suggestion.snoozed_until,
        "next_followup_date": state.next_followup_date,
        "rule_cooldowns": state.rule_cooldowns,
    }


def detail(db, user, company_id):
    from app.client_desk.sources import build_customer_sources
    from app.client_desk.queue import visible_suggestion

    scoped(db, user, company_id)
    source = build_customer_sources(db, user, company_id)
    state = (
        db.query(State)
        .filter_by(user_id=user_id(user), company_id=int(company_id))
        .first()
    )
    row = (
        db.query(Suggestion)
        .filter_by(
            user_id=user_id(user), company_id=int(company_id), biz_date=beijing_today()
        )
        .order_by(Suggestion.run_seq.desc())
        .first()
    )
    suggestion = (
        visible_suggestion(db, row, source, state, beijing_now()) if row else None
    )
    if suggestion and row.shown_at is None:
        row.shown_at = beijing_now()
        row.shown_channel = "detail"
        db.commit()
    brief = (
        state.brief_md
        if state and dependencies_valid(db, user, company_id, state.brief_dependencies)
        else None
    )
    from app.client_desk.calendar import offset_workdays

    return {
        **{
            k: source[k]
            for k in (
                "card",
                "contacts",
                "grade",
                "grade_options",
                "orders_summary",
                "research_summary",
                "sync_times",
                "wa_targets",
                "coverage_gaps",
            )
        },
        "last_analyzed_at": state.last_analyzed_at if state else None,
        "remaining_reanalyses": max(
            0,
            3
            - db.query(Suggestion)
            .filter(
                Suggestion.user_id == user_id(user),
                Suggestion.company_id == int(company_id),
                Suggestion.biz_date == beijing_today(),
                Suggestion.run_seq > 0,
            )
            .count(),
        ),
        "personal_state": {
            **state_dto(state),
            "last_touch_at": source["last_touch_at"],
            "last_touch_channel": source["last_touch_channel"],
        },
        "suggestion": suggestion,
        "brief_md": brief,
        "sample_followup_date": offset_workdays(beijing_today(), 10),
    }


def customer_list(
    db, user, filter="all", keyword="", page=1, page_size=30, reason=None
):
    actor = require_enabled(db, user)
    from app.invoice.models import CustomerProfile
    from app.client_desk.sources import build_customer_sources
    from app.client_desk.queue import visible_suggestion
    from app.client_desk.source_context import list_last_touches, prepare

    folded_keyword = keyword.casefold()
    cards = [
        card
        for card in list_private_companies(db, actor)
        if folded_keyword in (card["name"] or "").casefold()
        or keyword in card["company_id"]
    ]
    grades = {
        cid: grade
        for cid, grade in db.query(
            CustomerProfile.customer_id, CustomerProfile.customer_grade
        ).filter(CustomerProfile.customer_id.in_([c["company_id"] for c in cards]))
    }
    if filter == "ungraded":
        cards = [card for card in cards if grades.get(card["company_id"]) is None]
    elif filter.startswith("grade:"):
        allowed_grades = set(filter[6:].split(","))
        cards = [
            card for card in cards if grades.get(card["company_id"]) in allowed_grades
        ]

    suggestions = {}
    for row in (
        db.query(Suggestion)
        .filter(
            Suggestion.user_id == user_id(actor),
            Suggestion.biz_date == beijing_today(),
            Suggestion.company_id.in_([int(c["company_id"]) for c in cards]),
        )
        .order_by(Suggestion.run_seq)
    ):
        suggestions[str(row.company_id)] = row
    suggestion_cards = [card for card in cards if card["company_id"] in suggestions]
    context = prepare(db, actor, suggestion_cards) if suggestion_cards else None

    # Only suggestions need full sources before paging to establish live visibility and rank.
    result = []
    for card in cards:
        cid = card["company_id"]
        row = suggestions.get(cid)
        suggestion = None
        source = {}
        if row is not None:
            source = build_customer_sources(
                db, actor, int(cid), realtime=False, card=card, context=context
            )
            suggestion = visible_suggestion(
                db, row, source, context["states"].get(cid), beijing_now()
            )
        if filter == "suggested" and not suggestion:
            continue
        if reason and (
            not suggestion or reason not in suggestion.get("rule_codes", [])
        ):
            continue
        result.append(
            {
                **card,
                "grade": grades.get(cid),
                "reason": suggestion.get("reason") if suggestion else None,
                "rule_codes": suggestion.get("rule_codes", []) if suggestion else [],
                "rank_score": float(row.rank_score) if suggestion else 0,
                "last_touch_at": source.get("last_touch_at"),
                "channel": source.get("last_touch_channel"),
                "analysis_state": row.status if suggestion else None,
                "suggestion_id": str(row.id) if suggestion else None,
            }
        )
    result.sort(key=lambda r: (-r["rank_score"], int(r["company_id"])))
    items = result[(page - 1) * page_size : page * page_size]
    plain_ids = [
        item["company_id"] for item in items if item["company_id"] not in suggestions
    ]
    if plain_ids:
        touches = list_last_touches(db, actor, plain_ids)
        for item in items:
            if touch := touches.get(item["company_id"]):
                item["last_touch_at"], item["channel"] = touch
    return {
        "items": items,
        "total": len(result),
        "page": page,
        "page_size": page_size,
    }


def today(db, user, reason=None):
    result = customer_list(
        db, user, filter="suggested", page_size=100000, reason=reason
    )
    items = result["items"]
    from app.client_desk.link_service import conversations

    return {
        "biz_date": beijing_today(),
        "items": items,
        "counts": {
            "unreplied": sum("R1_UNREPLIED" in i["rule_codes"] for i in items),
            "due": sum(
                any(c in i["rule_codes"] for c in ("R2_FOLLOWUP_DUE", "R3_RECHECK_DUE"))
                for i in items
            ),
            "repurchase": sum("R5_REPURCHASE" in i["rule_codes"] for i in items),
            "silent": sum("R6_LONG_SILENT" in i["rule_codes"] for i in items),
        },
        "unlinked_count": conversations(db, user, page_size=1)["total"],
    }


def wa_open(db, user, company_id, payload):
    from urllib.parse import quote
    import re
    from app.client_desk.sources import build_customer_sources
    from app.client_desk.queue import visible_suggestion

    source = build_customer_sources(db, user, company_id)
    target = next(
        (
            t
            for t in source["wa_targets"]
            if t["account_uid"] == payload.account_uid
            and t["conversation_uid"] == payload.conversation_uid
        ),
        None,
    )
    if target is None:
        raise HTTPException(404, "会话已不可访问或关联已变更")
    phone = re.sub(r"[ +()-]", "", target.get("phone") or "")
    if not re.fullmatch(r"[1-9][0-9]{6,14}", phone):
        raise HTTPException(409, "当前会话缺少可核验国际号码，请查看档案")
    draft = ""
    if payload.suggestion_id:
        row = suggestion_for(db, user, payload.suggestion_id, company_id)
        state = (
            db.query(State)
            .filter_by(user_id=user_id(user), company_id=int(company_id))
            .first()
        )
        visible = visible_suggestion(db, row, source, state, beijing_now())
        if not visible or not visible.get("draft_message"):
            raise HTTPException(409, "建议来源已变更，请重新分析")
        draft = visible["draft_message"]
    return {"url": f'https://wa.me/{phone}?text={quote(draft,safe="")}'}
