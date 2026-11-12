"""Evidence and order access checks for both generation and snapshot reads."""
from datetime import timedelta

from sqlalchemy import select

from app.domestic.models import DomesticCustomer, DomesticOrder
from app.domestic_followup import customer_overview, visibility
from app.domestic_followup.collaboration_models import FollowupCustomerProfile


def won_customer_ids(db, customer_ids, today):
    """Count only customers represented in the actual input, using the overview's deal rules."""
    if not customer_ids:
        return set()
    customer, profile = DomesticCustomer, FollowupCustomerProfile
    candidates = select(
        customer.id, customer.first_order_date, customer.last_order_date, customer.total_order_count,
        customer.total_sales_amount, customer.lifecycle_status, profile.deal_status.label("verified_status"),
        profile.deal_verified_at, profile.deal_verified_by_user_id, profile.deal_evidence, profile.deal_override_status,
    ).outerjoin(profile, profile.customer_id == customer.id).where(
        customer.id.in_(customer_ids), customer.status == 1,
    ).cte("insight_candidates")
    orders = customer_overview._order_evidence(db, candidates)
    status, *_ = customer_overview._deal_evidence(candidates, orders, today)
    return set(db.scalars(select(candidates.c.id).outerjoin(
        orders, orders.c.customer_id == candidates.c.id,
    ).where(status == "won")))


def order_comparison(db, user, customer_id, today):
    """Order amounts never enter AI prose; read them with the current viewer's order scope."""
    permissions = user.get("permissions") or []
    super_admin = visibility.is_super_admin(user)
    if not super_admin and "domestic:read" not in permissions:
        return None
    query = db.query(DomesticOrder).filter(
        DomesticOrder.customer_id == customer_id, DomesticOrder.deleted_flag == 0,
        DomesticOrder.order_kind == "business", DomesticOrder.status.in_((1, 2, 3)),
        DomesticOrder.order_date > today - timedelta(days=180), DomesticOrder.order_date <= today,
    )
    if not super_admin and "domestic:read_all" not in permissions:
        query = query.filter(DomesticOrder.created_by == visibility.uid(user))
    orders = query.all()
    recent = [order for order in orders if order.order_date > today - timedelta(days=90)]
    previous = [order for order in orders if order.order_date <= today - timedelta(days=90)]
    return {"recent_count": len(recent), "previous_count": len(previous),
            "recent_amount": float(sum((order.total_amount for order in recent), 0)),
            "previous_amount": float(sum((order.total_amount for order in previous), 0))}


def valid_evidence_ids(item, evidence):
    versions = item.evidence_versions or {}
    return [record_id for record_id in item.evidence_followup_ids or []
            if record_id in evidence and versions.get(str(record_id)) == evidence[record_id]["version"]]
