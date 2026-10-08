"""Capture business row changes in the original SQLAlchemy transaction.

Flush hooks also cover deleted items and changes made outside HTTP handlers.
Old rows are read directly on the transaction connection, before SQL is flushed.
Only a field whitelist enters evidence; contact and voucher data never do.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session
from app.domestic.models import DomesticCustomer, DomesticOrder, DomesticOrderItem, DomesticCustomerLedger
from app.domestic_decision.models import DecisionEvent
from app.core.time import beijing_now
from app.domestic_decision.schemas import PRODUCT_FIELDS

FIELDS = {
    DomesticCustomer: ("id", "owner_user_id", "membership_level", "settle_mode", "status", "province", "city", "customer_source", "store_type", "customer_level", "lifecycle_status"),
    DomesticOrder: ("id", "customer_id", "order_kind", "order_date", "order_category", "order_type", "order_channel", "status", "total_amount", "charged_amount", "deleted_flag", "created_by"),
    DomesticOrderItem: ("id", "order_id", "line_no", "attrs_snapshot", "order_qty", "unit_price", "original_price", "default_discount_price", "discount_amount", "labor_fee", "membership_level_snapshot", "pricing_rule", "pricing_version", "status", "ship_time", "color"),
    DomesticCustomerLedger: ("id", "customer_id", "order_id", "transaction_type", "amount", "balance_before", "balance_after", "business_key", "created_by", "created_at"),
}
NAMES = {DomesticCustomer: "customer", DomesticOrder: "order", DomesticOrderItem: "item", DomesticCustomerLedger: "ledger"}


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def safe_snapshot(value):
    return {key: value[key] for key in PRODUCT_FIELDS if key in value} if isinstance(value, dict) else None


def _fields(values):
    return {key: safe_snapshot(value) if key == "attrs_snapshot" else _json(value) for key, value in values.items()}


@event.listens_for(Session, "before_flush")
def capture_before(session, _context, _instances):
    pending = []
    for row in set(session.new) | set(session.dirty) | set(session.deleted):
        cls = type(row)
        if cls not in FIELDS:
            continue
        if row in session.dirty and not session.is_modified(row, include_collections=False):
            continue
        keys = FIELDS[cls]
        before = None
        if row not in session.new:
            old = session.connection().execute(select(*(cls.__table__.c[key] for key in keys)).where(cls.__table__.c.id == row.id)).mappings().first()
            before = _fields(old) if old else None
        pending.append((row, before, row in session.deleted))
    if pending:
        session.info["domestic_decision_pending_events"] = pending


@event.listens_for(Session, "after_flush_postexec")
def capture_after(session, _context):
    for row, before, deleted in session.info.pop("domestic_decision_pending_events", []):
        cls = type(row)
        after = None if deleted else _fields({key: getattr(row, key) for key in FIELDS[cls]})
        if before == after:
            continue
        customer_id = row.id if cls is DomesticCustomer else getattr(row, "customer_id", None)
        order_id = row.id if cls is DomesticOrder else getattr(row, "order_id", None)
        business_date = getattr(row, "order_date", None)
        if order_id and cls is not DomesticOrder:
            order = session.connection().execute(select(DomesticOrder.__table__.c.customer_id, DomesticOrder.__table__.c.order_date).where(DomesticOrder.__table__.c.id == order_id)).first()
            if order:
                customer_id, business_date = order
        owner = getattr(row, "owner_user_id", None)
        if customer_id and cls is not DomesticCustomer:
            owner = session.connection().execute(select(DomesticCustomer.__table__.c.owner_user_id).where(DomesticCustomer.__table__.c.id == customer_id)).scalar()
        session.add(DecisionEvent(
            source_event_key=str(uuid4()), entity_type=NAMES[cls], entity_id=row.id,
            customer_id=customer_id, order_id=order_id,
            event_type="deleted" if deleted else "created" if before is None else "changed",
            business_date=business_date, before=before, after=after,
            owner_user_id=owner, actor_user_id=session.info.get("domestic_actor_id"),
            occurred_at=beijing_now(),
        ))


@event.listens_for(Session, "after_rollback")
def discard_pending(session):
    session.info.pop("domestic_decision_pending_events", None)
