"""Authorized customer source projection; never reads conversation previews."""

import hashlib
import json
from sqlalchemy import text
from app.client_desk.private_scope import (
    assert_company_access,
    list_private_companies,
    user_id,
)
from app.client_desk.models import ClientDeskWaLink, ClientDeskFollowup, ClientDeskState
from app.invoice.customer_profile_service import get_customer_grade
from app.invoice.product_service import _schema, _table_columns
from app.whatsapp.access import readable_accounts
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage
from app.core.time import beijing_now
from app.invoice.product_service import _parse_ts


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def visible_wa(
    db, user, company_id=None, *, for_ai=False, owner_only=False, company_ids=None
):
    uid = user_id(user)
    accounts = readable_accounts(db, uid, crm=True, ai=for_ai)
    query = (
        db.query(WhatsAppConversation, WhatsAppAccount)
        .join(
            WhatsAppAccount,
            WhatsAppAccount.account_uid == WhatsAppConversation.account_uid,
        )
        .filter(
            WhatsAppConversation.is_group.is_(False),
            WhatsAppAccount.account_uid.in_(accounts),
        )
    )
    if owner_only:
        query = query.filter(WhatsAppAccount.ark_user_id == uid)
    if company_id is not None or company_ids is not None:
        query = query.join(
            ClientDeskWaLink,
            (ClientDeskWaLink.account_uid == WhatsAppConversation.account_uid)
            & (
                ClientDeskWaLink.conversation_uid
                == WhatsAppConversation.conversation_uid
            ),
        ).filter(
            ClientDeskWaLink.company_id.in_(
                [int(company_id)]
                if company_id is not None
                else [int(cid) for cid in company_ids]
            ),
            ClientDeskWaLink.deleted_at.is_(None),
            ClientDeskWaLink.link_type.in_(["linked", "imported"]),
        )
    result = []
    pairs = query.all()
    conv_ids = [conv.conversation_uid for conv, _ in pairs]
    messages = (
        db.query(WhatsAppMessage)
        .filter(
            WhatsAppMessage.conversation_uid.in_(conv_ids),
            WhatsAppMessage.account_uid.in_(accounts),
            WhatsAppMessage.deleted_at.is_(None),
        )
        .all()
        if conv_ids
        else []
    )
    grouped = {}
    for message in messages:
        if message.sent_at or message.received_at:
            grouped.setdefault(
                (message.account_uid, message.conversation_uid), []
            ).append(message)
    for conv, account in pairs:
        rows = grouped.get((account.account_uid, conv.conversation_uid), [])
        rows.sort(key=lambda m: (m.sent_at or m.received_at, m.id))
        if rows:
            result.append((conv, account, rows))
    return result


def research_sources(db, user, company_id):
    from app.customer.models import (
        CustomerExternalIdentity as Identity,
        CustomerResearchTask as Task,
    )
    from app.customer.logical_customer_service import (
        logical_owner_expression,
        logical_subject_matches_customer,
    )
    from app.customer.models import CustomerAccount
    from app.customer.access_service import (
        require_customer_access,
        CustomerAccessDenied,
    )

    identities = (
        db.query(Identity)
        .filter(
            Identity.source_system == "okki",
            Identity.identifier_type == "company_id",
            Identity.normalized_value == str(company_id),
            Identity.status == "active",
            Identity.verification_status == "verified",
            Identity.identity_strength == "strong",
            Identity.cardinality == "one_to_one",
        )
        .all()
    )
    owners = (
        {
            r[0]
            for r in db.query(CustomerAccount.id)
            .join(
                Identity,
                logical_subject_matches_customer(
                    Identity, "external_identity", CustomerAccount
                ),
            )
            .filter(Identity.id.in_([i.id for i in identities]))
            .all()
        }
        if identities
        else set()
    )
    if len(owners) != 1:
        return []
    customer_id = owners.pop()
    actor = (
        user
        if isinstance(user, dict)
        else {"sub": str(user), "permissions": ["client_desk:read"], "roles": []}
    )
    try:
        access = require_customer_access(
            db,
            customer_id=customer_id,
            user=actor,
            action_permissions=["client_desk:read", "client_desk:write"],
            manage_permissions=[],
        )
    except CustomerAccessDenied:
        return []
    task_owner = logical_owner_expression(Task, "research_task")
    rows = (
        db.query(Task)
        .filter(
            task_owner == customer_id,
            Task.task_status == "completed",
            Task.result_review_status.in_(["accepted", "not_required"]),
            Task.data_classification.in_(access.allowed_classifications()),
            Task.visibility_scope.in_(access.allowed_visibility_scopes()),
        )
        .order_by(Task.updated_at.desc(), Task.id.desc())
        .all()
    )
    return [
        {
            "id": str(t.id),
            "result": t.result_json,
            "updated_at": t.updated_at,
            "classification": t.data_classification,
            "visibility": t.visibility_scope,
            "event_key": f"research:{t.id}",
        }
        for t in rows
    ]


