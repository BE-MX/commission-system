"""OKKI order and order-item source-first projection."""

from __future__ import annotations

from datetime import datetime, time as datetime_time
from decimal import Decimal
from typing import Mapping, Sequence

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.fact_service import DirectFactEvidence, append_fact
from app.customer.identity_service import CustomerDomainError, CustomerTransactionRetryRequired
from app.customer.models import (
    CustomerAccount,
    CustomerExternalIdentity,
    CustomerOpportunity,
    CustomerOrder,
    CustomerOrderItem,
    CustomerSourceRecord,
)
from app.customer.projection_common import (
    ProjectionError,
    ProjectionReceipt,
    ProjectionRetryRequired,
    aggregate_outcome,
    append_raw,
    bind_source,
    business_date,
    decimal_value,
    error_code,
    is_exact_processed_replay,
    insert_or_load_expected_unique,
    normalized_identifier,
    optional_string,
    quarantine,
    raw_external_id,
    retryable_operational_error,
    sha256,
)
from app.customer.workflow_service import (
    CustomerWorkflowError,
    activate_customer_from_order,
    reconcile_invalidated_order,
)
from app.insight.external_binding_service import resolve_projection_owner
from app.order_intelligence.service import is_valid_business_order


_ITEM_TYPES = frozenset({"sample", "bulk", "unknown"})


def okki_customer_identity(
    db: Session, *, source_account_key: str, company_id: str,
) -> CustomerAccount:
    identity = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.source_system == "okki",
        CustomerExternalIdentity.source_account_key == source_account_key,
        CustomerExternalIdentity.identifier_type == "company_id",
        CustomerExternalIdentity.normalized_value == company_id,
        CustomerExternalIdentity.customer_id.is_not(None),
        CustomerExternalIdentity.verification_status == "verified",
        CustomerExternalIdentity.status == "active",
    ).with_for_update().one_or_none()
    account = (
        db.query(CustomerAccount).filter(
            CustomerAccount.id == identity.customer_id,
        ).with_for_update().one_or_none()
        if identity else None
    )
    if account is None or account.record_status != "active":
        raise ProjectionError("OKKI_CUSTOMER_IDENTITY_NOT_FOUND")
    return account


