"""Versioned conversation association, serialized on the owned conversation."""

import re

from fastapi import HTTPException
from app.client_desk.access import require_account, require_enabled
from app.client_desk.private_scope import assert_company_access, user_id
from app.client_desk.models import ClientDeskWaLink as Link, ClientDeskState as State
from app.whatsapp.models import WhatsAppConversation
from app.core.time import beijing_now


def link_dto(row):
    return {
        "id": str(row.id),
        "account_uid": row.account_uid,
        "conversation_uid": row.conversation_uid,
        "company_id": str(row.company_id) if row.company_id else None,
        "link_type": row.link_type,
        "deleted_at": row.deleted_at,
    }


def invalidate(db, company_ids):
    # Keep stored dependency metadata: subsequent reads fail comparison, including old image.
    for state in (
        db.query(State)
        .filter(State.company_id.in_([c for c in company_ids if c is not None]))
        .all()
    ):
        state.last_touch_at = None
        state.last_touch_channel = None


def save_link(db, user, payload):
    require_enabled(db, user, True)
    require_account(db, user, payload.account_uid, owner_only=True)
    conv = (
        db.query(WhatsAppConversation)
        .filter_by(
            account_uid=payload.account_uid,
            conversation_uid=payload.conversation_uid,
            is_group=False,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if conv is None:
        raise HTTPException(404, "会话不存在或不可访问")
    if payload.link_type == "linked":
        if not payload.company_id:
            raise HTTPException(422, "请选择本人私海客户")
        assert_company_access(db, user, payload.company_id)
    elif payload.company_id is not None:
        raise HTTPException(422, "忽略会话不能指定客户")
    old = (
        db.query(Link)
        .filter_by(
            account_uid=payload.account_uid,
            conversation_uid=payload.conversation_uid,
            deleted_at=None,
        )
        .with_for_update()
        .first()
    )
    target = int(payload.company_id) if payload.company_id else None
    if old and old.company_id == target and old.link_type == payload.link_type:
        return link_dto(old)
    if (str(old.id) if old else None) != payload.expected_link_id:
        raise HTTPException(
            409,
            detail={"code": "LINK_CONFLICT", "current": link_dto(old) if old else None},
        )
    if old:
        old.deleted_at = beijing_now()
        old.updated_by = user_id(user)
        db.flush()
    row = Link(
        account_uid=payload.account_uid,
        conversation_uid=payload.conversation_uid,
        company_id=target,
        link_type=payload.link_type,
        created_by=user_id(user),
    )
    db.add(row)
    invalidate(db, [old.company_id if old else None, target])
    db.commit()
    return link_dto(row)


def delete_link(db, user, link_id):
    require_enabled(db, user, True)
    row = db.query(Link).filter_by(id=int(link_id)).first()
    if row is None:
        raise HTTPException(404, "关联不存在或不可访问")
    require_account(db, user, row.account_uid, owner_only=True)
    db.query(WhatsAppConversation).filter_by(
        account_uid=row.account_uid, conversation_uid=row.conversation_uid
    ).with_for_update().one()
    row = (
        db.query(Link).filter_by(id=row.id).populate_existing().with_for_update().one()
    )
    if row.deleted_at:
        return link_dto(row)
    row.deleted_at = beijing_now()
    row.updated_by = user_id(user)
    invalidate(db, [row.company_id])
    db.commit()
    return link_dto(row)


def _personal_jid(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([0-9]{1,30})(?::[0-9]+)?@(lid|s\.whatsapp\.net|c\.us)", value)
    if not match:
        return None
    user, domain = match.groups()
    return f"{user}@{'s.whatsapp.net' if domain == 'c.us' else domain}"


def non_customer_reason(conv, account):
    """Classify by exact provider identity; never by contact names or alias guesses."""
    jid = _personal_jid(conv.chat_id)
    if jid == "0@s.whatsapp.net":
        return "platform_notice"
    payload = account.raw_payload if isinstance(account.raw_payload, dict) else {}
    identity = payload.get("self_identity")
    conversation_payload = conv.raw_payload if isinstance(conv.raw_payload, dict) else {}
    if (not jid or account.provider != "baileys" or not isinstance(identity, dict)
            or account.status == "reconnect_required"
            or str(conversation_payload.get("session_generation")) != str(account.session_generation)
            or conv.account_uid != account.account_uid
            or payload.get("account_uid") != account.account_uid
            or str(payload.get("session_generation")) != str(account.session_generation)
            or str(payload.get("consent_version")) != str(account.consent_version)
            or str(identity.get("session_generation")) != str(account.session_generation)):
        return None
    if jid in {_personal_jid(identity.get("pn_jid")), _personal_jid(identity.get("lid_jid"))}:
        return "self"
    return None


def conversations(db, user, keyword="", page=1, page_size=30, scope=None):
    require_enabled(db, user)
    from app.client_desk.sources import visible_wa

    result = []
    for conv, account, messages in visible_wa(db, user, owner_only=True):
        if scope is None and non_customer_reason(conv, account):
            continue
        link = (
            db.query(Link)
            .filter_by(
                account_uid=account.account_uid,
                conversation_uid=conv.conversation_uid,
                deleted_at=None,
            )
            .first()
        )
        kind = link.link_type if link else None
        if scope == "linked" and kind not in ("linked", "imported"):
            continue
        if scope == "ignored" and kind != "ignored":
            continue
        if scope is None and link:
            continue
        if keyword.casefold() not in (
            conv.contact_name or ""
        ).casefold() and keyword not in (conv.contact_phone or ""):
            continue
        last = messages[-1]
        result.append(
            {
                "account_uid": account.account_uid,
                "conversation_uid": conv.conversation_uid,
                "name": conv.contact_name,
                "phone": conv.contact_phone,
                "last_at": last.sent_at or last.received_at,
                "awaiting_reply": last.direction in ("in", "inbound"),
                "link": link_dto(link) if link else None,
            }
        )
    result.sort(
        key=lambda r: (r["awaiting_reply"], r["last_at"], r["conversation_uid"]),
        reverse=True,
    )
    return {
        "items": result[(page - 1) * page_size : page * page_size],
        "total": len(result),
        "unreplied_count": sum(r["awaiting_reply"] for r in result),
        "page": page,
        "page_size": page_size,
    }
