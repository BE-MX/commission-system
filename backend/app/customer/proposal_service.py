"""Deterministic governance lifecycle for high-impact customer changes."""

from __future__ import annotations

import secrets
from collections.abc import Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, to_beijing_naive
from app.customer.models import (
    CustomerAccount,
    CustomerChangeProposal,
    CustomerFact,
    CustomerProfileVersion,
)
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.proposal_hash_service import (
    ProposalActionHashConflict, apply_action_hash_updates,
    canonical_action_hash, is_action_hash_unique_conflict,
)
from app.customer.schemas import validate_proposal_action_payload

_is_action_hash_unique_conflict = is_action_hash_unique_conflict


class ProposalError(ValueError):
    pass


class ProposalNotFound(ProposalError):
    pass


class ProposalConflict(ProposalError):
    pass


SUPPORTED_EXECUTORS = {
    "merge", "split", "assign_primary", "transfer_primary",
    "set_dnc", "remove_dnc", "confirm_material_risk",
}
OWNERSHIP_ACTIONS = {"merge", "split"}
GOVERNANCE_ACTIONS = {"set_dnc", "remove_dnc", "confirm_material_risk"}


def _require_current_action_hash(
    row: CustomerChangeProposal, *, require_approval: bool = False,
) -> None:
    current = canonical_action_hash(
        action_type=row.action_type, customer_id=row.customer_id,
        target_customer_id=row.target_customer_id,
        payload_json=row.payload_json,
        profile_version_id=row.profile_version_id,
        evidence_fact_ids=list(row.evidence_fact_ids or []),
    )
    if not secrets.compare_digest(current, row.action_hash):
        raise ProposalConflict("PROPOSAL_ACTION_HASH_INVALID")
    if require_approval and (
        not row.approved_action_hash
        or not secrets.compare_digest(row.approved_action_hash, row.action_hash)
    ):
        raise ProposalConflict("PROPOSAL_APPROVAL_INVALID")


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
        logical_root_predicate(CustomerFact, "fact", customer_id),
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
    account = _validate_live_basis(
        db, customer_id=customer_id, profile_version_id=profile_version_id,
        evidence_fact_ids=evidence, lock=False,
    )
    try:
        validate_proposal_action_payload(
            db, account=account, action_type=action_type,
            payload_schema_version=payload_schema_version, payload_json=payload_json,
            customer_id=customer_id, target_customer_id=target_customer_id,
            profile_version_id=profile_version_id, evidence_fact_ids=evidence,
        )
    except ValueError as exc:
        raise ProposalConflict("PROPOSAL_PAYLOAD_INVALID") from exc
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
        if not is_action_hash_unique_conflict(exc):
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
    _require_current_action_hash(row)
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
    _require_current_action_hash(row)
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


def rebase_proposal(
    db: Session, *, proposal_id: int, actor_user_id: int,
    profile_version_id: int, evidence_fact_ids: list[int],
) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    _require_active_human(db, actor_user_id)
    _require_current_action_hash(row)
    if (
        row.action_type not in {"assign_primary", "transfer_primary"}
        or row.status != "draft"
        or row.approved_action_hash is not None
        or row.decided_by is not None
        or row.decided_at is not None
        or row.execution_idempotency_key is not None
        or row.executed_by is not None
        or row.executed_at is not None
    ):
        raise ProposalConflict("PROPOSAL_REBASE_INVALID")
    evidence = sorted(set(evidence_fact_ids))
    _validate_live_basis(
        db, customer_id=row.customer_id, profile_version_id=profile_version_id,
        evidence_fact_ids=evidence, lock=True,
    )
    action_hash = canonical_action_hash(
        action_type=row.action_type, customer_id=row.customer_id,
        target_customer_id=row.target_customer_id,
        payload_json=dict(row.payload_json or {}),
        profile_version_id=profile_version_id, evidence_fact_ids=evidence,
    )
    try:
        apply_action_hash_updates(db, [(row, action_hash, {
            "profile_version_id": profile_version_id,
            "evidence_fact_ids": evidence, "updated_at": beijing_now(),
        })], savepoint=True)
    except ProposalActionHashConflict as exc:
        raise ProposalConflict("PROPOSAL_ACTION_HASH_CONFLICT") from exc
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


