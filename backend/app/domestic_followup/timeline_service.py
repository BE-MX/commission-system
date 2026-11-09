"""Customer history pages with independent shipment and communication permissions."""
from sqlalchemy import func, literal, select, union_all

from app.domestic.models import DomesticCustomer
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine
from app.domestic_followup import config_service, visibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask

PAGE_SIZE = 100


def _event_ids(db, records, customer_id, include_shipments, event_type, offset):
    sources = []
    if event_type in ("all", "followup"):
        sources.append(records.with_only_columns(
            literal(1).label("kind"), func.date(DomesticFollowup.followup_date).label("event_date"),
            DomesticFollowup.id.label("event_id"),
        ))
    if include_shipments and event_type in ("all", "shipment"):
        sources.append(select(
            literal(0).label("kind"), func.date(DomesticShipment.ship_time).label("event_date"),
            DomesticShipment.id.label("event_id"),
        ).where(DomesticShipment.customer_id == customer_id, DomesticShipment.cancelled_at.is_(None)))
    if not sources:
        return [], False
    index = (union_all(*sources) if len(sources) > 1 else sources[0]).subquery()
    rows = db.execute(select(index).order_by(
        index.c.event_date.desc(), index.c.kind.desc(), index.c.event_id.desc(),
    ).offset(offset).limit(PAGE_SIZE + 1)).all()
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def _serialize_events(db, event_ids):
    from app.domestic_followup.followup_service import serialize

    followup_ids = [row.event_id for row in event_ids if row.kind]
    shipment_ids = [row.event_id for row in event_ids if not row.kind]
    followups = {r.id: r for r in db.scalars(select(DomesticFollowup).where(
        DomesticFollowup.id.in_(followup_ids),
    ))} if followup_ids else {}
    shipments = {r.id: r for r in db.scalars(select(DomesticShipment).where(
        DomesticShipment.id.in_(shipment_ids),
    ))} if shipment_ids else {}
    quantities = dict(db.execute(select(DomesticShipmentLine.shipment_id, func.sum(DomesticShipmentLine.quantity))
                                 .where(DomesticShipmentLine.shipment_id.in_(shipment_ids))
                                 .group_by(DomesticShipmentLine.shipment_id)).all()) if shipment_ids else {}
    events = []
    for row in event_ids:
        if row.kind:
            followup = followups[row.event_id]
            events.append({"type": "followup", "date": followup.followup_date.isoformat(), "data": serialize(db, followup)})
        else:
            shipment = shipments[row.event_id]
            events.append({"type": "shipment", "date": shipment.ship_time.date().isoformat(),
                           "data": {"id": shipment.id, "shipment_no": shipment.shipment_no,
                                    "quantity": int(quantities.get(shipment.id) or 0),
                                    "received_date": shipment.received_date.isoformat() if shipment.received_date else None}})
    return events


def customer_timeline(db, user, customer_id, *, today, offset=0, event_type="all"):
    from app.domestic_followup.collaboration_access import responsibility_for
    from app.domestic_followup.followup_service import serialize_item
    from app.domestic_followup.record_access import can_record_history

    customer = db.get(DomesticCustomer, customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    writable = visibility.can_write_customer(db, user, customer)
    readable = visibility.in_customer_scope(db, user, customer_id)
    shipment_readable = visibility.can_read_all(user) or visibility.in_legacy_customer_scope(db, user, customer_id)
    records = select(DomesticFollowup).where(
        DomesticFollowup.customer_id == customer_id, DomesticFollowup.status == "confirmed",
    )
    if not readable:
        records = records.where(visibility.followup_filter(user))
    last = db.scalar(records.with_only_columns(func.max(DomesticFollowup.followup_date)))
    if not readable and not writable and last is None:
        active_task = db.scalar(select(DomesticFollowupTask.id).where(
            DomesticFollowupTask.customer_id == customer_id, DomesticFollowupTask.assignee_user_id == visibility.uid(user),
            DomesticFollowupTask.status == "todo",
        ).limit(1))
        if active_task is None:
            raise PermissionError("无权查看该客户的跟进")
    event_ids, has_more = _event_ids(db, records, customer_id, shipment_readable, event_type, offset)
    frequency = config_service.get_config(db)["frequency_days"].get(customer.customer_level or "")
    open_items = (db.query(DomesticFollowupItem)
                  .filter(DomesticFollowupItem.customer_id == customer_id,
                          DomesticFollowupItem.status.in_(("open", "handling")))
                  .order_by(DomesticFollowupItem.created_at).all()) if readable else []
    responsibility = responsibility_for(db, customer_id) if readable or writable else None
    return {
        "customer": {
            "id": customer.id, "shop_name": customer.shop_name, "customer_level": customer.customer_level,
            "lifecycle_status": customer.lifecycle_status, "owner_user_id": customer.owner_user_id,
            "last_followup_date": last.isoformat() if last else None,
            "days_since_followup": (today - last).days if last else None,
            "frequency_days": frequency, "writable": writable, "readable": readable,
            "shipment_readable": shipment_readable,
            "responsibility_version": responsibility.version if responsibility else None,
            "can_record_history": can_record_history(db, user, customer),
        },
        "open_items": [serialize_item(i) for i in open_items],
        "events": _serialize_events(db, event_ids),
        "has_more": has_more,
        "next_offset": offset + len(event_ids) if has_more else None,
    }
