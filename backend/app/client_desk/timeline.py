"""Stable cross-source timeline; evidence is re-read through live source ACL."""

import base64, json
from datetime import datetime
from app.core.time import beijing_now
from fastapi import HTTPException
from app.client_desk.private_scope import user_id
from app.client_desk.models import ClientDeskFollowup
from app.client_desk.sources import build_customer_sources


def all_events(db, user, company_id):
    source = build_customer_sources(db, user, company_id)
    events = []
    events.append(
        {
            "id": str(company_id),
            "event_key": "rule:CARD",
            "source": "rule",
            "occurred_at": source["created_at"] or beijing_now(),
            "card": source["card"],
        }
    )
    from app.client_desk.models import ClientDeskState

    state = (
        db.query(ClientDeskState)
        .filter_by(user_id=user_id(user), company_id=int(company_id))
        .first()
    )
    from app.client_desk.models import ClientDeskSuggestion
    from app.client_desk.queue import visible_suggestion
    from app.client_desk.rules import REASONS
    from app.core.time import beijing_today

    suggestion = (
        db.query(ClientDeskSuggestion)
        .filter_by(
            user_id=user_id(user), company_id=int(company_id), biz_date=beijing_today()
        )
        .order_by(ClientDeskSuggestion.run_seq.desc())
        .first()
    )
    view = (
        visible_suggestion(db, suggestion, source, state, beijing_now())
        if suggestion
        else None
    )
    for code in view.get("rule_codes", []) if view else []:
        events.append(
            {
                "id": code,
                "event_key": "rule:" + code,
                "source": "rule",
                "occurred_at": suggestion.snapshot_at or suggestion.created_at,
                "rule_code": code,
                "title": REASONS.get(code, code),
                "biz_date": suggestion.biz_date,
                "rule_version": suggestion.rule_version,
                "snapshot_at": suggestion.snapshot_at,
                "next_followup_date": (
                    state.next_followup_date
                    if state and code == "R2_FOLLOWUP_DUE"
                    else None
                ),
                "next_followup_remark": (
                    state.next_followup_remark
                    if state and code == "R2_FOLLOWUP_DUE"
                    else None
                ),
            }
        )
    created = source["created_at"]
    if created:
        events.append(
            {
                "id": str(company_id),
                "event_key": f"created:{company_id}",
                "source": "created",
                "occurred_at": created,
                "title": "客户建档",
            }
        )
    for o in source["orders"]:
        if o["account_date"]:
            events.append(
                {
                    **o,
                    "source": "order",
                    "occurred_at": o["account_date"],
                    "title": o["order_no"],
                }
            )
    for r in source["research"]:
        events.append(
            {
                **r,
                "source": "research",
                "occurred_at": r["updated_at"],
                "title": "已审核背调",
            }
        )
    grouped = {}
    for m in source["messages"]:
        grouped.setdefault(m["event_key"], []).append(m)
    for key, messages in grouped.items():
        events.append(
            {
                "id": key,
                "event_key": key,
                "source": "whatsapp",
                "occurred_at": max(m["at"] for m in messages),
                "count": len(messages),
                "messages": messages,
                "conversation_uid": messages[0]["conversation_uid"],
            }
        )
    for row in db.query(ClientDeskFollowup).filter_by(
        user_id=user_id(user), company_id=int(company_id), deleted_at=None
    ):
        events.append(
            {
                "id": str(row.id),
                "event_key": f"followup:{row.id}",
                "source": "followup",
                "occurred_at": row.happened_at,
                "content": row.content,
                "channel": row.channel,
                "author_id": str(row.user_id),
                "manual": True,
            }
        )
    for e in events:
        value = e["occurred_at"]
        if not isinstance(value, datetime):
            value = datetime.fromisoformat(str(value))
        e["occurred_at"] = value
    return events


def key(event):
    return (event["occurred_at"].isoformat(), event["source"], event["id"])


def timeline(db, user, company_id, source="all", cursor=None, limit=30):
    events = [
        e
        for e in all_events(db, user, company_id)
        if source == "all" or e["source"] == source
    ]
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if data["source"] != source or data["company_id"] != str(company_id):
                raise ValueError()
            last = tuple(data["key"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "无效时间轴游标") from exc
        events = [e for e in events if key(e) < last]
    events.sort(key=key, reverse=True)
    page = events[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"source": source, "company_id": str(company_id), "key": key(page[-1])}
            ).encode()
        ).decode()
        if len(events) > limit
        else None
    )
    return {
        "items": [
            {k: v for k, v in e.items() if k not in ("messages", "result")}
            for e in page
        ],
        "next_cursor": next_cursor,
    }


def event(db, user, company_id, event_key):
    found = next(
        (e for e in all_events(db, user, company_id) if e["event_key"] == event_key),
        None,
    )
    if found is None:
        raise HTTPException(404, "来源事件已不可见")
    return found
