"""Deterministic customer profile compilation and current read projections."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Callable, Mapping, Protocol

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerContact,
    CustomerContactRelationship,
    CustomerExternalIdentity,
    CustomerEvent,
    CustomerFact,
    CustomerFactConflict,
    CustomerListProjection,
    CustomerName,
    CustomerOrder,
    CustomerOrderItem,
    CustomerProfileVersion,
    CustomerRelationship,
    CustomerSourceRecord,
    CustomerTargetMatch,
)
from app.sales_automation.models import AcquisitionProfile


logger = logging.getLogger(__name__)

PROFILE_SCHEMA_VERSION = "customer_profile_v1"
CONTEXT_SCHEMA_VERSION = "customer_context_v1"
TARGET_MATCH_SCHEMA_VERSION = "target_match_v1"
CANONICALIZATION_VERSION = "jcs_v1"
COMPILER_VERSION = "profile_compiler_v1"
TARGET_MATCH_POLICY_VERSION = "target_match_v1"
MAX_CAS_RETRIES = 5

_CLASSIFICATION_ORDER = (
    "public_business",
    "internal_business",
    "personal_contact",
    "restricted_internal",
)
_VISIBILITY_ORDER = (
    "all_authorized",
    "customer_team",
    "management",
    "private",
)
_SHARED_VISIBILITIES = frozenset({
    "all_authorized",
    "customer_team",
    "management",
})
_AGENT_VISIBILITIES = frozenset({"all_authorized", "customer_team"})
_PROFILE_SECTIONS = (
    "identity",
    "business",
    "contacts",
    "ownership",
    "engagement",
    "commercial",
    "preferences",
    "behavior",
    "opportunities",
    "risks",
    "recommended_actions",
    "quality",
)
_SEMANTIC_SET_ARRAY_PATHS = frozenset({
    ("identity", "strong_identities"),
    ("identity", "aliases"),
    ("business", "channels"),
    ("business", "scale_signals"),
    ("business", "related_companies"),
    ("ownership", "collaborator_user_ids"),
    ("preferences", "expressed"),
    ("preferences", "observed"),
    ("preferences", "inferred"),
    ("preferences", "confirmed"),
    ("preferences", "conflicts"),
    ("behavior", "observed"),
    ("behavior", "inferred"),
    ("behavior", "confirmed"),
    ("risks", "items"),
    ("quality", "conflicts"),
    ("quality", "preference_conflicts"),
    ("quality", "corrections"),
    ("quality", "stale_facts"),
    ("quality", "gaps"),
    ("quality", "open_questions"),
})
_RISK_FACT_TYPES = {
    "behavior.inferred.churn_risk": "churn_risk",
    "behavior.inferred.supplier_switch_signal": "supplier_switch_signal",
    "behavior.observed.silence_period": "silence_period",
}


class CompileObserver(Protocol):
    """Optional orchestration seam used by deterministic concurrency tests."""

    def __call__(
        self,
        phase: str,
        db: Session,
        customer_id: int,
        base_seq: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProjectionState:
    status: str
    profile_version_id: int | None
    target_profile_version_id: int
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileCompileResult:
    customer_id: int
    profile_version_id: int
    version_no: int
    created: bool
    retry_count: int
    projections: Mapping[str, ProjectionState]


class ProfileCompileError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class _Snapshot:
    customer: dict
    names: tuple[dict, ...]
    identities: tuple[dict, ...]
    facts: tuple[dict, ...]
    conflicts: tuple[dict, ...]
    contacts: tuple[dict, ...]
    relationships: tuple[dict, ...]
    assignments: tuple[dict, ...]
    orders: tuple[dict, ...]
    annotations: tuple[dict, ...]


def _notify(
    observer: CompileObserver | None,
    phase: str,
    db: Session,
    customer_id: int,
    base_seq: int,
) -> None:
    if observer is not None:
        observer(phase, db, customer_id, base_seq)


def _json_value(value):
    if isinstance(value, Decimal):
        normalized = value.normalize()
        if normalized == normalized.to_integral():
            return int(normalized)
        return float(normalized)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _max_classification(values) -> str:
    known = [
        value if value in _CLASSIFICATION_ORDER else "restricted_internal"
        for value in values
    ]
    return max(
        known or ["public_business"],
        key=_CLASSIFICATION_ORDER.index,
    )


def _max_visibility(values) -> str:
    normalized = [
        value if value in _VISIBILITY_ORDER else "private"
        for value in values
    ]
    return max(normalized or ["all_authorized"], key=_VISIBILITY_ORDER.index)


def _active_at(
    effective_from: datetime | None,
    effective_to: datetime | None,
    now: datetime,
) -> bool:
    return bool(
        (effective_from is None or effective_from <= now)
        and (effective_to is None or effective_to > now)
    )


def _source_security(source: CustomerSourceRecord | None) -> tuple[str, str]:
    if source is None:
        return "internal_business", "customer_team"
    return source.data_classification, source.visibility_scope


def _load_snapshot(db: Session, customer: CustomerAccount, now: datetime) -> _Snapshot:
    name_rows = db.query(CustomerName).filter(
        CustomerName.customer_id == customer.id
    ).all()
    identity_rows = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.customer_id == customer.id,
        CustomerExternalIdentity.status == "active",
    ).all()
    referenced_source_ids = {
        row.source_record_id
        for row in (*name_rows, *identity_rows)
        if row.source_record_id is not None
    }
    source_filter = CustomerSourceRecord.customer_id == customer.id
    if referenced_source_ids:
        source_filter = source_filter | CustomerSourceRecord.id.in_(referenced_source_ids)
    sources = {
        row.id: row
        for row in db.query(CustomerSourceRecord).filter(source_filter)
    }
    names = []
    for row in name_rows:
        if row.verification_status == "rejected" or not _active_at(
            row.valid_from, row.valid_to, now
        ):
            continue
        classification, visibility = _source_security(sources.get(row.source_record_id))
        names.append({
            "name": row.name,
            "name_type": row.name_type,
            "verification_status": row.verification_status,
            "confidence": _json_value(row.confidence),
            "data_classification": classification,
            "visibility_scope": visibility,
            "last_seen_at": row.last_seen_at,
        })

    identities = []
    for row in identity_rows:
        if row.verification_status == "rejected":
            continue
        classification, visibility = _source_security(sources.get(row.source_record_id))
        identities.append({
            "source_system": row.source_system,
            "identifier_type": row.identifier_type,
            "normalized_value": row.normalized_value,
            "identity_strength": row.identity_strength,
            "cardinality": row.cardinality,
            "verification_status": row.verification_status,
            "confidence": _json_value(row.confidence),
            "data_classification": classification,
            "visibility_scope": visibility,
            "last_seen_at": row.last_seen_at,
        })

    facts = []
    fact_rows = db.query(CustomerFact).filter(CustomerFact.customer_id == customer.id).all()
    fact_by_id = {row.id: row for row in fact_rows}
    for row in fact_rows:
        facts.append({
            "id": row.id,
            "fact_key": row.fact_key,
            "value": _json_value((row.value_json or {}).get("value")),
            "value_meta": {
                key: _json_value(value)
                for key, value in (row.value_json or {}).items()
                if key != "value"
            },
            "fact_layer": row.fact_layer,
            "verification_status": row.verification_status,
            "confidence": _json_value(row.confidence),
            "data_classification": row.data_classification,
            "visibility_scope": row.visibility_scope,
            "agent_run_id": row.agent_run_id,
            "fact_fingerprint": row.fact_fingerprint,
            "effective_from": row.effective_from,
            "effective_to": row.effective_to,
            "observed_at": row.observed_at,
            "expires_at": row.expires_at,
        })

    conflicts = []
    for row in db.query(CustomerFactConflict).filter(
        CustomerFactConflict.customer_id == customer.id,
        CustomerFactConflict.status == "open",
    ):
        left = fact_by_id.get(row.left_fact_id)
        right = fact_by_id.get(row.right_fact_id)
        if left is None or right is None:
            continue
        conflicts.append({
            "conflict_key": row.conflict_key,
            "conflict_type": row.conflict_type,
            "left_fact_id": row.left_fact_id,
            "right_fact_id": row.right_fact_id,
            "data_classification": row.data_classification,
            "visibility_scope": row.visibility_scope,
            "detected_at": row.detected_at,
        })

    contacts = []
    contact_rows = {
        row.id: row
        for row in db.query(CustomerContact).filter(CustomerContact.record_status == "active")
    }
    for row in db.query(CustomerContactRelationship).filter(
        CustomerContactRelationship.customer_id == customer.id,
    ):
        contact = contact_rows.get(row.contact_id)
        if (
            contact is None
            or row.verification_status in {"rejected", "disputed"}
            or not _active_at(row.effective_from, row.effective_to, now)
        ):
            continue
        source_fact = fact_by_id.get(row.source_fact_id)
        contacts.append({
            "contact_id": contact.id,
            "display_name": contact.canonical_name or contact.display_name,
            "identity_status": contact.identity_status,
            "relationship_type": row.relationship_type,
            "job_title": row.job_title,
            "buying_role": row.buying_role,
            "influence_level": row.influence_level,
            "verification_status": row.verification_status,
            "confidence": _json_value(row.confidence),
            "source_fact_id": row.source_fact_id,
            "data_classification": (
                source_fact.data_classification if source_fact else "internal_business"
            ),
            "visibility_scope": (
                source_fact.visibility_scope if source_fact else "customer_team"
            ),
            "data_as_of": row.effective_from or row.created_at,
        })

    relationships = []
    for row in db.query(CustomerRelationship).filter(
        (CustomerRelationship.from_customer_id == customer.id)
        | (CustomerRelationship.to_customer_id == customer.id),
    ):
        if (
            row.verification_status in {"rejected", "disputed"}
            or not _active_at(row.effective_from, row.effective_to, now)
        ):
            continue
        source_fact = fact_by_id.get(row.source_fact_id)
        relationships.append({
            "related_customer_id": (
                row.to_customer_id
                if row.from_customer_id == customer.id
                else row.from_customer_id
            ),
            "direction": "outbound" if row.from_customer_id == customer.id else "inbound",
            "relationship_type": row.relationship_type,
            "verification_status": row.verification_status,
            "confidence": _json_value(row.confidence),
            "source_fact_id": row.source_fact_id,
            "data_classification": (
                source_fact.data_classification if source_fact else "internal_business"
            ),
            "visibility_scope": (
                source_fact.visibility_scope if source_fact else "customer_team"
            ),
            "data_as_of": row.effective_from or row.created_at,
        })

    assignments = [{
        "user_id": row.user_id,
        "assignment_role": row.assignment_role,
        "effective_from": row.effective_from,
    } for row in db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == customer.id,
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )]

    item_rows = db.query(CustomerOrderItem).join(
        CustomerOrder, CustomerOrder.id == CustomerOrderItem.order_id
    ).filter(CustomerOrder.customer_id == customer.id).all()
    items_by_order: dict[int, list[dict]] = defaultdict(list)
    for item in item_rows:
        items_by_order[item.order_id].append({
            "product_family": item.product_family,
            "model": item.model,
            "color": item.color,
            "length": item.length,
            "quantity": _json_value(item.quantity),
            "quantity_unit": item.quantity_unit,
            "item_type": item.item_type,
        })
    orders = [{
        "id": row.id,
        "account_date": row.account_date,
        "amount_usd": _json_value(row.amount_usd),
        "source_category": row.source_category,
        "is_valid_business_order": row.is_valid_business_order,
        "items": tuple(items_by_order.get(row.id, ())),
    } for row in db.query(CustomerOrder).filter(CustomerOrder.customer_id == customer.id)]

    annotations = []
    for row in db.query(CustomerAnnotation).filter(
        CustomerAnnotation.customer_id == customer.id,
        CustomerAnnotation.status == "active",
    ):
        if row.visibility == "private":
            continue
        if row.visibility not in _SHARED_VISIBILITIES:
            if row.annotation_type == "correction":
                raise ProfileCompileError(
                    "CORRECTION_ANNOTATION_INVALID",
                    "active correction has an invalid shared visibility",
                )
            continue
        target_fact = None
        if row.annotation_type == "correction":
            target_fact = fact_by_id.get(row.target_fact_id)
            if target_fact is None:
                raise ProfileCompileError(
                    "CORRECTION_ANNOTATION_INVALID",
                    "active correction target must belong to the same customer",
                )
        annotations.append({
            "id": row.id,
            "annotation_type": row.annotation_type,
            "target_fact_id": row.target_fact_id,
            "target_fact_key": target_fact.fact_key if target_fact else None,
            "content": _json_value(row.content_json or {}),
            "policy_scope_type": row.policy_scope_type,
            "policy_scope_ref_id": row.policy_scope_ref_id,
            "policy_effective_at": row.policy_effective_at,
            "visibility_scope": _max_visibility([
                row.visibility,
                target_fact.visibility_scope if target_fact else row.visibility,
            ]),
            "data_classification": _max_classification([
                row.data_classification,
                target_fact.data_classification if target_fact else row.data_classification,
            ]),
            "created_at": row.created_at,
        })

    return _Snapshot(
        customer={
            "id": customer.id,
            "customer_code": customer.customer_code,
            "display_name": customer.display_name,
            "canonical_company_name": customer.canonical_company_name,
            "entity_type": customer.entity_type,
            "identity_status": customer.identity_status,
            "identity_confidence": _json_value(customer.identity_confidence),
            "relationship_stage": customer.relationship_stage,
            "record_status": customer.record_status,
            "merged_into_customer_id": customer.merged_into_customer_id,
            "primary_country_code": customer.primary_country_code,
            "primary_region": customer.primary_region,
            "default_language": customer.default_language,
            "timezone": customer.timezone,
            "created_at": customer.created_at,
            "updated_at": customer.updated_at,
        },
        names=tuple(names),
        identities=tuple(identities),
        facts=tuple(facts),
        conflicts=tuple(conflicts),
        contacts=tuple(contacts),
        relationships=tuple(relationships),
        assignments=tuple(assignments),
        orders=tuple(orders),
        annotations=tuple(annotations),
    )


def _fact_rank(fact: dict) -> tuple:
    if fact["fact_layer"] == "confirmed":
        authority = 5
    elif fact["verification_status"] == "verified":
        authority = 4
    elif fact["fact_layer"] == "inferred":
        authority = 3
    elif fact["verification_status"] == "candidate":
        authority = 2
    elif fact["verification_status"] == "unverified":
        authority = 1
    else:
        authority = 0
    return (
        authority,
        Decimal(str(fact["confidence"])),
        fact["observed_at"],
        fact["fact_fingerprint"],
    )


def _fact_entry(fact: dict) -> dict:
    entry = {
        "fact_id": fact["id"],
        "fact_key": fact["fact_key"],
        "value": fact["value"],
        "fact_layer": fact["fact_layer"],
        "verification_status": fact["verification_status"],
        "confidence": fact["confidence"],
        "data_classification": fact["data_classification"],
        "visibility_scope": fact["visibility_scope"],
        "observed_at": _json_value(fact["observed_at"]),
        "fact_fingerprint": fact["fact_fingerprint"],
    }
    entry.update(fact["value_meta"])
    return entry


def _latest(values: list[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _section_for_fact_key(fact_key: str) -> str:
    if fact_key.startswith("business."):
        return "business"
    if fact_key.startswith("preference."):
        return "preferences"
    if fact_key.startswith("behavior."):
        return "behavior"
    if fact_key.startswith("commercial."):
        return "commercial"
    return "quality"


def _build_profile(snapshot: _Snapshot, now: datetime):
    corrections = [
        annotation for annotation in snapshot.annotations
        if annotation["annotation_type"] == "correction"
    ]
    corrected_fact_ids = {
        annotation["target_fact_id"] for annotation in corrections
    }
    corrected_fact_keys = {
        annotation["target_fact_key"] for annotation in corrections
    }
    current_facts: list[dict] = []
    stale_facts: list[dict] = []
    for fact in snapshot.facts:
        if fact["id"] in corrected_fact_ids or (
            fact["fact_key"] in corrected_fact_keys
            and (
                fact["fact_layer"] == "inferred"
                or fact["agent_run_id"] is not None
            )
        ):
            continue
        if (
            fact["verification_status"] in {"rejected", "superseded"}
            or not _active_at(fact["effective_from"], fact["effective_to"], now)
        ):
            continue
        if fact["expires_at"] is not None and fact["expires_at"] <= now:
            stale_facts.append(fact)
            continue
        current_facts.append(fact)

    selected: dict[str, dict] = {}
    for fact in current_facts:
        if fact["verification_status"] == "disputed":
            continue
        existing = selected.get(fact["fact_key"])
        if existing is None or _fact_rank(fact) > _fact_rank(existing):
            selected[fact["fact_key"]] = fact

    fact_entries = {key: _fact_entry(value) for key, value in selected.items()}
    fact_fingerprints = {
        fact["id"]: fact["fact_fingerprint"] for fact in snapshot.facts
    }
    effective_fact_fingerprints = sorted(
        fact["fact_fingerprint"] for fact in current_facts
    )

    strong_identities = sorted(
        [item for item in snapshot.identities if item["identity_strength"] == "strong"],
        key=lambda item: (
            item["source_system"], item["identifier_type"], item["normalized_value"]
        ),
    )
    aliases = sorted(
        list(snapshot.names),
        key=lambda item: (item["name_type"], item["name"], item["verification_status"]),
    )
    identity = {
        "customer_id": snapshot.customer["id"],
        "customer_code": snapshot.customer["customer_code"],
        "display_name": snapshot.customer["display_name"],
        "canonical_company_name": snapshot.customer["canonical_company_name"],
        "entity_type": snapshot.customer["entity_type"],
        "identity_status": snapshot.customer["identity_status"],
        "identity_confidence": snapshot.customer["identity_confidence"],
        "record_status": snapshot.customer["record_status"],
        "merged_into_customer_id": snapshot.customer["merged_into_customer_id"],
        "strong_identities": strong_identities,
        "aliases": aliases,
    }

    industry = fact_entries.get("business.industry")
    business = {
        "industry": industry,
        "market": snapshot.customer["primary_country_code"],
        "region": snapshot.customer["primary_region"],
        "default_language": snapshot.customer["default_language"],
        "timezone": snapshot.customer["timezone"],
        "operating_model": None,
        "channels": [],
        "scale_signals": [],
        "related_companies": sorted(
            list(snapshot.relationships),
            key=lambda item: (
                item["related_customer_id"], item["relationship_type"], item["direction"]
            ),
        ),
    }

    contacts = {
        "items": sorted(
            list(snapshot.contacts),
            key=lambda item: (
                item["buying_role"] or "", item["display_name"], item["contact_id"]
            ),
        )
    }
    primary = sorted(
        [item for item in snapshot.assignments if item["assignment_role"] == "primary"],
        key=lambda item: (item["effective_from"], item["user_id"]),
        reverse=True,
    )
    collaborators = sorted(
        item["user_id"]
        for item in snapshot.assignments
        if item["assignment_role"] == "collaborator"
    )
    ownership = {
        "primary_owner_user_id": primary[0]["user_id"] if primary else None,
        "collaborator_user_ids": collaborators,
        "is_public_pool": not primary,
    }

    expressed = []
    observed = []
    inferred = []
    confirmed = []
    for key, entry in sorted(fact_entries.items()):
        if key.startswith("preference.expressed."):
            expressed.append(entry)
        elif key.startswith("preference.observed."):
            observed.append(entry)
        elif key.startswith("preference.inferred."):
            inferred.append(entry)
        elif key.startswith("preference.confirmed.") or (
            key.startswith("preference.") and entry["fact_layer"] == "confirmed"
        ):
            confirmed.append(entry)

    preference_conflicts = []
    expressed_by_attribute = {
        item["fact_key"].removeprefix("preference.expressed."): item
        for item in expressed
    }
    observed_by_attribute = {
        item["fact_key"].removeprefix("preference.observed."): item
        for item in observed
    }
    for attribute in sorted(expressed_by_attribute.keys() & observed_by_attribute.keys()):
        left = expressed_by_attribute[attribute]
        right = observed_by_attribute[attribute]
        if _canonical_json(left["value"]) != _canonical_json(right["value"]):
            preference_conflicts.append({
                "attribute": attribute,
                "expressed_fact_ids": [left["fact_id"]],
                "observed_fact_ids": [right["fact_id"]],
                "status": "open",
            })
    preferences = {
        "expressed": expressed,
        "observed": observed,
        "inferred": inferred,
        "confirmed": confirmed,
        "conflicts": preference_conflicts,
    }

    behavior = {"observed": [], "inferred": [], "confirmed": []}
    for key, entry in sorted(fact_entries.items()):
        if not key.startswith("behavior."):
            continue
        layer = key.split(".", 2)[1]
        if layer in behavior:
            behavior[layer].append(entry)
        elif entry["fact_layer"] in behavior:
            behavior[entry["fact_layer"]].append(entry)

    valid_orders = sorted(
        [item for item in snapshot.orders if item["is_valid_business_order"]],
        key=lambda item: (item["account_date"] or date.min, item["id"]),
    )
    order_dates = [item["account_date"] for item in valid_orders if item["account_date"]]
    intervals = [
        (right - left).days
        for left, right in zip(order_dates, order_dates[1:])
        if right >= left
    ]
    product_counts = Counter(
        item["product_family"]
        for order in valid_orders
        for item in order["items"]
        if item["product_family"]
    )
    product_distribution = [
        {"product_family": product, "line_count": count}
        for product, count in sorted(product_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    total_amount = sum(
        (Decimal(str(item["amount_usd"] or 0)) for item in valid_orders),
        Decimal("0"),
    )
    commercial = {
        "has_valid_order": bool(valid_orders),
        "valid_order_count": len(valid_orders),
        "valid_order_amount_usd": _json_value(total_amount.quantize(Decimal("0.01"))),
        "first_order_at": order_dates[0].isoformat() if order_dates else None,
        "last_order_at": order_dates[-1].isoformat() if order_dates else None,
        "purchase_cycle_days": (
            round(sum(intervals) / len(intervals), 2) if intervals else None
        ),
        "trend": "insufficient_data",
        "product_distribution": product_distribution,
        "fact_signals": [
            entry for key, entry in sorted(fact_entries.items())
            if key.startswith("commercial.")
        ],
    }

    engagement = {
        "relationship_stage": snapshot.customer["relationship_stage"],
        "current_needs": expressed,
        "objections": [],
        "commitments": [],
        "recent_changes": [],
    }
    opportunities = {"open": [], "history_summary": []}

    active_dnc = [
        item for item in snapshot.annotations
        if item["annotation_type"] == "do_not_contact"
        and (
            item["policy_effective_at"] is None
            or item["policy_effective_at"] <= now
        )
    ]
    risk_items = []
    if snapshot.customer["identity_status"] == "disputed":
        risk_items.append({
            "risk_type": "identity_disputed",
            "data_classification": "internal_business",
            "visibility_scope": "customer_team",
        })
    for annotation in active_dnc:
        risk_items.append({
            "risk_type": "do_not_contact",
            "risk_source": "annotation",
            "scope_type": annotation["policy_scope_type"],
            "scope_ref_id": annotation["policy_scope_ref_id"],
            "data_classification": annotation["data_classification"],
            "visibility_scope": annotation["visibility_scope"],
        })
    for fact_key, risk_type in _RISK_FACT_TYPES.items():
        entry = fact_entries.get(fact_key)
        if entry is None or (
            entry["visibility_scope"] not in _SHARED_VISIBILITIES
            or entry["data_classification"] not in _CLASSIFICATION_ORDER
        ):
            continue
        risk_items.append({
            **entry,
            "risk_type": risk_type,
        })
    risk_items.sort(key=lambda item: (
        item["risk_type"],
        item.get("fact_id", 0),
        item.get("scope_type") or "",
        item.get("scope_ref_id") or "",
    ))
    risks = {
        "has_active_dnc": bool(active_dnc),
        "items": risk_items,
    }

    gaps = []
    if not snapshot.customer["canonical_company_name"]:
        gaps.append("canonical_company_name")
    if industry is None:
        gaps.append("business.industry")
    if not contacts["items"]:
        gaps.append("contacts")
    stale_summary = sorted(
        [{
            "fact_id": item["id"],
            "fact_key": item["fact_key"],
            "expires_at": _json_value(item["expires_at"]),
            "data_classification": item["data_classification"],
            "visibility_scope": item["visibility_scope"],
        } for item in stale_facts],
        key=lambda item: (item["fact_key"], item["fact_id"]),
    )
    persisted_conflicts = sorted(
        [{
            "conflict_key": item["conflict_key"],
            "conflict_type": item["conflict_type"],
            "left_fact_id": item["left_fact_id"],
            "right_fact_id": item["right_fact_id"],
            "data_classification": item["data_classification"],
            "visibility_scope": item["visibility_scope"],
        } for item in snapshot.conflicts],
        key=lambda item: (
            item["conflict_key"], item["left_fact_id"], item["right_fact_id"]
        ),
    )

    used_classifications = [item["data_classification"] for item in selected.values()]
    used_classifications.extend(item["data_classification"] for item in stale_facts)
    used_classifications.extend(item["data_classification"] for item in aliases)
    used_classifications.extend(item["data_classification"] for item in strong_identities)
    used_classifications.extend(item["data_classification"] for item in contacts["items"])
    used_classifications.extend(item["data_classification"] for item in business["related_companies"])
    used_classifications.extend(item["data_classification"] for item in risk_items)
    used_classifications.extend(
        item["data_classification"] for item in snapshot.conflicts
    )
    used_visibilities = [item["visibility_scope"] for item in selected.values()]
    used_visibilities.extend(item["visibility_scope"] for item in stale_facts)
    used_visibilities.extend(item["visibility_scope"] for item in aliases)
    used_visibilities.extend(item["visibility_scope"] for item in strong_identities)
    used_visibilities.extend(item["visibility_scope"] for item in contacts["items"])
    used_visibilities.extend(
        item["visibility_scope"] for item in business["related_companies"]
    )
    used_visibilities.extend(item["visibility_scope"] for item in risk_items)
    used_visibilities.extend(item["visibility_scope"] for item in snapshot.conflicts)

    correction_summary = sorted(
        [{
            "target_fact_id": item["target_fact_id"],
            "fact_key": item["target_fact_key"],
            "status": "active",
            "data_classification": item["data_classification"],
            "visibility_scope": item["visibility_scope"],
            "open_question": f"review_correction:{item['target_fact_key']}",
        } for item in corrections],
        key=lambda item: (item["fact_key"], item["target_fact_id"]),
    )
    used_classifications.extend(
        item["data_classification"] for item in correction_summary
    )
    used_visibilities.extend(
        item["visibility_scope"] for item in correction_summary
    )
    correction_questions = [
        item["open_question"] for item in correction_summary
    ]

    filled = sum((
        bool(snapshot.customer["canonical_company_name"]),
        industry is not None,
        bool(contacts["items"]),
        bool(expressed),
        bool(behavior["observed"] or behavior["confirmed"]),
        bool(valid_orders),
        bool(snapshot.assignments),
        snapshot.customer["identity_status"] in {"identified", "verified"},
    ))
    completeness = Decimal(filled * 100) / Decimal(8)
    quality = {
        "completeness": _json_value(completeness.quantize(Decimal("0.01"))),
        "conflicts": persisted_conflicts,
        "preference_conflicts": preference_conflicts,
        "corrections": correction_summary,
        "stale_facts": stale_summary,
        "gaps": gaps,
        "open_questions": [
            *[f"confirm:{item}" for item in gaps],
            *correction_questions,
        ],
        "max_data_classification": _max_classification(used_classifications),
        "max_visibility_scope": _max_visibility(used_visibilities),
    }
    recommended_actions = {
        "items": [
            {"action_type": "complete_customer_identity", "reason": "identity_gap"}
            for gap in gaps if gap == "canonical_company_name"
        ]
    }

    profile = {
        "identity": identity,
        "business": business,
        "contacts": contacts,
        "ownership": ownership,
        "engagement": engagement,
        "commercial": commercial,
        "preferences": preferences,
        "behavior": behavior,
        "opportunities": opportunities,
        "risks": risks,
        "recommended_actions": recommended_actions,
        "quality": quality,
    }
    effective_fact_ids = {fact["id"] for fact in current_facts}
    evidence_fact_ids = sorted(_collect_fact_ids(profile) & effective_fact_ids)

    section_times: dict[str, datetime | None] = {section: None for section in _PROFILE_SECTIONS}
    section_times["identity"] = _latest([
        snapshot.customer["updated_at"],
        *[item["last_seen_at"] for item in aliases],
        *[item["last_seen_at"] for item in strong_identities],
    ])
    section_times["business"] = _latest([
        *[
            fact["observed_at"] for fact in selected.values()
            if _section_for_fact_key(fact["fact_key"]) == "business"
        ],
        *[item["data_as_of"] for item in snapshot.relationships],
    ])
    section_times["contacts"] = _latest([item["data_as_of"] for item in snapshot.contacts])
    section_times["ownership"] = _latest([item["effective_from"] for item in snapshot.assignments])
    section_times["engagement"] = _latest([
        fact["observed_at"] for fact in selected.values()
        if fact["fact_key"].startswith(("preference.expressed.", "behavior.observed."))
    ])
    for section in ("commercial", "preferences", "behavior"):
        section_times[section] = _latest([
            fact["observed_at"] for fact in selected.values()
            if _section_for_fact_key(fact["fact_key"]) == section
        ])
    if order_dates:
        section_times["commercial"] = _latest([
            section_times["commercial"],
            datetime.combine(order_dates[-1], time.min),
        ])
    section_times["risks"] = _latest([
        *[
            item["policy_effective_at"] or item["created_at"]
            for item in active_dnc
        ],
        *[
            fact["observed_at"] for fact in selected.values()
            if fact["fact_key"] in _RISK_FACT_TYPES
        ],
    ])
    section_times["recommended_actions"] = _latest([
        section_times["identity"], section_times["risks"]
    ])
    section_times["quality"] = _latest([
        *section_times.values(),
        *[item["expires_at"] for item in stale_facts],
        *[item["detected_at"] for item in snapshot.conflicts],
        *[item["created_at"] for item in corrections],
    ])
    serialized_times = {
        section: _json_value(section_times[section])
        for section in _PROFILE_SECTIONS
    }
    data_as_of = _latest(list(section_times.values()))
    return (
        _json_value(profile),
        serialized_times,
        evidence_fact_ids,
        data_as_of,
        fact_fingerprints,
        effective_fact_fingerprints,
    )


def _semantic_value(
    value,
    fact_fingerprints: Mapping[int, str],
    path: tuple[str, ...] = (),
):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if (
                (key == "fact_id" or key.endswith("_fact_id"))
                and isinstance(item, int)
            ):
                fingerprint_key = key.removesuffix("_id") + "_fingerprint"
                result[fingerprint_key] = fact_fingerprints.get(
                    item, f"missing:{item}"
                )
            elif key.endswith("_fact_ids") and isinstance(item, list):
                result[key.removesuffix("_ids") + "_fingerprints"] = sorted({
                    fact_fingerprints.get(fact_id, f"missing:{fact_id}")
                    for fact_id in item
                })
            else:
                result[key] = _semantic_value(
                    item,
                    fact_fingerprints,
                    path + (key,),
                )
        return result
    if isinstance(value, list):
        items = [
            _semantic_value(item, fact_fingerprints, path + ("*",))
            for item in value
        ]
        if path in _SEMANTIC_SET_ARRAY_PATHS:
            unique = {_canonical_json(item): item for item in items}
            return [unique[key] for key in sorted(unique)]
        return items
    return value


def _section_hashes(profile: dict, fact_fingerprints: Mapping[int, str]) -> dict[str, str]:
    return {
        section: _hash(_semantic_value(
            profile[section],
            fact_fingerprints,
            (section,),
        ))
        for section in _PROFILE_SECTIONS
    }


def _change_summary(
    previous: CustomerProfileVersion | None,
    section_hashes: Mapping[str, str],
    profile: dict,
) -> dict:
    previous_hashes = previous.section_hashes if previous is not None else {}
    changes = []
    for section in _PROFILE_SECTIONS:
        if previous_hashes.get(section) == section_hashes[section]:
            continue
        classification, visibility = _content_security(profile[section])
        changes.append({
            "section": section,
            "change_type": "created" if previous is None else "updated",
            "summary": f"{section}_changed",
            "evidence_fact_ids": sorted(_collect_fact_ids(profile[section])),
            "data_classification": classification,
            "visibility_scope": visibility,
        })
    return {"changes": changes}


def _content_security(value) -> tuple[str, str]:
    classifications: list[str] = []
    visibilities: list[str] = []

    def collect(item) -> None:
        if isinstance(item, dict):
            classification = item.get(
                "data_classification",
                item.get("max_data_classification"),
            )
            visibility = item.get(
                "visibility_scope",
                item.get("max_visibility_scope"),
            )
            if isinstance(classification, str):
                classifications.append(classification)
            if isinstance(visibility, str):
                visibilities.append(visibility)
            for nested in item.values():
                collect(nested)
        elif isinstance(item, list):
            for nested in item:
                collect(nested)

    collect(value)
    return _max_classification(classifications), _max_visibility(visibilities)


def _collect_fact_ids(value) -> set[int]:
    found: set[int] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                (key == "fact_id" or key.endswith("_fact_id"))
                and isinstance(item, int)
            ):
                found.add(item)
            elif key.endswith("_fact_ids") and isinstance(item, list):
                found.update(fact_id for fact_id in item if isinstance(fact_id, int))
            else:
                found.update(_collect_fact_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_fact_ids(item))
    return found


def _collect_fact_keys(value) -> dict[int, str]:
    found: dict[int, str] = {}
    if isinstance(value, dict):
        fact_id = value.get("fact_id")
        fact_key = value.get("fact_key")
        if isinstance(fact_id, int) and isinstance(fact_key, str):
            found[fact_id] = fact_key
        for item in value.values():
            found.update(_collect_fact_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_fact_keys(item))
    return found


def _evidence_description(fact_key: str) -> str:
    if fact_key == "business.industry":
        return "Supports the current business industry conclusion"
    if fact_key.startswith("preference.expressed."):
        return "Supports a customer-expressed preference"
    if fact_key.startswith("preference.observed."):
        return "Supports an order-observed preference"
    if fact_key.startswith("preference.inferred."):
        return "Supports an inferred product preference"
    if fact_key.startswith("behavior.observed."):
        return "Supports an observed customer behavior pattern"
    if fact_key.startswith("behavior.inferred."):
        return "Supports an inferred customer behavior or risk signal"
    if fact_key.startswith("behavior.confirmed."):
        return "Supports a manually confirmed customer behavior conclusion"
    if fact_key.startswith("commercial."):
        return "Supports a current commercial profile conclusion"
    return "Supports a current customer profile conclusion"


def _safe_entry(entry: dict) -> bool:
    classification = entry.get("data_classification", "internal_business")
    visibility = entry.get("visibility_scope", "customer_team")
    return bool(
        classification in _CLASSIFICATION_ORDER
        and _CLASSIFICATION_ORDER.index(classification)
        <= _CLASSIFICATION_ORDER.index("internal_business")
        and visibility in _AGENT_VISIBILITIES
    )


def _safe_entries(entries: list[dict]) -> list[dict]:
    return [entry for entry in entries if _safe_entry(entry)]


def _build_context(version: CustomerProfileVersion) -> dict:
    profile = version.profile_json
    identity = dict(profile["identity"])
    identity["strong_identities"] = _safe_entries(identity["strong_identities"])
    identity["aliases"] = _safe_entries(identity["aliases"])
    business = dict(profile["business"])
    if business["industry"] is not None and not _safe_entry(business["industry"]):
        business["industry"] = None
    business["related_companies"] = _safe_entries(business["related_companies"])
    preferences = {
        key: _safe_entries(list(profile["preferences"][key]))
        for key in ("expressed", "observed", "inferred", "confirmed")
    }
    safe_fact_ids = set()
    for entries in preferences.values():
        safe_fact_ids.update(item["fact_id"] for item in entries)
    preferences["conflicts"] = [
        conflict for conflict in profile["preferences"]["conflicts"]
        if set(conflict["expressed_fact_ids"] + conflict["observed_fact_ids"])
        <= safe_fact_ids
    ]
    behavior = {
        key: _safe_entries(list(profile["behavior"][key]))
        for key in ("observed", "inferred", "confirmed")
    }
    commercial = dict(profile["commercial"])
    commercial["fact_signals"] = _safe_entries(commercial["fact_signals"])
    safe_contacts = _safe_entries(list(profile["contacts"]["items"]))
    safe_risks = _safe_entries(list(profile["risks"]["items"]))
    safe_fact_ids.update(_collect_fact_ids(business))
    safe_fact_ids.update(_collect_fact_ids(behavior))
    safe_fact_ids.update(_collect_fact_ids(commercial))
    safe_fact_ids.update(_collect_fact_ids(safe_contacts))
    evidence_facts: dict[int, str] = {}
    for section in (
        business,
        preferences,
        behavior,
        commercial,
        safe_contacts,
        safe_risks,
    ):
        fact_keys = _collect_fact_keys(section)
        evidence_facts.update(fact_keys)
        for fact_id in _collect_fact_ids(section):
            evidence_facts.setdefault(fact_id, "")
    evidence_refs = [{
        "fact_id": fact_id,
        "reference_type": "customer_fact",
        "description": _evidence_description(evidence_facts[fact_id]),
    } for fact_id in sorted(evidence_facts)]
    recent_changes = []
    for change in version.change_summary["changes"]:
        evidence_ids = change.get("evidence_fact_ids", [])
        visible_ids = sorted(set(evidence_ids) & safe_fact_ids)
        if evidence_ids and not visible_ids:
            continue
        if not evidence_ids and not _safe_entry(change):
            continue
        recent_changes.append({
            key: value
            for key, value in {
                **change,
                "evidence_fact_ids": visible_ids,
            }.items()
            if key not in {"data_classification", "visibility_scope"}
        })
    safe_stale_facts = _safe_entries(list(profile["quality"]["stale_facts"]))
    safe_conflicts = _safe_entries(list(profile["quality"]["conflicts"]))
    corrections = list(profile["quality"].get("corrections", []))
    safe_corrections = _safe_entries(corrections)
    hidden_correction_questions = {
        item["open_question"] for item in corrections
        if not _safe_entry(item)
    }
    return {
        "identity": identity,
        "business_profile": business,
        "ownership": profile["ownership"],
        "key_contacts": safe_contacts,
        "current_needs": preferences["expressed"],
        "commercial_summary": commercial,
        "preferences": preferences,
        "behavior_patterns": behavior,
        "open_opportunities": profile["opportunities"]["open"],
        "risks": {
            "has_active_dnc": profile["risks"]["has_active_dnc"],
            "items": safe_risks,
        },
        "recommended_actions": profile["recommended_actions"]["items"],
        "recent_changes": recent_changes,
        "data_quality": {
            "completeness": profile["quality"]["completeness"],
            "section_data_as_of": version.section_data_as_of,
            "stale_facts": safe_stale_facts,
            "conflicts": safe_conflicts,
            "corrections": safe_corrections,
        },
        "open_questions": [
            question for question in profile["quality"]["open_questions"]
            if question not in hidden_correction_questions
        ],
        "evidence_refs": evidence_refs,
        "profile_version": {
            "version_no": version.version_no,
            "profile_schema_version": version.profile_schema_version,
            "compiled_at": _json_value(version.compiled_at),
        },
    }


def _upsert_agent_context(db: Session, version: CustomerProfileVersion, now: datetime) -> None:
    context = _build_context(version)
    row = db.get(CustomerAgentContext, version.customer_id)
    values = {
        "profile_version_id": version.id,
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "context_json": context,
        "max_data_classification": "internal_business",
        "context_hash": _hash(context),
        "data_as_of": version.data_as_of,
        "built_at": now,
        "updated_at": now,
    }
    if row is None:
        db.add(CustomerAgentContext(customer_id=version.customer_id, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)


def _primary_product(profile: dict, *, safe_only: bool = False) -> str | None:
    distribution = profile["commercial"]["product_distribution"]
    if distribution:
        return distribution[0]["product_family"]
    for layer in ("confirmed", "observed", "expressed", "inferred"):
        for entry in profile["preferences"][layer]:
            if safe_only and not _safe_entry(entry):
                continue
            if entry["fact_key"].endswith(("product_family", "product_direction")):
                return str(entry["value"])
    return None


def _engagement_health(profile: dict) -> str:
    if profile["engagement"]["relationship_stage"] == "inactive":
        return "dormant"
    if profile["commercial"]["has_valid_order"]:
        return "active"
    if profile["engagement"]["current_needs"]:
        return "active"
    return "new" if profile["identity"]["identity_status"] == "provisional" else "unknown"


def _upsert_list_projection(db: Session, version: CustomerProfileVersion, now: datetime) -> None:
    profile = version.profile_json
    industry = profile["business"]["industry"]
    safe_industry = industry if industry is not None and _safe_entry(industry) else None
    global_dnc = any(
        item.get("risk_type") == "do_not_contact" and item.get("scope_type") == "global"
        for item in profile["risks"]["items"]
    )
    record_status = profile["identity"]["record_status"]
    identity_blocked = profile["identity"]["identity_status"] == "disputed"
    record_blocked = record_status in {"merged", "archived"}
    reason = (
        f"record_{record_status}"
        if record_blocked
        else "identity_disputed"
        if identity_blocked
        else "do_not_contact"
        if global_dnc
        else None
    )
    blocked = record_blocked or identity_blocked or global_dnc
    amount = Decimal(str(profile["commercial"]["valid_order_amount_usd"] or 0))
    commercial_score = min(Decimal("100"), amount / Decimal("1000")) if amount else None
    row = db.get(CustomerListProjection, version.customer_id)
    values = {
        "primary_industry": safe_industry["value"] if safe_industry else None,
        "primary_market": profile["business"]["market"],
        "acquisition_source": None,
        "primary_product_family": _primary_product(profile, safe_only=True),
        "commercial_value_score": commercial_score,
        "has_valid_order": profile["commercial"]["has_valid_order"],
        "valid_order_count": profile["commercial"]["valid_order_count"],
        "valid_order_amount_usd": amount,
        "last_order_at": (
            datetime.combine(
                date.fromisoformat(profile["commercial"]["last_order_at"]), time.min
            ) if profile["commercial"]["last_order_at"] else None
        ),
        "last_engagement_at": (
            datetime.fromisoformat(version.section_data_as_of["engagement"])
            if version.section_data_as_of.get("engagement")
            else None
        ),
        "engagement_health": _engagement_health(profile),
        "open_opportunity_count": len(profile["opportunities"]["open"]),
        "highest_opportunity_priority": None,
        "next_action_at": None,
        "global_claim_blocked": blocked,
        "global_claim_block_reason": reason,
        "claim_cooldown_until": None,
        "has_active_dnc": profile["risks"]["has_active_dnc"],
        "data_quality_score": Decimal(str(profile["quality"]["completeness"])),
        "profile_version_id": version.id,
        "compiled_at": now,
    }
    if row is None:
        db.add(CustomerListProjection(customer_id=version.customer_id, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)


def _normalized_terms(values) -> set[str]:
    return {
        str(value).strip().casefold()
        for value in (values or [])
        if str(value).strip()
    }


def _target_match_plan(version: CustomerProfileVersion, target: AcquisitionProfile) -> dict:
    profile = version.profile_json
    dimensions = []
    weighted = []
    evidence_ids: set[int] = set()
    qualification_evidence_ready = True
    raw_industry = profile["business"]["industry"]
    industry = (
        raw_industry
        if raw_industry is not None and _safe_entry(raw_industry)
        else None
    )
    industry_value = str(industry["value"]).casefold() if industry else None
    industries = _normalized_terms(target.target_industries)
    if industries:
        matched = industry_value in industries
        dimensions.append({"dimension": "industry", "weight": 50, "matched": matched})
        weighted.append((50, matched))
        if matched:
            evidence_ids.add(industry["fact_id"])
            qualification_evidence_ready = qualification_evidence_ready and bool(
                industry["verification_status"] == "verified"
                or industry["fact_layer"] == "confirmed"
            )
    countries = _normalized_terms(target.target_countries)
    if countries:
        matched = str(profile["business"]["market"] or "").casefold() in countries
        dimensions.append({"dimension": "market", "weight": 30, "matched": matched})
        weighted.append((30, matched))
        if matched:
            qualification_evidence_ready = qualification_evidence_ready and bool(
                profile["identity"]["identity_status"] == "verified"
            )
    products = _normalized_terms(target.products)
    if products:
        primary_product = str(_primary_product(profile, safe_only=True) or "").casefold()
        matched = primary_product in products
        dimensions.append({"dimension": "product", "weight": 20, "matched": matched})
        weighted.append((20, matched))
        if matched:
            matching_product_facts = []
            for layer in ("confirmed", "observed", "expressed", "inferred"):
                for entry in profile["preferences"][layer]:
                    if (
                        _safe_entry(entry)
                        and entry["fact_key"].endswith(
                            ("product_family", "product_direction")
                        )
                        and str(entry["value"]).casefold() == primary_product
                    ):
                        evidence_ids.add(entry["fact_id"])
                        matching_product_facts.append(entry)
            if matching_product_facts:
                qualification_evidence_ready = qualification_evidence_ready and any(
                    entry["verification_status"] == "verified"
                    or entry["fact_layer"] == "confirmed"
                    for entry in matching_product_facts
                )
            else:
                qualification_evidence_ready = qualification_evidence_ready and bool(
                    profile["commercial"]["has_valid_order"]
                    and profile["commercial"]["product_distribution"]
                )
    exclusions = _normalized_terms(target.exclusions)
    searchable = _canonical_json({
        "industry": industry_value,
        "market": profile["business"]["market"],
        "product": _primary_product(profile, safe_only=True),
    }).casefold()
    excluded = any(term in searchable for term in exclusions)
    denominator = sum(weight for weight, _matched in weighted)
    score = Decimal("0") if not denominator else (
        Decimal(sum(weight for weight, matched in weighted if matched))
        * Decimal("100") / Decimal(denominator)
    ).quantize(Decimal("0.01"))
    status = (
        "poor_fit"
        if excluded
        else "qualified"
        if score >= 70 and qualification_evidence_ready
        else "candidate"
    )
    reasons = {
        "schema_version": TARGET_MATCH_SCHEMA_VERSION,
        "profile_version_id": version.id,
        "dimensions": dimensions,
        "excluded": excluded,
    }
    fingerprint = _hash({
        "customer_id": version.customer_id,
        "target_profile_id": target.id,
        "target_profile": {
            "profile_key": target.profile_key,
            "target_countries": target.target_countries,
            "target_industries": target.target_industries,
            "products": target.products,
            "exclusions": target.exclusions,
        },
        "policy_version": TARGET_MATCH_POLICY_VERSION,
        "profile_fingerprint": version.profile_fingerprint,
        "score": _json_value(score),
        "status": status,
        "reasons": reasons,
    })
    return {
        "target_profile_id": target.id,
        "policy_version": TARGET_MATCH_POLICY_VERSION,
        "match_score": score,
        "score_reasons": reasons,
        "match_status": status,
        "evidence_fact_ids": sorted(evidence_ids),
        "match_fingerprint": fingerprint,
        "data_as_of": version.data_as_of,
        "expires_at": None,
    }


def _replace_target_matches(db: Session, version: CustomerProfileVersion, now: datetime) -> None:
    targets = db.query(AcquisitionProfile).filter(
        AcquisitionProfile.status == "active",
        AcquisitionProfile.deleted_at.is_(None),
    ).order_by(AcquisitionProfile.id).all()
    plans = [_target_match_plan(version, target) for target in targets]
    current_rows = db.query(CustomerTargetMatch).filter(
        CustomerTargetMatch.customer_id == version.customer_id,
        CustomerTargetMatch.is_current.is_(True),
    ).all()
    for row in current_rows:
        row.is_current = False
    for plan in plans:
        existing = db.query(CustomerTargetMatch).filter(
            CustomerTargetMatch.match_fingerprint == plan["match_fingerprint"]
        ).one_or_none()
        if existing is None:
            db.add(CustomerTargetMatch(
                customer_id=version.customer_id,
                is_current=True,
                computed_at=now,
                **plan,
            ))
        else:
            existing.is_current = True
            existing.computed_at = now


def _existing_projection_version(db: Session, name: str, customer_id: int) -> int | None:
    if name == "agent_context":
        row = db.get(CustomerAgentContext, customer_id)
        return row.profile_version_id if row else None
    if name == "list_projection":
        row = db.get(CustomerListProjection, customer_id)
        return row.profile_version_id if row else None
    rows = db.query(CustomerTargetMatch).filter(
        CustomerTargetMatch.customer_id == customer_id,
        CustomerTargetMatch.is_current.is_(True),
    ).all()
    versions = {
        (row.score_reasons or {}).get("profile_version_id")
        for row in rows
        if (row.score_reasons or {}).get("profile_version_id") is not None
    }
    return next(iter(versions)) if len(versions) == 1 else None


def _target_matches_are_current(db: Session, version: CustomerProfileVersion) -> bool:
    targets = db.query(AcquisitionProfile).filter(
        AcquisitionProfile.status == "active",
        AcquisitionProfile.deleted_at.is_(None),
    ).order_by(AcquisitionProfile.id).all()
    expected = {
        target.id: _target_match_plan(version, target)["match_fingerprint"]
        for target in targets
    }
    rows = db.query(CustomerTargetMatch).filter(
        CustomerTargetMatch.customer_id == version.customer_id,
        CustomerTargetMatch.is_current.is_(True),
    ).all()
    actual = {row.target_profile_id: row.match_fingerprint for row in rows}
    return bool(
        expected == actual
        and all(
            (row.score_reasons or {}).get("profile_version_id") == version.id
            for row in rows
        )
    )


def _projection_state(
    db: Session,
    name: str,
    customer_id: int,
    target_version_id: int,
) -> ProjectionState:
    current_id = _existing_projection_version(db, name, customer_id)
    is_current = current_id == target_version_id
    if name == "target_matches":
        version = db.get(CustomerProfileVersion, target_version_id)
        is_current = bool(
            version is not None and _target_matches_are_current(db, version)
        )
        if is_current:
            current_id = target_version_id
    return ProjectionState(
        status="current" if is_current else "stale",
        profile_version_id=current_id,
        target_profile_version_id=target_version_id,
        error_code=None,
    )


def _build_projection(
    db: Session,
    *,
    name: str,
    version: CustomerProfileVersion,
    now: datetime,
    observer: CompileObserver | None,
    builder: Callable[[Session, CustomerProfileVersion, datetime], None],
) -> ProjectionState:
    previous_version_id = _existing_projection_version(db, name, version.customer_id)
    try:
        with db.begin_nested():
            _notify(
                observer,
                f"before_{name}_projection",
                db,
                version.customer_id,
                version.input_seq,
            )
            builder(db, version, now)
            db.flush()
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning(
            "Customer %s %s projection failed: %s",
            version.customer_id,
            name,
            error_type,
        )
        print(
            f"Customer {version.customer_id} {name} projection failed: {error_type}",
            flush=True,
        )
        return ProjectionState(
            status="stale" if previous_version_id is not None else "failed",
            profile_version_id=previous_version_id,
            target_profile_version_id=version.id,
            error_code="PROJECTION_BUILD_FAILED",
        )
    return ProjectionState(
        status="current",
        profile_version_id=version.id,
        target_profile_version_id=version.id,
        error_code=None,
    )


def _project_published_version(
    db: Session,
    version: CustomerProfileVersion,
    now: datetime,
    observer: CompileObserver | None,
) -> dict[str, ProjectionState]:
    return {
        "agent_context": _build_projection(
            db,
            name="agent_context",
            version=version,
            now=now,
            observer=observer,
            builder=_upsert_agent_context,
        ),
        "list_projection": _build_projection(
            db,
            name="list_projection",
            version=version,
            now=now,
            observer=observer,
            builder=_upsert_list_projection,
        ),
        "target_matches": _build_projection(
            db,
            name="target_matches",
            version=version,
            now=now,
            observer=observer,
            builder=_replace_target_matches,
        ),
    }


def _repair_stale_projections(
    db: Session,
    version: CustomerProfileVersion,
    now: datetime,
    observer: CompileObserver | None,
    states: Mapping[str, ProjectionState],
) -> dict[str, ProjectionState]:
    builders = {
        "agent_context": _upsert_agent_context,
        "list_projection": _upsert_list_projection,
        "target_matches": _replace_target_matches,
    }
    repaired: dict[str, ProjectionState] = {}
    for name, state in states.items():
        if state.status == "current":
            repaired[name] = state
            continue
        repaired[name] = _build_projection(
            db,
            name=name,
            version=version,
            now=now,
            observer=observer,
            builder=builders[name],
        )
    return repaired


def _current_version_after_account_lock(
    db: Session,
    account: CustomerAccount,
) -> CustomerProfileVersion | None:
    if account.current_profile_version_id is None:
        return None
    return db.query(CustomerProfileVersion).filter(
        CustomerProfileVersion.id == account.current_profile_version_id,
        CustomerProfileVersion.customer_id == account.id,
    ).populate_existing().with_for_update().one_or_none()


def compile_customer_profile(
    session_factory: Callable[[], Session],
    customer_id: int,
    *,
    trigger_event_id: int | None = None,
    agent_run_id: int | None = None,
    observer: CompileObserver | None = None,
) -> ProfileCompileResult:
    """Compile one profile in compiler-owned, retry-isolated transactions."""
    if type(customer_id) is not int or customer_id <= 0:
        raise ProfileCompileError("CUSTOMER_ID_INVALID", "customer_id must be a positive integer")
    if not callable(session_factory):
        raise ProfileCompileError(
            "SESSION_FACTORY_INVALID",
            "session_factory must create a fresh Session",
        )
    if trigger_event_id is not None and (
        type(trigger_event_id) is not int or trigger_event_id <= 0
    ):
        raise ProfileCompileError(
            "TRIGGER_EVENT_INVALID",
            "trigger_event_id must be a positive integer",
        )

    for retry_count in range(MAX_CAS_RETRIES):
        with session_factory() as snapshot_db:
            with snapshot_db.begin():
                account = snapshot_db.get(CustomerAccount, customer_id)
                if account is None:
                    raise ProfileCompileError(
                        "CUSTOMER_NOT_FOUND",
                        "customer does not exist",
                    )
                if trigger_event_id is not None:
                    trigger_event = snapshot_db.get(CustomerEvent, trigger_event_id)
                    if trigger_event is None or trigger_event.customer_id != customer_id:
                        raise ProfileCompileError(
                            "TRIGGER_EVENT_CUSTOMER_MISMATCH",
                            "trigger event does not belong to customer",
                        )
                base_seq = int(account.profile_input_seq)
                now = beijing_now()
                snapshot = _load_snapshot(snapshot_db, account, now)
                previous_hashes = None
                if account.current_profile_version_id is not None:
                    previous_snapshot = snapshot_db.get(
                        CustomerProfileVersion,
                        account.current_profile_version_id,
                    )
                    if previous_snapshot is not None:
                        previous_hashes = dict(previous_snapshot.section_hashes)
                _notify(observer, "after_snapshot", snapshot_db, customer_id, base_seq)
        (
            profile,
            section_data_as_of,
            evidence_ids,
            data_as_of,
            fact_fingerprints,
            effective_fact_fingerprints,
        ) = _build_profile(snapshot, now)
        hashes = _section_hashes(profile, fact_fingerprints)
        semantic_profile = _semantic_value(profile, fact_fingerprints)
        profile_fingerprint = _hash({
            "profile_schema_version": PROFILE_SCHEMA_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "compiler_version": COMPILER_VERSION,
            "profile": semantic_profile,
            "section_data_as_of": section_data_as_of,
            "fact_fingerprints": effective_fact_fingerprints,
        })
        cas_mismatch = False
        result = None
        with session_factory() as publish_db:
            with publish_db.begin():
                phase = (
                    "before_no_change_cas"
                    if previous_hashes == hashes
                    else "before_publish_cas"
                )
                _notify(observer, phase, publish_db, customer_id, base_seq)
                locked = publish_db.query(CustomerAccount).filter(
                    CustomerAccount.id == customer_id
                ).populate_existing().with_for_update().one()
                if int(locked.profile_input_seq) != base_seq:
                    cas_mismatch = True
                else:
                    previous = _current_version_after_account_lock(publish_db, locked)
                    if previous is not None and previous.section_hashes == hashes:
                        states = {
                            name: _projection_state(
                                publish_db,
                                name,
                                customer_id,
                                previous.id,
                            )
                            for name in (
                                "agent_context",
                                "list_projection",
                                "target_matches",
                            )
                        }
                        projections = _repair_stale_projections(
                            publish_db,
                            previous,
                            beijing_now(),
                            observer,
                            states,
                        )
                        result = ProfileCompileResult(
                            customer_id=customer_id,
                            profile_version_id=previous.id,
                            version_no=previous.version_no,
                            created=False,
                            retry_count=retry_count,
                            projections=projections,
                        )
                    else:
                        latest_version_no = publish_db.query(
                            func.max(CustomerProfileVersion.version_no)
                        ).filter(
                            CustomerProfileVersion.customer_id == customer_id
                        ).scalar() or 0
                        compiled_at = beijing_now()
                        version = CustomerProfileVersion(
                            customer_id=customer_id,
                            version_no=int(latest_version_no) + 1,
                            profile_schema_version=PROFILE_SCHEMA_VERSION,
                            canonicalization_version=CANONICALIZATION_VERSION,
                            input_seq=base_seq,
                            profile_json=profile,
                            section_hashes=hashes,
                            section_data_as_of=section_data_as_of,
                            evidence_fact_ids=evidence_ids,
                            change_summary=_change_summary(previous, hashes, profile),
                            compiler_version=COMPILER_VERSION,
                            profile_fingerprint=profile_fingerprint,
                            data_as_of=data_as_of,
                            trigger_event_id=trigger_event_id,
                            agent_run_id=agent_run_id,
                            compiled_at=compiled_at,
                            created_at=compiled_at,
                        )
                        publish_db.add(version)
                        publish_db.flush()
                        locked.current_profile_version_id = version.id
                        locked.profile_completeness = Decimal(
                            str(profile["quality"]["completeness"])
                        )
                        locked.data_as_of = data_as_of
                        locked.profile_compiled_at = compiled_at
                        locked.updated_at = compiled_at
                        publish_db.flush()
                        projections = _project_published_version(
                            publish_db,
                            version,
                            compiled_at,
                            observer,
                        )
                        result = ProfileCompileResult(
                            customer_id=customer_id,
                            profile_version_id=version.id,
                            version_no=version.version_no,
                            created=True,
                            retry_count=retry_count,
                            projections=projections,
                        )
        if cas_mismatch:
            continue
        if result is not None:
            return result

    raise ProfileCompileError(
        "PROFILE_INPUT_CHANGED_REPEATEDLY",
        "customer profile inputs changed during every CAS attempt",
    )
