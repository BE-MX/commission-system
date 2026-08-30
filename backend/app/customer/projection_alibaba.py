"""Alibaba inquiry, conversation and message projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.fact_service import append_customer_event
from app.customer.identity_service import (
    CustomerDomainError,
    CustomerTransactionRetryRequired,
    IdentityCandidate,
    resolve_business_context,
)
from app.customer.models import (
    CustomerConversation,
    CustomerMessage,
    CustomerOpportunity,
    CustomerSourceRecord,
)
from app.customer.projection_common import (
    ProjectionError,
    ProjectionReceipt,
    ProjectionRetryRequired,
    aggregate_outcome,
    append_raw,
    attachment_metadata,
    bind_source,
    business_datetime,
    error_code,
    existing_contact_id,
    is_exact_processed_replay,
    insert_or_load_expected_unique,
    normalized_identifier,
    optional_content,
    optional_string,
    quarantine,
    raw_external_id,
    retryable_operational_error,
    safe_business_datetime,
    sha256,
    upsert_contact_email,
)
from app.customer.workflow_service import CustomerWorkflowError, upsert_opportunity
from app.insight.external_binding_service import resolve_projection_owner


_ATTACHMENT_SOURCE_KEYS = ("file_name", "mime_type", "size", "source_ref")


def _source_safe_message(raw: object) -> dict:
    if not isinstance(raw, Mapping):
        return {"invalid_value": repr(raw)}
    result = dict(raw)
    attachments = raw.get("attachments")
    if isinstance(attachments, list):
        result["attachments"] = [
            {
                key: attachment.get(key)
                for key in _ATTACHMENT_SOURCE_KEYS
                if attachment.get(key) is not None
            }
            if isinstance(attachment, Mapping) else attachment
            for attachment in attachments
        ]
    return result


def project_alibaba_inquiry(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    try:
        return _project_alibaba_inquiry_from_source(
            db, source_account_key=source_account_key, payload=payload,
            sync_cursor=sync_cursor, captured_at=captured_at,
        )
    except ProjectionRetryRequired:
        db.rollback()
        raise


def _project_alibaba_inquiry_from_source(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    """Project one Alibaba inquiry and its supplied messages source-first."""
    if not isinstance(payload, Mapping):
        raise ProjectionError("SOURCE_PAYLOAD_INVALID")
    account_key = normalized_identifier(source_account_key, "SOURCE_ACCOUNT_INVALID")
    captured = to_beijing_naive(captured_at) if captured_at is not None else beijing_now()
    inquiry_id = raw_external_id(payload, "inquiry_id", "inquiry")
    source_payload = {key: value for key, value in payload.items() if key != "messages"}
    inquiry_source = append_raw(
        db,
        source_system="alibaba",
        source_account_key=account_key,
        source_entity_type="inquiry",
        external_record_id=inquiry_id,
        schema_version="alibaba_inquiry_v1",
        payload=source_payload,
        occurred_at=safe_business_datetime(payload.get("occurred_at")),
        captured_at=captured,
        sync_cursor=sync_cursor,
        data_classification="restricted_internal",
    )
    raw_messages = payload.get("messages", [])
    message_sources: list[CustomerSourceRecord] = []
    if isinstance(raw_messages, list):
        for index, item in enumerate(raw_messages):
            raw_item = _source_safe_message(item)
            message_sources.append(append_raw(
                db,
                source_system="alibaba",
                source_account_key=account_key,
                source_entity_type="message",
                external_record_id=raw_external_id(
                    raw_item, "message_id", f"message:{index}"
                ),
                schema_version="alibaba_message_v1",
                payload=raw_item,
                occurred_at=safe_business_datetime(raw_item.get("sent_at")),
                captured_at=captured,
                sync_cursor=sync_cursor,
                data_classification="restricted_internal",
            ))
    sources = [inquiry_source, *message_sources]
    if is_exact_processed_replay(sources):
        inquiry_key = normalized_identifier(
            payload.get("inquiry_id"), "INQUIRY_ID_INVALID"
        )
        conversation_key = normalized_identifier(
            payload.get("conversation_id"), "CONVERSATION_ID_INVALID"
        )
        conversation = db.query(CustomerConversation).filter_by(
            source_system="alibaba",
            source_account_key=account_key,
            external_conversation_id=conversation_key,
        ).one_or_none()
        opportunity = db.query(CustomerOpportunity).filter_by(
            source_system="alibaba",
            source_account_key=account_key,
            source_key=f"inquiry:{inquiry_key}",
        ).one_or_none()
        messages = db.query(CustomerMessage).filter(
            CustomerMessage.source_record_id.in_([row.id for row in message_sources]),
        ).order_by(CustomerMessage.id).all()
        if conversation is None or opportunity is None:
            raise ProjectionError("SOURCE_PROJECTION_STATE_INVALID")
        return ProjectionReceipt(
            "processed",
            inquiry_source.id,
            outcome="unchanged",
            customer_id=inquiry_source.customer_id,
            contact_id=conversation.contact_id,
            conversation_id=conversation.id,
            message_ids=tuple(row.id for row in messages),
            opportunity_id=opportunity.id,
        )
    try:
        with db.begin_nested():
            result = _project_alibaba_inquiry(
                db,
                source_account_key=account_key,
                payload=payload,
                inquiry_source=inquiry_source,
                message_sources=message_sources,
                captured_at=inquiry_source.captured_at,
            )
            for source in sources:
                source.processing_status = "processed"
                source.processing_error_code = None
                source.processing_error_message = None
            db.flush()
            return result
    except ProjectionRetryRequired:
        raise
    except CustomerTransactionRetryRequired as exc:
        raise ProjectionRetryRequired() from exc
    except IntegrityError:
        return quarantine(db, sources, "PROJECTION_CONSTRAINT_INVALID")
    except OperationalError as exc:
        if retryable_operational_error(exc):
            raise ProjectionRetryRequired() from exc
        raise
    except (ProjectionError, CustomerDomainError, CustomerWorkflowError) as exc:
        return quarantine(db, sources, error_code(exc, "ALIBABA_PROJECTION_INVALID"))


def _project_alibaba_inquiry(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    inquiry_source: CustomerSourceRecord,
    message_sources: Sequence[CustomerSourceRecord],
    captured_at: datetime,
) -> ProjectionReceipt:
    inquiry_id = normalized_identifier(payload.get("inquiry_id"), "INQUIRY_ID_INVALID")
    conversation_id = normalized_identifier(
        payload.get("conversation_id"), "CONVERSATION_ID_INVALID")
    messages = payload.get("messages", [])
    if not isinstance(messages, list) or len(messages) != len(message_sources):
        raise ProjectionError("MESSAGE_LIST_INVALID")
    inquiry_occurred = business_datetime(
        payload.get("occurred_at"), "SOURCE_BUSINESS_TIME_INVALID", required=False,
    ) or captured_at
    contact_name = optional_string(payload.get("contact_name"), "CONTACT_NAME_INVALID")
    company_name = optional_string(payload.get("company_name"), "COMPANY_NAME_INVALID")
    contact_email = optional_string(payload.get("contact_email"), "CONTACT_POINT_INVALID")
    candidates: list[IdentityCandidate] = []
    for field, identifier_type in (("buyer_id", "buyer_id"), ("member_id", "member_id")):
        value = payload.get(field)
        if value is not None:
            candidates.append(IdentityCandidate(
                identifier_type, normalized_identifier(value, "IDENTITY_VALUE_INVALID"),
                verification_status="verified",
                confidence=Decimal("1.0000"),
                is_primary=field == "buyer_id",
            ))
    company_id = payload.get("company_id")
    if company_id is not None:
        candidates.append(IdentityCandidate(
            "company_id", normalized_identifier(company_id, "IDENTITY_VALUE_INVALID"),
            verification_status="verified",
            confidence=Decimal("1.0000"),
            is_primary=True,
        ))
    known_contact_id = None
    for field, identifier_type in (("buyer_id", "buyer_id"), ("member_id", "member_id")):
        known_contact_id = known_contact_id or existing_contact_id(
            db,
            source_system="alibaba",
            source_account_key=source_account_key,
            identifier_type=identifier_type,
            raw_value=payload.get(field),
        )
    context = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key=source_account_key,
        source_entity_type="company",
        external_context_id=conversation_id,
        source_record_id=inquiry_source.id,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=contact_email if known_contact_id is None else None,
        identity_candidates=candidates,
        worker_id=f"alibaba:{source_account_key}:{inquiry_id}",
        now=inquiry_occurred,
    )
    account = context.customer
    contact = context.contact
    for source in message_sources:
        bind_source(source, account.id)
    if contact is not None and known_contact_id is not None:
        upsert_contact_email(
            db,
            contact_id=contact.id,
            raw_email=contact_email,
            source_record=inquiry_source,
            fingerprint_scope=f"alibaba:{source_account_key}:{inquiry_id}",
            now=inquiry_occurred,
        )

    owner_user_id = None
    owner_external_id = payload.get("owner_external_user_id")
    if owner_external_id is not None:
        owner_user_id = resolve_projection_owner(
            db,
            "alibaba_icbu",
            normalized_identifier(owner_external_id, "OWNER_ID_INVALID"),
        )
    conversation_query = db.query(CustomerConversation).filter(
        CustomerConversation.source_system == "alibaba",
        CustomerConversation.source_account_key == source_account_key,
        CustomerConversation.external_conversation_id == conversation_id,
    )
    conversation = conversation_query.with_for_update().one_or_none()
    derived_outcomes: list[str] = []
    if conversation is None:
        candidate_conversation = CustomerConversation(
            customer_id=account.id,
            contact_id=contact.id if contact is not None else None,
            source_system="alibaba",
            source_account_key=source_account_key,
            external_conversation_id=conversation_id,
            channel="alibaba",
            owner_user_id=owner_user_id,
            conversation_status="active",
            latest_source_record_id=inquiry_source.id,
            created_at=captured_at,
            updated_at=captured_at,
        )
        def insert_conversation() -> CustomerConversation:
            db.add(candidate_conversation)
            db.flush()
            return candidate_conversation

        conversation, inserted = insert_or_load_expected_unique(
            db,
            entity_type="conversation",
            insert=insert_conversation,
            load_winner=lambda: conversation_query.with_for_update().one_or_none(),
        )
        derived_outcomes.append("inserted" if inserted else "unchanged")
        if conversation.customer_id != account.id:
            raise ProjectionError("CONVERSATION_CUSTOMER_MISMATCH")
        if not inserted:
            recovered_values = {
                "contact_id": contact.id if contact is not None else conversation.contact_id,
                "owner_user_id": owner_user_id or conversation.owner_user_id,
                "latest_source_record_id": inquiry_source.id,
            }
            recovered_changed = any(
                getattr(conversation, key) != value
                for key, value in recovered_values.items()
            )
            for key, value in recovered_values.items():
                setattr(conversation, key, value)
            conversation.updated_at = captured_at
            if recovered_changed:
                derived_outcomes[-1] = "updated"
    elif conversation.customer_id != account.id:
        raise ProjectionError("CONVERSATION_CUSTOMER_MISMATCH")
    else:
        conversation_values = {
            "contact_id": contact.id if contact is not None else conversation.contact_id,
            "owner_user_id": owner_user_id or conversation.owner_user_id,
            "latest_source_record_id": inquiry_source.id,
            "updated_at": captured_at,
        }
        changed = any(
            getattr(conversation, key) != value
            for key, value in conversation_values.items()
            if key != "updated_at"
        )
        for key, value in conversation_values.items():
            setattr(conversation, key, value)
        derived_outcomes.append("updated" if changed else "unchanged")

    append_customer_event(
        db,
        customer_id=account.id,
        event_type="inquiry.received",
        event_source="alibaba",
        event_title="收到阿里询盘",
        event_summary=inquiry_id,
        event_payload={"channel": "alibaba"},
        payload_schema_version="customer_event_v1",
        occurred_at=inquiry_occurred,
        source_ref_type="source_record",
        source_ref_id=str(inquiry_source.id),
    )
    projected_messages: list[CustomerMessage] = []
    for raw, source in zip(messages, message_sources, strict=True):
        if not isinstance(raw, Mapping):
            raise ProjectionError("MESSAGE_INPUT_INVALID")
        message_id = normalized_identifier(raw.get("message_id"), "MESSAGE_ID_INVALID")
        direction = raw.get("direction")
        if direction not in {"in", "out"}:
            raise ProjectionError("MESSAGE_DIRECTION_INVALID")
        sender_type = raw.get("sender_type")
        if sender_type not in {"customer_contact", "ark_user", "external_user", "system"}:
            raise ProjectionError("MESSAGE_SENDER_INVALID")
        content_type = raw.get("content_type", "text")
        if content_type not in {"text", "image", "video", "document", "mixed", "system"}:
            raise ProjectionError("MESSAGE_CONTENT_TYPE_INVALID")
        content_text = optional_content(raw.get("content_text"))
        attachments = attachment_metadata(raw.get("attachments", []))
        sent_at = business_datetime(raw.get("sent_at"), "MESSAGE_TIME_INVALID")
        content_hash = sha256(content_text, attachments)
        message_query = db.query(CustomerMessage).filter(
            CustomerMessage.conversation_id == conversation.id,
            CustomerMessage.external_message_id == message_id,
        )
        row = message_query.with_for_update().one_or_none()
        message_values = {
            "direction": direction,
            "sender_type": sender_type,
            "sender_contact_id": (
                contact.id
                if direction == "in" and sender_type == "customer_contact" and contact
                else None
            ),
            "sender_user_id": None,
            "content_type": content_type,
            "content_text": content_text,
            "attachment_meta_json": attachments,
            "source_record_id": source.id,
            "content_hash": content_hash,
            "sent_at": sent_at,
            "captured_at": source.captured_at,
        }
        if row is None:
            candidate_message = CustomerMessage(
                conversation_id=conversation.id,
                external_message_id=message_id,
                created_at=captured_at,
                **message_values,
            )
            def insert_message() -> CustomerMessage:
                db.add(candidate_message)
                db.flush()
                return candidate_message

            row, inserted = insert_or_load_expected_unique(
                db,
                entity_type="message",
                insert=insert_message,
                load_winner=lambda: message_query.with_for_update().one_or_none(),
            )
            derived_outcomes.append("inserted" if inserted else "unchanged")
            if not inserted:
                recovered_changed = any(
                    getattr(row, key) != value
                    for key, value in message_values.items()
                )
                for key, value in message_values.items():
                    setattr(row, key, value)
                if recovered_changed:
                    derived_outcomes[-1] = "updated"
        else:
            changed = any(
                getattr(row, key) != value for key, value in message_values.items()
            )
            for key, value in message_values.items():
                setattr(row, key, value)
            derived_outcomes.append("updated" if changed else "unchanged")
        append_customer_event(
            db,
            customer_id=account.id,
            event_type="message.received" if direction == "in" else "message.sent",
            event_source="alibaba",
            event_title="收到客户消息" if direction == "in" else "发送客户消息",
            event_summary=message_id,
            event_payload={"direction": direction},
            payload_schema_version="customer_event_v1",
            occurred_at=sent_at,
            source_ref_type="message",
            source_ref_id=str(row.id),
        )
        projected_messages.append(row)
    if projected_messages:
        sent_times = [row.sent_at for row in projected_messages]
        conversation.started_at = min(
            [conversation.started_at, *sent_times]
            if conversation.started_at else sent_times
        )
        conversation.last_message_at = max(
            [conversation.last_message_at, *sent_times]
            if conversation.last_message_at else sent_times
        )
    opportunity = upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="alibaba",
        source_account_key=source_account_key,
        source_key=f"inquiry:{inquiry_id}",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title=f"阿里询盘 {inquiry_id}",
        owner_user_id=None,
        source_ref_type="source_record",
        source_ref_id=inquiry_source.id,
        primary_contact_id=contact.id if contact is not None else None,
        summary="待资格审核的阿里询盘",
        latest_message_at=conversation.last_message_at,
    )
    db.flush()
    return ProjectionReceipt(
        status="processed",
        source_record_id=inquiry_source.id,
        outcome=aggregate_outcome(
            [inquiry_source, *message_sources],
            *derived_outcomes,
        ),
        customer_id=account.id,
        contact_id=contact.id if contact is not None else None,
        conversation_id=conversation.id,
        message_ids=tuple(row.id for row in projected_messages),
        opportunity_id=opportunity.id,
    )


__all__ = ["project_alibaba_inquiry"]
