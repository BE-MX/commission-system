"""Deterministic governance lifecycle for high-impact customer changes."""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.models import (
    CustomerAccount,
    CustomerChangeProposal,
    CustomerFact,
    CustomerProfileVersion,
)


class ProposalError(ValueError):
    pass


class ProposalNotFound(ProposalError):
    pass


class ProposalConflict(ProposalError):
    pass


SUPPORTED_EXECUTORS = {"assign_primary", "transfer_primary"}


def _is_action_hash_unique_conflict(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return (
        "action_hash" in message
        and ("unique" in message or "duplicate" in message)
    )


def canonical_action_hash(
    *, action_type: str, customer_id: int, target_customer_id: int | None,
    payload_json: dict, profile_version_id: int, evidence_fact_ids: list[int],
) -> str:
    body = {
        "action_type": action_type,
        "customer_id": customer_id,
        "target_customer_id": target_customer_id,
        "payload_json": payload_json,
        "profile_version_id": profile_version_id,
        "evidence_fact_ids": sorted(set(evidence_fact_ids)),
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_live_basis(
    db: Session, *, customer_id: int, profile_version_id: int,
    evidence_fact_ids: list[int], lock: bool,
) -> CustomerAccount:
    query = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    )
    account = (query.with_for_update() if lock else query).one_or_none()
    if account is None:
        raise ProposalConflict("PROPOSAL_CUSTOMER_INVALID")
    if account.current_profile_version_id != profile_version_id:
        raise ProposalConflict("PROPOSAL_PROFILE_STALE")
    profile = db.query(CustomerProfileVersion.id).filter(
        CustomerProfileVersion.id == profile_version_id,
        CustomerProfileVersion.customer_id == customer_id,
    ).one_or_none()
    if profile is None:
        raise ProposalConflict("PROPOSAL_PROFILE_INVALID")
    requested = set(evidence_fact_ids)
    if not requested:
        raise ProposalConflict("PROPOSAL_EVIDENCE_REQUIRED")
    rows = db.query(CustomerFact.id).filter(
        CustomerFact.customer_id == customer_id,
        CustomerFact.id.in_(requested),
        CustomerFact.verification_status.in_(("verified", "candidate", "unverified")),
        CustomerFact.effective_to.is_(None),
    ).all()
    if {row.id for row in rows} != requested:
        raise ProposalConflict("PROPOSAL_EVIDENCE_INVALID")
    return account


def create_proposal(
    db: Session, *, customer_id: int, target_customer_id: int | None,
    action_type: str, payload_schema_version: str, payload_json: dict,
    profile_version_id: int, evidence_fact_ids: list[int], risk_level: str,
    expires_at, proposed_by: int,
) -> CustomerChangeProposal:
    if action_type not in SUPPORTED_EXECUTORS:
        raise ProposalConflict("PROPOSAL_EXECUTOR_NOT_IMPLEMENTED")
    evidence = sorted(set(evidence_fact_ids))
    _validate_live_basis(
        db, customer_id=customer_id, profile_version_id=profile_version_id,
        evidence_fact_ids=evidence, lock=False,
    )
    action_hash = canonical_action_hash(
        action_type=action_type, customer_id=customer_id,
        target_customer_id=target_customer_id, payload_json=payload_json,
        profile_version_id=profile_version_id, evidence_fact_ids=evidence,
    )
    existing = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.action_hash == action_hash,
    ).one_or_none()
    if existing is not None:
        return existing
    expires = to_beijing_naive(expires_at)
    if expires <= beijing_now():
        raise ProposalConflict("PROPOSAL_EXPIRY_INVALID")
    row = CustomerChangeProposal(
        customer_id=customer_id,
        target_customer_id=target_customer_id,
        action_type=action_type,
        payload_schema_version=payload_schema_version,
        payload_json=payload_json,
        profile_version_id=profile_version_id,
        evidence_fact_ids=evidence,
        risk_level=risk_level,
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash=action_hash,
        expires_at=expires,
        status="draft",
        proposed_by=proposed_by,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        if not _is_action_hash_unique_conflict(exc):
            raise
        # MySQL REPEATABLE READ may retain the pre-insert snapshot after the
        # savepoint rollback, so querying the winner here can return a false miss.
        # End the caller transaction explicitly and require a fresh request.
        db.rollback()
        raise ProposalConflict("PROPOSAL_CREATE_RETRY_NEW_TRANSACTION") from exc
    return row


def _locked(db: Session, proposal_id: int) -> CustomerChangeProposal:
    row = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id == proposal_id,
    ).with_for_update().one_or_none()
    if row is None:
        raise ProposalNotFound("PROPOSAL_NOT_FOUND")
    return row