def build_customer_sources(
    db, user, company_id, *, for_ai=False, realtime=True, card=None, context=None
):
    from app.client_desk.access import require_enabled

    actor = context["actor"] if context else require_enabled(db, user)
    user = actor
    if card is None or realtime:
        assert_company_access(db, user, company_id, realtime=realtime)
    if card is None:
        card = next(
            c
            for c in list_private_companies(db, user)
            if c["company_id"] == str(company_id)
        )
    card = dict(card)
    schema = _schema()
    if context is not None:
        raw = dict(context["raw"].get(str(company_id), {}))
        contacts = context["contacts"].get(str(company_id), [])
        orders = [dict(o) for o in context["orders"].get(str(company_id), [])]
    else:
        raw = (
            db.execute(
                text(f"SELECT * FROM `{schema}`.customer_info WHERE company_id=:cid"),
                {"cid": str(company_id)},
            )
            .mappings()
            .first()
        )
        raw = dict(raw or {})
        card["created_at"] = _parse_ts(raw.get("create_time") or raw.get("created_at"))
        contacts = [
            {
                k: (str(r[k]) if k == "id" else r[k])
                for k in ("id", "name", "email", "tel")
            }
            for r in db.execute(
                text(
                    f"SELECT id,name,email,tel FROM `{schema}`.customer_contacts WHERE company_id=:cid ORDER BY id"
                ),
                {"cid": str(company_id)},
            ).mappings()
        ]
        from app.order_intelligence.service import VALID_ORDER_SQL

        orders = [
            dict(r)
            for r in db.execute(
                text(
                    f'SELECT o.*, CASE WHEN {VALID_ORDER_SQL.format(a="o")} THEN 1 ELSE 0 END AS valid_business FROM `{schema}`.okki_orders o WHERE o.company_id=:cid ORDER BY o.account_date,o.order_id'
                ),
                {"cid": str(company_id)},
            ).mappings()
        ]
    card["created_at"] = _parse_ts(raw.get("create_time") or raw.get("created_at"))
    order_days, in_transit, gaps = classify_orders(orders, raw)
    from app.core.config import get_settings

    status_map = (
        get_settings()
        .CLIENT_DESK_RULES.get("order_classification", {})
        .get("status_map", {})
    )
    last_non_cancelled = max(
        [
            o["account_date"]
            for o in orders
            if o.get("account_date")
            and status_map.get(str(o.get("status"))) in ("completed", "in_transit")
            and o.get("valid_business")
        ],
        default=None,
    )
    orders = [o for o in orders if o.get("valid_business")]
    for o in orders:
        o["id"] = str(o.pop("order_id"))
        o["event_key"] = "order:" + o["id"]
        o["amount_usd"] = (
            float(o["amount_usd"]) if o["amount_usd"] is not None else None
        )
    allowed_order_keys = {
        "id",
        "event_key",
        "order_no",
        "account_date",
        "amount_usd",
        "status",
        "status_name",
    }
    orders = [{k: v for k, v in o.items() if k in allowed_order_keys} for o in orders]
    research = research_sources(db, user, company_id)
    messages = []
    conversations = []
    targets = []
    deps = []
    wa_rows = (
        context["wa"].get(str(company_id), [])
        if context
        else visible_wa(db, user, company_id, for_ai=for_ai)
    )
    for conv, account, rows in wa_rows:
        last = rows[-1]
        at = last.sent_at or last.received_at
        conversations.append(
            {
                "account_uid": account.account_uid,
                "conversation_uid": conv.conversation_uid,
                "last_at": at,
                "direction": (
                    "inbound" if last.direction in ("in", "inbound") else "outbound"
                ),
                "owner_user_id": str(account.ark_user_id),
            }
        )
        targets.append(
            {
                "account_uid": account.account_uid,
                "conversation_uid": conv.conversation_uid,
                "phone": conv.contact_phone,
                "name": conv.contact_name,
            }
        )
        if context is not None:
            link = context["links"][(account.account_uid, conv.conversation_uid)]
        else:
            link = (
                db.query(ClientDeskWaLink)
                .filter_by(
                    account_uid=account.account_uid,
                    conversation_uid=conv.conversation_uid,
                    deleted_at=None,
                )
                .one()
            )
        deps.append(
            {
                "account": account.account_uid,
                "version": account.consent_version,
                "generation": account.session_generation,
                "link": str(link.id),
                "ai": account.ai_egress_allowed,
                "messages": [
                    [str(m.id), m.source_revision, message_fingerprint(m)] for m in rows
                ],
            }
        )
        for m in rows:
            at = m.sent_at or m.received_at
            messages.append(
                {
                    "key": f"M-{m.id}",
                    "id": str(m.id),
                    "event_key": f"wa:{conv.conversation_uid}:{at.date().isoformat()}",
                    "text": m.content_text or "",
                    "at": at,
                    "direction": (
                        "inbound" if m.direction in ("in", "inbound") else "outbound"
                    ),
                    "account_uid": account.account_uid,
                    "conversation_uid": conv.conversation_uid,
                    "owner_user_id": str(account.ark_user_id),
                }
            )
    if context is not None:
        followups = context["followups"].get(str(company_id), [])
    else:
        followups = (
            db.query(ClientDeskFollowup)
            .filter_by(
                user_id=user_id(user), company_id=int(company_id), deleted_at=None
            )
            .all()
        )
    touches = [(m["at"], "whatsapp") for m in messages] + [
        (f.happened_at, f.channel) for f in followups
    ]
    last_touch = max(touches, default=(None, None), key=lambda x: x[0])
    if context is not None:
        state = context["states"].get(str(company_id))
        grade = context["grades"].get(str(company_id))
    else:
        state = (
            db.query(ClientDeskState)
            .filter_by(user_id=user_id(user), company_id=int(company_id))
            .first()
        )
        grade = get_customer_grade(db, company_id)
    manual = (
        {
            "remark": state.remark,
            "next_followup_date": state.next_followup_date,
            "next_followup_remark": state.next_followup_remark,
        }
        if state
        else {}
    )
    deps.sort(key=lambda dep: (dep["account"], dep["link"]))
    dependencies = {
        "manual": digest(manual),
        "followups": digest([(f.id, f.content, f.happened_at) for f in followups]),
        "grade": grade,
        "wa": deps,
        "research": [{"id": r["id"], "hash": digest(r)} for r in research],
        "orders": digest(orders),
        "card": digest(card),
        "contacts": digest(contacts),
    }
    refs = {
        m["key"]: {"source": "whatsapp", "event_key": m["event_key"], "text": m["text"]}
        for m in messages
    }
    refs.update(
        {
            f'O-{o["id"]}': {"source": "order", "event_key": o["event_key"], "datum": o}
            for o in orders
        }
    )
    refs.update(
        {
            f'S-{r["id"]}': {
                "source": "research",
                "event_key": r["event_key"],
                "datum": r["result"],
            }
            for r in research
        }
    )
    refs.update(
        {
            f"F-{f.id}": {
                "source": "followup",
                "event_key": f"followup:{f.id}",
                "text": f.content,
                "at": f.happened_at,
            }
            for f in followups
        }
    )
    activities = [o["account_date"] for o in orders if o["account_date"]] + [
        r["updated_at"] for r in research
    ]
    ai_dependencies = dict(dependencies)
    if not for_ai:
        ai_dependencies["wa"] = [d for d in deps if d["ai"]]
    return {
        "ai_source_dependencies": ai_dependencies,
        "outbound_coverage_complete": False,
        "communication_times": [
            m["at"]
            for m in messages
            if m["direction"] == "outbound" and m["owner_user_id"] == str(user_id(user))
        ]
        + [f.happened_at for f in followups],
        "manual": manual,
        "company_id": str(company_id),
        "card": card,
        "contacts": contacts,
        "grade": get_customer_grade(db, company_id),
        "created_at": card["created_at"],
        "grade_options": context["grade_options"] if context else grade_options(db),
        "own_last_outbound_at": max(
            [
                m["at"]
                for m in messages
                if m["direction"] == "outbound"
                and m["owner_user_id"] == str(user_id(user))
            ],
            default=None,
        ),
        "orders": orders,
        "orders_summary": {
            "count": len(orders),
            "amount_usd": sum(
                o["amount_usd"] for o in orders if o["amount_usd"] is not None
            ),
            "unknown_amount_count": sum(o["amount_usd"] is None for o in orders),
        },
        "research": research,
        "research_summary": research[0]["result"] if research else None,
        "conversations": conversations,
        "wa_targets": targets,
        "messages": messages,
        "refs": refs,
        "source_dependencies": dependencies,
        "fingerprint": digest(dependencies),
        "last_touch_at": last_touch[0],
        "last_touch_channel": last_touch[1],
        "order_days": order_days,
        "order_count": len(orders),
        "last_order_date": last_non_cancelled,
        "in_transit": in_transit,
        "activity_at": max(activities, key=str) if activities else None,
        "activity_watermark": digest({"orders": orders, "research": research}),
        "sync_times": {
            "customer": raw.get("update_time"),
            "whatsapp": max(
                [a.last_sync_at for _, a, _ in wa_rows if a.last_sync_at], default=None
            ),
        },
        "coverage_gaps": gaps,
    }


