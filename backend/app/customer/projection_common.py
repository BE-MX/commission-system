"""Shared source-first projection contracts and deterministic helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from typing import Mapping, Sequence

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.fact_service import append_source_record
from app.customer.models import (
    CustomerContactPoint,
    CustomerExternalIdentity,
    CustomerSourceRecord,
)
from app.customer.projection_write_race import insert_or_load_expected_unique


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RETRYABLE_MYSQL_CODES = frozenset({1205, 1213})
_ATTACHMENT_KEYS = ("file_name", "mime_type", "size", "source_ref")


class ProjectionError(ValueError):
    """Stable, non-leaking source projection rejection."""

    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__("Customer source projection rejected")


class ProjectionRetryRequired(ProjectionError):
    """The database transaction was invalidated and must be retried fresh."""

    requires_new_transaction = True

    def __init__(self):
        super().__init__("RETRY_NEW_TRANSACTION")


@dataclass(frozen=True, slots=True)
class ProjectionReceipt:
    status: str
    source_record_id: int
    outcome: str = "inserted"
    customer_id: int | None = None
    contact_id: int | None = None
    conversation_id: int | None = None
    message_ids: tuple[int, ...] = ()
    opportunity_id: int | None = None
    order_id: int | None = None
    item_ids: tuple[int, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class SyncLease:
    cursor_id: int
    source_system: str
    resource_type: str
    scope_key: str
    generation: int
    lease_token: str
    expected_cursor_value: str | None


@dataclass(frozen=True, slots=True)
class SyncBatchResult:
    receipts: tuple[ProjectionReceipt, ...]
    committed_cursor: str | None


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def sha256(*parts: object) -> str:
    encoded = "\x1f".join(canonical_json(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_identifier(value: str, error_code: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(character) <= 0x1F or ord(character) == 0x7F for character in value)
    ):
        raise ProjectionError(error_code)
    return unicodedata.normalize("NFKC", value).strip()


def optional_string(value: object, error_code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionError(error_code)
    return value.strip() or None


def optional_content(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionError("MESSAGE_CONTENT_INVALID")
    return value


def business_datetime(
    value: object, error_code: str, *, required: bool = True,
) -> datetime | None:
    if value is None:
        if required:
            raise ProjectionError(error_code)
        return None
    if isinstance(value, datetime):
        result = to_beijing_naive(value)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProjectionError(error_code) from exc
        result = to_beijing_naive(parsed)
    else:
        raise ProjectionError(error_code)
    if result is None:
        raise ProjectionError(error_code)
    return result


def safe_business_datetime(value: object) -> datetime | None:
    try:
        return business_datetime(value, "SOURCE_TIME_INVALID", required=False)
    except ProjectionError:
        return None


def business_date(value: object, error_code: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_beijing_naive(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ProjectionError(error_code) from exc
    raise ProjectionError(error_code)


def decimal_value(
    value: object,
    error_code: str,
    *,
    default: str | None = None,
) -> Decimal | None:
    if value is None and default is None:
        return None
    try:
        result = Decimal(str(default if value is None else value))
    except (InvalidOperation, ValueError) as exc:
        raise ProjectionError(error_code) from exc
    if not result.is_finite():
        raise ProjectionError(error_code)
    return result


def retryable_operational_error(exc: OperationalError) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and (
            args[0] in _RETRYABLE_MYSQL_CODES
            or any("40001" in str(argument) for argument in args)
        ):
            return True
        for related in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return False


def error_code(exc: BaseException, fallback: str) -> str:
    code = getattr(exc, "error_code", None)
    return code if isinstance(code, str) and code else fallback


def raw_external_id(payload: Mapping, field: str, prefix: str) -> str:
    value = payload.get(field)
    if (
        isinstance(value, str)
        and value.strip()
        and len(value.strip()) <= 255
        and not any(
            ord(character) <= 0x1F or ord(character) == 0x7F
            for character in value
        )
    ):
        return value.strip()
    return f"invalid:{prefix}:{sha256(payload)[:32]}"


def append_raw(
    db: Session,
    *,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_record_id: str,
    schema_version: str,
    payload: Mapping,
    occurred_at: datetime | None,
    captured_at: datetime,
    sync_cursor: str | None,
    data_classification: str | None = None,
) -> CustomerSourceRecord:
    prior_version_exists = db.query(CustomerSourceRecord.id).filter(
        CustomerSourceRecord.source_system == source_system,
        CustomerSourceRecord.source_account_key == source_account_key,
        CustomerSourceRecord.source_entity_type == source_entity_type,
        CustomerSourceRecord.external_record_id == external_record_id,
    ).first() is not None
    payload_copy = dict(payload)

    def insert_source() -> CustomerSourceRecord:
        return append_source_record(
            db,
            customer_id=None,
            source_system=source_system,
            source_account_key=source_account_key,
            source_entity_type=source_entity_type,
            external_record_id=external_record_id,
            payload_schema_version=schema_version,
            payload_json=payload_copy,
            occurred_at=occurred_at,
            captured_at=captured_at,
            sync_cursor=sync_cursor,
            processing_status="pending",
            data_classification=data_classification,
        )

    def load_source_winner() -> CustomerSourceRecord | None:
        return db.query(CustomerSourceRecord).filter(
            CustomerSourceRecord.source_system == source_system,
            CustomerSourceRecord.source_account_key == source_account_key,
            CustomerSourceRecord.source_entity_type == source_entity_type,
            CustomerSourceRecord.external_record_id == external_record_id,
            CustomerSourceRecord.content_hash == sha256(payload_copy),
        ).with_for_update().one_or_none()

    try:
        row, _inserted = insert_or_load_expected_unique(
            db,
            entity_type="source_record",
            insert=insert_source,
            load_winner=load_source_winner,
        )
        entry_status = row.processing_status
        row._projection_entry_status = entry_status
        row._projection_outcome = (
            "unchanged"
            if entry_status == "processed"
            else "updated"
            if prior_version_exists
            else "inserted"
        )
        return row
    except OperationalError as exc:
        if retryable_operational_error(exc):
            db.rollback()
            raise ProjectionRetryRequired() from exc
        raise


def quarantine(
    db: Session,
    sources: Sequence[CustomerSourceRecord],
    code: str,
) -> ProjectionReceipt:
    for source in sources:
        if getattr(source, "_projection_entry_status", None) == "pending":
            source.processing_status = "quarantined"
            source.processing_error_code = code
            source.processing_error_message = f"Projection rejected: {code}"
    try:
        db.flush()
    except OperationalError as exc:
        if retryable_operational_error(exc):
            db.rollback()
            raise ProjectionRetryRequired() from exc
        raise
    return ProjectionReceipt(
        status="quarantined",
        source_record_id=sources[0].id,
        outcome="quarantined",
        error_code=code,
    )


def source_outcome(source: CustomerSourceRecord) -> str:
    outcome = getattr(source, "_projection_outcome", "inserted")
    return outcome if outcome in {"inserted", "updated", "unchanged"} else "inserted"


def aggregate_outcome(
    sources: Sequence[CustomerSourceRecord],
    *derived_outcomes: str,
) -> str:
    """Return the highest material change across raw and derived projection writes."""
    outcomes = [source_outcome(source) for source in sources]
    outcomes.extend(derived_outcomes)
    for candidate in ("inserted", "updated", "unchanged"):
        if candidate in outcomes:
            return candidate
    return "unchanged"


def is_exact_processed_replay(sources: Sequence[CustomerSourceRecord]) -> bool:
    return bool(sources) and all(
        getattr(source, "_projection_entry_status", None) == "processed"
        for source in sources
    )


def bind_source(source: CustomerSourceRecord, customer_id: int) -> None:
    if source.customer_id not in {None, customer_id}:
        raise ProjectionError("SOURCE_CUSTOMER_MISMATCH")
    source.customer_id = customer_id


def normalize_email(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionError("CONTACT_POINT_INVALID")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ProjectionError("CONTACT_POINT_INVALID")
    return normalized


def existing_contact_id(
    db: Session,
    *,
    source_system: str,
    source_account_key: str,
    identifier_type: str,
    raw_value: str | None,
) -> int | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", raw_value).strip()
    row = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.source_system == source_system,
        CustomerExternalIdentity.source_account_key == source_account_key,
        CustomerExternalIdentity.identifier_type == identifier_type,
        CustomerExternalIdentity.normalized_value == normalized,
        CustomerExternalIdentity.contact_id.is_not(None),
        CustomerExternalIdentity.status == "active",
    ).one_or_none()
    return row.contact_id if row is not None else None


def upsert_contact_email(
    db: Session,
    *,
    contact_id: int,
    raw_email: object,
    source_record: CustomerSourceRecord,
    fingerprint_scope: str,
    now: datetime,
) -> CustomerContactPoint | None:
    normalized = normalize_email(raw_email)
    if normalized is None:
        return None
    existing = db.query(CustomerContactPoint).filter(
        CustomerContactPoint.contact_id == contact_id,
        CustomerContactPoint.point_type == "email",
        CustomerContactPoint.normalized_value == normalized,
    ).order_by(CustomerContactPoint.id).first()
    if existing is not None:
        existing.raw_value = str(raw_email).strip()
        existing.source_record_id = source_record.id
        existing.last_seen_at = max(existing.last_seen_at, now)
        return existing
    db.query(CustomerContactPoint).filter(
        CustomerContactPoint.contact_id == contact_id,
        CustomerContactPoint.point_type == "email",
        CustomerContactPoint.is_primary.is_(True),
    ).update({CustomerContactPoint.is_primary: False}, synchronize_session="fetch")
    row = CustomerContactPoint(
        contact_id=contact_id,
        point_type="email",
        platform=None,
        raw_value=str(raw_email).strip(),
        normalized_value=normalized,
        email_domain_type="unknown",
        verification_status="unknown",
        contactability_status="unknown",
        contactability_reason_code="unknown",
        contactability_source="import",
        contactability_effective_at=now,
        is_primary=True,
        data_classification="personal_contact",
        source_record_id=source_record.id,
        point_fingerprint=sha256(
            "contact_point_v1",
            "contact",
            contact_id,
            "email",
            normalized,
            fingerprint_scope,
        ),
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def attachment_metadata(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectionError("MESSAGE_ATTACHMENT_INVALID")
    result: list[dict] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ProjectionError("MESSAGE_ATTACHMENT_INVALID")
        metadata = {
            key: item.get(key)
            for key in _ATTACHMENT_KEYS
            if item.get(key) is not None
        }
        if "size" in metadata and (
            type(metadata["size"]) is not int or metadata["size"] < 0
        ):
            raise ProjectionError("MESSAGE_ATTACHMENT_INVALID")
        if any(
            not isinstance(metadata.get(key), str)
            for key in ("file_name", "mime_type", "source_ref")
            if key in metadata
        ):
            raise ProjectionError("MESSAGE_ATTACHMENT_INVALID")
        result.append(metadata)
    return result


__all__ = [
    "ProjectionError",
    "ProjectionReceipt",
    "ProjectionRetryRequired",
    "SyncBatchResult",
    "SyncLease",
    "aggregate_outcome",
    "append_raw",
    "attachment_metadata",
    "bind_source",
    "business_date",
    "business_datetime",
    "decimal_value",
    "error_code",
    "existing_contact_id",
    "normalized_identifier",
    "optional_content",
    "optional_string",
    "quarantine",
    "raw_external_id",
    "retryable_operational_error",
    "safe_business_datetime",
    "sha256",
    "upsert_contact_email",
]