def submit_proposal(db: Session, *, proposal_id: int, actor_user_id: int) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    if row.status == "pending":
        return row
    if row.status != "draft":
        raise ProposalConflict("PROPOSAL_NOT_DRAFT")
    _validate_live_basis(
        db, customer_id=row.customer_id, profile_version_id=row.profile_version_id,
        evidence_fact_ids=list(row.evidence_fact_ids or []), lock=True,
    )
    row.status = "pending"
    row.updated_at = beijing_now()
    db.flush()
    return row


def approve_proposal(db: Session, *, proposal_id: int, actor_user_id: int) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    if row.status == "approved" and row.decided_by == actor_user_id:
        return row
    if row.status != "pending":
        raise ProposalConflict("PROPOSAL_NOT_PENDING")
    if row.proposed_by == actor_user_id:
        raise ProposalConflict("PROPOSAL_FOUR_EYES_REQUIRED")
    _validate_live_basis(
        db, customer_id=row.customer_id, profile_version_id=row.profile_version_id,
        evidence_fact_ids=list(row.evidence_fact_ids or []), lock=True,
    )
    if row.expires_at <= beijing_now():
        row.status = "expired"
        row.updated_at = beijing_now()
        db.flush()
        return row
    row.status = "approved"
    row.approved_action_hash = row.action_hash
    row.decided_by = actor_user_id
    row.decided_at = beijing_now()
    row.updated_at = row.decided_at
    db.flush()
    return row


def reject_proposal(db: Session, *, proposal_id: int, actor_user_id: int) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    if row.status == "rejected":
        return row
    if row.status not in {"pending", "approved"}:
        raise ProposalConflict("PROPOSAL_NOT_DECIDABLE")
    row.status = "rejected"
    row.approved_action_hash = None
    row.decided_by = actor_user_id
    row.decided_at = beijing_now()
    row.updated_at = row.decided_at
    db.flush()
    return row


def execute_proposal(
    db: Session, *, proposal_id: int, actor_user_id: int, idempotency_key: str,
) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    if row.status == "executed":
        if row.execution_idempotency_key and secrets.compare_digest(
            row.execution_idempotency_key, idempotency_key,
        ):
            return row
        raise ProposalConflict("PROPOSAL_EXECUTION_KEY_MISMATCH")
    if row.status != "approved" or not row.approved_action_hash or not secrets.compare_digest(
        row.approved_action_hash, row.action_hash,
    ):
        raise ProposalConflict("PROPOSAL_APPROVAL_INVALID")
    _validate_live_basis(
        db, customer_id=row.customer_id, profile_version_id=row.profile_version_id,
        evidence_fact_ids=list(row.evidence_fact_ids or []), lock=True,
    )
    if row.expires_at <= beijing_now():
        row.status = "expired"
        row.updated_at = beijing_now()
        db.flush()
        return row
    # Split requires a complete graph partition executor. Until that exists, preserving
    # approved is safer than falsely recording execution or partially redirecting proposals.
    if row.action_type == "split":
        raise ProposalConflict("SPLIT_DATA_EXECUTOR_NOT_IMPLEMENTED")
    payload = row.payload_json or {}
    if row.action_type in {"assign_primary", "transfer_primary"}:
        user_id = payload.get("user_id")
        reason = payload.get("reason")
        if type(user_id) is not int or user_id <= 0 or not isinstance(reason, str) or not reason.strip():
            raise ProposalConflict("PROPOSAL_PAYLOAD_INVALID")
        from app.customer.workflow_service import assign_customer, transfer_primary_owner
        if row.action_type == "assign_primary":
            assign_customer(
                db,
                customer_id=row.customer_id,
                user_id=user_id,
                assignment_role="primary",
                assignment_source="admin_assign",
                operated_by=actor_user_id,
                change_reason=reason.strip(),
            )
        else:
            transfer_primary_owner(
                db,
                customer_id=row.customer_id,
                new_user_id=user_id,
                operated_by=actor_user_id,
                change_reason=reason.strip(),
            )
    else:
        raise ProposalConflict("PROPOSAL_EXECUTOR_NOT_IMPLEMENTED")
    now = beijing_now()
    row.execution_idempotency_key = idempotency_key
    row.executed_by = actor_user_id
    row.executed_at = now
    row.status = "executed"
    row.updated_at = now
    db.flush()
    return row


def serialize_proposal(row: CustomerChangeProposal) -> dict:
    return {
        "proposal_id": row.id,
        "customer_id": row.customer_id,
        "target_customer_id": row.target_customer_id,
        "action_type": row.action_type,
        "payload_schema_version": row.payload_schema_version,
        "payload_json": row.payload_json,
        "profile_version_id": row.profile_version_id,
        "evidence_fact_ids": row.evidence_fact_ids,
        "risk_level": row.risk_level,
        "action_hash": row.action_hash,
        "status": row.status,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