def analysis_input(db, user_id, company_id, now=None, *, feed_item_ids=None):
    source = build_customer_sources(db, user_id, company_id, for_ai=True)
    if feed_item_ids:
        from app.alibaba_feed.business_service import select_for_analysis

        selected = select_for_analysis(db, user_id, company_id, feed_item_ids)
        source["refs"] = (source.get("refs") or {}) | selected["refs"]
        source["messages"] = (source.get("messages") or []) + selected["messages"]
        source["source_dependencies"] = source["source_dependencies"] | {
            "alibaba_feed": selected["dependencies"]
        }
        source["coverage_gaps"] = (source.get("coverage_gaps") or []) + selected[
            "coverage_gaps"
        ]
        source["analysis_policy"] = "manual_only_v1"
    return source


def scan_inputs(db, user_id, now=None):
    from app.client_desk.source_context import prepare

    cards = list_private_companies(db, user_id)
    context = prepare(db, user_id, cards)
    return [
        build_customer_sources(
            db,
            user_id,
            c["company_id"],
            for_ai=False,
            realtime=False,
            card=c,
            context=context,
        )
        for c in cards
    ]


def grade_options(db):
    from app.system.models import SysDict

    return [
        r.code
        for r in db.query(SysDict)
        .filter(
            SysDict.type == "customer_grade",
            SysDict.is_active.is_(True),
            SysDict.code.in_(list("SABCDE")),
        )
        .order_by(SysDict.sort, SysDict.id)
    ]


