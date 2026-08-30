"""Append-only source, fact, evidence, conflict, and customer event services."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Sequence

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, to_beijing_naive
from app.customer.contracts import (
    DATA_CLASSIFICATIONS,
    FACT_REGISTRY,
    SOURCE_REGISTRY,
    DataClassification,
    source_policy,
    validate_registered_fact,
)
from app.customer.identity_service import (
    CustomerDomainError,
    reject_ascii_control_characters,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerAnnotation,
    CustomerContact,
    CustomerContactRelationship,
    CustomerConversation,
    CustomerEvent,
    CustomerExternalIdentity,
    CustomerFact,
    CustomerFactConflict,
    CustomerFactEvidenceLink,
    CustomerMessage,
    CustomerOrder,
    CustomerQualificationReview,
    CustomerResearchTask,
    CustomerSourceRecord,
)


_CLASSIFICATION_ORDER = (
    DataClassification.PUBLIC_BUSINESS.value,
    DataClassification.INTERNAL_BUSINESS.value,
    DataClassification.PERSONAL_CONTACT.value,
    DataClassification.RESTRICTED_INTERNAL.value,
)
_VISIBILITY_ORDER = ("all_authorized", "customer_team", "management")
_FACT_LAYERS = {"source", "expressed", "observed", "inferred", "confirmed"}
_FACT_STATUSES = {"unverified", "candidate", "verified", "disputed", "rejected", "superseded"}
_ACTIVE_FACT_STATUSES = {"unverified", "candidate", "verified", "disputed"}
_VALUE_TYPES = {"string", "number", "boolean", "date", "datetime", "list", "object"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_VERIFIED_FACT_STATUS = "verified"


@dataclass(frozen=True, slots=True)
class DirectFactEvidence:
    evidence_kind: Literal["source_record", "conversation", "message", "order", "fact"]
    evidence_id: int
    locator: Mapping


@dataclass(frozen=True, slots=True)
class HumanReviewEvidence:
    reviewer_id: int
    reviewed_at: datetime
    review_reference: str
    supporting_fact_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EventEvidenceRef:
    evidence_kind: Literal["source_record", "conversation", "message", "order", "fact"]
    evidence_id: int


@dataclass(frozen=True, slots=True)
class EventRegistration:
    registry_version: str
    allowed_sources: frozenset[str]
    payload_fields: Mapping[str, type]
    required_payload_fields: frozenset[str]
    default_classification: DataClassification
    allowed_reference_kinds: frozenset[str | None]
    human_actor_required: bool = False


EVENT_REGISTRY_VERSION = "customer_event_registry_v2"


def _event_registration(
    sources: Sequence[str],
    payload_fields: Mapping[str, type],
    *,
    required: Sequence[str] = (),
    classification: DataClassification = DataClassification.INTERNAL_BUSINESS,
    reference: str | None = None,
    references: Sequence[str | None] | None = None,
    human: bool = False,
) -> EventRegistration:
    return EventRegistration(
        registry_version=EVENT_REGISTRY_VERSION,
        allowed_sources=frozenset(sources),
        payload_fields=MappingProxyType(dict(payload_fields)),
        required_payload_fields=frozenset(required),
        default_classification=classification,
        allowed_reference_kinds=frozenset(
            references if references is not None else (reference,)
        ),
        human_actor_required=human,
    )


EVENT_REGISTRY: Mapping[str, EventRegistration] = MappingProxyType({
    "inquiry.received": _event_registration(
        ("alibaba",), {"channel": str}, reference="source_record"
    ),
    "message.received": _event_registration(
        ("alibaba", "email", "whatsapp"), {"direction": str},
        required=("direction",), reference="message",
        classification=DataClassification.RESTRICTED_INTERNAL,
    ),
    "message.sent": _event_registration(
        ("alibaba", "email", "whatsapp"), {"direction": str},
        required=("direction",), reference="message",
        classification=DataClassification.RESTRICTED_INTERNAL,
    ),
    "order.placed": _event_registration(
        ("okki",), {"is_valid_business_order": bool, "historical_replay": bool},
        required=("is_valid_business_order",), reference="order",
    ),
    "research.completed": _event_registration(
        ("agent",), {"result_status": str}, required=("result_status",),
        reference="research_task",
    ),
    "identity.confirmed": _event_registration(
        ("manual", "identity"), {"identity_id": int},
        required=("identity_id",), reference="identity", human=True,
    ),
    "identity.conflict": _event_registration(
        ("identity",), {"identity_ids": list}, required=("identity_ids",),
    ),
    "relationship.stage_changed": _event_registration(
        ("manual", "qualification", "okki"),
        {
            "reason_code": str,
            "is_valid_business_order": bool,
            "historical_replay": bool,
        },
        required=("reason_code",),
        references=("customer", "qualification_review", "order"),
    ),
    "assignment.changed": _event_registration(
        ("manual", "assignment"), {"assignment_status": str},
        required=("assignment_status",), reference="assignment", human=True,
    ),
    "qualification.reviewed": _event_registration(
        ("manual", "qualification"), {"decision": str},
        required=("decision",), reference="qualification_review", human=True,
    ),
    "annotation.created": _event_registration(
        ("annotation", "manual"), {"annotation_type": str},
        required=("annotation_type",), reference="annotation", human=True,
        classification=DataClassification.RESTRICTED_INTERNAL,
    ),
})


def _sha256(parts: Iterable[object]) -> str:
    material = tuple(parts)
    reject_ascii_control_characters(material)
    encoded = "\x1f".join("" if item is None else str(item) for item in material)
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


def _visibility_max(*values: str | None) -> str:
    normalized = [value for value in values if value is not None]
    if not normalized or any(value not in _VISIBILITY_ORDER for value in normalized):
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    return max(normalized, key=_VISIBILITY_ORDER.index)


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


def _require_active_human(db: Session, user_id: int, error_code: str) -> ArkUser:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if user is None:
        raise CustomerDomainError(error_code)
    authorized = any(
        role.name == "super_admin"
        or any(permission.code == "customer:write" for permission in role.permissions)
        for role in user.roles
    )
    if not authorized:
        raise CustomerDomainError(error_code)
    return user


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


def _source_security_tightening_requires_rebuild(
    db: Session,
    *,
    source: CustomerSourceRecord,
    prospective_customer_id: int | None,
    target_classification: str,
    target_visibility: str,
) -> bool:
    customer_id = source.customer_id or prospective_customer_id
    if customer_id is None:
        # An unbound source can already support a contact identity.  Its
        # eventual customer event lineage is not queryable from the event row,
        # so tightening must wait for an explicit customer-bound rebuild.
        return db.query(CustomerExternalIdentity.id).filter(
            CustomerExternalIdentity.source_record_id == source.id,
        ).first() is not None

    def is_wider(classification: str, visibility: str | None = None) -> bool:
        if _CLASSIFICATION_ORDER.index(classification) < (
            _CLASSIFICATION_ORDER.index(target_classification)
        ):
            return True
        return bool(
            visibility is not None
            and _VISIBILITY_ORDER.index(visibility)
            < _VISIBILITY_ORDER.index(target_visibility)
        )

    message_ids = {
        row[0]
        for row in db.query(CustomerMessage.id).filter(
            CustomerMessage.source_record_id == source.id,
        ).all()
    }
    order_ids = {
        row[0]
        for row in db.query(CustomerOrder.id).filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.source_record_id == source.id,
        ).all()
    }
    conversation_ids = {
        row[0]
        for row in db.query(CustomerConversation.id).filter(
            CustomerConversation.customer_id == customer_id,
            CustomerConversation.latest_source_record_id == source.id,
        ).all()
    }
    facts = db.query(CustomerFact).filter(
        CustomerFact.customer_id == customer_id,
    ).all()
    links = db.query(CustomerFactEvidenceLink).filter(
        CustomerFactEvidenceLink.customer_id == customer_id,
    ).all()

    affected_fact_ids: set[int] = set()
    for fact in facts:
        evidence = fact.evidence_json or {}
        if (
            fact.source_record_id == source.id
            or source.id in evidence.get("source_record_ids", ())
            or message_ids.intersection(evidence.get("message_ids", ()))
            or order_ids.intersection(evidence.get("order_ids", ()))
            or conversation_ids.intersection(evidence.get("conversation_ids", ()))
        ):
            affected_fact_ids.add(fact.id)
    for link in links:
        if (
            link.source_record_id == source.id
            or link.message_id in message_ids
            or link.order_id in order_ids
        ):
            affected_fact_ids.add(link.fact_id)

    changed = True
    while changed:
        changed = False
        for fact in facts:
            if fact.id in affected_fact_ids:
                continue
            if affected_fact_ids.intersection(
                (fact.evidence_json or {}).get("fact_ids", ())
            ):
                affected_fact_ids.add(fact.id)
                changed = True
        for link in links:
            if (
                link.fact_id not in affected_fact_ids
                and link.supporting_fact_id in affected_fact_ids
            ):
                affected_fact_ids.add(link.fact_id)
                changed = True

    facts_by_id = {fact.id: fact for fact in facts}
    if any(
        is_wider(facts_by_id[fact_id].data_classification,
                 facts_by_id[fact_id].visibility_scope)
        for fact_id in affected_fact_ids
    ):
        return True
    if any(
        is_wider(link.data_classification)
        for link in links
        if (
            link.fact_id in affected_fact_ids
            or link.supporting_fact_id in affected_fact_ids
            or link.source_record_id == source.id
            or link.message_id in message_ids
            or link.order_id in order_ids
        )
    ):
        return True

    conflicts = db.query(CustomerFactConflict).filter(
        CustomerFactConflict.customer_id == customer_id,
    ).all()
    if any(
        is_wider(conflict.data_classification, conflict.visibility_scope)
        for conflict in conflicts
        if (
            conflict.left_fact_id in affected_fact_ids
            or conflict.right_fact_id in affected_fact_ids
            or conflict.resolution_fact_id in affected_fact_ids
        )
    ):
        return True

    events = db.query(CustomerEvent).filter(
        CustomerEvent.customer_id == customer_id,
    ).all()
    # Generic event evidence lineage is fingerprinted but is not persisted as
    # queryable foreign keys.  Until the schema stores that lineage, a source
    # security change cannot prove that any wider event is unrelated.
    return any(
        is_wider(event.data_classification, event.visibility_scope)
        for event in events
    )


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
    reject_ascii_control_characters(
        source_system,
        source_account_key,
        source_entity_type,
        external_record_id,
        payload_schema_version,
        source_version,
        publisher_key,
        source_family_key,
        source_url,
        data_classification,
        visibility_scope,
        classification_reason,
        sync_cursor,
        processing_status,
        processing_error_code,
        processing_error_message,
    )
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
    effective_classification = _classification_max(
        policy.default_classification,
        data_classification,
    )

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
        .with_for_update()
        .one_or_none()
    )
    if existing is not None:
        if customer_id is not None and existing.customer_id not in {None, customer_id}:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        target_classification = _classification_max(
            existing.data_classification,
            effective_classification,
        )
        target_visibility = _visibility_max(
            existing.visibility_scope,
            visibility_scope,
        )
        affected = account
        if existing.customer_id is not None:
            affected = affected or _account_for_update(db, existing.customer_id)
        if (
            (
                target_classification != existing.data_classification
                or target_visibility != existing.visibility_scope
            )
            and _source_security_tightening_requires_rebuild(
                db,
                source=existing,
                prospective_customer_id=customer_id,
                target_classification=target_classification,
                target_visibility=target_visibility,
            )
        ):
            raise CustomerDomainError("SOURCE_SECURITY_TIGHTENING_REQUIRES_REBUILD")
        changed = False
        if customer_id is not None and existing.customer_id is None:
            existing.customer_id = customer_id
            changed = True
        if existing.data_classification != target_classification:
            existing.data_classification = target_classification
            changed = True
        if existing.visibility_scope != target_visibility:
            existing.visibility_scope = target_visibility
            changed = True
        if changed and classification_reason:
            existing.classification_reason = classification_reason
        if changed:
            if existing.customer_id is not None:
                affected = affected or _account_for_update(db, existing.customer_id)
                affected.profile_input_seq = int(affected.profile_input_seq) + 1
                affected.updated_at = beijing_now()
            db.flush()
        return existing

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
        if valid:
            decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
            valid = decimal_value.is_finite()
            if valid and decimal_value == decimal_value.to_integral_value():
                normalized = int(decimal_value)
            elif valid:
                normalized = float(decimal_value)
                valid = math.isfinite(normalized)
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
        now = beijing_now()
        relation = db.query(CustomerContactRelationship.id).filter(
            CustomerContactRelationship.customer_id == customer_id,
            CustomerContactRelationship.contact_id == subject_id,
            CustomerContactRelationship.effective_to.is_(None),
            (
                CustomerContactRelationship.effective_from.is_(None)
                | (CustomerContactRelationship.effective_from <= now)
            ),
            CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        ).first()
        if contact is None or contact.record_status != "active" or relation is None:
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


def _source_lineage(row: CustomerSourceRecord) -> Mapping[str, object]:
    return {
        "source_system": row.source_system,
        "source_account_key": row.source_account_key,
        "source_entity_type": row.source_entity_type,
        "external_record_id": row.external_record_id,
        "source_version": row.source_version,
        "content_hash": row.content_hash,
        "publisher_key": row.publisher_key,
        "source_family_key": row.source_family_key,
    }


def _resolved_evidence(
    db: Session,
    customer_id: int,
    item: DirectFactEvidence | EventEvidenceRef,
) -> tuple[Mapping[str, object], str, str]:
    if type(item.evidence_id) is not int or item.evidence_id <= 0:
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")
    kind = item.evidence_kind
    locator = getattr(item, "locator", {})
    if not isinstance(locator, Mapping):
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")
    locator_json = copy.deepcopy(dict(locator))
    if isinstance(item, DirectFactEvidence) and not locator_json:
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")
    _canonical_json(locator_json)
    if kind == "source_record":
        row = db.get(CustomerSourceRecord, item.evidence_id)
        if row is None or row.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        lineage = {"kind": kind, "record": _source_lineage(row), "locator": locator_json}
        return lineage, row.data_classification, row.visibility_scope
    if kind == "conversation":
        row = db.get(CustomerConversation, item.evidence_id)
        source = db.get(CustomerSourceRecord, row.latest_source_record_id) if row else None
        if (
            row is None
            or row.customer_id != customer_id
            or source is None
            or source.customer_id != customer_id
        ):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        lineage = {
            "kind": kind,
            "source_system": row.source_system,
            "source_account_key": row.source_account_key,
            "external_conversation_id": row.external_conversation_id,
            "latest_source": _source_lineage(source),
            "locator": locator_json,
        }
        return lineage, source.data_classification, source.visibility_scope
    if kind == "message":
        row = db.get(CustomerMessage, item.evidence_id)
        conversation = db.get(CustomerConversation, row.conversation_id) if row else None
        source = db.get(CustomerSourceRecord, row.source_record_id) if row else None
        if (
            row is None
            or conversation is None
            or conversation.customer_id != customer_id
            or source is None
            or source.customer_id != customer_id
        ):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        lineage = {
            "kind": kind,
            "external_message_id": row.external_message_id,
            "content_hash": row.content_hash,
            "source": _source_lineage(source),
            "locator": locator_json,
        }
        return lineage, source.data_classification, source.visibility_scope
    if kind == "order":
        row = db.get(CustomerOrder, item.evidence_id)
        source = db.get(CustomerSourceRecord, row.source_record_id) if row else None
        if (
            row is None
            or row.customer_id != customer_id
            or source is None
            or source.customer_id != customer_id
        ):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        lineage = {
            "kind": kind,
            "external_order_id": row.external_order_id,
            "source_hash": row.source_hash,
            "source": _source_lineage(source),
            "locator": locator_json,
        }
        return lineage, source.data_classification, source.visibility_scope
    if kind == "fact":
        row = db.get(CustomerFact, item.evidence_id)
        if row is None or row.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        lineage = {
            "kind": kind,
            "fact_fingerprint": row.fact_fingerprint,
            "locator": locator_json,
        }
        return lineage, row.data_classification, row.visibility_scope
    raise CustomerDomainError("FACT_EVIDENCE_INVALID")


def _direct_evidence_contract(
    db: Session,
    customer_id: int,
    evidence: Sequence[DirectFactEvidence],
) -> tuple[
    dict[str, list[int]],
    tuple[Mapping[str, object], ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    indexes = {
        "source_record_ids": [],
        "conversation_ids": [],
        "message_ids": [],
        "order_ids": [],
        "fact_ids": [],
    }
    resolved: list[tuple[str, Mapping[str, object], str, str, int]] = []
    for item in evidence:
        if not isinstance(item, DirectFactEvidence):
            raise CustomerDomainError("FACT_EVIDENCE_INVALID")
        lineage, classification, visibility = _resolved_evidence(db, customer_id, item)
        resolved.append((
            item.evidence_kind,
            lineage,
            classification,
            visibility,
            item.evidence_id,
        ))
    resolved.sort(key=lambda row: (row[0], _canonical_json(row[1]), row[4]))
    for kind, _lineage, _classification, _visibility, evidence_id in resolved:
        indexes[f"{kind}_ids"].append(evidence_id)
    return (
        indexes,
        tuple(row[1] for row in resolved),
        tuple(row[2] for row in resolved),
        tuple(row[3] for row in resolved),
    )


def _validate_layer_provenance(
    *,
    fact_key: str,
    fact_layer: str,
    direct_evidence: Sequence[DirectFactEvidence],
    rule_version: str | None,
    human_review: HumanReviewEvidence | None,
) -> None:
    kinds = {item.evidence_kind for item in direct_evidence}
    if fact_layer == "expressed" and not kinds.intersection({"message", "conversation"}):
        raise CustomerDomainError("FACT_DIRECT_EVIDENCE_REQUIRED")
    if fact_layer == "observed":
        allowed = (
            {"order"}
            if fact_key.startswith("preference.observed.") or fact_key == "commercial.has_valid_order"
            else {"message", "conversation"}
        )
        if not kinds.intersection(allowed):
            raise CustomerDomainError("FACT_DIRECT_EVIDENCE_REQUIRED")
    if fact_layer == "inferred" and (
        not rule_version or not direct_evidence or kinds != {"fact"}
    ):
        raise CustomerDomainError("FACT_INFERENCE_EVIDENCE_REQUIRED")
    if fact_layer == "confirmed" and human_review is None:
        raise CustomerDomainError("FACT_REVIEW_EVIDENCE_REQUIRED")


def _validate_authoritative_order_fact(
    db: Session,
    *,
    fact_key: str,
    normalized_value: object,
    source_record_id: int | None,
    direct_evidence: Sequence[DirectFactEvidence],
    observed_at: datetime,
) -> None:
    if fact_key != "commercial.has_valid_order":
        return
    order_evidence = [
        item for item in direct_evidence if item.evidence_kind == "order"
    ]
    if len(order_evidence) != 1:
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")
    order = db.query(CustomerOrder).filter(
        CustomerOrder.id == order_evidence[0].evidence_id,
    ).with_for_update().one_or_none()
    source = db.get(CustomerSourceRecord, source_record_id) if source_record_id else None
    if (
        order is None
        or source is None
        or order.source_record_id != source.id
        or normalized_value is not order.is_valid_business_order
    ):
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")
    authoritative_time = source.occurred_at
    if authoritative_time is None and order.account_date is not None:
        authoritative_time = datetime.combine(order.account_date, datetime_time.min)
    if authoritative_time is None or observed_at != authoritative_time:
        raise CustomerDomainError("FACT_EVIDENCE_INVALID")


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
    direct_evidence: Sequence[DirectFactEvidence] = (),
    human_review: HumanReviewEvidence | None = None,
    agent_run_id: int | None = None,
    rule_version: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    expires_at: datetime | None = None,
    supersedes_fact_id: int | None = None,
) -> CustomerFact:
    """Append a registered, typed, temporally-scoped customer fact."""
    reject_ascii_control_characters(
        subject_type,
        fact_key,
        value_type,
        value,
        fact_layer,
        verification_status,
        confidence_method_version,
        confidence_components,
        source_system,
        source_entity_type,
        value_metadata,
        data_classification,
        visibility_scope,
        classification_reason,
        rule_version,
        tuple(
            (
                getattr(item, "evidence_kind", None),
                getattr(item, "locator", None),
            )
            for item in direct_evidence
        ),
        human_review.review_reference if human_review is not None else None,
    )
    account = _account_for_update(db, customer_id)
    registration = FACT_REGISTRY.get(fact_key)
    if registration is None:
        raise CustomerDomainError("FACT_NOT_REGISTERED")
    source_key = (source_system, source_entity_type)
    if source_key not in SOURCE_REGISTRY or source_key not in registration.allowed_sources:
        raise CustomerDomainError("FACT_SOURCE_NOT_ALLOWED")
    source_registration = SOURCE_REGISTRY[source_key]
    if fact_key not in source_registration.allowed_fact_keys:
        raise CustomerDomainError("FACT_SOURCE_NOT_ALLOWED")
    if source_system not in {"manual", "agent"} and source_record_id is None:
        raise CustomerDomainError("FACT_SOURCE_RECORD_REQUIRED")
    registered_classification = validate_registered_fact(
        fact_key,
        source_system,
        source_entity_type,
    )
    _validate_fact_layer(fact_key, fact_layer)
    if verification_status not in _FACT_STATUSES:
        raise CustomerDomainError("FACT_STATUS_INVALID")
    if fact_layer == "confirmed" and verification_status != "verified":
        raise CustomerDomainError("FACT_STATUS_INVALID")
    if human_review is not None and fact_layer != "confirmed":
        raise CustomerDomainError("FACT_REVIEW_EVIDENCE_INVALID")
    if (
        verification_status == _VERIFIED_FACT_STATUS
        or fact_layer == "confirmed"
    ) and source_registration.promotion_ceiling != "verified":
        raise CustomerDomainError("FACT_PROMOTION_CEILING_EXCEEDED")
    if visibility_scope not in {"all_authorized", "customer_team", "management"}:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    try:
        confidence_value = Decimal(str(confidence))
        if not confidence_value.is_finite():
            raise InvalidOperation
        confidence_value = confidence_value.quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
        if confidence_value.is_zero():
            confidence_value = Decimal("0.0000")
    except (InvalidOperation, ValueError) as exc:
        raise CustomerDomainError("FACT_CONFIDENCE_INVALID") from exc
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
    if value_type not in registration.value_types:
        raise CustomerDomainError("FACT_VALUE_TYPE_INVALID")
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

    review_time: datetime | None = None
    review_by: int | None = None
    evidence_items = list(direct_evidence)
    if human_review is not None:
        if (
            type(human_review.reviewer_id) is not int
            or human_review.reviewer_id <= 0
            or not isinstance(human_review.review_reference, str)
            or not human_review.review_reference.strip()
            or not human_review.supporting_fact_ids
        ):
            raise CustomerDomainError("FACT_REVIEW_EVIDENCE_REQUIRED")
        review_time = _business_time(human_review.reviewed_at)
        if review_time is None:
            raise CustomerDomainError("FACT_REVIEW_EVIDENCE_REQUIRED")
        review_by = human_review.reviewer_id
        _require_active_human(db, review_by, "FACT_REVIEWER_UNAUTHORIZED")
        for supporting_fact_id in human_review.supporting_fact_ids:
            evidence_items.append(DirectFactEvidence(
                "fact",
                supporting_fact_id,
                {"review_reference": human_review.review_reference},
            ))
    _validate_layer_provenance(
        fact_key=fact_key,
        fact_layer=fact_layer,
        direct_evidence=evidence_items,
        rule_version=rule_version,
        human_review=human_review,
    )

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
    (
        evidence_json,
        direct_lineage,
        evidence_classifications,
        evidence_visibilities,
    ) = _direct_evidence_contract(db, customer_id, evidence_items)
    _validate_authoritative_order_fact(
        db,
        fact_key=fact_key,
        normalized_value=normalized_value,
        source_record_id=source_record_id,
        direct_evidence=evidence_items,
        observed_at=observed,
    )
    if source_record_id is not None and source_record_id not in evidence_json["source_record_ids"]:
        evidence_json["source_record_ids"].append(source_record_id)
        evidence_json["source_record_ids"].sort()
    lineage = {
        "source_record": _source_lineage(source_record) if source_record is not None else None,
        "direct_evidence": direct_lineage,
        "human_review": (
            {
                "reviewer_id": review_by,
                "reviewed_at": review_time.isoformat(),
                "review_reference": human_review.review_reference,
            }
            if human_review is not None
            else None
        ),
    }
    _canonical_json(evidence_json)
    effective_classification = _classification_max(
        registered_classification,
        source_record.data_classification if source_record is not None else None,
        data_classification,
        *evidence_classifications,
    )
    effective_visibility = _visibility_max(
        visibility_scope,
        source_record.visibility_scope if source_record is not None else None,
        *evidence_visibilities,
    )
    effective_classification_reason = (
        classification_reason
        or f"fact_registry:{fact_key};source:{source_system}/{source_entity_type}"
    )
    fingerprint = _sha256((
        "fact_v1",
        customer_id,
        subject_type,
        subject_id or "",
        fact_key,
        value_type,
        fact_layer,
        _canonical_json(value_json),
        _canonical_json(lineage),
        verification_status,
        format(confidence_value, "f"),
        confidence_method_version,
        _canonical_json(confidence_components),
        rule_version or "",
        agent_run_id or "",
        observed.isoformat(),
        effective_start.isoformat(),
        effective_end.isoformat() if effective_end is not None else "",
        expiry.isoformat() if expiry is not None else "",
        supersedes_fact_id or "",
        effective_classification,
        effective_visibility,
        effective_classification_reason,
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
        visibility_scope=effective_visibility,
        classification_reason=effective_classification_reason,
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
        reviewed_by=review_by,
        reviewed_at=review_time,
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
) -> tuple[object, str, int, str, str]:
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
        classification = target.data_classification if target is not None else ""
        visibility = target.visibility_scope if target is not None else ""
    elif evidence_kind == "message":
        target = db.get(CustomerMessage, target_id)
        expected_hash = target.content_hash if target is not None else ""
        conversation = db.get(CustomerConversation, target.conversation_id) if target is not None else None
        source = db.get(CustomerSourceRecord, target.source_record_id) if target is not None else None
        customer_id = conversation.customer_id if conversation is not None else None
        if source is None or source.customer_id != customer_id:
            customer_id = None
        classification = source.data_classification if source is not None else ""
        visibility = source.visibility_scope if source is not None else ""
    elif evidence_kind == "order":
        target = db.get(CustomerOrder, target_id)
        expected_hash = target.source_hash if target is not None else ""
        customer_id = target.customer_id if target is not None else None
        source = db.get(CustomerSourceRecord, target.source_record_id) if target is not None else None
        if source is None or source.customer_id != customer_id:
            customer_id = None
        classification = source.data_classification if source is not None else ""
        visibility = source.visibility_scope if source is not None else ""
    else:
        target = db.get(CustomerFact, target_id)
        expected_hash = target.fact_fingerprint if target is not None else ""
        customer_id = target.customer_id if target is not None else None
        classification = target.data_classification if target is not None else ""
        visibility = target.visibility_scope if target is not None else ""
    if target is None or customer_id is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    return target, expected_hash, customer_id, classification, visibility


def _fact_evidence_path_exists(
    db: Session,
    *,
    customer_id: int,
    start_fact_id: int,
    target_fact_id: int,
) -> bool:
    frontier = {start_fact_id}
    visited: set[int] = set()
    while frontier:
        if target_fact_id in frontier:
            return True
        current = frontier - visited
        if not current:
            return False
        visited.update(current)
        rows = db.query(CustomerFactEvidenceLink.supporting_fact_id).filter(
            CustomerFactEvidenceLink.customer_id == customer_id,
            CustomerFactEvidenceLink.fact_id.in_(current),
            CustomerFactEvidenceLink.supporting_fact_id.is_not(None),
        ).all()
        direct_rows = db.query(CustomerFact.evidence_json).filter(
            CustomerFact.customer_id == customer_id,
            CustomerFact.id.in_(current),
        ).all()
        supporting_ids = {row[0] for row in rows}
        for row in direct_rows:
            evidence_json = row[0] or {}
            supporting_ids.update(evidence_json.get("fact_ids", ()))
        frontier = {fact_id for fact_id in supporting_ids if fact_id not in visited}
    return False


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
    reject_ascii_control_characters(
        evidence_kind,
        relation_type,
        evidence_content_hash,
        locator,
        excerpt_text,
        data_classification,
    )
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
    (
        target,
        expected_hash,
        evidence_customer_id,
        target_classification,
        target_visibility,
    ) = _evidence_target(
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
    if (
        supporting_fact_id is not None
        and _fact_evidence_path_exists(
            db,
            customer_id=fact.customer_id,
            start_fact_id=supporting_fact_id,
            target_fact_id=fact.id,
        )
    ):
        raise CustomerDomainError("FACT_EVIDENCE_CYCLE")
    effective_classification = _classification_max(
        fact.data_classification,
        target_classification,
        data_classification,
    )
    effective_visibility = _visibility_max(
        fact.visibility_scope,
        target_visibility,
    )
    if effective_visibility != fact.visibility_scope:
        raise CustomerDomainError("EVIDENCE_VISIBILITY_SCOPE_INVALID")
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
        effective_classification,
        effective_visibility,
        excerpt_text or "",
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
    reject_ascii_control_characters(
        detection_rule_version,
        conflict_type,
        visibility_scope,
    )
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
    if visibility_scope not in _VISIBILITY_ORDER:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    if not detection_rule_version:
        raise CustomerDomainError("FACT_CONFLICT_RULE_INVALID")
    conflict_key = left_registration.conflict_key
    effective_classification = _classification_max(
        left.data_classification,
        right.data_classification,
    )
    effective_visibility = _visibility_max(
        visibility_scope,
        left.visibility_scope,
        right.visibility_scope,
    )
    fingerprint = _sha256((
        "fact_conflict_v1",
        left.customer_id,
        conflict_key,
        first_id,
        second_id,
        detection_rule_version,
        conflict_type,
        effective_classification,
        effective_visibility,
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
        data_classification=effective_classification,
        visibility_scope=effective_visibility,
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


def _validate_event_payload(
    registration: EventRegistration,
    payload: Mapping,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise CustomerDomainError("EVENT_INPUT_INVALID")
    copied = copy.deepcopy(dict(payload))
    reject_ascii_control_characters(copied)
    if (
        not registration.required_payload_fields.issubset(copied)
        or not set(copied).issubset(registration.payload_fields)
    ):
        raise CustomerDomainError("EVENT_PAYLOAD_INVALID")
    for field, value in copied.items():
        expected = registration.payload_fields[field]
        if type(value) is not expected:
            raise CustomerDomainError("EVENT_PAYLOAD_INVALID")
    _canonical_json(copied)
    return copied


def _event_reference(
    db: Session,
    *,
    customer_id: int,
    reference_kind: str | None,
    reference_id: str | None,
) -> tuple[object | None, str | None, str | None]:
    if reference_kind is None:
        if reference_id is not None:
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        return None, None, None
    if not isinstance(reference_id, str) or not reference_id.isdecimal():
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    object_id = int(reference_id)
    if reference_kind in {"source_record", "conversation", "message", "order", "fact"}:
        lineage, classification, visibility = _resolved_evidence(
            db,
            customer_id,
            EventEvidenceRef(reference_kind, object_id),
        )
        return lineage, classification, visibility
    if reference_kind == "customer":
        if object_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        return object_id, DataClassification.INTERNAL_BUSINESS.value, None
    if reference_kind == "assignment":
        row = db.get(CustomerAssignment, object_id)
    elif reference_kind == "qualification_review":
        row = db.get(CustomerQualificationReview, object_id)
    elif reference_kind == "research_task":
        row = db.get(CustomerResearchTask, object_id)
    elif reference_kind == "annotation":
        row = db.get(CustomerAnnotation, object_id)
    elif reference_kind == "identity":
        row = db.get(CustomerExternalIdentity, object_id)
        if row is None:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        if not _identity_owned_by_customer(db, row, customer_id):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        source = db.get(CustomerSourceRecord, row.source_record_id) if row.source_record_id else None
        return (
            row,
            source.data_classification
            if source is not None
            else DataClassification.INTERNAL_BUSINESS.value,
            source.visibility_scope if source is not None else None,
        )
    else:
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    if row is None or row.customer_id != customer_id:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if reference_kind == "annotation" and row.visibility == "private":
        raise CustomerDomainError("PRIVATE_VISIBILITY_NOT_SHAREABLE")
    return (
        row,
        getattr(
            row,
            "data_classification",
            DataClassification.INTERNAL_BUSINESS.value,
        ),
        (
            row.visibility
            if reference_kind == "annotation"
            else getattr(row, "visibility_scope", None)
        ),
    )


def _identity_owned_by_customer(
    db: Session,
    identity: CustomerExternalIdentity,
    customer_id: int,
) -> bool:
    if identity.customer_id == customer_id:
        return True
    if identity.contact_id is None:
        return False
    now = beijing_now()
    contact = db.query(CustomerContact.id).filter(
        CustomerContact.id == identity.contact_id,
        CustomerContact.record_status == "active",
    ).first()
    relation = db.query(CustomerContactRelationship.id).filter(
        CustomerContactRelationship.customer_id == customer_id,
        CustomerContactRelationship.contact_id == identity.contact_id,
        CustomerContactRelationship.effective_to.is_(None),
        (
            CustomerContactRelationship.effective_from.is_(None)
            | (CustomerContactRelationship.effective_from <= now)
        ),
        CustomerContactRelationship.verification_status.in_(("identified", "verified")),
    ).first()
    return contact is not None and relation is not None


def _identity_conflict_security(
    db: Session,
    *,
    customer_id: int,
    payload: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identity_ids = payload.get("identity_ids")
    if (
        not isinstance(identity_ids, list)
        or not identity_ids
        or any(
            type(identity_id) is not int or identity_id <= 0
            for identity_id in identity_ids
        )
        or len(set(identity_ids)) != len(identity_ids)
    ):
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    rows = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.id.in_(identity_ids),
    ).with_for_update().all()
    if len(rows) != len(identity_ids):
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    classifications: list[str] = []
    visibilities: list[str] = []
    for row in rows:
        if not _identity_owned_by_customer(db, row, customer_id):
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        if row.status != "disputed" or row.verification_status != "disputed":
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        source = (
            db.get(CustomerSourceRecord, row.source_record_id)
            if row.source_record_id
            else None
        )
        if source is not None and source.customer_id != customer_id:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        classifications.append(
            source.data_classification
            if source is not None
            else DataClassification.INTERNAL_BUSINESS.value
        )
        if source is not None:
            visibilities.append(source.visibility_scope)
    return tuple(classifications), tuple(visibilities)


def _validate_event_reference_semantics(
    db: Session,
    *,
    event_type: str,
    event_source: str,
    source_ref_type: str | None,
    source_ref_id: str | None,
    payload: Mapping[str, object],
    actor_user_id: int | None,
    target_relationship_stage: str | None,
    fallback_occurred_at: datetime,
) -> datetime:
    if source_ref_type is None or source_ref_id is None:
        return fallback_occurred_at
    object_id = int(source_ref_id)
    if source_ref_type == "source_record":
        row = db.get(CustomerSourceRecord, object_id)
        if (
            row is None
            or row.source_system != event_source
            or (event_type == "inquiry.received" and row.source_entity_type != "inquiry")
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        return row.occurred_at or fallback_occurred_at
    if source_ref_type == "message":
        row = db.get(CustomerMessage, object_id)
        conversation = db.get(CustomerConversation, row.conversation_id) if row else None
        expected_direction = "in" if event_type == "message.received" else "out"
        if (
            row is None
            or conversation is None
            or conversation.source_system != event_source
            or row.direction != expected_direction
            or payload.get("direction") != row.direction
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        return row.sent_at
    if source_ref_type == "order":
        row = db.get(CustomerOrder, object_id)
        source = db.get(CustomerSourceRecord, row.source_record_id) if row else None
        if (
            row is None
            or source is None
            or row.source_system != event_source
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        if payload.get("is_valid_business_order") is not row.is_valid_business_order:
            raise CustomerDomainError(
                "RELATIONSHIP_TRANSITION_INVALID"
                if target_relationship_stage is not None
                else "EVENT_REFERENCE_INVALID"
            )
        if source.occurred_at is not None:
            return source.occurred_at
        if row.account_date is not None:
            return datetime.combine(row.account_date, datetime_time.min)
        raise CustomerDomainError("EVENT_TIME_INVALID")
    if source_ref_type == "identity":
        row = db.get(CustomerExternalIdentity, object_id)
        if (
            row is None
            or payload.get("identity_id") != object_id
            or row.verification_status != "verified"
            or row.status != "active"
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    elif source_ref_type == "research_task":
        row = db.get(CustomerResearchTask, object_id)
        if (
            row is None
            or row.task_status != "completed"
            or payload.get("result_status") != row.task_status
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    elif source_ref_type == "annotation":
        row = db.get(CustomerAnnotation, object_id)
        if (
            row is None
            or row.status != "active"
            or payload.get("annotation_type") != row.annotation_type
            or actor_user_id != row.authored_by
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    elif source_ref_type == "assignment":
        row = db.get(CustomerAssignment, object_id)
        if row is None or payload.get("assignment_status") != row.assignment_status:
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    elif source_ref_type == "qualification_review":
        row = db.get(CustomerQualificationReview, object_id)
        if event_type == "relationship.stage_changed":
            if (
                row is None
                or not row.is_current
                or row.decision != "approved"
                or row.reason_code != "qualified"
                or payload.get("reason_code") != "qualification_approved"
                or actor_user_id != row.reviewed_by
                or target_relationship_stage != "qualified"
            ):
                raise CustomerDomainError("EVENT_REFERENCE_INVALID")
            return row.reviewed_at
        if (
            row is None
            or payload.get("decision") != row.decision
            or actor_user_id != row.reviewed_by
        ):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    return fallback_occurred_at


def _relationship_transition_applies(
    db: Session,
    *,
    account: CustomerAccount,
    target_stage: str,
    trigger: str | None,
    event_type: str,
    event_source: str,
    actor_user_id: int | None,
    source_ref_type: str | None,
    source_ref_id: str | None,
    occurred_at: datetime,
    payload: Mapping[str, object],
) -> bool:
    current = account.relationship_stage
    if not trigger:
        raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
    if target_stage == "inactive" and current != "inactive":
        if event_source != "manual" or actor_user_id is None or trigger != "manual_inactivation":
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        return True
    if current == "discovered" and target_stage == "qualified":
        review = (
            db.get(CustomerQualificationReview, int(source_ref_id))
            if source_ref_type == "qualification_review" and source_ref_id and source_ref_id.isdecimal()
            else None
        )
        if (
            review is None
            or review.customer_id != account.id
            or not review.is_current
            or review.decision != "approved"
            or trigger != "qualification_approved"
        ):
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        return True
    if target_stage == "active_customer":
        order = (
            db.get(CustomerOrder, int(source_ref_id))
            if event_type in {"order.placed", "relationship.stage_changed"}
            and source_ref_type == "order"
            and source_ref_id
            and source_ref_id.isdecimal()
            else None
        )
        if (
            order is None
            or order.customer_id != account.id
            or not order.is_valid_business_order
            or payload.get("is_valid_business_order") is not order.is_valid_business_order
            or trigger not in {"valid_order", "historical_order_replay"}
        ):
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        source = db.get(CustomerSourceRecord, order.source_record_id)
        authoritative_time = (
            source.occurred_at
            if source is not None and source.occurred_at is not None
            else occurred_at
        )
        historical = bool(payload.get("historical_replay")) or trigger == "historical_order_replay"
        if historical or (
            current == "inactive" and authoritative_time <= account.relationship_stage_changed_at
        ):
            return False
        if current not in {"discovered", "qualified", "developing", "active_customer", "inactive"}:
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        return current != "active_customer"
    if current == "qualified" and target_stage == "developing":
        has_primary = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == account.id,
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ).first() is not None
        # The phase-one opportunity table has no customer ownership contract;
        # therefore development cannot be asserted safely yet.
        if trigger != "sales_development_ready" or not has_primary:
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
    if current == "inactive" and target_stage == "developing":
        if event_source != "manual" or actor_user_id is None or trigger != "manual_reactivation":
            raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
        raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
    if current == "developing" and target_stage == "qualified":
        raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
    if current == target_stage:
        return False
    raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")


def append_customer_event(
    db: Session,
    *,
    customer_id: int,
    event_type: str,
    event_source: str,
    event_title: str,
    event_payload: Mapping,
    payload_schema_version: str,
    occurred_at: datetime,
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    event_summary: str | None = None,
    importance: str = "normal",
    data_classification: str = "internal_business",
    visibility_scope: str = "customer_team",
    classification_reason: str | None = None,
    evidence_fact_ids: Sequence[int] = (),
    evidence_refs: Sequence[EventEvidenceRef] = (),
    actor_user_id: int | None = None,
    target_relationship_stage: str | None = None,
    transition_trigger: str | None = None,
    transition_condition_met: bool = False,
    has_primary_assignment: bool = False,
    has_open_opportunity: bool = False,
) -> CustomerEvent:
    """Append a registered event and derive transitions only from database state."""
    del transition_condition_met, has_primary_assignment, has_open_opportunity
    reject_ascii_control_characters(
        event_type,
        event_source,
        event_title,
        event_payload,
        payload_schema_version,
        source_ref_type,
        source_ref_id,
        event_summary,
        importance,
        data_classification,
        visibility_scope,
        classification_reason,
        target_relationship_stage,
        transition_trigger,
        tuple(getattr(item, "evidence_kind", None) for item in evidence_refs),
    )
    account = _account_for_update(db, customer_id)
    if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
        raise CustomerDomainError("EVENT_TYPE_INVALID")
    registration = EVENT_REGISTRY.get(event_type)
    if registration is None:
        raise CustomerDomainError("EVENT_NOT_REGISTERED")
    if event_source not in registration.allowed_sources:
        raise CustomerDomainError("EVENT_SOURCE_NOT_ALLOWED")
    if payload_schema_version != "customer_event_v1":
        raise CustomerDomainError("EVENT_PAYLOAD_SCHEMA_INVALID")
    relationship_human_actor = (
        event_type == "relationship.stage_changed"
        and event_source in {"manual", "qualification"}
    )
    if (registration.human_actor_required or relationship_human_actor) and (
        type(actor_user_id) is not int or actor_user_id <= 0
    ):
        raise CustomerDomainError("EVENT_ACTOR_REQUIRED")
    if registration.human_actor_required or relationship_human_actor:
        _require_active_human(db, actor_user_id, "EVENT_ACTOR_UNAUTHORIZED")
    if not event_title:
        raise CustomerDomainError("EVENT_INPUT_INVALID")
    if importance not in {"critical", "high", "normal", "low"}:
        raise CustomerDomainError("EVENT_IMPORTANCE_INVALID")
    if visibility_scope not in {"all_authorized", "customer_team", "management"}:
        raise CustomerDomainError("VISIBILITY_SCOPE_INVALID")
    if source_ref_type not in registration.allowed_reference_kinds:
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    if event_type == "relationship.stage_changed" and (
        (event_source, source_ref_type)
        not in {
            ("manual", "customer"),
            ("qualification", "qualification_review"),
            ("okki", "order"),
        }
    ):
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    payload = _validate_event_payload(registration, event_payload)
    occurred = _business_time(occurred_at)
    if occurred is None:
        raise CustomerDomainError("EVENT_TIME_INVALID")
    _reference, reference_classification, reference_visibility = _event_reference(
        db,
        customer_id=customer_id,
        reference_kind=source_ref_type,
        reference_id=source_ref_id,
    )
    (
        payload_reference_classifications,
        payload_reference_visibilities,
    ) = (
        _identity_conflict_security(
            db,
            customer_id=customer_id,
            payload=payload,
        )
        if event_type == "identity.conflict"
        else ((), ())
    )
    occurred = _validate_event_reference_semantics(
        db,
        event_type=event_type,
        event_source=event_source,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        payload=payload,
        actor_user_id=actor_user_id,
        target_relationship_stage=target_relationship_stage,
        fallback_occurred_at=occurred,
    )
    if event_type == "relationship.stage_changed" and (
        target_relationship_stage is None
        or not transition_trigger
        or payload.get("reason_code") != transition_trigger
    ):
        raise CustomerDomainError("RELATIONSHIP_TRANSITION_INVALID")
    if any(type(item) is not int or item <= 0 for item in evidence_fact_ids):
        raise CustomerDomainError("EVENT_REFERENCE_INVALID")
    fact_ids = sorted(set(evidence_fact_ids))
    all_refs = list(evidence_refs)
    all_refs.extend(EventEvidenceRef("fact", item) for item in fact_ids)
    evidence_classifications: list[str] = []
    evidence_visibilities: list[str] = []
    evidence_lineage: list[Mapping[str, object]] = []
    for item in all_refs:
        if not isinstance(item, EventEvidenceRef):
            raise CustomerDomainError("EVENT_REFERENCE_INVALID")
        item_lineage, item_classification, item_visibility = _resolved_evidence(
            db,
            customer_id,
            item,
        )
        evidence_lineage.append(item_lineage)
        evidence_classifications.append(item_classification)
        evidence_visibilities.append(item_visibility)
    evidence_lineage.sort(key=_canonical_json)
    classification = _classification_max(
        registration.default_classification,
        data_classification,
        reference_classification,
        *payload_reference_classifications,
        *evidence_classifications,
    )
    effective_visibility = _visibility_max(
        visibility_scope,
        reference_visibility,
        *payload_reference_visibilities,
        *evidence_visibilities,
    )
    effective_classification_reason = (
        classification_reason
        or f"event_registry:{registration.registry_version};source:{event_source}"
    )
    fingerprint = _sha256((
        "customer_event_v1",
        customer_id,
        event_type,
        _canonical_json({
            "event_title": event_title,
            "event_summary": event_summary,
        }),
        event_source,
        source_ref_type or "",
        source_ref_id or "",
        occurred.isoformat(),
        payload_schema_version,
        _canonical_json(payload),
        actor_user_id or "",
        _canonical_json(fact_ids),
        _canonical_json(evidence_lineage),
        target_relationship_stage or "",
        transition_trigger or "",
        importance,
        classification,
        effective_visibility,
        effective_classification_reason,
    ))
    existing = db.query(CustomerEvent).filter(
        CustomerEvent.event_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        return existing

    apply_transition = False
    if target_relationship_stage is not None:
        apply_transition = _relationship_transition_applies(
            db,
            account=account,
            target_stage=target_relationship_stage,
            trigger=transition_trigger,
            event_type=event_type,
            event_source=event_source,
            actor_user_id=actor_user_id,
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
            occurred_at=occurred,
            payload=payload,
        )

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
        visibility_scope=effective_visibility,
        classification_reason=effective_classification_reason,
        evidence_fact_ids=fact_ids,
        actor_user_id=actor_user_id,
        occurred_at=occurred,
        ingested_at=now,
        event_fingerprint=fingerprint,
        created_at=now,
    )
    db.add(row)
    if apply_transition:
        account.relationship_stage = target_relationship_stage
        account.relationship_stage_changed_at = occurred
        account.relationship_stage_reason = transition_trigger
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = now
    db.flush()
    return row


__all__ = [
    "DirectFactEvidence",
    "EVENT_REGISTRY",
    "EVENT_REGISTRY_VERSION",
    "EventEvidenceRef",
    "HumanReviewEvidence",
    "append_customer_event",
    "append_fact",
    "append_source_record",
    "link_fact_evidence",
    "open_fact_conflict",
]
