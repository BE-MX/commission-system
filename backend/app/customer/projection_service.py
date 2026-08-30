"""Stable facade and fenced batch cursor for customer source projections.

Adapters receive already-fetched normalized records and write only Ark.  The
Alibaba and OKKI entity projectors live in focused sibling modules; callers use
this facade so the public contract remains one small service boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Mapping, Sequence

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.models import CustomerSourceRecord, CustomerSyncCursor
from app.customer.projection_alibaba import project_alibaba_inquiry
from app.customer.projection_common import (
    ProjectionError,
    ProjectionReceipt,
    ProjectionRetryRequired,
    SyncBatchResult,
    SyncLease,
    normalized_identifier,
    retryable_operational_error,
)
from app.customer.projection_okki import (
    project_okki_contact,
    project_okki_customer,
    project_okki_order,
)


_RESOURCE_PROJECTORS = {
    ("alibaba", "inquiries"): project_alibaba_inquiry,
    ("okki", "customers"): project_okki_customer,
    ("okki", "contacts"): project_okki_contact,
    ("okki", "orders"): project_okki_order,
}


def claim_sync_scope(
    db: Session,
    *,
    source_system: str,
    resource_type: str,
    scope_key: str,
    claimed_by: str,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> SyncLease:
    """Claim one sync scope and increment its fencing generation."""
    source = normalized_identifier(source_system, "SYNC_SOURCE_INVALID")
    resource = normalized_identifier(resource_type, "SYNC_RESOURCE_INVALID")
    scope = normalized_identifier(scope_key, "SYNC_SCOPE_INVALID")
    worker = normalized_identifier(claimed_by, "SYNC_WORKER_INVALID")
    if (
        (source, resource) not in _RESOURCE_PROJECTORS
        or type(lease_seconds) is not int
        or lease_seconds <= 0
    ):
        raise ProjectionError("SYNC_RESOURCE_INVALID")
    claimed_at = to_beijing_naive(now) if now is not None else beijing_now()
    row = db.query(CustomerSyncCursor).filter(
        CustomerSyncCursor.source_system == source,
        CustomerSyncCursor.resource_type == resource,
        CustomerSyncCursor.scope_key == scope,
    ).with_for_update().one_or_none()
    if (
        row is not None
        and row.lease_expires_at is not None
        and row.lease_expires_at > claimed_at
    ):
        raise ProjectionError("SYNC_SCOPE_ALREADY_CLAIMED")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if row is None:
        row = CustomerSyncCursor(
            source_system=source,
            resource_type=resource,
            scope_key=scope,
            cursor_value=None,
            sync_status="running",
            generation=1,
            claimed_by=worker,
            lease_token_hash=token_hash,
            lease_expires_at=claimed_at + timedelta(seconds=lease_seconds),
            last_attempt_at=claimed_at,
            last_counts_json={
                "fetched": 0,
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "quarantined": 0,
            },
            created_at=claimed_at,
            updated_at=claimed_at,
        )
        db.add(row)
    else:
        row.generation = int(row.generation) + 1
        row.sync_status = "running"
        row.claimed_by = worker
        row.lease_token_hash = token_hash
        row.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        row.last_attempt_at = claimed_at
        row.error_code = None
        row.error_message = None
        row.updated_at = claimed_at
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ProjectionRetryRequired() from exc
    except OperationalError as exc:
        if retryable_operational_error(exc):
            db.rollback()
            raise ProjectionRetryRequired() from exc
        raise
    return SyncLease(
        row.id,
        source,
        resource,
        scope,
        row.generation,
        token,
        row.cursor_value,
    )


def _locked_cursor_for_lease(
    db: Session,
    lease: SyncLease,
    *,
    now: datetime,
    expected_cursor_value: str | None = None,
    use_lease_cursor: bool = True,
) -> CustomerSyncCursor:
    try:
        row = db.query(CustomerSyncCursor).filter(
            CustomerSyncCursor.id == lease.cursor_id,
        ).with_for_update().one_or_none()
    except OperationalError as exc:
        if retryable_operational_error(exc):
            db.rollback()
            raise ProjectionRetryRequired() from exc
        raise
    token_hash = hashlib.sha256(lease.lease_token.encode("utf-8")).hexdigest()
    if (
        row is None
        or row.source_system != lease.source_system
        or row.resource_type != lease.resource_type
        or row.scope_key != lease.scope_key
        or row.generation != lease.generation
        or row.cursor_value != (
            lease.expected_cursor_value
            if use_lease_cursor
            else expected_cursor_value
        )
        or not row.lease_token_hash
        or row.lease_expires_at is None
        or row.lease_expires_at <= now
        or not hmac.compare_digest(row.lease_token_hash, token_hash)
    ):
        raise ProjectionError("SYNC_CURSOR_FENCE_REJECTED")
    return row


def project_sync_batch(
    db: Session,
    *,
    lease: SyncLease,
    source_account_key: str,
    expected_cursor_value: str | None,
    records: Sequence[Mapping],
) -> SyncBatchResult:
    """Project every record while advancing only its continuous success prefix."""
    account_key = normalized_identifier(
        source_account_key, "SOURCE_ACCOUNT_INVALID"
    )
    if account_key != lease.scope_key:
        raise ProjectionError("SYNC_SCOPE_SOURCE_ACCOUNT_MISMATCH")
    if expected_cursor_value != lease.expected_cursor_value:
        raise ProjectionError("CURSOR_SEQUENCE_CONFLICT")
    _locked_cursor_for_lease(db, lease, now=beijing_now())
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ProjectionError("SYNC_BATCH_INVALID")
    projector = _RESOURCE_PROJECTORS.get((lease.source_system, lease.resource_type))
    if projector is None:
        raise ProjectionError("SYNC_RESOURCE_INVALID")
    expected_previous = expected_cursor_value
    normalized_records: list[tuple[str, Mapping]] = []
    for record in records:
        if (
            not isinstance(record, Mapping)
            or "previous_cursor_value" not in record
        ):
            raise ProjectionError("SYNC_RECORD_INVALID")
        previous = record.get("previous_cursor_value")
        if previous is not None:
            previous = normalized_identifier(
                previous, "SYNC_RECORD_CURSOR_INVALID"
            )
        cursor_value = normalized_identifier(
            record.get("cursor_value"), "SYNC_RECORD_CURSOR_INVALID"
        )
        if previous != expected_previous:
            raise ProjectionError("CURSOR_SEQUENCE_CONFLICT")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise ProjectionError("SYNC_RECORD_INVALID")
        normalized_records.append((cursor_value, payload))
        expected_previous = cursor_value

    receipts: list[ProjectionReceipt] = []
    contiguous = True
    committed_cursor: str | None = None
    last_record_at: datetime | None = None
    for cursor_value, payload in normalized_records:
        current_cursor = committed_cursor or lease.expected_cursor_value
        _locked_cursor_for_lease(
            db,
            lease,
            now=beijing_now(),
            expected_cursor_value=current_cursor,
            use_lease_cursor=False,
        )
        receipt = projector(
            db,
            source_account_key=account_key,
            payload=payload,
            sync_cursor=cursor_value,
        )
        receipts.append(receipt)
        if contiguous and receipt.status == "processed":
            committed_cursor = cursor_value
            cursor_row = _locked_cursor_for_lease(
                db,
                lease,
                now=beijing_now(),
                expected_cursor_value=current_cursor,
                use_lease_cursor=False,
            )
            cursor_row.cursor_value = committed_cursor
            cursor_row.last_success_at = beijing_now()
            try:
                db.flush()
            except OperationalError as exc:
                if retryable_operational_error(exc):
                    db.rollback()
                    raise ProjectionRetryRequired() from exc
                raise
        else:
            contiguous = False
        source = db.get(CustomerSourceRecord, receipt.source_record_id)
        if source is not None and source.occurred_at is not None:
            last_record_at = (
                max(last_record_at, source.occurred_at)
                if last_record_at else source.occurred_at
            )
    row = _locked_cursor_for_lease(
        db,
        lease,
        now=beijing_now(),
        expected_cursor_value=committed_cursor or lease.expected_cursor_value,
        use_lease_cursor=False,
    )
    completed_at = beijing_now()
    quarantined = sum(receipt.status == "quarantined" for receipt in receipts)
    row.sync_status = "degraded" if quarantined else "idle"
    row.last_record_at = last_record_at or row.last_record_at
    row.last_counts_json = {
        "fetched": len(receipts),
        "inserted": sum(receipt.outcome == "inserted" for receipt in receipts),
        "updated": sum(receipt.outcome == "updated" for receipt in receipts),
        "unchanged": sum(receipt.outcome == "unchanged" for receipt in receipts),
        "quarantined": quarantined,
    }
    row.error_code = "SOURCE_RECORD_QUARANTINED" if quarantined else None
    row.error_message = (
        "One or more source records require correction" if quarantined else None
    )
    row.claimed_by = None
    row.lease_token_hash = None
    row.lease_expires_at = None
    row.updated_at = completed_at
    try:
        db.flush()
    except OperationalError as exc:
        if retryable_operational_error(exc):
            db.rollback()
            raise ProjectionRetryRequired() from exc
        raise
    return SyncBatchResult(tuple(receipts), committed_cursor)


__all__ = [
    "ProjectionError",
    "ProjectionReceipt",
    "ProjectionRetryRequired",
    "SyncBatchResult",
    "SyncLease",
    "claim_sync_scope",
    "project_alibaba_inquiry",
    "project_okki_contact",
    "project_okki_customer",
    "project_okki_order",
    "project_sync_batch",
]
