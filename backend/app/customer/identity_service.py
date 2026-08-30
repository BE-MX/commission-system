"""Transactional identity resolution for the unified Ark customer domain.

The functions in this module flush but never commit.  The caller owns the
transaction boundary.  A resolution key is claimed before any customer graph
is created, and the claim plus graph live in one savepoint so a failed writer
cannot leave an orphan account.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Literal, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.contracts import IdentityPolicy, identity_policy
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerExternalIdentity,
    CustomerName,
    CustomerResearchTask,
    CustomerResolutionKey,
    CustomerSourceRecord,
)


_FREE_EMAIL_DOMAINS = frozenset({
    "126.com",
    "163.com",
    "aol.com",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "qq.com",
    "yahoo.com",
    "yandex.com",
})
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CLASSIFICATION_COMPONENTS = {
    "identifier_strength": 0,
    "source_authority": 0,
    "independence": 0,
    "freshness": 0,
    "conflict_penalty": 0,
}
_ALIBABA_ORGANIZATION_SCHEMAS = frozenset({"alibaba_inquiry_v1"})
_RESOLUTION_SOURCE_ENTITY_MAP = {
    ("alibaba", "company"): "inquiry",
    ("okki", "company"): "customer",
}
_RESOLUTION_RETRYABLE_MYSQL_CODES = frozenset({1205, 1213})


class CustomerDomainError(ValueError):
    """Stable, non-leaking rejection for customer-domain service calls."""

    def __init__(self, error_code: str, message: str = "Customer domain operation rejected"):
        self.error_code = error_code
        super().__init__(message)


def reject_ascii_control_characters(*values: object) -> None:
    """Reject normalized external string material that can collide in slots/hashes."""
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if any(ord(character) <= 0x1F or ord(character) == 0x7F for character in value):
                raise CustomerDomainError("ASCII_CONTROL_CHARACTER_INVALID")
        elif isinstance(value, Mapping):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)


class CustomerTransactionRetryRequired(CustomerDomainError):
    """Signals that MySQL rolled back the transaction and caller must retry."""

    requires_new_transaction = True
    max_attempts = 3

    def __init__(self):
        super().__init__("IDENTITY_TRANSACTION_RETRY_REQUIRED")


@dataclass(frozen=True, slots=True)
class IdentityCandidate:
    identifier_type: str
    raw_value: str
    verification_status: Literal["candidate", "verified"] = "candidate"
    confidence: Decimal | float | int = Decimal("0.8000")
    is_primary: bool = False
    provider_declared_subject_type: Literal["customer", "contact"] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedBusinessContext:
    customer: CustomerAccount
    contact: CustomerContact | None
    resolution: CustomerResolutionKey
    created: bool


@dataclass(frozen=True, slots=True)
class IdentityConfirmationResult:
    identity: CustomerExternalIdentity
    conflict: bool
    conflicting_identity_ids: tuple[int, ...] = ()


class ResolutionKeyArbiter:
    """Database-backed first-writer arbitration, injectable in deterministic tests."""

    def try_claim(
        self,
        db: Session,
        *,
        resolution_key: str,
        resolution_type: str,
        source_system: str,
        source_account_key: str,
        source_entity_type: str,
        source_record_id: int | None,
        worker_id: str,
        now: datetime,
    ) -> CustomerResolutionKey | None:
        try:
            with db.begin_nested():
                row = CustomerResolutionKey(
                    resolution_key=resolution_key,
                    resolution_type=resolution_type,
                    source_system=source_system,
                    source_account_key=source_account_key,
                    source_entity_type=source_entity_type,
                    source_record_id=source_record_id,
                    status="claiming",
                    generation=1,
                    claimed_by=worker_id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            return None
        except OperationalError as exc:
            if _retryable_mysql_error(exc):
                raise CustomerTransactionRetryRequired() from exc
            raise


DEFAULT_RESOLUTION_KEY_ARBITER = ResolutionKeyArbiter()


def _sha256(parts: Iterable[object]) -> str:
    material = tuple(parts)
    reject_ascii_control_characters(material)
    encoded = "\x1f".join("" if item is None else str(item) for item in material)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_name(value: str) -> str:
    reject_ascii_control_characters(value)
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _normalize_email(value: str) -> str:
    reject_ascii_control_characters(value)
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not _EMAIL_RE.fullmatch(normalized):
        raise CustomerDomainError("CONTACT_POINT_INVALID")
    return normalized


def _normalize_domain(value: str) -> str:
    reject_ascii_control_characters(value)
    candidate = unicodedata.normalize("NFKC", value).strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = (parsed.hostname or "").rstrip(".").casefold()
    if not host or " " in host or "." not in host:
        raise CustomerDomainError("IDENTITY_VALUE_INVALID")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise CustomerDomainError("IDENTITY_VALUE_INVALID") from exc


def _effective_policy(
    source_system: str,
    identifier_type: str,
    provider_declared_subject_type: str | None,
    *,
    source_record: CustomerSourceRecord | None = None,
    raw_value: str | None = None,
) -> IdentityPolicy:
    try:
        policy = identity_policy(source_system, identifier_type)
    except KeyError as exc:
        raise CustomerDomainError("IDENTITY_NOT_REGISTERED") from exc

    if provider_declared_subject_type is None or provider_declared_subject_type == policy.subject_type:
        return policy
    if (
        source_system == "alibaba"
        and identifier_type in {"buyer_id", "member_id"}
        and provider_declared_subject_type == "customer"
    ):
        declarations = (
            source_record.payload_json.get("provider_identity_declarations", [])
            if source_record is not None
            and source_record.source_system == "alibaba"
            and source_record.source_entity_type == "inquiry"
            and source_record.payload_schema_version in _ALIBABA_ORGANIZATION_SCHEMAS
            and isinstance(source_record.payload_json, dict)
            else []
        )
        declared = any(
            isinstance(item, dict)
            and item.get("identifier_type") == identifier_type
            and item.get("subject_type") == "organization"
            and isinstance(item.get("raw_value"), str)
            and raw_value is not None
            and unicodedata.normalize("NFKC", item["raw_value"]).strip()
            == unicodedata.normalize("NFKC", raw_value).strip()
            for item in declarations
        )
        if not declared:
            raise CustomerDomainError("IDENTITY_SUBJECT_EVIDENCE_REQUIRED")
        return replace(
            policy,
            subject_type="customer",
            strength="strong",
            cardinality="one_to_one",
            auto_match_ceiling="identified",
            unique_slot=True,
        )
    raise CustomerDomainError("IDENTITY_SUBJECT_INVALID")


def _normalize_identity_value(policy: IdentityPolicy, raw_value: str) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise CustomerDomainError("IDENTITY_VALUE_INVALID")
    if policy.normalization_rule == "registrable_domain":
        return _normalize_domain(raw_value)
    return unicodedata.normalize("NFKC", raw_value).strip()


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


def _bump_accounts(db: Session, customer_ids: Iterable[int]) -> None:
    for customer_id in sorted(set(customer_ids)):
        account = _account_for_update(db, customer_id)
        account.profile_input_seq = int(account.profile_input_seq) + 1
        account.updated_at = beijing_now()


def _contact_customer_ids(db: Session, contact_id: int) -> tuple[int, ...]:
    rows = (
        db.query(CustomerContactRelationship.customer_id)
        .filter(
            CustomerContactRelationship.contact_id == contact_id,
            CustomerContactRelationship.effective_to.is_(None),
            CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        )
        .all()
    )
    return tuple(row[0] for row in rows)


def _identity_customer_ids(db: Session, identity: CustomerExternalIdentity) -> tuple[int, ...]:
    if identity.customer_id is not None:
        return (identity.customer_id,)
    if identity.contact_id is not None:
        return _contact_customer_ids(db, identity.contact_id)
    return ()


def _load_resolved_context(db: Session, row: CustomerResolutionKey) -> ResolvedBusinessContext:
    if row.status != "resolved" or row.customer_id is None:
        raise CustomerDomainError("IDENTITY_RESOLUTION_IN_PROGRESS")
    customer = _account_for_update(db, row.customer_id)
    contact = db.get(CustomerContact, row.contact_id) if row.contact_id is not None else None
    return ResolvedBusinessContext(customer, contact, row, False)


def _resolution_material(
    *,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_context_id: str,
    candidates: Sequence[IdentityCandidate],
    source_record: CustomerSourceRecord | None,
) -> tuple[str, str]:
    strong_customer_keys: list[tuple[str, str]] = []
    for candidate in candidates:
        policy = _effective_policy(
            source_system,
            candidate.identifier_type,
            candidate.provider_declared_subject_type,
            source_record=source_record,
            raw_value=candidate.raw_value,
        )
        normalized = _normalize_identity_value(policy, candidate.raw_value)
        if (
            policy.subject_type == "customer"
            and policy.strength == "strong"
            and policy.cardinality == "one_to_one"
            and candidate.verification_status == "verified"
            and policy.auto_match_ceiling in {"identified", "verified"}
        ):
            strong_customer_keys.append((candidate.identifier_type, normalized))
    if strong_customer_keys:
        identifier_type, normalized = sorted(strong_customer_keys)[0]
        return "strong_identity", _sha256((
            "strong_identity_v1",
            source_system,
            source_account_key,
            identifier_type,
            normalized,
        ))
    return "business_context", _sha256((
        "business_context_v1",
        source_system,
        source_account_key,
        source_entity_type,
        external_context_id,
    ))


def _existing_verified_strong_customer_id(
    db: Session,
    *,
    source_system: str,
    source_account_key: str,
    candidates: Sequence[IdentityCandidate],
    source_record: CustomerSourceRecord | None,
) -> int | None:
    matches: set[int] = set()
    for candidate in candidates:
        policy = _effective_policy(
            source_system,
            candidate.identifier_type,
            candidate.provider_declared_subject_type,
            source_record=source_record,
            raw_value=candidate.raw_value,
        )
        if not (
            policy.subject_type == "customer"
            and policy.strength == "strong"
            and policy.cardinality == "one_to_one"
            and candidate.verification_status == "verified"
            and policy.auto_match_ceiling in {"identified", "verified"}
        ):
            continue
        normalized = _normalize_identity_value(policy, candidate.raw_value)
        rows = db.query(CustomerExternalIdentity.customer_id).filter(
            CustomerExternalIdentity.source_system == source_system,
            CustomerExternalIdentity.source_account_key == source_account_key,
            CustomerExternalIdentity.identifier_type == candidate.identifier_type,
            CustomerExternalIdentity.normalized_value == normalized,
            CustomerExternalIdentity.customer_id.is_not(None),
            CustomerExternalIdentity.verification_status == "verified",
            CustomerExternalIdentity.status == "active",
        ).with_for_update().all()
        matches.update(row[0] for row in rows)
    if len(matches) > 1:
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
    return next(iter(matches), None)


def _validate_source_record_for_resolution(
    db: Session,
    source_record_id: int | None,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
) -> CustomerSourceRecord | None:
    if source_record_id is None:
        return None
    row = db.get(CustomerSourceRecord, source_record_id)
    if (
        row is None
        or row.source_system != source_system
        or row.source_account_key != source_account_key
        or row.source_entity_type != _RESOLUTION_SOURCE_ENTITY_MAP.get(
            (source_system, source_entity_type),
            source_entity_type,
        )
    ):
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    return row


def _create_contact(
    db: Session,
    *,
    contact_name: str | None,
    candidates: Sequence[IdentityCandidate],
    source_system: str,
    source_account_key: str,
    source_record: CustomerSourceRecord | None,
    created_by: int | None,
    now: datetime,
) -> CustomerContact | None:
    contact_candidates: list[tuple[IdentityCandidate, IdentityPolicy, str]] = []
    existing_contact_ids: set[int] = set()
    for candidate in candidates:
        policy = _effective_policy(
            source_system,
            candidate.identifier_type,
            candidate.provider_declared_subject_type,
            source_record=source_record,
            raw_value=candidate.raw_value,
        )
        if policy.subject_type != "contact":
            continue
        normalized = _normalize_identity_value(policy, candidate.raw_value)
        contact_candidates.append((candidate, policy, normalized))
        existing_identities = (
            db.query(CustomerExternalIdentity.contact_id)
            .filter(
                CustomerExternalIdentity.source_system == source_system,
                CustomerExternalIdentity.source_account_key == source_account_key,
                CustomerExternalIdentity.identifier_type == candidate.identifier_type,
                CustomerExternalIdentity.normalized_value == normalized,
                CustomerExternalIdentity.contact_id.is_not(None),
                CustomerExternalIdentity.status == "active",
            )
            .order_by(CustomerExternalIdentity.id)
            .all()
        )
        existing_contact_ids.update(row[0] for row in existing_identities)

    if len(existing_contact_ids) > 1:
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
    if existing_contact_ids:
        return db.get(CustomerContact, next(iter(existing_contact_ids)))

    if not (contact_name or contact_candidates):
        return None
    normalized_name = _normalize_name(contact_name) if contact_name else None
    row = CustomerContact(
        display_name=contact_name.strip() if contact_name else "待识别联系人",
        canonical_name=None,
        normalized_name=normalized_name,
        identity_status="provisional",
        confidence=Decimal("0.5000"),
        confidence_method_version="confidence_v1",
        confidence_components_json={
            "name_match": 0,
            "external_identity": 0,
            "contact_point": 0,
            "source_authority": 0,
            "conflict_penalty": 0,
        },
        record_status="active",
        created_by=created_by,
        updated_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _attach_identity_candidate(
    db: Session,
    *,
    customer_id: int | None,
    contact_id: int | None,
    source_system: str,
    source_account_key: str,
    identifier_type: str,
    raw_value: str,
    source_record_id: int | None,
    verification_status: str,
    confidence: Decimal | float | int,
    is_primary: bool,
    provider_declared_subject_type: str | None,
    created_by: int | None,
    now: datetime,
    bump_profile: bool,
) -> tuple[CustomerExternalIdentity, bool]:
    reject_ascii_control_characters(
        source_system,
        source_account_key,
        identifier_type,
        raw_value,
        verification_status,
        provider_declared_subject_type,
    )
    if (customer_id is None) == (contact_id is None):
        raise CustomerDomainError("IDENTITY_SUBJECT_INVALID")
    source_record = db.get(CustomerSourceRecord, source_record_id) if source_record_id else None
    if source_record_id and (
        source_record is None
        or source_record.source_system != source_system
        or source_record.source_account_key != source_account_key
    ):
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    policy = _effective_policy(
        source_system,
        identifier_type,
        provider_declared_subject_type,
        source_record=source_record,
        raw_value=raw_value,
    )
    expected_subject = "customer" if customer_id is not None else "contact"
    if expected_subject != policy.subject_type:
        raise CustomerDomainError("IDENTITY_SUBJECT_INVALID")
    if verification_status not in {"candidate", "verified"}:
        raise CustomerDomainError("IDENTITY_STATUS_INVALID")
    confidence_value = Decimal(str(confidence))
    if confidence_value < 0 or confidence_value > 1:
        raise CustomerDomainError("IDENTITY_CONFIDENCE_INVALID")

    affected_ids: tuple[int, ...]
    if customer_id is not None:
        _account_for_update(db, customer_id)
        affected_ids = (customer_id,)
    else:
        contact = db.get(CustomerContact, contact_id)
        if contact is None or contact.record_status != "active":
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        affected_ids = _contact_customer_ids(db, contact_id)
        if not affected_ids:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")

    if source_record_id and (
        source_record is None
        or (
            source_record.customer_id is not None
            and source_record.customer_id not in affected_ids
        )
    ):
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if (
        provider_declared_subject_type == "customer"
        and source_system == "alibaba"
        and identifier_type in {"buyer_id", "member_id"}
        and (source_record is None or source_record.customer_id != customer_id)
    ):
        raise CustomerDomainError("IDENTITY_SUBJECT_EVIDENCE_REQUIRED")

    normalized_value = _normalize_identity_value(policy, raw_value)
    subject_type = "customer" if customer_id is not None else "contact"
    subject_id = customer_id if customer_id is not None else contact_id
    fingerprint = _sha256((
        "identity_v1",
        subject_type,
        subject_id,
        source_system,
        source_account_key,
        identifier_type,
        normalized_value,
        source_record_id or "direct",
    ))
    semantic_rows = (
        db.query(CustomerExternalIdentity)
        .filter(
            CustomerExternalIdentity.source_system == source_system,
            CustomerExternalIdentity.source_account_key == source_account_key,
            CustomerExternalIdentity.identifier_type == identifier_type,
            CustomerExternalIdentity.normalized_value == normalized_value,
            CustomerExternalIdentity.identity_strength == "strong",
            CustomerExternalIdentity.cardinality == "one_to_one",
            CustomerExternalIdentity.status == "active",
        )
        .with_for_update()
        .all()
    )
    same_subject_rows = [row for row in semantic_rows if (
        row.customer_id == customer_id and row.contact_id == contact_id
    )]
    existing = same_subject_rows[0] if same_subject_rows else None
    if verification_status == "verified" and any(
        (row.customer_id != customer_id or row.contact_id != contact_id)
        and row.verification_status == "verified"
        for row in semantic_rows
    ):
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
    if len(same_subject_rows) > 1:
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
    if existing is None:
        existing = (
            db.query(CustomerExternalIdentity)
            .filter(CustomerExternalIdentity.identity_fingerprint == fingerprint)
            .with_for_update()
            .one_or_none()
        )
    if existing is not None:
        changed = False
        if verification_status == "verified" and existing.verification_status == "candidate":
            existing.verification_status = "verified"
            existing.status = "active"
            existing.verified_at = now
            changed = True
        if confidence_value > existing.confidence:
            existing.confidence = confidence_value
            changed = True
        if is_primary and not existing.is_primary:
            existing.is_primary = True
            changed = True
        if source_record_id is not None and existing.source_record_id != source_record_id:
            existing.source_record_id = source_record_id
            existing.identity_fingerprint = fingerprint
            existing.raw_value = raw_value
            changed = True
        if changed and now > existing.last_seen_at:
            existing.last_seen_at = now
        if changed:
            existing.updated_by = created_by
            existing.updated_at = now
            if bump_profile:
                _bump_accounts(db, affected_ids)
            db.flush()
        return existing, changed

    row = CustomerExternalIdentity(
        customer_id=customer_id,
        contact_id=contact_id,
        source_system=source_system,
        source_account_key=source_account_key,
        identifier_type=identifier_type,
        raw_value=raw_value,
        normalized_value=normalized_value,
        identity_strength=policy.strength,
        cardinality=policy.cardinality,
        auto_match_ceiling=policy.auto_match_ceiling,
        verification_status=verification_status,
        confidence=confidence_value,
        confidence_method_version="confidence_v1",
        confidence_components_json=dict(_CLASSIFICATION_COMPONENTS),
        is_primary=bool(is_primary),
        source_record_id=source_record_id,
        first_seen_at=now,
        last_seen_at=now,
        verified_at=now if verification_status == "verified" else None,
        status="active",
        identity_fingerprint=fingerprint,
        created_by=created_by,
        updated_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    if bump_profile:
        _bump_accounts(db, affected_ids)
        db.flush()
    return row, True


def attach_identity_candidate(
    db: Session,
    *,
    customer_id: int | None = None,
    contact_id: int | None = None,
    source_system: str,
    source_account_key: str,
    identifier_type: str,
    raw_value: str,
    source_record_id: int | None = None,
    verification_status: Literal["candidate", "verified"] = "candidate",
    confidence: Decimal | float | int = Decimal("0.8000"),
    is_primary: bool = False,
    provider_declared_subject_type: Literal["customer", "contact"] | None = None,
    created_by: int | None = None,
    now: datetime | None = None,
) -> CustomerExternalIdentity:
    """Append an identity candidate using only registered policy metadata."""
    row, _created = _attach_identity_candidate(
        db,
        customer_id=customer_id,
        contact_id=contact_id,
        source_system=source_system,
        source_account_key=source_account_key,
        identifier_type=identifier_type,
        raw_value=raw_value,
        source_record_id=source_record_id,
        verification_status=verification_status,
        confidence=confidence,
        is_primary=is_primary,
        provider_declared_subject_type=provider_declared_subject_type,
        created_by=created_by,
        now=now or beijing_now(),
        bump_profile=True,
    )
    return row


def _new_account(
    db: Session,
    *,
    resolution_key: str,
    company_name: str | None,
    contact_name: str | None,
    created_by: int | None,
    now: datetime,
) -> CustomerAccount:
    personal_alias = bool(
        company_name
        and contact_name
        and _normalize_name(company_name) == _normalize_name(contact_name)
    )
    display_seed = contact_name or company_name or "待识别客户"
    account = CustomerAccount(
        customer_code=f"CUST-{resolution_key[:20].upper()}",
        display_name=(
            f"{display_seed.strip()}（公司待识别）"
            if contact_name or personal_alias
            else display_seed.strip()
        ),
        canonical_company_name=None,
        entity_type="unknown",
        identity_status="provisional",
        relationship_stage="discovered",
        relationship_stage_changed_at=now,
        relationship_stage_reason="business_context_created",
        record_status="active",
        identity_confidence=Decimal("0.0000"),
        profile_completeness=Decimal("0.00"),
        profile_input_seq=0,
        created_by=created_by,
        updated_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.flush()
    return account


def _policy_for_candidate(
    source_system: str,
    candidate: IdentityCandidate,
    source_record: CustomerSourceRecord | None,
) -> IdentityPolicy:
    return _effective_policy(
        source_system,
        candidate.identifier_type,
        candidate.provider_declared_subject_type,
        source_record=source_record,
        raw_value=candidate.raw_value,
    )


_ACCOUNT_IDENTITY_RANK = {
    "provisional": 0,
    "identified": 1,
    "verified": 2,
}


def _merge_account_identity(
    account: CustomerAccount,
    *,
    target_status: str,
    confidence: Decimal,
) -> bool:
    if account.identity_status == "disputed":
        return False
    merged_status = (
        target_status
        if _ACCOUNT_IDENTITY_RANK[target_status]
        > _ACCOUNT_IDENTITY_RANK[account.identity_status]
        else account.identity_status
    )
    merged_confidence = max(account.identity_confidence, confidence)
    if (
        account.identity_status == merged_status
        and account.identity_confidence == merged_confidence
    ):
        return False
    account.identity_status = merged_status
    account.identity_confidence = merged_confidence
    return True


def _apply_context_material(
    db: Session,
    *,
    account: CustomerAccount,
    resolution: CustomerResolutionKey,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_context_id: str,
    source_record: CustomerSourceRecord | None,
    company_name: str | None,
    contact_name: str | None,
    contact_email: str | None,
    normalized_email: str | None,
    candidates: Sequence[IdentityCandidate],
    created_by: int | None,
    now: datetime,
    is_new_account: bool,
) -> CustomerContact | None:
    """Idempotently apply every signal carried by one immutable business context."""
    changed = False
    context_ref = (
        f"source:{source_record.id}"
        if source_record is not None
        else f"context:{source_system}:{source_account_key}:{source_entity_type}:{external_context_id}"
    )
    if source_record is not None:
        if source_record.customer_id not in {None, account.id}:
            raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
        if source_record.customer_id is None:
            source_record.customer_id = account.id
            changed = True

    personal_alias = bool(
        company_name
        and contact_name
        and _normalize_name(company_name) == _normalize_name(contact_name)
    )
    if company_name and company_name.strip():
        name_type = "person_alias" if personal_alias else "platform_alias"
        normalized_company_name = _normalize_name(company_name)
        name_fingerprint = _sha256((
            "name_v1",
            account.id,
            name_type,
            normalized_company_name,
            "",
            context_ref,
        ))
        if db.query(CustomerName.id).filter_by(name_fingerprint=name_fingerprint).first() is None:
            db.add(CustomerName(
                customer_id=account.id,
                name=company_name.strip(),
                normalized_name=normalized_company_name,
                name_type=name_type,
                verification_status="candidate",
                confidence=Decimal("0.5000"),
                confidence_method_version="confidence_v1",
                confidence_components_json={
                    "source_authority": 0,
                    "independence": 0,
                    "exactness": 1,
                    "freshness": 1,
                    "conflict_penalty": 0,
                },
                source_record_id=source_record.id if source_record is not None else None,
                name_fingerprint=name_fingerprint,
                first_seen_at=now,
                last_seen_at=now,
                created_by=created_by,
                updated_by=created_by,
                created_at=now,
                updated_at=now,
            ))
            changed = True

    policies = tuple(_policy_for_candidate(source_system, item, source_record) for item in candidates)
    contact_needed = bool(
        contact_name or normalized_email or any(item.subject_type == "contact" for item in policies)
    )
    contact: CustomerContact | None = None
    if contact_needed:
        existing_relations = db.query(CustomerContactRelationship).filter(
            CustomerContactRelationship.customer_id == account.id,
            CustomerContactRelationship.effective_to.is_(None),
        ).all()
        for relation in existing_relations:
            expected = _sha256((
                "contact_relationship_v1",
                account.id,
                relation.contact_id,
                "buyer",
                context_ref,
                "",
            ))
            if relation.relationship_fingerprint == expected:
                contact = db.get(CustomerContact, relation.contact_id)
                break
        if contact is None:
            contact = _create_contact(
                db,
                contact_name=contact_name,
                candidates=candidates,
                source_system=source_system,
                source_account_key=source_account_key,
                source_record=source_record,
                created_by=created_by,
                now=now,
            )
        if contact is None:
            raise CustomerDomainError("IDENTITY_SUBJECT_INVALID")
        if (
            contact_name
            and contact.display_name == "待识别联系人"
            and contact.normalized_name is None
        ):
            contact.display_name = contact_name.strip()
            contact.normalized_name = _normalize_name(contact_name)
            contact.updated_by = created_by
            contact.updated_at = now
            changed = True
        relationship_fingerprint = _sha256((
            "contact_relationship_v1",
            account.id,
            contact.id,
            "buyer",
            context_ref,
            "",
        ))
        if db.query(CustomerContactRelationship.id).filter_by(
            relationship_fingerprint=relationship_fingerprint,
        ).first() is None:
            db.add(CustomerContactRelationship(
                customer_id=account.id,
                contact_id=contact.id,
                relationship_type="buyer",
                buying_role="unknown",
                influence_level="unknown",
                verification_status="identified",
                confidence=Decimal("0.8000"),
                confidence_method_version="confidence_v1",
                confidence_components_json={
                    "explicit_employment": 0,
                    "source_authority": 0,
                    "independence": 0,
                    "temporal_fit": 1,
                    "conflict_penalty": 0,
                },
                relationship_fingerprint=relationship_fingerprint,
                created_by=created_by,
                updated_by=created_by,
                created_at=now,
                updated_at=now,
            ))
            db.flush()
            changed = True
        if resolution.contact_id is None:
            resolution.contact_id = contact.id

    point: CustomerContactPoint | None = None
    if contact is not None and normalized_email:
        email_domain = normalized_email.rsplit("@", 1)[1]
        point_fingerprint = _sha256((
            "contact_point_v1",
            "contact",
            contact.id,
            "email",
            "",
            normalized_email,
            context_ref,
        ))
        point = db.query(CustomerContactPoint).filter_by(
            point_fingerprint=point_fingerprint,
        ).one_or_none()
        if point is None:
            point = CustomerContactPoint(
                contact_id=contact.id,
                point_type="email",
                raw_value=contact_email,
                normalized_value=normalized_email,
                email_domain_type="free" if email_domain in _FREE_EMAIL_DOMAINS else "unknown",
                verification_status="unknown",
                contactability_status="unknown",
                contactability_reason_code="unknown",
                contactability_source="import",
                contactability_effective_at=now,
                is_primary=True,
                data_classification="personal_contact",
                source_record_id=source_record.id if source_record is not None else None,
                point_fingerprint=point_fingerprint,
                first_seen_at=now,
                last_seen_at=now,
                created_by=created_by,
                updated_by=created_by,
                created_at=now,
                updated_at=now,
            )
            db.add(point)
            db.flush()
            changed = True

    for candidate, policy in zip(candidates, policies, strict=True):
        if policy.subject_type == "contact" and contact is None:
            raise CustomerDomainError("IDENTITY_SUBJECT_INVALID")
        identity, created = _attach_identity_candidate(
            db,
            customer_id=account.id if policy.subject_type == "customer" else None,
            contact_id=contact.id if policy.subject_type == "contact" else None,
            source_system=source_system,
            source_account_key=source_account_key,
            identifier_type=candidate.identifier_type,
            raw_value=candidate.raw_value,
            source_record_id=source_record.id if source_record is not None else None,
            verification_status=candidate.verification_status,
            confidence=candidate.confidence,
            is_primary=candidate.is_primary,
            provider_declared_subject_type=candidate.provider_declared_subject_type,
            created_by=created_by,
            now=now,
            bump_profile=False,
        )
        changed = changed or created
        if (
            policy.subject_type == "customer"
            and candidate.verification_status == "verified"
            and policy.auto_match_ceiling in {"identified", "verified"}
            and _merge_account_identity(
                account,
                target_status=policy.auto_match_ceiling,
                confidence=identity.confidence,
            )
        ):
            changed = True

    if point is not None and (point.email_domain_type == "free" or personal_alias):
        research_fingerprint = _sha256((
            "identity_enrichment_v1",
            account.id,
            context_ref,
            "reverse_business_identity_v1",
        ))
        if db.query(CustomerResearchTask.id).filter_by(
            task_fingerprint=research_fingerprint,
        ).first() is None:
            email_domain = normalized_email.rsplit("@", 1)[1]
            db.add(CustomerResearchTask(
                customer_id=account.id,
                task_type="identity_enrichment",
                source_ref_type="source_record" if source_record is not None else source_entity_type,
                source_ref_id=str(source_record.id if source_record is not None else external_context_id),
                task_status="pending",
                gate_status="not_required",
                result_review_status="pending",
                selection_reason=[{
                    "reason": "personal_identity_requires_business_resolution",
                    "fact_ids": [],
                }],
                research_policy_version="reverse_business_identity_v1",
                task_fingerprint=research_fingerprint,
                input_snapshot={
                    "contact_id": contact.id,
                    "contact_point_id": point.id,
                    "contact_name": contact.display_name,
                    "email_domain": email_domain,
                    "email_local_part": normalized_email.split("@", 1)[0],
                    "allowed_research": [
                        "public_employment",
                        "official_company_page",
                        "public_business_social",
                        "public_storefront",
                    ],
                },
                data_classification="personal_contact",
                visibility_scope="customer_team",
                classification_reason="inherits personal contact identity seed",
                evidence_fact_ids=[],
                lease_generation=0,
                attempt_count=0,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            ))
            changed = True

    if is_new_account:
        account.profile_input_seq = 1
    elif changed:
        account.profile_input_seq = int(account.profile_input_seq) + 1
        account.updated_at = now
    db.flush()
    return contact


def _retryable_mysql_error(exc: OperationalError) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and args[0] in _RESOLUTION_RETRYABLE_MYSQL_CODES:
            return True
        for related in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return False


def _load_resolution_winner(db: Session, resolution_key: str) -> CustomerResolutionKey:
    try:
        row = db.query(CustomerResolutionKey).filter(
            CustomerResolutionKey.resolution_key == resolution_key,
        ).with_for_update().one_or_none()
    except OperationalError as exc:
        if _retryable_mysql_error(exc):
            raise CustomerTransactionRetryRequired() from exc
        raise
    if row is None:
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
    return row


def resolve_business_context(
    db: Session,
    *,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_context_id: str,
    source_record_id: int | None = None,
    company_name: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    identity_candidates: Sequence[IdentityCandidate] = (),
    created_by: int | None = None,
    worker_id: str = "inline",
    arbiter: ResolutionKeyArbiter | None = None,
    now: datetime | None = None,
) -> ResolvedBusinessContext:
    """Resolve a business context through insert-first transaction arbitration."""
    candidates = tuple(identity_candidates)
    reject_ascii_control_characters(
        source_system,
        source_account_key,
        source_entity_type,
        external_context_id,
        company_name,
        contact_name,
        contact_email,
        worker_id,
        tuple(
            (
                candidate.identifier_type,
                candidate.raw_value,
                candidate.verification_status,
                candidate.provider_declared_subject_type,
            )
            for candidate in candidates
        ),
    )
    if not all(isinstance(value, str) and value.strip() for value in (
        source_system,
        source_account_key,
        source_entity_type,
        external_context_id,
    )):
        raise CustomerDomainError("RESOLUTION_INPUT_INVALID")
    normalized_email = _normalize_email(contact_email) if contact_email else None
    now = now or beijing_now()
    source_record = _validate_source_record_for_resolution(
        db,
        source_record_id,
        source_system,
        source_account_key,
        source_entity_type,
    )
    resolution_type, resolution_key = _resolution_material(
        source_system=source_system,
        source_account_key=source_account_key,
        source_entity_type=source_entity_type,
        external_context_id=external_context_id,
        candidates=candidates,
        source_record=source_record,
    )
    arbiter = arbiter or DEFAULT_RESOLUTION_KEY_ARBITER

    try:
        with db.begin_nested():
            resolution = arbiter.try_claim(
                db,
                resolution_key=resolution_key,
                resolution_type=resolution_type,
                source_system=source_system,
                source_account_key=source_account_key,
                source_entity_type=source_entity_type,
                source_record_id=source_record_id,
                worker_id=worker_id,
                now=now,
            )
            if resolution is None:
                raise _ResolutionClaimLost
            matched_customer_id = _existing_verified_strong_customer_id(
                db,
                source_system=source_system,
                source_account_key=source_account_key,
                candidates=candidates,
                source_record=source_record,
            )
            if matched_customer_id is None and resolution_type == "strong_identity":
                prior_context_key = _sha256((
                    "business_context_v1",
                    source_system,
                    source_account_key,
                    source_entity_type,
                    external_context_id,
                ))
                prior_context = db.query(CustomerResolutionKey).filter(
                    CustomerResolutionKey.resolution_key == prior_context_key,
                    CustomerResolutionKey.status == "resolved",
                    CustomerResolutionKey.customer_id.is_not(None),
                ).with_for_update().one_or_none()
                if prior_context is not None:
                    matched_customer_id = prior_context.customer_id
            created = matched_customer_id is None
            account = (
                _new_account(
                    db,
                    resolution_key=resolution_key,
                    company_name=company_name,
                    contact_name=contact_name,
                    created_by=created_by,
                    now=now,
                )
                if created
                else _account_for_update(db, matched_customer_id)
            )
            contact = _apply_context_material(
                db,
                account=account,
                resolution=resolution,
                source_system=source_system,
                source_account_key=source_account_key,
                source_entity_type=source_entity_type,
                external_context_id=external_context_id,
                source_record=source_record,
                company_name=company_name,
                contact_name=contact_name,
                contact_email=contact_email,
                normalized_email=normalized_email,
                candidates=candidates,
                created_by=created_by,
                now=now,
                is_new_account=created,
            )
            resolution.customer_id = account.id
            resolution.contact_id = resolution.contact_id or (contact.id if contact else None)
            resolution.status = "resolved"
            resolution.updated_at = now
            db.flush()
            return ResolvedBusinessContext(account, contact, resolution, created)
    except OperationalError as exc:
        if _retryable_mysql_error(exc):
            raise CustomerTransactionRetryRequired() from exc
        raise
    except _ResolutionClaimLost:
        winner = _load_resolution_winner(db, resolution_key)
        context = _load_resolved_context(db, winner)
        with db.begin_nested():
            contact = _apply_context_material(
                db,
                account=context.customer,
                resolution=winner,
                source_system=source_system,
                source_account_key=source_account_key,
                source_entity_type=source_entity_type,
                external_context_id=external_context_id,
                source_record=source_record,
                company_name=company_name,
                contact_name=contact_name,
                contact_email=contact_email,
                normalized_email=normalized_email,
                candidates=candidates,
                created_by=created_by,
                now=now,
                is_new_account=False,
            )
        return ResolvedBusinessContext(context.customer, contact or context.contact, winner, False)


class _ResolutionClaimLost(Exception):
    pass


def _verified_strong_resolution_key(identity: CustomerExternalIdentity) -> str:
    return _sha256((
        "strong_identity_v1",
        identity.source_system,
        identity.source_account_key,
        identity.identifier_type,
        identity.normalized_value,
    ))


def _claim_identity_confirmation(
    db: Session,
    *,
    identity: CustomerExternalIdentity,
    arbiter: ResolutionKeyArbiter,
    now: datetime,
) -> tuple[CustomerResolutionKey, bool]:
    resolution_key = _verified_strong_resolution_key(identity)
    try:
        resolution = arbiter.try_claim(
            db,
            resolution_key=resolution_key,
            resolution_type="strong_identity",
            source_system=identity.source_system,
            source_account_key=identity.source_account_key,
            source_entity_type="company" if identity.customer_id is not None else "buyer",
            source_record_id=identity.source_record_id,
            worker_id=f"identity:{identity.id}",
            now=now,
        )
    except OperationalError as exc:
        if _retryable_mysql_error(exc):
            raise CustomerTransactionRetryRequired() from exc
        raise
    created = resolution is not None
    if resolution is None:
        resolution = _load_resolution_winner(db, resolution_key)
    else:
        resolution.customer_id = identity.customer_id
        resolution.contact_id = identity.contact_id
        resolution.status = "resolved"
        resolution.updated_at = now
        db.flush()
    return resolution, created


def _resolution_has_other_subject(
    resolution: CustomerResolutionKey,
    identity: CustomerExternalIdentity,
) -> bool:
    if identity.customer_id is not None:
        return resolution.customer_id != identity.customer_id
    return resolution.contact_id != identity.contact_id


def _sync_verified_identity_subject(
    db: Session,
    *,
    identity: CustomerExternalIdentity,
    now: datetime,
) -> bool:
    if identity.auto_match_ceiling not in {"identified", "verified"}:
        return False
    target = "verified" if identity.auto_match_ceiling == "verified" else "identified"
    if identity.customer_id is not None:
        account = _account_for_update(db, identity.customer_id)
        return _merge_account_identity(
            account,
            target_status=target,
            confidence=identity.confidence,
        )
    contact = db.query(CustomerContact).filter(
        CustomerContact.id == identity.contact_id,
        CustomerContact.record_status == "active",
    ).with_for_update().one_or_none()
    if contact is None:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if contact.identity_status == target and contact.confidence == identity.confidence:
        return False
    contact.identity_status = target
    contact.confidence = identity.confidence
    contact.updated_at = now
    return True


def confirm_identity(
    db: Session,
    identity_id: int,
    *,
    verified_by: int | None = None,
    arbiter: ResolutionKeyArbiter | None = None,
    now: datetime | None = None,
) -> IdentityConfirmationResult:
    """Verify one identity, surfacing strong-key collisions as review state."""
    now = now or beijing_now()
    identity = (
        db.query(CustomerExternalIdentity)
        .filter(CustomerExternalIdentity.id == identity_id)
        .with_for_update()
        .one_or_none()
    )
    if identity is None or identity.status not in {"active", "disputed"}:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    affected_ids = set(_identity_customer_ids(db, identity))
    if not affected_ids:
        raise CustomerDomainError("CUSTOMER_REFERENCE_INVALID")
    if identity.verification_status == "disputed" or identity.status == "disputed":
        disputed_ids = tuple(
            row[0]
            for row in db.query(CustomerExternalIdentity.id).filter(
                CustomerExternalIdentity.source_system == identity.source_system,
                CustomerExternalIdentity.source_account_key == identity.source_account_key,
                CustomerExternalIdentity.identifier_type == identity.identifier_type,
                CustomerExternalIdentity.normalized_value == identity.normalized_value,
                CustomerExternalIdentity.id != identity.id,
                CustomerExternalIdentity.status == "disputed",
            ).order_by(CustomerExternalIdentity.id).all()
        )
        return IdentityConfirmationResult(identity, True, disputed_ids)

    confirmation_resolution: CustomerResolutionKey | None = None
    arbitration_conflict = False
    if identity.identity_strength == "strong" and identity.cardinality == "one_to_one":
        confirmation_resolution, _created = _claim_identity_confirmation(
            db,
            identity=identity,
            arbiter=arbiter or DEFAULT_RESOLUTION_KEY_ARBITER,
            now=now,
        )
        arbitration_conflict = _resolution_has_other_subject(
            confirmation_resolution,
            identity,
        )

    conflicts: list[CustomerExternalIdentity] = []
    if identity.identity_strength == "strong" and identity.cardinality == "one_to_one":
        query = db.query(CustomerExternalIdentity).filter(
            CustomerExternalIdentity.source_system == identity.source_system,
            CustomerExternalIdentity.source_account_key == identity.source_account_key,
            CustomerExternalIdentity.identifier_type == identity.identifier_type,
            CustomerExternalIdentity.normalized_value == identity.normalized_value,
            CustomerExternalIdentity.id != identity.id,
            CustomerExternalIdentity.verification_status == "verified",
            CustomerExternalIdentity.status.in_(("active", "disputed")),
        )
        if identity.customer_id is not None:
            query = query.filter(
                (CustomerExternalIdentity.customer_id.is_(None))
                | (CustomerExternalIdentity.customer_id != identity.customer_id)
            )
        else:
            query = query.filter(
                (CustomerExternalIdentity.contact_id.is_(None))
                | (CustomerExternalIdentity.contact_id != identity.contact_id)
            )
        conflicts = query.with_for_update().order_by(CustomerExternalIdentity.id).all()

    if arbitration_conflict and not conflicts:
        raise CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")

    if conflicts:
        identity.verification_status = "disputed"
        identity.status = "disputed"
        identity.verified_by = verified_by
        identity.updated_by = verified_by
        identity.updated_at = now
        for conflict in conflicts:
            conflict.verification_status = "disputed"
            conflict.status = "disputed"
            conflict.updated_at = now
            affected_ids.update(_identity_customer_ids(db, conflict))
        disputed_identities = [identity, *conflicts]
        contact_ids = {
            row.contact_id for row in disputed_identities if row.contact_id is not None
        }
        customer_ids = {
            row.customer_id for row in disputed_identities if row.customer_id is not None
        }
        for contact_id in contact_ids:
            contact = db.query(CustomerContact).filter(
                CustomerContact.id == contact_id,
                CustomerContact.record_status == "active",
            ).with_for_update().one_or_none()
            if contact is not None:
                contact.identity_status = "disputed"
                contact.confidence = Decimal("0.0000")
                contact.updated_at = now
        for customer_id in customer_ids:
            account = _account_for_update(db, customer_id)
            account.identity_status = "disputed"
            account.identity_confidence = Decimal("0.0000")
        if confirmation_resolution is not None:
            confirmation_resolution.status = "conflict"
            confirmation_resolution.updated_at = now
        _bump_accounts(db, affected_ids)
        db.flush()
        return IdentityConfirmationResult(
            identity,
            True,
            tuple(row.id for row in conflicts),
        )

    if identity.verification_status == "verified" and identity.status == "active":
        if _sync_verified_identity_subject(db, identity=identity, now=now):
            _bump_accounts(db, affected_ids)
            db.flush()
        return IdentityConfirmationResult(identity, False)

    identity.verification_status = "verified"
    identity.status = "active"
    identity.verified_at = now
    identity.verified_by = verified_by
    identity.updated_by = verified_by
    identity.updated_at = now
    _sync_verified_identity_subject(db, identity=identity, now=now)
    _bump_accounts(db, affected_ids)
    db.flush()
    return IdentityConfirmationResult(identity, False)


__all__ = [
    "CustomerDomainError",
    "CustomerTransactionRetryRequired",
    "IdentityCandidate",
    "IdentityConfirmationResult",
    "ResolvedBusinessContext",
    "ResolutionKeyArbiter",
    "attach_identity_candidate",
    "confirm_identity",
    "reject_ascii_control_characters",
    "resolve_business_context",
]