def classify_orders(orders, raw):
    """Only a versioned, explicitly calibrated mapping may classify sample/in-flight status."""
    from app.core.config import get_settings

    config = get_settings().CLIENT_DESK_RULES.get("order_classification", {})
    sample_field = config.get("sample_field")
    sample_values = config.get("sample_values", [])
    bulk_values = config.get("bulk_values", [])
    statuses = config.get("status_map", {})
    days = []
    unknown = False
    in_transit = False
    for order in orders:
        status = statuses.get(str(order.get("status")))
        if status not in ("cancelled", "in_transit", "completed"):
            unknown = True
        if status == "in_transit":
            in_transit = True
        if status == "cancelled":
            continue
        sample = order.get(sample_field) if sample_field else None
        if (
            sample in bulk_values
            and status == "completed"
            and order.get("account_date")
            and order.get("valid_business", True)
        ):
            days.append(order["account_date"])
        elif sample not in sample_values and sample not in bulk_values:
            unknown = True
    gaps = (
        ["部分订单样品或物流状态未校准，暂不推断复购"]
        if unknown or (orders and not sample_field)
        else []
    )
    return ([] if gaps else days), (None if gaps else in_transit), gaps


def message_fingerprint(message):
    return digest(
        {
            "text": message.content_text,
            "preview": message.content_preview,
            "type": message.content_type,
            "direction": message.direction,
            "sent_at": message.sent_at,
            "received_at": message.received_at,
            "deleted_at": message.deleted_at,
        }
    )
