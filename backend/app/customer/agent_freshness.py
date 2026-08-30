"""Freshness metadata derived from Ark evidence and sync health."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer.models import (
    CustomerFact,
    CustomerProfileVersion,
    CustomerSourceRecord,
    CustomerSyncCursor,
)


_RESOURCE_TYPES = {
    "customer": "customers", "contact": "contacts", "order": "orders",
    "order_item": "order_items", "conversation": "conversations",
    "message": "messages", "inquiry": "inquiries",
}
_MAX_AGE = timedelta(days=7)


def _parsed(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def profile_freshness(
    db: Session, *, access: CustomerAccess, version: CustomerProfileVersion | None,
    requested_sections: list[str], context_current: bool, now: datetime,
) -> tuple[dict, list[str], list[str]]:
    fact_ids = list(version.evidence_fact_ids or []) if version else []
    facts = apply_record_access(
        db.query(CustomerFact), CustomerFact, access, logical_object_type="fact",
    ).filter(CustomerFact.id.in_(fact_ids)).all() if fact_ids else []
    source_ids = {row.source_record_id for row in facts if row.source_record_id is not None}
    sources = apply_record_access(
        db.query(CustomerSourceRecord), CustomerSourceRecord, access,
        logical_object_type="source_record",
    ).filter(CustomerSourceRecord.id.in_(source_ids)).all() if source_ids else []

    freshness: dict[str, dict] = {}
    unavailable: list[str] = []
    for source in sources:
        resource = _RESOURCE_TYPES.get(source.source_entity_type, source.source_entity_type)
        key = f"{source.source_system}:{resource}:{source.source_account_key}"
        cursor = db.query(CustomerSyncCursor).filter_by(
            source_system=source.source_system,
            resource_type=resource,
            scope_key=source.source_account_key,
        ).one_or_none()
        success_at = cursor.last_success_at if cursor else None
        if cursor is None or cursor.sync_status in {"failed", "degraded"} or success_at is None:
            status = "unavailable"
        elif now - success_at > _MAX_AGE:
            status = "stale"
        else:
            status = "fresh"
        freshness[key] = {
            "status": status,
            "source_system": source.source_system,
            "resource_type": resource,
            "scope_key": source.source_account_key,
            "last_success_at": success_at,
            "last_record_at": cursor.last_record_at if cursor else source.captured_at,
            "error_code": cursor.error_code if cursor else "SYNC_SCOPE_MISSING",
        }
        if status == "unavailable":
            unavailable.append(key)

    section_dates = version.section_data_as_of or {} if version else {}
    stale_sections = [
        section for section in requested_sections
        if not context_current
        or (date_value := _parsed(section_dates.get(section))) is None
        or now - date_value > _MAX_AGE
    ]
    return freshness, sorted(unavailable), stale_sections


__all__ = ["profile_freshness"]