def _require_active_human(db: Session, actor_user_id: int) -> None:
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise ProposalConflict("PROPOSAL_ACTOR_INVALID")
    actor = db.query(ArkUser.id).filter(
        ArkUser.id == actor_user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if actor is None:
        raise ProposalConflict("PROPOSAL_ACTOR_INVALID")


def _redirect_open_proposals(db: Session, row: CustomerChangeProposal) -> None:
    plan = (row.payload_json or {}).get("proposal_redirects")
    if not isinstance(plan, list):
        raise ProposalConflict("PROPOSAL_REDIRECT_PLAN_INVALID")
    by_id: dict[int, tuple[int, int]] = {}
    for item in plan:
        if (
            not isinstance(item, Mapping)
            or set(item) != {
                "proposal_id", "target_customer_id", "target_profile_version_id",
            }
            or any(type(item[key]) is not int or item[key] <= 0 for key in item)
            or item["proposal_id"] == row.id
            or item["proposal_id"] in by_id
        ):
            raise ProposalConflict("PROPOSAL_REDIRECT_PLAN_INVALID")
        by_id[item["proposal_id"]] = (
            item["target_customer_id"], item["target_profile_version_id"],
        )
    if not by_id:
        return
    payload = row.payload_json or {}
    affected = {row.customer_id, *(payload.get("target_customer_ids") or [])}
    redirects = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id.in_(by_id),
        CustomerChangeProposal.status.in_(("draft", "pending", "approved")),
    ).order_by(CustomerChangeProposal.id).with_for_update().all()
    if {item.id for item in redirects} != set(by_id):
        raise ProposalConflict("PROPOSAL_REDIRECT_PLAN_INVALID")
    now = beijing_now()
    updates = []
    for redirect in redirects:
        if (
            redirect.action_type not in {"assign_primary", "transfer_primary"}
            or
            redirect.customer_id not in affected
            and redirect.target_customer_id not in affected
        ):
            raise ProposalConflict("PROPOSAL_REDIRECT_PLAN_INVALID")
        target_customer_id, target_profile_version_id = by_id[redirect.id]
        profile = db.query(CustomerProfileVersion.id).filter(
            CustomerProfileVersion.id == target_profile_version_id,
            CustomerProfileVersion.customer_id == target_customer_id,
        ).one_or_none()
        if profile is None:
            raise ProposalConflict("PROPOSAL_REDIRECT_PLAN_INVALID")
        action_hash = canonical_action_hash(
            action_type=redirect.action_type,
            customer_id=target_customer_id,
            target_customer_id=redirect.target_customer_id,
            payload_json=dict(redirect.payload_json or {}),
            profile_version_id=target_profile_version_id,
            evidence_fact_ids=list(redirect.evidence_fact_ids or []),
        )
        updates.append((redirect, action_hash, {
            "customer_id": target_customer_id,
            "profile_version_id": target_profile_version_id,
            "approved_action_hash": None, "decided_by": None, "decided_at": None,
            "execution_idempotency_key": None, "executed_by": None,
            "executed_at": None, "status": "draft", "updated_at": now,
        }))
    try:
        apply_action_hash_updates(db, updates, savepoint=False)
    except ProposalActionHashConflict as exc:
        raise ProposalConflict("PROPOSAL_ACTION_HASH_CONFLICT") from exc


def _execute_ownership(
    db: Session, *, row: CustomerChangeProposal, actor_user_id: int,
    idempotency_key: str,
) -> CustomerChangeProposal:
    from app.customer.ownership_execution_service import (
        OwnershipExecutionError, execute_customer_ownership_change,
    )
    from app.customer.workflow_service import supersede_related_proposals

    try:
        _redirect_open_proposals(db, row)
        result = execute_customer_ownership_change(
            db, proposal_id=row.id, actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
        )
        supersede_related_proposals(
            db, executing_proposal_id=row.id,
            expected_execution_idempotency_key=idempotency_key,
            declared_plan=result.open_proposal_plan.get("supersede", []),
        )
        return db.get(CustomerChangeProposal, row.id)
    except OwnershipExecutionError as exc:
        db.rollback()
        raise ProposalConflict(exc.error_code) from exc
    except Exception:
        db.rollback()
        raise


def execute_proposal(
    db: Session, *, proposal_id: int, actor_user_id: int, idempotency_key: str,
) -> CustomerChangeProposal:
    row = _locked(db, proposal_id)
    _require_current_action_hash(row, require_approval=True)
    _require_active_human(db, actor_user_id)
    if row.status == "executed":
        if row.execution_idempotency_key and secrets.compare_digest(
            row.execution_idempotency_key, idempotency_key,
        ) and row.executed_by == actor_user_id:
            return row
        if row.execution_idempotency_key and secrets.compare_digest(
            row.execution_idempotency_key, idempotency_key,
        ):
            raise ProposalConflict("PROPOSAL_EXECUTION_ACTOR_MISMATCH")
        raise ProposalConflict("PROPOSAL_EXECUTION_KEY_MISMATCH")
    if row.status != "approved":
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
    if row.action_type in OWNERSHIP_ACTIONS:
        return _execute_ownership(
            db, row=row, actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
        )
    if row.action_type in GOVERNANCE_ACTIONS:
        from app.customer.governance_policy_service import (
            GovernancePolicyError, execute_governance_policy,
        )
        try:
            result = execute_governance_policy(
                db, proposal_id=row.id, actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
            )
        except GovernancePolicyError as exc:
            raise ProposalConflict(str(exc)) from exc
        return result.proposal
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
