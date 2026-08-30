"""Scoped, budgeted Ark-only reads for governed customer Agent Runs."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.access_service import (
    CustomerAccessDenied,
    apply_record_access,
    require_customer_access,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAgentContext,
    CustomerConversation,
    CustomerFact,
    CustomerMessage,
    CustomerOrder,
    CustomerOrderItem,
    CustomerProfileVersion,
    CustomerSourceRecord,
)
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.evidence_contract import fact_evidence_content_hash
from app.customer.agent_freshness import profile_freshness
from app.customer.agent_search_service import search_customers as _search_customers
from app.customer.agent_query_service import (
    ascending_id_page,
    descending_pair_page,
    finish_keyset_page,
    id_key,
    pair_key,
)
from app.customer.agent_tool_contract import (
    MAX_LIST_BYTES, MAX_LIST_ITEMS, MAX_NESTED_ITEMS,
    MAX_PROFILE_BYTES, MAX_SECTION_BYTES, MAX_SOURCE_BYTES, MAX_SOURCE_CHARS,
    MAX_STRING_CHARS, PROFILE_SECTIONS, CustomerAgentAccessError,
    clip as _clip,
    decode_cursor,
    deny as _deny,
    encode_cursor,
    envelope as _envelope,
    fit as _fit,
    fit_page as _fit_page,
    page as _page,
    plain_text as _plain_text,
    serialize_envelope,
)


_READ_PERMISSIONS = {"customer:read", "customer:read_all", "customer:admin"}
_MANAGE_PERMISSIONS = {"customer:read_all", "customer:admin"}


def _access(db: Session, user: dict, customer_id: int):
    try:
        return require_customer_access(
            db, customer_id=customer_id, user=user,
            action_permissions=_READ_PERMISSIONS, manage_permissions=_MANAGE_PERMISSIONS,
        )
    except CustomerAccessDenied:
        _deny()


def _profile_version(db: Session, customer: CustomerAccount) -> CustomerProfileVersion | None:
    if customer.current_profile_version_id is None:
        return None
    return db.query(CustomerProfileVersion).filter(
        CustomerProfileVersion.id == customer.current_profile_version_id,
        CustomerProfileVersion.customer_id == customer.id,
    ).one_or_none()


def resolve_customer(
    db: Session, *, user: dict, value: str, identifier_type: str | None = None,
    limit: int = 10,
) -> dict:
    return search_customers(
        db, user=user, keyword=value, identifier_type=identifier_type, limit=limit,
    )


def search_customers(
    db: Session, *, user: dict, keyword: str | None = None,
    identifier_type: str | None = None, cursor: str | None = None, limit: int = 20,
) -> dict:
    return _search_customers(
        db, user=user, keyword=keyword, identifier_type=identifier_type,
        cursor=cursor, limit=limit,
    )


def get_customer_profile(
    db: Session, *, user: dict, customer_id: int,
    sections: Iterable[str] | None = None, now: datetime | None = None,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    customer = db.get(CustomerAccount, customer_id)
    if customer is None:
        _deny()
    version = _profile_version(db, customer)
    context = db.get(CustomerAgentContext, customer_id)
    requested = list(dict.fromkeys(sections or PROFILE_SECTIONS))
    if any(item not in PROFILE_SECTIONS for item in requested):
        raise ValueError("UNKNOWN_PROFILE_SECTION")
    context_allowed = bool(
        context and version and context.profile_version_id == version.id
        and access.allows_classification(context.max_data_classification)
    )
    source = context.context_json if context_allowed else {}
    output, truncated = {}, False
    for name in requested:
        clipped, changed = _clip(source.get(name, {}))
        if len(json.dumps(clipped, ensure_ascii=False, default=str).encode()) > MAX_SECTION_BYTES:
            clipped = {"truncated": True}
            changed = True
        output[name] = clipped
        truncated |= changed
    freshness, unavailable, stale_sections = profile_freshness(
        db, access=access, version=version, requested_sections=requested,
        context_current=context_allowed, now=now or beijing_now(),
    )
    result = _envelope(
        profile_version=version.version_no if version else None,
        data_as_of=context.data_as_of if context else (version.data_as_of if version else None),
    )
    result.update({
        "customer_id": customer.id, "customer_code": customer.customer_code,
        "display_name": customer.display_name,
        "canonical_company_name": customer.canonical_company_name,
        "sections": output, "requested_section_data_as_of": {
            key: (version.section_data_as_of or {}).get(key) if version else None for key in requested
        },
        "profile_data_as_of": version.data_as_of if version else None,
        "source_freshness_map": freshness, "unavailable_sources": unavailable,
        "stale_sections": stale_sections,
        "truncated": truncated,
        "truncation_reason": "string_or_section_budget" if truncated else None,
    })
    return _fit(result, max_bytes=MAX_PROFILE_BYTES)


def _fact_ref(
    row: CustomerFact, *, customer_id: int, profile_version: int | None, stale: bool,
) -> dict:
    digest = fact_evidence_content_hash(
        fact_id=row.id, value=row.value_json, fingerprint=row.fact_fingerprint,
    )
    return {
        "evidence_ref": f"fact:{row.id}", "evidence_content_hash": digest,
        "customer_id": customer_id, "profile_version": profile_version,
        "freshness": "stale" if stale else "current", "metadata_only": True,
    }


def get_customer_facts(
    db: Session, *, user: dict, customer_id: int, fact_keys: list[str] | None = None,
    layers: list[str] | None = None, statuses: list[str] | None = None,
    cursor: str | None = None, limit: int = 50, now: datetime | None = None,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    query = apply_record_access(
        db.query(CustomerFact), CustomerFact, access, logical_object_type="fact",
    )
    if fact_keys:
        query = query.filter(CustomerFact.fact_key.in_(fact_keys))
    if layers:
        query = query.filter(CustomerFact.fact_layer.in_(layers))
    if statuses:
        query = query.filter(CustomerFact.verification_status.in_(statuses))
    customer = db.get(CustomerAccount, customer_id)
    version = _profile_version(db, customer)
    version_no = version.version_no if version else None
    filters = {"fact_keys": fact_keys or [], "layers": layers or [], "statuses": statuses or []}
    page, has_more = ascending_id_page(
        query, CustomerFact.id, user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no, cursor=cursor, limit=limit,
    )
    current = now or beijing_now()
    items, refs = [], []
    for row in page:
        stale = row.expires_at is not None and row.expires_at <= current
        clipped, _ = _clip(row.value_json)
        items.append({
            "fact_id": row.id, "fact_key": row.fact_key, "value": clipped,
            "layer": row.fact_layer, "verification_status": row.verification_status,
            "confidence": float(row.confidence), "observed_at": row.observed_at,
            "expires_at": row.expires_at, "stale": stale,
            "can_support_current_claim": not stale,
        })
        refs.append(_fact_ref(
            row, customer_id=customer_id, profile_version=version_no, stale=stale,
        ))
    result = _envelope(
        profile_version=version_no, data_as_of=version.data_as_of if version else None,
        items=items, evidence_refs=refs,
    )
    result.update(customer_id=customer_id)
    return finish_keyset_page(
        result, page, max_bytes=MAX_LIST_BYTES, has_more=has_more,
        key_for_row=id_key, user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no,
    )


def get_customer_orders(
    db: Session, *, user: dict, customer_id: int, date_from: date | None = None,
    date_to: date | None = None, include_items: bool = False,
    cursor: str | None = None, limit: int = 50,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    if not access.allows_classification("internal_business"):
        _deny()
    # Orders are uniformly internal_business; apply_record_access cannot use
    # non-existent policy columns, so retain only its logical customer predicate.
    query = db.query(CustomerOrder).filter(
        logical_root_predicate(CustomerOrder, "order", customer_id),
    )
    if date_from:
        query = query.filter(CustomerOrder.account_date >= date_from)
    if date_to:
        query = query.filter(CustomerOrder.account_date <= date_to)
    customer = db.get(CustomerAccount, customer_id)
    version = _profile_version(db, customer)
    version_no = version.version_no if version else None
    filters = {"date_from": date_from, "date_to": date_to, "include_items": include_items}
    page, has_more = descending_pair_page(
        query, CustomerOrder.account_date, CustomerOrder.id, sort_type=date,
        user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no, cursor=cursor, limit=limit,
    )
    detail_by_order: dict[int, list[CustomerOrderItem]] = {}
    if include_items and page:
        detail_rows = db.query(CustomerOrderItem).filter(
            CustomerOrderItem.order_id.in_([row.id for row in page]),
        ).order_by(
            CustomerOrderItem.order_id, CustomerOrderItem.id,
        ).limit(MAX_NESTED_ITEMS).all()
        for detail_row in detail_rows:
            detail_by_order.setdefault(detail_row.order_id, []).append(detail_row)
    nested_left, items = MAX_NESTED_ITEMS, []
    for row in page:
        selected_details = detail_by_order.get(row.id, [])[:nested_left]
        nested_left -= len(selected_details)
        detail = [{
                "item_id": item.id, "product_name": item.product_name,
                "product_family": item.product_family, "model": item.model,
                "color": item.color, "length": item.length,
                "quantity": item.quantity, "quantity_unit": item.quantity_unit,
                "line_amount": item.line_amount,
            } for item in selected_details]
        items.append({
            "order_id": row.id, "order_no": row.order_no, "order_status": row.order_status,
            "account_date": row.account_date, "currency": row.currency,
            "amount_original": row.amount_original, "amount_usd": row.amount_usd,
            "is_valid_business_order": row.is_valid_business_order, "items": detail,
        })
    result = _envelope(
        profile_version=version_no, data_as_of=version.data_as_of if version else None,
        items=items,
    )
    result.update(customer_id=customer_id)
    return finish_keyset_page(
        result, page, max_bytes=MAX_LIST_BYTES, has_more=has_more,
        key_for_row=pair_key("account_date"), user=user, customer_id=customer_id,
        filters=filters, profile_version=version_no,
    )


def search_customer_messages(
    db: Session, *, user: dict, customer_id: int, query: str | None = None,
    conversation_id: int | None = None, date_from: datetime | None = None,
    date_to: datetime | None = None, cursor: str | None = None, limit: int = 20,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    if not access.allows_classification("restricted_internal"):
        _deny()
    conversations = db.query(CustomerConversation.id).filter(
        logical_root_predicate(CustomerConversation, "conversation", customer_id),
    )
    if conversation_id is not None and conversations.filter(
        CustomerConversation.id == conversation_id,
    ).first() is None:
        _deny()
    message_query = db.query(CustomerMessage).filter(CustomerMessage.conversation_id.in_(conversations))
    if conversation_id is not None:
        message_query = message_query.filter(CustomerMessage.conversation_id == conversation_id)
    cleaned = (query or "").strip()
    if cleaned:
        message_query = message_query.filter(CustomerMessage.content_text.ilike(f"%{cleaned}%"))
    if date_from:
        message_query = message_query.filter(CustomerMessage.sent_at >= date_from)
    if date_to:
        message_query = message_query.filter(CustomerMessage.sent_at <= date_to)
    customer = db.get(CustomerAccount, customer_id)
    version = _profile_version(db, customer)
    version_no = version.version_no if version else None
    filters = {
        "query": cleaned, "conversation_id": conversation_id,
        "date_from": date_from, "date_to": date_to,
    }
    page, has_more = descending_pair_page(
        message_query, CustomerMessage.sent_at, CustomerMessage.id, sort_type=datetime,
        user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no, cursor=cursor, limit=limit,
    )
    items = [{
        "message_id": row.id, "conversation_id": row.conversation_id,
        "direction": row.direction, "sent_at": row.sent_at,
        "excerpt": _plain_text(row.content_text, MAX_STRING_CHARS),
        "content_hash": row.content_hash, "locator": {"message_id": row.id},
        "untrusted_content": True,
    } for row in page]
    result = _envelope(
        profile_version=version_no, data_as_of=max((row.sent_at for row in page), default=None),
        items=items,
    )
    result.update(customer_id=customer_id)
    return finish_keyset_page(
        result, page, max_bytes=MAX_LIST_BYTES, has_more=has_more,
        key_for_row=pair_key("sent_at"), user=user, customer_id=customer_id,
        filters=filters, profile_version=version_no,
    )


def get_customer_actions(
    db: Session, *, user: dict, customer_id: int, statuses: list[str] | None = None,
    cursor: str | None = None, limit: int = 50,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    query = apply_record_access(
        db.query(CustomerAction), CustomerAction, access, logical_object_type="action",
    )
    if statuses:
        query = query.filter(CustomerAction.status.in_(statuses))
    customer = db.get(CustomerAccount, customer_id)
    version = _profile_version(db, customer)
    version_no = version.version_no if version else None
    filters = {"statuses": statuses or []}
    page, has_more = descending_pair_page(
        query, CustomerAction.action_date, CustomerAction.id, sort_type=date,
        user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no, cursor=cursor, limit=limit,
    )
    items = [{
        "action_id": row.id, "action_type": row.action_type, "priority": row.priority,
        "reason": row.reason, "next_action": row.next_action, "action_date": row.action_date,
        "status": row.status, "evidence_status": row.evidence_status,
        "evidence_fact_ids": list(row.evidence_fact_ids or [])[:MAX_NESTED_ITEMS],
    } for row in page]
    result = _envelope(
        profile_version=version_no, data_as_of=version.data_as_of if version else None,
        items=items,
    )
    result.update(customer_id=customer_id)
    return finish_keyset_page(
        result, page, max_bytes=MAX_LIST_BYTES, has_more=has_more,
        key_for_row=pair_key("action_date"), user=user, customer_id=customer_id,
        filters=filters, profile_version=version_no,
    )


def get_customer_evidence(
    db: Session, *, user: dict, customer_id: int, fact_ids: list[int], cursor: str | None = None,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    ids = list(dict.fromkeys(int(value) for value in fact_ids))
    if not ids or len(ids) > MAX_LIST_ITEMS:
        raise ValueError("FACT_ID_BUDGET_EXCEEDED")
    rows = apply_record_access(
        db.query(CustomerFact), CustomerFact, access, logical_object_type="fact",
    ).filter(CustomerFact.id.in_(ids)).all()
    rows_by_id = {row.id: row for row in rows}
    if set(rows_by_id) != set(ids):
        _deny()
    ordered_rows = [rows_by_id[fact_id] for fact_id in ids]
    customer = db.get(CustomerAccount, customer_id)
    version = _profile_version(db, customer)
    version_no = version.version_no if version else None
    filters = {"fact_ids_hash": hashlib.sha256(
        json.dumps(ids, separators=(",", ":")).encode()).hexdigest()}
    selected, has_more, next_cursor = _page(
        ordered_rows, user=user, customer_id=customer_id, filters=filters,
        profile_version=version_no, cursor=cursor, limit=MAX_LIST_ITEMS,
    )
    current = beijing_now()
    refs, items = [], []
    for row in selected:
        stale = row.expires_at is not None and row.expires_at <= current
        ref = _fact_ref(
            row, customer_id=customer_id, profile_version=version_no, stale=stale,
        )
        refs.append(ref)
        items.append({
            "fact_id": row.id, "fact_key": row.fact_key, "value": _clip(row.value_json)[0],
            "verification_status": row.verification_status, "confidence": float(row.confidence),
            "observed_at": row.observed_at, "stale": stale, "evidence_ref": ref["evidence_ref"],
            "evidence_content_hash": ref["evidence_content_hash"],
        })
    result = _envelope(
        profile_version=version_no, data_as_of=version.data_as_of if version else None,
        items=items, evidence_refs=refs,
    )
    result.update(customer_id=customer_id, has_more=has_more, cursor=next_cursor)
    return _fit_page(
        result, max_bytes=MAX_LIST_BYTES, user=user, customer_id=customer_id,
        filters=filters, profile_version=version_no, incoming_cursor=cursor,
    )


def get_customer_source_chunks(
    db: Session, *, user: dict, customer_id: int, source_record_id: int,
    locator: dict | None = None, max_chars: int = MAX_SOURCE_CHARS,
) -> dict:
    access = _access(db, user, customer_id)
    customer_id = access.customer_id
    if not access.allows_classification("restricted_internal"):
        _deny()
    row = apply_record_access(
        db.query(CustomerSourceRecord), CustomerSourceRecord, access,
        logical_object_type="source_record",
    ).filter(CustomerSourceRecord.id == source_record_id).one_or_none()
    if row is None:
        _deny()
    maximum = min(max(int(max_chars), 1), MAX_SOURCE_CHARS)
    raw = json.dumps(row.payload_json, ensure_ascii=False, sort_keys=True)
    start = int((locator or {}).get("start") or 0)
    if start < 0 or start > len(raw):
        raise ValueError("INVALID_SOURCE_LOCATOR")
    chunk = _plain_text(raw[start: start + maximum], maximum)
    result = _envelope(profile_version=None, data_as_of=row.occurred_at or row.captured_at, items=[{
        "source_record_id": row.id, "source_system": row.source_system,
        "source_entity_type": row.source_entity_type,
        "locator": {"start": start, "length": len(chunk)}, "content": chunk,
        "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
        "untrusted_content": True,
    }])
    result["customer_id"] = customer_id
    return _fit(result, max_bytes=MAX_SOURCE_BYTES)


__all__ = [
    "CustomerAgentAccessError", "decode_cursor", "encode_cursor", "get_customer_actions",
    "get_customer_evidence", "get_customer_facts", "get_customer_orders",
    "get_customer_profile", "get_customer_source_chunks", "resolve_customer",
    "search_customer_messages", "search_customers", "serialize_envelope",
]
