"""Stable cross-source timeline; evidence is re-read through live source ACL."""

import base64, json
from datetime import datetime
from app.core.time import beijing_now
from fastapi import HTTPException
from sqlalchemy import bindparam, text
from app.client_desk.private_scope import user_id
from app.client_desk.models import ClientDeskFollowup
from app.client_desk.rules import R4, REASONS
from app.client_desk.sources import build_customer_sources
from app.invoice.product_service import _schema


def order_names(db, company_id, ids):
    if not ids:
        return {}
    stmt = text(
        f"SELECT order_id, name FROM `{_schema()}`.okki_orders "
        "WHERE company_id = :company_id AND order_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    return {
        str(order_id): name.strip()
        for order_id, name in db.execute(stmt, {"company_id": company_id, "ids": ids})
        if name and name.strip()
    }


def order_event(event, names):
    name = names.get(event["id"])
    number = event.get("order_no")
    return {
        **event,
        "order_name": name,
        "title": name or (f"订单 {number}" if number else "历史订单"),
    }


def order_products(db, company_id, order_id):
    schema = _schema()
    stmt = text(f"""
        SELECT oi.id, COALESCE(NULLIF(TRIM(oi.product_name), ''),
                               NULLIF(TRIM(oi.product_cn_name), '')) AS name,
               NULLIF(TRIM(oi.product_model), '') AS model, oi.quantity
        FROM `{schema}`.okki_order_items oi
        JOIN `{schema}`.okki_orders o ON o.order_id = oi.order_id
        WHERE o.company_id = :company_id AND o.order_id = :order_id
        ORDER BY oi.item_index, oi.id
    """)
    return [
        {**row, "id": str(row["id"])}
        for row in db.execute(stmt, {"company_id": company_id, "order_id": order_id}).mappings()
    ]


def all_events(db, user, company_id):
    source = build_customer_sources(db, user, company_id)
    events = []
    events.append(
        {
            "id": str(company_id),
            "event_key": "rule:CARD",
            "source": "rule",
            "title": "客户档案",
            "occurred_at": source["created_at"],
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
                "title": "客户资料有更新" if code == R4 else REASONS.get(code, "系统跟进提醒"),
                "summary": (
                    "首次分析前已有订单或已审核背调，或这些资料晚于上次分析。"
                    if code == R4 else None
                ),
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
                "card": source["card"],
            }
        )
    for o in source["orders"]:
        if o["account_date"]:
            events.append(
                {
                    **o,
                    "source": "order",
                    "occurred_at": o["account_date"],
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
                "title": "WhatsApp 沟通",
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
    events.extend(feed_events(db, user, company_id))
    for e in events:
        value = e["occurred_at"]
        if value is not None and not isinstance(value, datetime):
            value = datetime.fromisoformat(str(value))
        e["occurred_at"] = value
    return events


def key(event):
    return (event["occurred_at"].isoformat(), event["source"], event["id"])


def timeline(db, user, company_id, source="all", cursor=None, limit=30):
    # These keys remain available to existing AI citations, but they duplicate
    # records that already have their own entries in the timeline.
    citation_only = {"rule:CARD", f"rule:{R4}"}
    events = [
        e
        for e in all_events(db, user, company_id)
        if (source == "all" or e["source"] == source)
        and e["event_key"] not in citation_only
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
    names = order_names(db, company_id, [e["id"] for e in page if e["source"] == "order"])
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
            {
                k: v for k, v in (order_event(e, names) if e["source"] == "order" else e).items()
                if k not in ("messages", "result", "card")
            }
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
    if found["source"] == "order":
        order_id = found["id"]
        return {
            **order_event(found, order_names(db, company_id, [order_id])),
            "products": order_products(db, company_id, order_id),
        }
    return found


def feed_events(db, user, company_id):
    from .models import ClientDeskSuggestion
    from .access import dependencies_valid
    from .source_policy import restricted_row
    from app.alibaba_feed.business_service import select_for_analysis

    events = {}
    rows = (
        db.query(ClientDeskSuggestion)
        .filter_by(
            user_id=user_id(user), company_id=int(company_id), status="succeeded"
        )
        .filter(ClientDeskSuggestion.run_seq > 0)
        .all()
    )
    for row in rows:
        if not restricted_row(row) or not row.selected_feed_item_ids:
            continue
        if not dependencies_valid(db, user, company_id, row.source_dependencies):
            continue
        try:
            material = select_for_analysis(
                db, user, company_id, row.selected_feed_item_ids
            )
        except HTTPException as exc:
            if exc.status_code in (403, 404, 409):
                continue
            raise
        if material["dependencies"] != row.source_dependencies.get("alibaba_feed"):
            continue
        for message in material["messages"]:
            event_key = message["event_key"]
            events[event_key] = {
                "id": message["key"],
                "event_key": event_key,
                "source": "alibaba_feed",
                "occurred_at": message["at"],
                "title": "TM历史快照（仅人工参考）",
                "messages": [message],
                "analysis_policy": "manual_only_v1",
                "coverage_gaps": material["coverage_gaps"],
            }
    return list(events.values())
