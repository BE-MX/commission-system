"""Authorized persisted choices for maintenance; labels never create source facts."""

from app.core.time import beijing_now
from app.customer.access_service import apply_record_access
from app.customer.evidence_service import visible_facts
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import CustomerContact, CustomerContactRelationship, CustomerFact, CustomerOrder
from app.customer.pcw_models import ShipmentOrderLink
from app.customer.work_item_evidence_service import evidence_revision
from app.customer.query_service import _access
from app.tracking.models import ShipmentTracking, TrackingEvent


def list_sources(db, user, customer_id):
    access = _access(db, customer_id, user, allow_public_pool=False)
    facts = visible_facts(db, access).filter(CustomerFact.fact_key == "contact.birthday",
        CustomerFact.verification_status == "verified").all()
    birthdays = {int(row.subject_id): row for row in facts if row.subject_type == "contact" and row.subject_id}
    contacts = db.query(CustomerContact).join(CustomerContactRelationship,
        CustomerContactRelationship.contact_id == CustomerContact.id).filter(
        CustomerContactRelationship.customer_id == access.customer_id,
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        CustomerContact.record_status == "active").distinct().all()
    choices = []
    for row in contacts:
        fact = birthdays.get(row.id)
        value = (fact.value_json or {}).get("value", {}) if fact else {}
        month, day = value.get("month"), value.get("day")
        valid = fact is not None and month is not None and day is not None
        choices.append({"contact_id": row.id, "name": row.display_name,
            "birthday_month": month, "birthday_day": day,
            "birthday_evidence_refs": [{"type": "fact", "id": fact.id, "revision": evidence_revision(fact)}] if valid else [],
            "selectable": valid, "unavailable_reason": None if valid else "缺少已核实且可见的生日依据"})
    links, events = [], []
    if {"tracking:read", "tracking:write"}.intersection(user.get("permissions", [])):
        linked = db.query(ShipmentOrderLink, ShipmentTracking, CustomerOrder).join(ShipmentTracking,
            ShipmentTracking.id == ShipmentOrderLink.shipment_id).join(CustomerOrder,
            CustomerOrder.id == ShipmentOrderLink.order_id).filter(
            logical_root_predicate(CustomerOrder, "order", access.customer_id),
            ShipmentOrderLink.state == "active", ShipmentTracking.deleted_at.is_(None)).all()
        by_shipment = {}
        for link, shipment, order in linked:
            links.append({"id": link.id, "shipment_id": shipment.id, "order_id": order.id,
                "order_no": order.order_no, "tracking_no": shipment.waybill_no, "state": link.state,
                "link_version": link.link_version, "selectable": True})
            by_shipment.setdefault(shipment.id, (shipment, []))[1].append(link.id)
        for shipment, identities in by_shipment.values():
            for event in db.query(TrackingEvent).filter(TrackingEvent.waybill_no == shipment.waybill_no,
                    TrackingEvent.carrier == shipment.carrier).order_by(TrackingEvent.event_time.desc(), TrackingEvent.id.desc()).all():
                events.append({"shipment_event_id": event.id, "shipment_id": shipment.id,
                    "trigger_event_type": event.status_code or "unknown", "occurred_at": event.event_time.isoformat(),
                    "title": event.description, "source_revision": evidence_revision(event),
                    "shipment_order_link_ids": identities, "evidence_refs": [{"type": "tracking_event", "id": event.id, "revision": evidence_revision(event)}],
                    "selectable": bool(event.status_code), "unavailable_reason": None if event.status_code else "事件状态未识别"})
    return {"contacts": choices, "shipment_links": links, "shipment_events": events,
        "data_as_of": beijing_now().isoformat()}


def validate_plan_sources(db, user, customer_id, plan_type, payload, evidence_refs):
    from app.customer import pcw_errors
    sources = list_sources(db, user, customer_id)
    if plan_type == "birthday":
        selected = next((row for row in sources["contacts"] if row["contact_id"] == payload["contact_id"] and row["selectable"]), None)
        if selected is None or (selected["birthday_month"], selected["birthday_day"]) != (payload["month"], payload["day"]):
            raise pcw_errors.conflict("生日来源尚未核实或已经变化", error_code="SOURCE_REVALIDATION_REQUIRED")
        if not all(ref in (evidence_refs or []) for ref in selected["birthday_evidence_refs"]):
            raise pcw_errors.conflict("请选择当前生日依据", error_code="EVIDENCE_VERSION_CONFLICT")
    elif plan_type == "shipping":
        selected = next((row for row in sources["shipment_events"] if row["shipment_event_id"] == payload["shipment_event_id"] and row["selectable"]), None)
        if selected is None or selected["trigger_event_type"] != payload["trigger_event_type"] or not payload["shipment_order_link_ids"] or not set(payload["shipment_order_link_ids"]).issubset(selected["shipment_order_link_ids"]):
            raise pcw_errors.conflict("物流事件和订单关联不可用", error_code="SOURCE_REVALIDATION_REQUIRED")
        if not all(ref in (evidence_refs or []) for ref in selected["evidence_refs"]):
            raise pcw_errors.conflict("物流事件已变化，请重新选择", error_code="EVIDENCE_VERSION_CONFLICT")
