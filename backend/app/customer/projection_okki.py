"""OKKI customer and contact source-first projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Mapping

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.identity_service import (
    CustomerDomainError,
    CustomerTransactionRetryRequired,
    IdentityCandidate,
    resolve_business_context,
)
from app.customer.models import CustomerContactRelationship
from app.customer.projection_common import (
    ProjectionError,
    ProjectionReceipt,
    ProjectionRetryRequired,
    append_raw,
    bind_source,
    business_datetime,
    error_code,
    existing_contact_id,
    is_exact_processed_replay,
    normalized_identifier,
    optional_string,
    quarantine,
    raw_external_id,
    retryable_operational_error,
    safe_business_datetime,
    source_outcome,
    upsert_contact_email,
)
from app.customer.projection_okki_order import (
    okki_customer_identity,
    project_okki_order,
)


def project_okki_customer(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    try:
        return _project_okki_customer_from_source(
            db,
            source_account_key=source_account_key,
            payload=payload,
            sync_cursor=sync_cursor,
            captured_at=captured_at,
        )
    except ProjectionRetryRequired:
        db.rollback()
        raise


def _project_okki_customer_from_source(
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
    company_id = raw_external_id(payload, "company_id", "customer")
    source = append_raw(
        db,
        source_system="okki",
        source_account_key=account_key,
        source_entity_type="customer",
        external_record_id=company_id,
        schema_version="okki_customer_v1",
        payload=payload,
        occurred_at=safe_business_datetime(payload.get("updated_at")),
        captured_at=captured,
        sync_cursor=sync_cursor,
    )
    if is_exact_processed_replay([source]):
        if source.customer_id is None:
            raise ProjectionError("SOURCE_PROJECTION_STATE_INVALID")
        return ProjectionReceipt(
            "processed", source.id, outcome="unchanged",
            customer_id=source.customer_id,
        )
    try:
        with db.begin_nested():
            actual_id = normalized_identifier(
                payload.get("company_id"), "COMPANY_ID_INVALID"
            )
            observed = business_datetime(
                payload.get("updated_at"),
                "SOURCE_BUSINESS_TIME_INVALID",
                required=False,
            ) or source.captured_at
            context = resolve_business_context(
                db,
                source_system="okki",
                source_account_key=account_key,
                source_entity_type="company",
                external_context_id=actual_id,
                source_record_id=source.id,
                company_name=optional_string(
                    payload.get("company_name"), "COMPANY_NAME_INVALID"
                ),
                identity_candidates=[IdentityCandidate(
                    "company_id", actual_id, verification_status="verified",
                    confidence=Decimal("1.0000"), is_primary=True,
                )],
                worker_id=f"okki:{account_key}:customer:{actual_id}",
                now=observed,
            )
            source.processing_status = "processed"
            db.flush()
            return ProjectionReceipt(
                "processed", source.id, outcome=source_outcome(source),
                customer_id=context.customer.id,
            )
    except ProjectionRetryRequired:
        raise
    except CustomerTransactionRetryRequired as exc:
        raise ProjectionRetryRequired() from exc
    except IntegrityError:
        return quarantine(db, [source], "PROJECTION_CONSTRAINT_INVALID")
    except OperationalError as exc:
        if retryable_operational_error(exc):
            raise ProjectionRetryRequired() from exc
        raise
    except (ProjectionError, CustomerDomainError) as exc:
        return quarantine(db, [source], error_code(exc, "OKKI_CUSTOMER_INVALID"))


def project_okki_contact(
    db: Session,
    *,
    source_account_key: str,
    payload: Mapping,
    sync_cursor: str | None = None,
    captured_at: datetime | None = None,
) -> ProjectionReceipt:
    try:
        return _project_okki_contact_from_source(
            db,
            source_account_key=source_account_key,
            payload=payload,
            sync_cursor=sync_cursor,
            captured_at=captured_at,
        )
    except ProjectionRetryRequired:
        db.rollback()
        raise


def _project_okki_contact_from_source(
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
    external_id = raw_external_id(payload, "contact_id", "contact")
    source = append_raw(
        db, source_system="okki", source_account_key=account_key,
        source_entity_type="contact", external_record_id=external_id,
        schema_version="okki_contact_v1", payload=payload,
        occurred_at=safe_business_datetime(payload.get("updated_at")),
        captured_at=captured, sync_cursor=sync_cursor,
    )
    if is_exact_processed_replay([source]):
        contact_id = existing_contact_id(
            db, source_system="okki", source_account_key=account_key,
            identifier_type="contact_id", raw_value=payload.get("contact_id"),
        )
        if source.customer_id is None or contact_id is None:
            raise ProjectionError("SOURCE_PROJECTION_STATE_INVALID")
        return ProjectionReceipt(
            "processed", source.id, outcome="unchanged",
            customer_id=source.customer_id, contact_id=contact_id,
        )
    try:
        with db.begin_nested():
            contact_id = normalized_identifier(
                payload.get("contact_id"), "CONTACT_ID_INVALID"
            )
            company_id = normalized_identifier(
                payload.get("company_id"), "COMPANY_ID_INVALID"
            )
            account = okki_customer_identity(
                db, source_account_key=account_key, company_id=company_id,
            )
            contact_name = optional_string(
                payload.get("contact_name"), "CONTACT_NAME_INVALID"
            )
            occurred = business_datetime(
                payload.get("updated_at"),
                "SOURCE_BUSINESS_TIME_INVALID",
                required=False,
            ) or source.occurred_at or source.captured_at
            known_contact_id = existing_contact_id(
                db, source_system="okki", source_account_key=account_key,
                identifier_type="contact_id", raw_value=contact_id,
            )
            stale = _stale_contact_move(
                db, contact_id=known_contact_id, target_customer_id=account.id,
                occurred_at=occurred,
            ) if known_contact_id is not None else False
            if stale:
                bind_source(source, account.id)
                source.processing_status = "processed"
                db.flush()
                return ProjectionReceipt(
                    "processed", source.id, outcome=source_outcome(source),
                    customer_id=account.id, contact_id=known_contact_id,
                )
            context = resolve_business_context(
                db,
                source_system="okki",
                source_account_key=account_key,
                source_entity_type="contact",
                external_context_id=contact_id,
                source_record_id=source.id,
                contact_name=contact_name or "待识别联系人",
                contact_email=None,
                identity_candidates=[
                    IdentityCandidate(
                        "company_id", company_id,
                        verification_status="verified",
                        confidence=Decimal("1.0000"), is_primary=True,
                    ),
                    IdentityCandidate(
                        "contact_id", contact_id,
                        verification_status="verified",
                        confidence=Decimal("1.0000"), is_primary=True,
                    ),
                ],
                worker_id=f"okki:{account_key}:contact:{contact_id}",
                now=occurred,
            )
            if context.customer.id != account.id or context.contact is None:
                raise ProjectionError("CONTACT_CUSTOMER_MISMATCH")
            contact = context.contact
            bind_source(source, account.id)
            upsert_contact_email(
                db, contact_id=contact.id, raw_email=payload.get("email"),
                source_record=source,
                fingerprint_scope=f"okki:{account_key}:contact:{contact_id}",
                now=occurred,
            )
            candidate = db.query(CustomerContactRelationship).filter(
                CustomerContactRelationship.customer_id == account.id,
                CustomerContactRelationship.contact_id == contact.id,
                CustomerContactRelationship.relationship_type == "buyer",
                CustomerContactRelationship.effective_to.is_(None),
            ).with_for_update().one_or_none()
            if candidate is None:
                raise ProjectionError("CONTACT_RELATIONSHIP_STATE_INVALID")
            candidate.job_title = optional_string(
                payload.get("job_title"), "JOB_TITLE_INVALID"
            )
            if candidate.verification_status != "verified":
                candidate.verification_status = "identified"
            candidate.effective_from = candidate.effective_from or occurred
            candidate.updated_at = max(candidate.updated_at, occurred)
            prior_relations = db.query(CustomerContactRelationship).filter(
                CustomerContactRelationship.contact_id == contact.id,
                CustomerContactRelationship.customer_id != account.id,
                CustomerContactRelationship.relationship_type == "buyer",
                CustomerContactRelationship.effective_to.is_(None),
            ).with_for_update().all()
            for prior in prior_relations:
                prior.effective_to = occurred
                prior.updated_at = occurred
            source.processing_status = "processed"
            db.flush()
            return ProjectionReceipt(
                "processed", source.id, outcome=source_outcome(source),
                customer_id=account.id, contact_id=contact.id,
            )
    except ProjectionRetryRequired:
        raise
    except CustomerTransactionRetryRequired as exc:
        raise ProjectionRetryRequired() from exc
    except IntegrityError:
        return quarantine(db, [source], "PROJECTION_CONSTRAINT_INVALID")
    except OperationalError as exc:
        if retryable_operational_error(exc):
            raise ProjectionRetryRequired() from exc
        raise
    except (ProjectionError, CustomerDomainError) as exc:
        return quarantine(db, [source], error_code(exc, "OKKI_CONTACT_INVALID"))


def _stale_contact_move(
    db: Session,
    *,
    contact_id: int,
    target_customer_id: int,
    occurred_at: datetime,
) -> bool:
    relations = db.query(CustomerContactRelationship).filter(
        CustomerContactRelationship.contact_id == contact_id,
        CustomerContactRelationship.relationship_type == "buyer",
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_((
            "identified", "verified",
        )),
    ).with_for_update().all()
    for relation in relations:
        relation_time = (
            relation.effective_from or relation.updated_at or relation.created_at
        )
        if relation.customer_id != target_customer_id and relation_time == occurred_at:
            raise ProjectionError("CONTACT_RELATIONSHIP_TIME_CONFLICT")
        if relation.customer_id != target_customer_id and relation_time > occurred_at:
            return True
    return False


__all__ = ["project_okki_contact", "project_okki_customer", "project_okki_order"]