def project_okki_order(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    try:
        return _project_okki_order_from_source(
            db,
            source_account_key=source_account_key,
            payload=payload,
            sync_cursor=sync_cursor,
            captured_at=captured_at,
        )
    except ProjectionRetryRequired:
        db.rollback()
        raise


def _project_okki_order_from_source(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    if not isinstance(payload, Mapping):
        raise ProjectionError("SOURCE_PAYLOAD_INVALID")
    account_key = normalized_identifier(source_account_key, "SOURCE_ACCOUNT_INVALID")
    captured = to_beijing_naive(captured_at) if captured_at else beijing_now()
    order_external_id = raw_external_id(payload, "order_id", "order")
    try:
        order_date = business_date(
            payload.get("account_date"), "SOURCE_BUSINESS_TIME_INVALID"
        )
    except ProjectionError:
        order_date = None
    order_source = append_raw(
        db, source_system="okki", source_account_key=account_key,
        source_entity_type="order", external_record_id=order_external_id,
        schema_version="okki_order_v1", payload=payload,
        occurred_at=(datetime.combine(order_date, datetime_time.min) if order_date else None),
        captured_at=captured, sync_cursor=sync_cursor,
    )
    raw_items = payload.get("items", [])
    item_sources: list[CustomerSourceRecord] = []
    if isinstance(raw_items, list):
        for index, item in enumerate(raw_items):
            raw_item = dict(item) if isinstance(item, Mapping) else {
                "invalid_value": repr(item)
            }
            item_id = raw_external_id(raw_item, "item_id", f"item:{index}")
            item_sources.append(append_raw(
                db, source_system="okki", source_account_key=account_key,
                source_entity_type="order_item",
                external_record_id=f"{order_external_id}:{item_id}",
                schema_version="okki_order_item_v1", payload=raw_item,
                occurred_at=(
                    datetime.combine(order_date, datetime_time.min)
                    if order_date else None
                ),
                captured_at=captured, sync_cursor=sync_cursor,
            ))
    sources = [order_source, *item_sources]
    if is_exact_processed_replay(sources):
        order = db.query(CustomerOrder).filter_by(
            source_system="okki",
            source_account_key=account_key,
            external_order_id=normalized_identifier(
                payload.get("order_id"), "ORDER_ID_INVALID"
            ),
        ).one_or_none()
        if order is None:
            raise ProjectionError("SOURCE_PROJECTION_STATE_INVALID")
        items = db.query(CustomerOrderItem).filter_by(order_id=order.id).order_by(
            CustomerOrderItem.id
        ).all()
        return ProjectionReceipt(
            "processed", order_source.id, outcome="unchanged",
            customer_id=order.customer_id, order_id=order.id,
            item_ids=tuple(row.id for row in items),
        )
    try:
        with db.begin_nested():
            result = _project_okki_order(
                db, source_account_key=account_key, payload=payload,
                order_source=order_source, item_sources=item_sources,
                captured_at=order_source.captured_at,
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
        return quarantine(db, sources, error_code(exc, "OKKI_ORDER_INVALID"))


def _project_okki_order(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    order_source: CustomerSourceRecord,
    item_sources: Sequence[CustomerSourceRecord],
    captured_at: datetime,
) -> ProjectionReceipt:
    external_id = normalized_identifier(payload.get("order_id"), "ORDER_ID_INVALID")
    company_id = normalized_identifier(payload.get("company_id"), "COMPANY_ID_INVALID")
    account = okki_customer_identity(
        db, source_account_key=source_account_key, company_id=company_id,
    )
    bind_source(order_source, account.id)
    for source in item_sources:
        bind_source(source, account.id)
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list) or len(raw_items) != len(item_sources):
        raise ProjectionError("ORDER_ITEM_LIST_INVALID")
    order_date = business_date(
        payload.get("account_date"), "SOURCE_BUSINESS_TIME_INVALID"
    )
    status, status_name, trail = (
        payload.get("status"), payload.get("status_name"), payload.get("trail")
    )
    valid = is_valid_business_order(status, status_name, trail)
    owner_external_user_id = optional_string(
        payload.get("owner_external_user_id"), "OWNER_ID_INVALID"
    )
    owner_user_id = (
        resolve_projection_owner(db, "okki", owner_external_user_id)
        if owner_external_user_id else None
    )
    order_query = db.query(CustomerOrder).filter(
        CustomerOrder.source_system == "okki",
        CustomerOrder.source_account_key == source_account_key,
        CustomerOrder.external_order_id == external_id,
    )
    order = order_query.with_for_update().one_or_none()
    if order is not None and order.customer_id != account.id:
        raise ProjectionError("ORDER_CUSTOMER_MISMATCH")
    values = {
        "order_no": optional_string(payload.get("order_no"), "ORDER_NO_INVALID"),
        "order_name": optional_string(payload.get("order_name"), "ORDER_NAME_INVALID"),
        "order_status": optional_string(status, "ORDER_STATUS_INVALID"),
        "account_date": order_date,
        "currency": optional_string(payload.get("currency"), "ORDER_CURRENCY_INVALID"),
        "amount_original": decimal_value(
            payload.get("amount_original"), "ORDER_AMOUNT_INVALID"
        ),
        "amount_usd": decimal_value(
            payload.get("amount_usd"), "ORDER_AMOUNT_INVALID", default="0"
        ),
        "source_category": optional_string(
            payload.get("source_category"), "ORDER_SOURCE_INVALID"
        ),
        "is_valid_business_order": valid,
        "invalid_reason": None if valid else "not_effective_business_order",
        "is_new_deal": (
            payload.get("is_new_deal")
            if type(payload.get("is_new_deal")) is bool else None
        ),
        "is_first_return": (
            payload.get("is_first_return")
            if type(payload.get("is_first_return")) is bool else None
        ),
        "owner_external_user_id": owner_external_user_id,
        "owner_user_id": owner_user_id,
        "source_record_id": order_source.id,
        "source_hash": order_source.content_hash,
        "synced_at": captured_at,
        "updated_at": captured_at,
    }
    order_outcome = "unchanged"
    if order is None:
        candidate_order = CustomerOrder(
            customer_id=account.id, source_system="okki",
            source_account_key=source_account_key, external_order_id=external_id,
            created_at=captured_at, **values,
        )
        def insert_order() -> CustomerOrder:
            db.add(candidate_order)
            db.flush()
            return candidate_order

        order, inserted = insert_or_load_expected_unique(
            db,
            entity_type="order",
            insert=insert_order,
            load_winner=lambda: order_query.with_for_update().one_or_none(),
        )
        if order.customer_id != account.id:
            raise ProjectionError("ORDER_CUSTOMER_MISMATCH")
        order_outcome = "inserted" if inserted else "unchanged"
        if not inserted:
            recovered_changed = any(
                getattr(order, key) != value for key, value in values.items()
            )
            for key, value in values.items():
                setattr(order, key, value)
            if recovered_changed:
                order_outcome = "updated"
    else:
        changed = any(
            getattr(order, key) != value for key, value in values.items()
        )
        for key, value in values.items():
            setattr(order, key, value)
        order_outcome = "updated" if changed else "unchanged"
    projected_items = _sync_order_items(
        db, order=order, raw_items=raw_items, item_sources=item_sources,
        snapshot_mode=payload.get("item_snapshot_mode", "partial"),
        captured_at=captured_at,
    )
    observed_at = order_source.occurred_at or (
        datetime.combine(order_date, datetime_time.min) if order_date else captured_at
    )
    if valid:
        append_fact(
            db, customer_id=account.id, subject_type="customer",
            fact_key="commercial.has_valid_order", value_type="boolean", value=True,
            fact_layer="observed", verification_status="verified", confidence=1,
            confidence_method_version="confidence_v1",
            confidence_components={"order_state": 1}, source_system="okki",
            source_entity_type="order", observed_at=observed_at,
            source_record_id=order_source.id,
            direct_evidence=[DirectFactEvidence(
                "order", order.id, {"json_path": "$.status"}
            )],
        )
    linked = _reconcile_opportunity_reference(
        db, account_id=account.id, order=order, payload=payload,
        valid=valid, captured_at=captured_at,
    )
    activate_customer_from_order(db, order.id)
    if not valid:
        reconcile_invalidated_order(db, order.id)
    db.flush()
    return ProjectionReceipt(
        "processed",
        order_source.id,
        outcome=aggregate_outcome(
            [order_source, *item_sources],
            order_outcome,
        ),
        customer_id=account.id, opportunity_id=linked.id if linked else None,
        order_id=order.id, item_ids=tuple(row.id for row in projected_items),
    )


def _sync_order_items(
    db: Session,
    *,
    order: CustomerOrder,
    raw_items: Sequence[Mapping],
    item_sources: Sequence[CustomerSourceRecord],
    snapshot_mode: str,
    captured_at: datetime,
) -> list[CustomerOrderItem]:
    if snapshot_mode not in {"partial", "full"}:
        raise ProjectionError("ORDER_ITEM_SNAPSHOT_MODE_INVALID")
    projected: list[CustomerOrderItem] = []
    occurrence_counts: dict[str, int] = {}
    for raw, source in zip(raw_items, item_sources, strict=True):
        if not isinstance(raw, Mapping):
            raise ProjectionError("ORDER_ITEM_INPUT_INVALID")
        item_type = raw.get("item_type", "unknown")
        if item_type not in _ITEM_TYPES:
            raise ProjectionError("ORDER_ITEM_INPUT_INVALID")
        external_item_id = optional_string(raw.get("item_id"), "ORDER_ITEM_ID_INVALID")
        values = {
            "external_item_id": external_item_id,
            "external_product_id": optional_string(raw.get("product_id"), "ORDER_ITEM_INPUT_INVALID"),
            "external_sku_id": optional_string(raw.get("sku_id"), "ORDER_ITEM_INPUT_INVALID"),
            "product_name": optional_string(raw.get("product_name"), "ORDER_ITEM_INPUT_INVALID"),
            "product_family": optional_string(raw.get("product_family"), "ORDER_ITEM_INPUT_INVALID"),
            "model": optional_string(raw.get("model"), "ORDER_ITEM_INPUT_INVALID"),
            "color": optional_string(raw.get("color"), "ORDER_ITEM_INPUT_INVALID"),
            "length": optional_string(raw.get("length"), "ORDER_ITEM_INPUT_INVALID"),
            "quantity": decimal_value(raw.get("quantity"), "ORDER_ITEM_INPUT_INVALID"),
            "quantity_unit": optional_string(raw.get("quantity_unit"), "ORDER_ITEM_INPUT_INVALID"),
            "unit_price": decimal_value(raw.get("unit_price"), "ORDER_ITEM_INPUT_INVALID"),
            "line_amount": decimal_value(raw.get("line_amount"), "ORDER_ITEM_INPUT_INVALID"),
            "item_type": item_type, "source_record_id": source.id,
            "updated_at": captured_at,
        }
        normalized = {
            key: format(value, "f") if isinstance(value, Decimal) else value
            for key, value in values.items()
            if key not in {"source_record_id", "updated_at"}
        }
        occurrence_key = sha256(normalized)
        ordinal = occurrence_counts.get(occurrence_key, 0)
        occurrence_counts[occurrence_key] = ordinal + 1
        fingerprint = sha256(
            "order_item_v1", order.id, external_item_id or normalized,
            0 if external_item_id else ordinal,
        )
        item_query = db.query(CustomerOrderItem).filter_by(
            order_id=order.id, item_fingerprint=fingerprint,
        )
        row = item_query.with_for_update().one_or_none()
        if row is None:
            candidate_item = CustomerOrderItem(
                order_id=order.id, item_fingerprint=fingerprint,
                created_at=captured_at, **values,
            )
            def insert_item() -> CustomerOrderItem:
                db.add(candidate_item)
                db.flush()
                return candidate_item

            row, inserted = insert_or_load_expected_unique(
                db,
                entity_type="order_item",
                insert=insert_item,
                load_winner=lambda: item_query.with_for_update().one_or_none(),
            )
            if not inserted:
                for key, value in values.items():
                    setattr(row, key, value)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        projected.append(row)
    if snapshot_mode == "full":
        retained_ids = [row.id for row in projected]
        stale = db.query(CustomerOrderItem).filter_by(order_id=order.id)
        if retained_ids:
            stale = stale.filter(CustomerOrderItem.id.not_in(retained_ids))
        for row in stale.with_for_update().all():
            db.delete(row)
    return projected


def _reconcile_opportunity_reference(
    db: Session,
    *,
    account_id: int,
    order: CustomerOrder,
    payload: Mapping,
    valid: bool,
    captured_at: datetime,
) -> CustomerOpportunity | None:
    opportunity_ref = payload.get("opportunity_ref")
    if opportunity_ref is None:
        return None
    if not isinstance(opportunity_ref, Mapping):
        raise ProjectionError("OPPORTUNITY_REFERENCE_INVALID")
    ref = tuple(normalized_identifier(
        opportunity_ref.get(key), "OPPORTUNITY_REFERENCE_INVALID"
    ) for key in ("source_system", "source_account_key", "source_key"))
    linked = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.source_system == ref[0],
        CustomerOpportunity.source_account_key == ref[1],
        CustomerOpportunity.source_key == ref[2],
    ).with_for_update().one_or_none()
    if linked is None:
        raise ProjectionError("OPPORTUNITY_REFERENCE_NOT_FOUND")
    if linked.customer_id != account_id:
        raise ProjectionError("OPPORTUNITY_CUSTOMER_MISMATCH")
    if linked.linked_order_id not in {None, order.id}:
        raise ProjectionError("OPPORTUNITY_ORDER_CONFLICT")
    conflict = db.query(CustomerOpportunity.id).filter(
        CustomerOpportunity.linked_order_id == order.id,
        CustomerOpportunity.id != linked.id,
    ).first()
    if conflict is not None:
        raise ProjectionError("OPPORTUNITY_ORDER_CONFLICT")
    if valid:
        linked.linked_order_id = order.id
        linked.updated_at = captured_at
    return linked


__all__ = ["okki_customer_identity", "project_okki_order"]
