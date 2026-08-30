"""Append-only source, fact, evidence, conflict, and customer event services."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.contracts import (
    DATA_CLASSIFICATIONS,
    FACT_REGISTRY,
    SOURCE_REGISTRY,
    DataClassification,
    allowed_relationship_transition,
    source_policy,
    validate_registered_fact,
)
from app.customer.identity_service import CustomerDomainError
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactRelationship,
    CustomerConversation,
    CustomerEvent,
    CustomerFact,
    CustomerFactConflict,
    CustomerFactEvidenceLink,
    CustomerMessage,
    CustomerOrder,
    CustomerSourceRecord,
)


_CLASSIFICATION_ORDER = (
    DataClassification.PUBLIC_BUSINESS.value,
    DataClassification.INTERNAL_BUSINESS.value,
    DataClassification.PERSONAL_CONTACT.value,
    DataClassification.RESTRICTED_INTERNAL.value,
)
_FACT_LAYERS = {"source", "expressed", "observed", "inferred", "confirmed"}
_FACT_STATUSES = {"unverified", "candidate", "verified", "disputed", "rejected", "superseded"}
_ACTIVE_FACT_STATUSES = {"unverified", "candidate", "verified", "disputed"}
_VALUE_TYPES = {"string", "number", "boolean", "date", "datetime", "list", "object"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _sha256(parts: Iterable[object]) -> str:
    encoded = "\x1f".join("" if item is None else str(item) for item in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise CustomerDomainError("PAYLOAD_INVALID") from exc


def _classification_max(*values: str | DataClassification | None) -> str:
    normalized: list[str] = []
    for value in values:
        if value is None:
            continue
        item = value.value if isinstance(value, DataClassification) else value
        if item not in DATA_CLASSIFICATIONS:
            raise CustomerDomainError("DATA_CLASSIFICATION_INVALID")
        normalized.append(item)
    if not normalized:
        raise CustomerDomainError("DATA_CLASSIFICATION_INVALID")
    return max(normalized, key=_CLASSIFICATION_ORDER.index)


def _business_time(value: datetime | None, *, default_now: bool = False) -> datetime | None:
    if value is None:
        return beijing_now() if default_now else None
    return to_beijing_naive(value)


def _account_for_update(db: Session, customer_id: int) -> CustomerAccount:
    account = (
        db.query(CustomerAccount)
        .filter(CustomerAccount.id == customer_id, CustomerAccount.record_status == "active")
        .with_for_update()
        .one_or_none()
    )
    if account is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    return account


def _bump_account(db: Session, customer_id: int) -> CustomerAccount:
    account = _account_for_update(db, customer_id)
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = beijing_now()
    return account


def _external_key_hash(
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_record_id: str,
) -> str:
    return _sha256((
        "source_record_key_v1",
        source_system,
        source_account_key,
        source_entity_type,
        external_record_id,
    ))


def append_source_record(
    db: Session,
    *,
    customer_id: int | None,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_record_id: str,
    payload_schema_version: str,
    payload_json: Mapping | Sequence,
    source_version: str | None = None,
    publisher_key: str | None = None,
    source_family_key: str | None = None,
    source_url: str | None = None,
    data_classification: str | None = None,
    visibility_scope: str = "customer_team",
    classification_reason: str | None = None,
    occurred_at: datetime | None = None,
    captured_at: datetime | None = None,
    sync_cursor: str | None = None,
    processing_status: str = "pending",
    processing_error_code: str | None = None,
    processing_error_message: str | None = None,
) -> CustomerSourceRecord:
    """Append one immutable normalized raw-source version.

    An unbound source record is allowed because ingestion precedes identity
    resolution.  It has no profile sequence to increment; binding it inside
    ``resolve_business_context`` is part of that customer's single identity
    mutation and increments the newly-created account exactly once.
    """
    try:
        policy = source_policy(source_system, source_entity_type)
    except KeyError as exc:
        raise CustomerDomainError("SOURCE_NOT_REGISTERED") from exc
    if not all(isinstance(value, str) and value.strip() for value in (
        source_account_key,
        external_record_id,
        payload_schema_version,
    )):
        raise CustomerDomainError("SOURCE_INPUT_INVALID")
    if visibility_scope not in {"all_authorized", "customer_team", "management"}:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    if processing_status not in {"pending", "processed", "quarantined", "superseded"}:
        raise CustomerDomainError("SOURCE_STATUS_INVALID")
    account = _account_for_update(db, customer_id) if customer_id is not None else None

    payload_copy = copy.deepcopy(payload_json)
    canonical_payload = _canonical_json(payload_copy)
    content_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    key_hash = _external_key_hash(
        source_system,
        source_account_key,
        source_entity_type,
        external_record_id,
    )
    existing = (
        db.query(CustomerSourceRecord)
        .filter(
            CustomerSourceRecord.external_record_key_hash == key_hash,
            CustomerSourceRecord.content_hash == content_hash,
        )
        .one_or_none()
    )
    if existing is not None:
        if customer_id is not None and existing.customer_id not in {None, customer_id}:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        if customer_id is not None and existing.customer_id is None:
            existing.customer_id = customer_id
            _bump_account(db, customer_id)
            db.flush()
        return existing

    effective_classification = _classification_max(
        policy.default_classification,
        data_classification,
    )
    captured = _business_time(captured_at, default_now=True)
    row = CustomerSourceRecord(
        customer_id=customer_id,
        source_system=source_system,
        source_account_key=source_account_key,
        publisher_key=publisher_key,
        source_family_key=source_family_key,
        authority_level=policy.authority,
        source_entity_type=source_entity_type,
        external_record_id=external_record_id,
        external_record_key_hash=key_hash,
        source_version=source_version,
        source_url=source_url,
        data_classification=effective_classification,
        visibility_scope=visibility_scope,
        classification_reason=(
            classification_reason
            or f"source_registry:{policy.registry_version}:{source_system}/{source_entity_type}"
        ),
        payload_schema_version=payload_schema_version,
        payload_json=payload_copy,
        content_hash=content_hash,
        occurred_at=_business_time(occurred_at),
        captured_at=captured,
        sync_cursor=sync_cursor,
        processing_status=processing_status,
        processing_error_code=processing_error_code,
        processing_error_message=processing_error_message,
        created_at=captured,
    )
    db.add(row)
    db.flush()
    if account is not None:
        account.profile_input_seq = int(account.profile_input_seq) + 1
        account.updated_at = beijing_now()
        db.flush()
    return row


def _validate_value(value_type: str, value: object) -> object:
    if value_type not in _VALUE_TYPES:
        raise CustomerDomainError("FACT_VALUE_INVALID")
    valid = False
    normalized = value
    if value_type == "string":
        valid = isinstance(value, str)
    elif value_type == "number":
        valid = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
        if valid and isinstance(value, Decimal):
            normalized = format(value, "f")
    elif value_type == "boolean":
        valid = type(value) is bool
    elif value_type == "date":
        if isinstance(value, datetime):
            valid = False
        elif isinstance(value, date):
            valid = True
            normalized = value.isoformat()
        elif isinstance(value, str):
            try:
                normalized = date.fromisoformat(value).isoformat()
                valid = True
            except ValueError:
                pass
    elif value_type == "datetime":
        if isinstance(value, datetime):
            valid = True
            normalized = _business_time(value).isoformat()
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
                if "T" not in value and " " not in value:
                    raise ValueError
                normalized = _business_time(parsed).isoformat()
                valid = True
            except ValueError:
                pass
    elif value_type == "list":
        valid = isinstance(value, list)
    elif value_type == "object":
        valid = isinstance(value, dict)
    if not valid:
        raise CustomerDomainError("FACT_VALUE_INVALID")
    _canonical_json(normalized)
    return normalized


def _validate_fact_layer(fact_key: str, fact_layer: str) -> None:
    if fact_layer not in _FACT_LAYERS:
        raise CustomerDomainError("FACT_LAYER_INVALID")
    for layer in ("expressed", "observed", "inferred", "confirmed"):
        if f".{layer}." in fact_key and fact_layer != layer:
            raise CustomerDomainError("FACT_LAYER_INVALID")
    if fact_key == "commercial.has_valid_order" and fact_layer != "observed":
        raise CustomerDomainError("FACT_LAYER_INVALID")
    if fact_key == "business.industry" and fact_layer not in {"source", "confirmed"}:
        raise CustomerDomainError("FACT_LAYER_INVALID")


def _validate_subject(
    db: Session,
    customer_id: int,
    subject_type: str,
    subject_id: int | None,
) -> None:
    if subject_type == "customer":
        if subject_id not in {None, customer_id}:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return
    if subject_id is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if subject_type == "contact":
        contact = db.get(CustomerContact, subject_id)
        relation = db.query(CustomerContactRelationship.id).filter(
            CustomerContactRelationship.customer_id == customer_id,
            CustomerContactRelationship.contact_id == subject_id,
            CustomerContactRelationship.effective_to.is_(None),
        ).first()
        if contact is None or relation is None:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return
    if subject_type == "conversation":
        row = db.get(CustomerConversation, subject_id)
        if row is None or row.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return
    if subject_type == "order":
        row = db.get(CustomerOrder, subject_id)
        if row is None or row.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return
    # Opportunity ownership is enabled atomically when Task 7 registers its model.
    raise CustomerDomainError("FACT_SUBJECT_INVALID")


def _evidence_classifications(
    db: Session,
    customer_id: int,
    evidence: Mapping,
) -> list[str]:
    classifications: list[str] = []
    for field in ("source_record_ids", "message_ids", "order_ids", "fact_ids"):
        values = evidence.get(field, [])
        if not isinstance(values, list) or any(type(item) is not int for item in values):
            raise CustomerDomainError("FACT_EVIDENCE_INVALID")
        for item_id in set(values):
            if field == "source_record_ids":
                row = db.get(CustomerSourceRecord, item_id)
                if row is None or row.customer_id != customer_id:
                    raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
                classifications.append(row.data_classification)
            elif field == "fact_ids":
                row = db.get(CustomerFact, item_id)
                if row is None or row.customer_id != customer_id:
                    raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
                classifications.append(row.data_classification)
            elif field == "message_ids":
                row = db.get(CustomerMessage, item_id)
                conversation = db.get(CustomerConversation, row.conversation_id) if row else None
                source = db.get(CustomerSourceRecord, row.source_record_id) if row else None
                if conversation is None or conversation.customer_id != customer_id or source is None:
                    raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
                classifications.append(source.data_classification)
            else:
                row = db.get(CustomerOrder, item_id)
                source = db.get(CustomerSourceRecord, row.source_record_id) if row else None
                if row is None or row.customer_id != customer_id or source is None:
                    raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
                classifications.append(source.data_classification)
    return classifications


def append_fact(
    db: Session,
    *,
    customer_id: int,
    subject_type: str,
    fact_key: str,
    value_type: str,
    value: object,
    fact_layer: str,
    verification_status: str,
    confidence: Decimal | float | int,
    confidence_method_version: str,
    confidence_components: Mapping,
    source_system: str,
    source_entity_type: str,
    observed_at: datetime,
    subject_id: int | None = None,
    value_metadata: Mapping | None = None,
    data_classification: str | None = None,
    visibility_scope: str = "customer_team",
    classification_reason: str | None = None,
    source_record_id: int | None = None,
    evidence: Mapping | None = None,
    agent_run_id: int | None = None,
    rule_version: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    expires_at: datetime | None = None,
    supersedes_fact_id: int | None = None,
    reviewed_by: int | None = None,
    reviewed_at: datetime | None = None,
) -> CustomerFact:
    """Append a registered, typed, temporally-scoped customer fact."""
    account = _account_for_update(db, customer_id)
    registration = FACT_REGISTRY.get(fact_key)
    if registration is None:
        raise CustomerDomainError("FACT_NOT_REGISTERED")
    source_key = (source_system, source_entity_type)
    if source_key not in SOURCE_REGISTRY or source_key not in registration.allowed_sources:
        raise CustomerDomainError("FACT_SOURCE_NOT_ALLOWED")
    if source_system not in {"manual", "agent"} and source_record_id is None:
        raise CustomerDomainError("FACT_SOURCE_RECORD_REQUIRED")
    registered_classification = validate_registered_fact(
        fact_key,
        source_system,
        source_entity_type,
    )
    if registered_classification is DataClassification.RESTRICTED_INTERNAL and (
        registration.data_classification is not DataClassification.RESTRICTED_INTERNAL
    ):
        raise CustomerDomainError("FACT_SOURCE_NOT_ALLOWED")
    _validate_fact_layer(fact_key, fact_layer)
    if verification_status not in _FACT_STATUSES:
        raise CustomerDomainError("FACT_STATUS_INVALID")
    if visibility_scope not in {"all_authorized", "customer_team", "management"}:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    confidence_value = Decimal(str(confidence))
    if confidence_value < 0 or confidence_value > 1:
        raise CustomerDomainError("FACT_CONFIDENCE_INVALID")
    if (
        not confidence_method_version
        or not isinstance(confidence_components, Mapping)
        or not confidence_components
    ):
        raise CustomerDomainError("FACT_CONFIDENCE_INVALID")
    _canonical_json(confidence_components)
    _validate_subject(db, customer_id, subject_type, subject_id)
    normalized_value = _validate_value(value_type, value)

    source_record = db.get(CustomerSourceRecord, source_record_id) if source_record_id else None
    if source_record_id is not None and (
        source_record is None
        or source_record.customer_id != customer_id
        or source_record.source_system != source_system
        or source_record.source_entity_type != source_entity_type
    ):
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if supersedes_fact_id is not None:
        superseded = db.get(CustomerFact, supersedes_fact_id)
        if superseded is None or superseded.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")

    observed = _business_time(observed_at)
    if observed is None:
        raise CustomerDomainError("FACT_TIME_INVALID")
    effective_start = _business_time(effective_from) or observed
    effective_end = _business_time(effective_to)
    expiry = _business_time(expires_at)
    if effective_end is not None and effective_end < effective_start:
        raise CustomerDomainError("FACT_TIME_INVALID")
    if expiry is None and registration.ttl_days is not None:
        expiry = observed + timedelta(days=registration.ttl_days)
    if expiry is not None and expiry < observed:
        raise CustomerDomainError("FACT_TIME_INVALID")

    value_json = {"value": normalized_value}
    if value_metadata:
        for key in ("unit", "currency", "language"):
            if key in value_metadata:
                value_json[key] = value_metadata[key]
    evidence_json = copy.deepcopy(dict(evidence or {}))
    evidence_json.setdefault("source_record_ids", [source_record_id] if source_record_id else [])
    _canonical_json(evidence_json)
    evidence_classifications = _evidence_classifications(db, customer_id, evidence_json)
    if fact_layer == "inferred":
        supporting_ids = evidence_json.get("fact_ids")
        if (
            not rule_version
            or not isinstance(supporting_ids, list)
            or not supporting_ids
            or any(type(item) is not int for item in supporting_ids)
        ):
            raise CustomerDomainError("FACT_INFERENCE_EVIDENCE_REQUIRED")
        if db.query(CustomerFact.id).filter(
            CustomerFact.customer_id == customer_id,
            CustomerFact.id.in_(set(supporting_ids)),
        ).count() != len(set(supporting_ids)):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    effective_classification = _classification_max(
        registered_classification,
        source_record.data_classification if source_record is not None else None,
        data_classification,
        *evidence_classifications,
    )
    fingerprint = _sha256((
        "fact_v1",
        customer_id,
        subject_type,
        subject_id or "",
        fact_key,
        fact_layer,
        _canonical_json(value_json),
        source_record.content_hash if source_record is not None else _canonical_json(evidence_json),
        rule_version or "",
        observed.isoformat(),
    ))
    existing = db.query(CustomerFact).filter(
        CustomerFact.fact_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        if existing.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return existing

    created = beijing_now()
    row = CustomerFact(
        customer_id=customer_id,
        subject_type=subject_type,
        subject_id=subject_id,
        fact_key=fact_key,
        value_type=value_type,
        value_json=value_json,
        fact_layer=fact_layer,
        verification_status=verification_status,
        confidence=confidence_value,
        confidence_method_version=confidence_method_version,
        confidence_components_json=copy.deepcopy(dict(confidence_components)),
        data_classification=effective_classification,
        visibility_scope=visibility_scope,
        classification_reason=(
            classification_reason
            or f"fact_registry:{fact_key};source:{source_system}/{source_entity_type}"
        ),
        source_record_id=source_record_id,
        evidence_json=evidence_json,
        agent_run_id=agent_run_id,
        rule_version=rule_version,
        fact_fingerprint=fingerprint,
        effective_from=effective_start,
        effective_to=effective_end,
        observed_at=observed,
        expires_at=expiry,
        supersedes_fact_id=supersedes_fact_id,
        reviewed_by=reviewed_by,
        reviewed_at=_business_time(reviewed_at),
        created_at=created,
    )
    db.add(row)
    db.flush()
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = created
    db.flush()
    return row


def _evidence_target(
    db: Session,
    *,
    evidence_kind: str,
    source_record_id: int | None,
    message_id: int | None,
    order_id: int | None,
    supporting_fact_id: int | None,
) -> tuple[object, str, int]:
    supplied = {
        "source_record": source_record_id,
        "message": message_id,
        "order": order_id,
        "fact": supporting_fact_id,
    }
    if evidence_kind not in supplied or supplied[evidence_kind] is None:
        raise CustomerDomainError("EVIDENCE_REFERENCE_INVALID")
    if sum(value is not None for value in supplied.values()) != 1:
        raise CustomerDomainError("EVIDENCE_REFERENCE_INVALID")
    target_id = supplied[evidence_kind]
    if evidence_kind == "source_record":
        target = db.get(CustomerSourceRecord, target_id)
        expected_hash = target.content_hash if target is not None else ""
        customer_id = target.customer_id if target is not None else None
    elif evidence_kind == "message":
        target = db.get(CustomerMessage, target_id)
        expected_hash = target.content_hash if target is not None else ""
        conversation = db.get(CustomerConversation, target.conversation_id) if target is not None else None
        customer_id = conversation.customer_id if conversation is not None else None
    elif evidence_kind == "order":
        target = db.get(CustomerOrder, target_id)
        expected_hash = target.source_hash if target is not None else ""
        customer_id = target.customer_id if target is not None else None
    else:
        target = db.get(CustomerFact, target_id)
        expected_hash = target.fact_fingerprint if target is not None else ""
        customer_id = target.customer_id if target is not None else None
    if target is None or customer_id is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    return target, expected_hash, customer_id


def link_fact_evidence(
    db: Session,
    *,
    fact_id: int,
    evidence_kind: str,
    relation_type: str,
    evidence_content_hash: str,
    locator: Mapping,
    source_record_id: int | None = None,
    message_id: int | None = None,
    order_id: int | None = None,
    supporting_fact_id: int | None = None,
    excerpt_text: str | None = None,
    data_classification: str | None = None,
) -> CustomerFactEvidenceLink:
    """Append an exact immutable evidence locator for one fact."""
    fact = db.get(CustomerFact, fact_id)
    if fact is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    account = _account_for_update(db, fact.customer_id)
    if relation_type not in {"supports", "contradicts"}:
        raise CustomerDomainError("EVIDENCE_RELATION_INVALID")
    if not isinstance(locator, Mapping) or not locator:
        raise CustomerDomainError("EVIDENCE_LOCATOR_INVALID")
    locator_json = copy.deepcopy(dict(locator))
    _canonical_json(locator_json)
    if not isinstance(evidence_content_hash, str) or not _HEX64.fullmatch(evidence_content_hash):
        raise CustomerDomainError("EVIDENCE_HASH_MISMATCH")
    target, expected_hash, evidence_customer_id = _evidence_target(
        db,
        evidence_kind=evidence_kind,
        source_record_id=source_record_id,
        message_id=message_id,
        order_id=order_id,
        supporting_fact_id=supporting_fact_id,
    )
    if evidence_customer_id != fact.customer_id:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if supporting_fact_id == fact_id:
        raise CustomerDomainError("EVIDENCE_REFERENCE_INVALID")
    if evidence_content_hash != expected_hash:
        raise CustomerDomainError("EVIDENCE_HASH_MISMATCH")
    target_classification = getattr(target, "data_classification", None)
    effective_classification = _classification_max(
        fact.data_classification,
        target_classification,
        data_classification,
    )
    target_id = {
        "source_record": source_record_id,
        "message": message_id,
        "order": order_id,
        "fact": supporting_fact_id,
    }[evidence_kind]
    fingerprint = _sha256((
        "fact_evidence_v1",
        fact.id,
        relation_type,
        evidence_kind,
        target_id,
        evidence_content_hash,
        _canonical_json(locator_json),
    ))
    existing = db.query(CustomerFactEvidenceLink).filter(
        CustomerFactEvidenceLink.evidence_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        return existing
    row = CustomerFactEvidenceLink(
        customer_id=fact.customer_id,
        fact_id=fact.id,
        relation_type=relation_type,
        evidence_kind=evidence_kind,
        source_record_id=source_record_id,
        message_id=message_id,
        order_id=order_id,
        supporting_fact_id=supporting_fact_id,
        evidence_content_hash=evidence_content_hash,
        locator_json=locator_json,
        excerpt_text=excerpt_text,
        data_classification=effective_classification,
        evidence_fingerprint=fingerprint,
        created_at=beijing_now(),
    )
    db.add(row)
    db.flush()
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = beijing_now()
    db.flush()
    return row


def _facts_temporally_overlap(left: CustomerFact, right: CustomerFact) -> bool:
    left_start = left.effective_from or left.observed_at
    right_start = right.effective_from or right.observed_at
    left_end = left.effective_to or datetime.max
    right_end = right.effective_to or datetime.max
    return left_start <= right_end and right_start <= left_end


def _fact_is_current(row: CustomerFact, now: datetime) -> bool:
    start = row.effective_from or row.observed_at
    return bool(
        row.verification_status in _ACTIVE_FACT_STATUSES
        and start <= now
        and (row.effective_to is None or row.effective_to >= now)
        and (row.expires_at is None or row.expires_at > now)
    )


def open_fact_conflict(
    db: Session,
    left_fact_id: int,
    right_fact_id: int,
    *,
    detection_rule_version: str,
    conflict_type: str = "contradictory",
    visibility_scope: str = "customer_team",
) -> CustomerFactConflict:
    """Persist an incompatible active fact pair without selecting a winner."""
    if left_fact_id == right_fact_id:
        raise CustomerDomainError("FACTS_NOT_IN_CONFLICT")
    first_id, second_id = sorted((left_fact_id, right_fact_id))
    left = db.get(CustomerFact, first_id)
    right = db.get(CustomerFact, second_id)
    if left is None or right is None or left.customer_id != right.customer_id:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    account = _account_for_update(db, left.customer_id)
    left_registration = FACT_REGISTRY.get(left.fact_key)
    right_registration = FACT_REGISTRY.get(right.fact_key)
    now = beijing_now()
    if (
        left_registration is None
        or right_registration is None
        or left_registration.conflict_key != right_registration.conflict_key
        or not _fact_is_current(left, now)
        or not _fact_is_current(right, now)
        or left.value_json == right.value_json
        or not _facts_temporally_overlap(left, right)
    ):
        raise CustomerDomainError("FACTS_NOT_IN_CONFLICT")
    if conflict_type not in {"contradictory", "ambiguous", "temporal_overlap", "identity_collision"}:
        raise CustomerDomainError("FACT_CONFLICT_TYPE_INVALID")
    if not detection_rule_version:
        raise CustomerDomainError("FACT_CONFLICT_RULE_INVALID")
    conflict_key = left_registration.conflict_key
    fingerprint = _sha256((
        "fact_conflict_v1",
        left.customer_id,
        conflict_key,
        first_id,
        second_id,
        detection_rule_version,
    ))
    existing = db.query(CustomerFactConflict).filter(
        CustomerFactConflict.conflict_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        return existing
    row = CustomerFactConflict(
        customer_id=left.customer_id,
        conflict_key=conflict_key,
        left_fact_id=first_id,
        right_fact_id=second_id,
        conflict_type=conflict_type,
        data_classification=_classification_max(
            left.data_classification,
            right.data_classification,
        ),
        visibility_scope=visibility_scope,
        detection_rule_version=detection_rule_version,
        conflict_fingerprint=fingerprint,
        status="open",
        detected_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = now
    db.flush()
    return row


def append_customer_event(
    db: Session,
    *,
    customer_id: int,
    event_type: str,
    event_source: str,
    event_title: str,
    event_payload: Mapping,
    occurred_at: datetime,
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    event_summary: str | None = None,
    importance: str = "normal",
    data_classification: str = "internal_business",
    visibility_scope: str = "customer_team",
    classification_reason: str | None = None,
    evidence_fact_ids: Sequence[int] = (),
    actor_user_id: int | None = None,
    target_relationship_stage: str | None = None,
    transition_trigger: str | None = None,
    transition_condition_met: bool = False,
    has_primary_assignment: bool = False,
    has_open_opportunity: bool = False,
) -> CustomerEvent:
    """Append one event and apply an allowed relationship transition atomically."""
    account = _account_for_update(db, customer_id)
    if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
        raise CustomerDomainError("EVENT_TYPE_INVALID")
    if not event_source or not event_title or not isinstance(event_payload, Mapping):
        raise CustomerDomainError("EVENT_INPUT_INVALID")
    if importance not in {"critical", "high", "normal", "low"}:
        raise CustomerDomainError("EVENT_IMPORTANCE_INVALID")
    if visibility_scope not in {"all_authorized", "customer_team", "management"}:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    classification = _classification_max(data_classification)
    payload = copy.deepcopy(dict(event_payload))
    _canonical_json(payload)
    occurred = _business_time(occurred_at)
    if occurred is None:
        raise CustomerDomainError("EVENT_TIME_INVALID")
    fact_ids = sorted(set(int(item) for item in evidence_fact_ids))
    if fact_ids:
        count = db.query(CustomerFact.id).filter(
            CustomerFact.customer_id == customer_id,
            CustomerFact.id.in_(fact_ids),
        ).count()
        if count != len(fact_ids):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    fingerprint = _sha256((
        "customer_event_v1",
        customer_id,
        event_type,
        event_source,
        source_ref_type or "",
        source_ref_id or "",
        occurred.isoformat(),
    ))
    existing = db.query(CustomerEvent).filter(
        CustomerEvent.event_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        return existing

    apply_transition = False
    if target_relationship_stage is not None:
        if transition_trigger is None:
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        allowed = allowed_relationship_transition(
            account.relationship_stage,
            target_relationship_stage,
            transition_trigger,
            transition_condition_met,
            has_primary_assignment=has_primary_assignment,
            has_open_opportunity=has_open_opportunity,
        )
        historical_inactive_replay = (
            account.relationship_stage == "inactive"
            and target_relationship_stage == "active_customer"
            and transition_trigger in {"historical_order_replay", "valid_order"}
            and transition_condition_met is True
            and occurred <= account.relationship_stage_changed_at
        )
        if not allowed and not historical_inactive_replay:
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        # Timestamp, not the caller-provided label, decides whether an order
        # happened after manual inactivation.  Delayed historical imports are
        # kept on the timeline but can never reactivate the customer.
        apply_transition = allowed and not historical_inactive_replay

    now = beijing_now()
    row = CustomerEvent(
        customer_id=customer_id,
        event_type=event_type,
        event_source=event_source,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        event_title=event_title,
        event_summary=event_summary,
        event_payload=payload,
        importance=importance,
        data_classification=classification,
        visibility_scope=visibility_scope,
        classification_reason=classification_reason or f"event_source:{event_source}",
        evidence_fact_ids=fact_ids,
        actor_user_id=actor_user_id,
        occurred_at=occurred,
        ingested_at=now,
        event_fingerprint=fingerprint,
        created_at=now,
    )
    db.add(row)
    if apply_transition and account.relationship_stage != target_relationship_stage:
        account.relationship_stage = target_relationship_stage
        account.relationship_stage_changed_at = occurred
        account.relationship_stage_reason = transition_trigger
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = now
    db.flush()
    return row


__all__ = [
    "append_customer_event",
    "append_fact",
    "append_source_record",
    "link_fact_evidence",
    "open_fact_conflict",
]
