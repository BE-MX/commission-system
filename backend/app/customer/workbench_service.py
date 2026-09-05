"""Permission-scoped daily work: SQL totals, effective deadlines and useful context."""

from datetime import datetime, time, timedelta

from sqlalchemy import and_, case, func, or_, select

from app.auth.models import ArkUser
from app.core.time import beijing_now, to_beijing_naive
from app.customer import query_service
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import (
    CustomerAccount, CustomerAction, CustomerConversation, CustomerListProjection,
    CustomerMessage, CustomerOpportunity,
)


VIEWS = {"focus", "first_contact", "today", "overdue", "high_priority", "completed",
         "unscheduled", "upcoming", "snoozed", "all"}


def effective_deadline():
    return case(
        (CustomerAction.status == "snoozed", CustomerAction.snoozed_until),
        else_=CustomerAction.due_at,
    )


def _first_contact():
    """Conservatively exclude established relationships and any recorded outreach."""
    previous = CustomerAction
    previous_owner = logical_owner_expression(previous, "action")
    contacted = select(previous_owner).where(and_(
        previous_owner.isnot(None),
        previous.status == "done",
        or_(
            previous.feedback_json["completion"]["channel"].as_string().in_(
                ("email", "whatsapp", "phone", "linkedin", "alibaba", "offline"),
            ),
            and_(
                previous.channel.in_(("email", "whatsapp", "phone", "linkedin", "alibaba", "offline")),
                previous.outcome_code.in_(("contacted", "replied", "no_response", "meeting_booked", "wrong_contact")),
            ),
        ),
    )).correlate(None)
    conversation_owner = logical_owner_expression(CustomerConversation, "conversation")
    outbound = select(conversation_owner).join(
        CustomerMessage, CustomerMessage.conversation_id == CustomerConversation.id,
    ).where(CustomerMessage.direction == "out", conversation_owner.isnot(None)).correlate(None)
    return and_(CustomerAccount.relationship_stage.in_(("discovered", "qualified", "developing")),
                CustomerAccount.id.notin_(contacted), CustomerAccount.id.notin_(outbound))


def _predicates(now):
    start = datetime.combine(now.date(), time.min)
    end = start + timedelta(days=1)
    due = effective_deadline()
    available = or_(
        CustomerAction.status == "pending",
        and_(CustomerAction.status == "snoozed", CustomerAction.snoozed_until <= now),
    )
    return {
        "focus": and_(available, or_(due.is_(None), due < end)),
        "first_contact": and_(available, _first_contact()),
        "today": and_(available, due >= now, due < end),
        "overdue": and_(available, due < now),
        "high_priority": and_(available, CustomerAction.priority.in_(("urgent", "high"))),
        "completed": and_(CustomerAction.status == "done", CustomerAction.completed_at >= start,
                          CustomerAction.completed_at < end),
        "unscheduled": and_(available, due.is_(None)),
        "upcoming": and_(available, due >= end),
        "snoozed": and_(CustomerAction.status == "snoozed", CustomerAction.snoozed_until > now),
        "all": True,
    }


def can_manage(user):
    return ("super_admin" in (user.get("roles") or []) and not user.get("_agent_run")) or (
        "customer:admin" in (user.get("permissions") or [])
    )


def customer_labels(db, customer_ids):
    """Caller supplies already-scoped IDs; no per-row access or profile compilation."""
    if not customer_ids:
        return {}
    rows = db.query(CustomerAccount, CustomerListProjection).outerjoin(
        CustomerListProjection, CustomerListProjection.customer_id == CustomerAccount.id,
    ).filter(CustomerAccount.id.in_(customer_ids)).all()
    return {account.id: {
        "customer_name": account.display_name or account.canonical_company_name or account.customer_code or "待核实客户",
        "customer_code": account.customer_code,
        "country_code": account.primary_country_code,
        "identity_status": account.identity_status,
        "relationship_stage": account.relationship_stage,
        "industry": projection.primary_industry if projection else None,
    } for account, projection in rows}


