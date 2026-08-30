"""Customer-id evidence timeline for the insight customer drawer."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer.fact_service import append_customer_event
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerEvent,
    CustomerConversation,
    CustomerMessage,
    CustomerOpportunity,
    CustomerOrder,
    CustomerSourceRecord,
)


def get_source_records(
    db: Session,
    customer_id: int,
    source_type: str | None = None,
    *,
    access: CustomerAccess,
) -> list[dict]:
    if access.customer_id != customer_id or db.get(CustomerAccount, customer_id) is None:
        return []
    records: list[dict] = []
    if source_type in {None, "source_record", "all"}:
        rows = apply_record_access(
            db.query(CustomerSourceRecord),
            CustomerSourceRecord,
            access,
        ).order_by(CustomerSourceRecord.captured_at.desc()).limit(20).all()
        records.extend({
            "type": "信源记录",
            "type_code": "source_record",
            "title": f"{row.source_system} · {row.source_entity_type}",
            "meta": row.external_record_id,
            "summary": row.processing_status,
            "source_record_id": row.id,
            "data_classification": row.data_classification,
            "visibility_scope": row.visibility_scope,
            "occurred_at": (row.occurred_at or row.captured_at).isoformat(),
        } for row in rows)
    if source_type in {None, "opportunity", "all"}:
        rows = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.customer_id == customer_id
        ).order_by(CustomerOpportunity.created_at.desc()).limit(20).all()
        records.extend({
            "type": "机会记录",
            "type_code": "opportunity",
            "title": row.title,
            "meta": f"{row.source_system} · {row.source_account_key}",
            "summary": row.summary or "",
            "opportunity_id": row.id,
            "occurred_at": row.created_at.isoformat(),
        } for row in rows)
    if source_type in {None, "message", "all"}:
        query = (
            db.query(CustomerMessage, CustomerConversation, CustomerSourceRecord)
            .join(
                CustomerConversation,
                CustomerConversation.id == CustomerMessage.conversation_id,
            )
            .join(
                CustomerSourceRecord,
                CustomerSourceRecord.id == CustomerMessage.source_record_id,
            )
            .filter(CustomerConversation.customer_id == customer_id)
        )
        rows = apply_record_access(query, CustomerSourceRecord, access).order_by(
            CustomerMessage.sent_at.desc()
        ).limit(20).all()
        records.extend({
            "type": "沟通消息",
            "type_code": "message",
            "title": "客户消息" if message.direction == "in" else "我方消息",
            "meta": f"{conversation.channel} · {message.external_message_id}",
            "summary": message.content_text or "",
            "message_id": message.id,
            "conversation_id": conversation.id,
            "source_record_id": source.id,
            "data_classification": source.data_classification,
            "visibility_scope": source.visibility_scope,
            "occurred_at": message.sent_at.isoformat(),
        } for message, conversation, source in rows)
    if source_type in {None, "order", "all"}:
        query = (
            db.query(CustomerOrder, CustomerSourceRecord)
            .join(
                CustomerSourceRecord,
                CustomerSourceRecord.id == CustomerOrder.source_record_id,
            )
        )
        rows = apply_record_access(query, CustomerSourceRecord, access).order_by(
            CustomerOrder.account_date.desc(),
            CustomerOrder.id.desc(),
        ).limit(20).all()
        records.extend({
            "type": "订单记录",
            "type_code": "order",
            "title": order.order_no or order.external_order_id,
            "meta": order.order_status or "",
            "summary": str(order.amount_usd),
            "order_id": order.id,
            "source_record_id": source.id,
            "is_valid_business_order": bool(order.is_valid_business_order),
            "data_classification": source.data_classification,
            "visibility_scope": source.visibility_scope,
            "occurred_at": (
                order.synced_at.isoformat()
                if order.account_date is None
                else f"{order.account_date.isoformat()}T00:00:00"
            ),
        } for order, source in rows)
    if source_type in {None, "event", "all"}:
        rows = apply_record_access(
            db.query(CustomerEvent),
            CustomerEvent,
            access,
        ).order_by(CustomerEvent.occurred_at.desc()).limit(20).all()
        records.extend({
            "type": "客户事件",
            "type_code": "event",
            "title": row.event_title,
            "meta": f"{row.event_source} · {row.event_type}",
            "summary": row.event_summary or "",
            "event_id": row.id,
            "data_classification": row.data_classification,
            "visibility_scope": row.visibility_scope,
            "occurred_at": row.occurred_at.isoformat(),
        } for row in rows)
    if source_type in {None, "note", "all"}:
        rows = apply_record_access(
            db.query(CustomerAnnotation),
            CustomerAnnotation,
            access,
            visibility_field="visibility",
            author_field="authored_by",
        ).filter(
            CustomerAnnotation.annotation_type == "note",
            CustomerAnnotation.status == "active",
        ).order_by(CustomerAnnotation.created_at.desc()).limit(20).all()
        records.extend({
            "type": "业务员备注",
            "type_code": "note",
            "title": "业务员备注",
            "meta": f"author:{row.authored_by}",
            "summary": str((row.content_json or {}).get("text") or ""),
            "annotation_id": row.id,
            "data_classification": row.data_classification,
            "visibility_scope": row.visibility,
            "occurred_at": row.created_at.isoformat(),
        } for row in rows)
    records.sort(key=lambda row: row.get("occurred_at") or "", reverse=True)
    return records


def add_manual_note(
    db: Session,
    customer_id: int,
    note_text: str,
    user_id: int,
    *,
    access: CustomerAccess,
) -> CustomerAnnotation:
    if access.customer_id != customer_id or access.actor_user_id != int(user_id):
        raise ValueError("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    account = db.get(CustomerAccount, customer_id)
    if account is None:
        raise ValueError("CUSTOMER_NOT_FOUND")
    text = note_text.strip()
    if not text:
        raise ValueError("ANNOTATION_TEXT_REQUIRED")
    now = beijing_now()
    row = CustomerAnnotation(
        customer_id=customer_id,
        annotation_type="note",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"text": text, "source": "insight_customer_drawer"},
        policy_scope_type=None,
        policy_scope_ref_id=None,
        policy_effective_at=None,
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    append_customer_event(
        db,
        customer_id=customer_id,
        event_type="annotation.created",
        event_source="annotation",
        event_title="业务员添加客户备注",
        event_summary=text[:200],
        event_payload={"annotation_type": "note"},
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        source_ref_type="annotation",
        source_ref_id=str(row.id),
        actor_user_id=user_id,
    )
    db.commit()
    db.refresh(row)
    return row


__all__ = ["add_manual_note", "get_source_records"]
