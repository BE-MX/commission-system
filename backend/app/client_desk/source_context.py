"""Bounded collection source reads shared by scans and customer lists."""

from collections import defaultdict
from sqlalchemy import text, bindparam, func
from app.client_desk.private_scope import user_id
from app.client_desk.access import require_enabled
from app.client_desk.models import ClientDeskState, ClientDeskFollowup, ClientDeskWaLink
from app.invoice.models import CustomerProfile
from app.invoice.product_service import _schema
from app.order_intelligence.service import VALID_ORDER_SQL


def _linked_whatsapp(db, actor, ids):
    from app.client_desk.sources import visible_wa

    links = {
        (r.account_uid, r.conversation_uid): r
        for r in db.query(ClientDeskWaLink).filter(
            ClientDeskWaLink.company_id.in_(ids),
            ClientDeskWaLink.deleted_at.is_(None),
            ClientDeskWaLink.link_type.in_(["linked", "imported"]),
        )
    }
    by_company = defaultdict(list)
    if links:
        for conv, account, messages in visible_wa(db, actor, company_ids=ids):
            link = links.get((account.account_uid, conv.conversation_uid))
            if link:
                by_company[str(link.company_id)].append((conv, account, messages))
    return links, by_company


def _manual_followups(db, actor, ids):
    return db.query(ClientDeskFollowup).filter(
        ClientDeskFollowup.user_id == user_id(actor),
        ClientDeskFollowup.company_id.in_(ids),
        ClientDeskFollowup.deleted_at.is_(None),
    )


def list_last_touches(db, actor, ids):
    """Read recent-contact fields for a page without assembling customer dossiers."""
    from app.client_desk.sources import visible_wa_query
    from app.whatsapp.models import WhatsAppConversation, WhatsAppMessage

    if not ids:
        return {}
    touches = defaultdict(list)
    # The same live account/consent/link scope as dossier sources, without bodies.
    whatsapp = visible_wa_query(db, actor, company_ids=ids).join(
        WhatsAppMessage,
        (WhatsAppMessage.account_uid == WhatsAppConversation.account_uid)
        & (WhatsAppMessage.conversation_uid == WhatsAppConversation.conversation_uid),
    ).filter(WhatsAppMessage.deleted_at.is_(None)).with_entities(
        ClientDeskWaLink.company_id,
        func.max(func.coalesce(WhatsAppMessage.sent_at, WhatsAppMessage.received_at)),
    ).group_by(ClientDeskWaLink.company_id)
    for cid, at in whatsapp:
        if at is not None:
            touches[str(cid)].append((at, "whatsapp"))
    latest = _manual_followups(db, actor, ids).with_entities(
        ClientDeskFollowup.company_id,
        func.max(ClientDeskFollowup.happened_at).label("last_at"),
    ).group_by(ClientDeskFollowup.company_id).subquery()
    for cid, at, channel in _manual_followups(db, actor, ids).join(
        latest,
        (ClientDeskFollowup.company_id == latest.c.company_id)
        & (ClientDeskFollowup.happened_at == latest.c.last_at),
    ).with_entities(
        ClientDeskFollowup.company_id,
        ClientDeskFollowup.happened_at,
        ClientDeskFollowup.channel,
    ).order_by(ClientDeskFollowup.id):
        touches[str(cid)].append((at, channel))
    return {
        cid: max(values, key=lambda touch: touch[0]) for cid, values in touches.items()
    }


def prepare(db, user, cards):
    from app.client_desk.sources import grade_options

    actor = require_enabled(db, user)
    ids = [c["company_id"] for c in cards]
    context = {
        "actor": actor,
        "raw": {},
        "contacts": defaultdict(list),
        "orders": defaultdict(list),
        "wa": defaultdict(list),
        "links": {},
        "followups": defaultdict(list),
        "states": {},
        "grades": {},
        "grade_options": grade_options(db),
    }
    if not ids:
        return context
    schema = _schema()

    def mirror(sql):
        return db.execute(
            text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": ids}
        ).mappings()

    for row in mirror(
        f"SELECT * FROM `{schema}`.customer_info WHERE company_id IN :ids"
    ):
        context["raw"][str(row["company_id"])] = dict(row)
    for row in mirror(
        f"SELECT id,company_id,name,email,tel FROM `{schema}`.customer_contacts WHERE company_id IN :ids ORDER BY id"
    ):
        context["contacts"][str(row["company_id"])].append(
            {
                k: str(row[k]) if k == "id" else row[k]
                for k in ("id", "name", "email", "tel")
            }
        )
    for row in mirror(
        f'SELECT o.*,CASE WHEN {VALID_ORDER_SQL.format(a="o")} THEN 1 ELSE 0 END valid_business FROM `{schema}`.okki_orders o WHERE o.company_id IN :ids ORDER BY o.account_date,o.order_id'
    ):
        context["orders"][str(row["company_id"])].append(dict(row))
    context["links"], context["wa"] = _linked_whatsapp(db, actor, ids)
    for row in _manual_followups(db, actor, ids):
        context["followups"][str(row.company_id)].append(row)
    context["states"] = {
        str(r.company_id): r
        for r in db.query(ClientDeskState).filter(
            ClientDeskState.user_id == user_id(actor),
            ClientDeskState.company_id.in_(ids),
        )
    }
    context["grades"] = {
        r.customer_id: r.customer_grade
        for r in db.query(CustomerProfile).filter(CustomerProfile.customer_id.in_(ids))
    }
    return context