def enrich_rows(db, items, user, *, kind="action", now=None):
    if not items:
        return items
    labels = customer_labels(db, {item["customer_id"] for item in items})
    owners = {row.id: row.real_name or row.username for row in db.query(ArkUser).filter(
        ArkUser.id.in_({item.get("owner_user_id") for item in items if item.get("owner_user_id")}),
    ).all()}
    opportunity_ids = {item.get("opportunity_id") for item in items if item.get("opportunity_id")}
    opportunities = {row.id: (row, int(owner)) for row, owner in db.query(
        CustomerOpportunity, logical_owner_expression(CustomerOpportunity, "opportunity"),
    ).filter(CustomerOpportunity.id.in_(opportunity_ids)).all()} if opportunity_ids else {}
    uid = int(user["sub"])
    for item in items:
        item.update(labels.get(item["customer_id"], {}))
        item["owner_name"] = owners.get(item.get("owner_user_id"), "待分配")
        linked = opportunities.get(item.get("opportunity_id"))
        valid_link = linked is not None and linked[1] == item["customer_id"]
        item["can_operate"] = can_manage(user) or (
            item.get("owner_user_id") == uid and
            (kind != "action" or not item.get("opportunity_id") or
             valid_link and linked[0].owner_user_id == uid)
        )
        if kind == "action":
            item["opportunity_title"] = linked[0].title if valid_link else None
            due = item.get("snoozed_until") if item["status"] == "snoozed" else item.get("due_at")
            item["effective_due_at"] = due
            snooze_due = (item["status"] == "snoozed" and due is not None
                          and to_beijing_naive(datetime.fromisoformat(due)) <= (now or beijing_now()))
            item["effective_status"] = "pending" if snooze_due else item["status"]
    return items


def list_workbench(db, user, *, page=1, page_size=20, view="focus", scope="mine", keyword=None, customer_id=None):
    now = beijing_now()
    predicates = _predicates(now)
    owner = logical_owner_expression(CustomerAction, "action")
    query = db.query(CustomerAction).join(CustomerAccount, CustomerAccount.id == owner).filter(
        owner.in_(query_service._scoped_ids(
            db, user, read_permissions=query_service.ACTION_READ, include_public_pool=False,
        )),
    )
    if scope == "mine":
        query = query.filter(CustomerAction.owner_user_id == int(user["sub"]))
    if customer_id is not None:
        # Resolve/authorize a direct customer filter rather than leaking its existence.
        access = query_service._access(db, customer_id, user, read_permissions=query_service.ACTION_READ,
                                       allow_public_pool=False)
        query = query.filter(owner == access.customer_id)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(CustomerAccount.display_name.ilike(pattern),
                                 CustomerAccount.canonical_company_name.ilike(pattern),
                                 CustomerAccount.customer_code.ilike(pattern)))
    counts = query.with_entities(*[
        func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name)
        for name, condition in predicates.items()
    ]).one()
    summary = {name: int(getattr(counts, name)) for name in predicates}
    selected = query.filter(predicates[view])
    due = effective_deadline()
    priority = case((CustomerAction.priority == "urgent", 0), (CustomerAction.priority == "high", 1),
                    (CustomerAction.priority == "normal", 2), else_=3)
    rows = selected.with_entities(CustomerAction, owner.label("logical_customer_id")).order_by(
        case((predicates["overdue"], 0), (predicates["today"], 1), else_=2),
        priority, due.is_(None), due, CustomerAction.id,
    ).offset((page - 1) * page_size).limit(page_size).all()
    items = [query_service.serialize_action(row, customer_id=int(logical_id)) for row, logical_id in rows]
    return {
        "items": enrich_rows(db, items, user, now=now), "total": summary[view],
        "page": page, "page_size": page_size, "summary": summary,
        "data_as_of": query_service.iso_beijing(now), "count_unit": "action",
    }
