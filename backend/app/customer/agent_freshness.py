"""Freshness metadata derived from Ark evidence and sync health."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer.contracts import FACT_REGISTRY, SOURCE_REGISTRY
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
_PROFILE_SECTION_BY_FACT_SECTION = {
    "business": "business_profile", "commercial": "commercial_summary",
    "preferences": "preferences", "behavior": "behavior_patterns",
    "risks": "risks", "quality": "data_quality",
}


def _fact_section(fact_key: str) -> str:
    prefix = fact_key.split(".", 1)[0]
    return _PROFILE_SECTION_BY_FACT_SECTION.get(prefix, "data_quality")


def _fact_is_stale(fact: CustomerFact, now: datetime) -> bool:
    if fact.expires_at is not None:
        return fact.expires_at <= now
    policy = FACT_REGISTRY.get(fact.fact_key)
    return bool(
        policy is not None
        and policy.ttl_days is not None
        and fact.observed_at + timedelta(days=policy.ttl_days) <= now
    )


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

    cursor_keys = {
        (source.source_system, _RESOURCE_TYPES.get(
            source.source_entity_type, source.source_entity_type,
        ), source.source_account_key)
        for source in sources
    }
    cursors = db.query(CustomerSyncCursor).filter(tuple_(
        CustomerSyncCursor.source_system,
        CustomerSyncCursor.resource_type,
        CustomerSyncCursor.scope_key,
    ).in_(cursor_keys)).all() if cursor_keys else []
    cursor_by_key = {
        (row.source_system, row.resource_type, row.scope_key): row for row in cursors
    }

    freshness: dict[str, dict] = {}
    unavailable: list[str] = []
    for source in sources:
        resource = _RESOURCE_TYPES.get(source.source_entity_type, source.source_entity_type)
        key = f"{source.source_system}:{resource}:{source.source_account_key}"
        cursor = cursor_by_key.get((source.source_system, resource, source.source_account_key))
        success_at = cursor.last_success_at if cursor else None
        policy = SOURCE_REGISTRY.get((source.source_system, source.source_entity_type))
        if cursor is None or cursor.sync_status in {"failed", "degraded"} or success_at is None:
            status = "unavailable"
        elif policy is None:
            status = "unavailable"
        elif policy.ttl_days is not None and now - success_at > timedelta(days=policy.ttl_days):
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

    stale_from_facts = {_fact_section(fact.fact_key) for fact in facts if _fact_is_stale(fact, now)}
    stale_sections = [
        section for section in requested_sections
        if not context_current or section in stale_from_facts
    ]
    return freshness, sorted(unavailable), stale_sections


__all__ = ["profile_freshness"]
