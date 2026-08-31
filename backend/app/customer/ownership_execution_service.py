"""Atomic pairwise merge/split executor over immutable storage ownership."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
from typing import Any, Mapping

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer import models
from app.customer.ownership_execution_apply import (
    ExecutionPostconditionError,
    apply_transition_plan,
    invalidate_projections,
    validate_postconditions,
)
from app.customer.ownership_contract_service import PARTITION_KEYS
from app.customer.ownership_execution_contract import (
    ExecutionContractError,
    ROOT_MODELS,
    build_execution_basis,
    validate_execution_contract,
)
from app.customer.ownership_service import (
    CustomerOwnershipError,
    CustomerOwnershipRetryRequired,
    compare_and_set_effective_owner,
)


class OwnershipExecutionError(ValueError):
    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class OwnershipExecutionResult:
    proposal_id: int
    action_type: str
    affected_customer_ids: tuple[int, ...]
    open_proposal_plan: dict[str, list[dict[str, object]]]


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(item) for item in parts).encode()).hexdigest()


def _valid_idempotency_key(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and value.isascii()


def _result(
    proposal: models.CustomerChangeProposal,
    payload: Mapping[str, Any],
    *, supersede: list[dict[str, object]] | None = None,
    frozen_plan: Mapping[str, Any] | None = None,
) -> OwnershipExecutionResult:
    if frozen_plan is None:
        redirects = [{
            "proposal_id": int(item["proposal_id"]),
            "target_customer_id": int(item["target_customer_id"]),
            "target_profile_version_id": int(item["target_profile_version_id"]),
            "next_status": "draft", "clear_approval": True, "rehash_required": True,
        } for item in payload["proposal_redirects"]]
        frozen_plan = {"redirect": redirects, "supersede": supersede or []}
    return OwnershipExecutionResult(
        proposal_id=int(proposal.id),
        action_type=proposal.action_type,
        affected_customer_ids=tuple(sorted({proposal.customer_id, *payload["target_customer_ids"]})),
        open_proposal_plan={
            "redirect": list(frozen_plan["redirect"]),
            "supersede": list(frozen_plan["supersede"]),
        },
    )


def _require_actor(db: Session, actor_user_id: int) -> ArkUser:
    actor = db.query(ArkUser).filter_by(id=actor_user_id).with_for_update().one_or_none()
    if actor is None or not actor.is_active or actor.deleted_at is not None:
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_ACTOR_INVALID")
    return actor


def _frozen_result(
    db: Session, proposal: models.CustomerChangeProposal, payload: Mapping[str, Any],
) -> OwnershipExecutionResult:
    event = db.query(models.CustomerEvent).filter_by(
        source_ref_type="change_proposal", source_ref_id=str(proposal.id),
        event_type="customer.merged" if proposal.action_type == "merge" else "customer.split",
    ).order_by(models.CustomerEvent.id).first()
    plan = event.event_payload.get("open_proposal_plan") if event else None
    if not isinstance(plan, Mapping) or set(plan) != {"redirect", "supersede"}:
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_RESULT_MISSING")
    return _result(proposal, payload, frozen_plan=plan)


def _lock_accounts(
    db: Session, proposal: models.CustomerChangeProposal, payload: Mapping[str, Any],
) -> list[models.CustomerAccount]:
    ids = sorted({proposal.customer_id, *payload["target_customer_ids"]})
    accounts = db.query(models.CustomerAccount).filter(
        models.CustomerAccount.id.in_(ids)
    ).order_by(models.CustomerAccount.id).with_for_update().all()
    if [int(row.id) for row in accounts] != ids:
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_TARGET_INVALID")
    by_id = {int(row.id): row for row in accounts}
    if by_id[proposal.customer_id].record_status != "active" or any(
        by_id[target_id].record_status != "active"
        for target_id in payload["target_customer_ids"]
    ):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_TARGET_INVALID")
    target_profiles = payload.get("target_profile_versions")
    if not isinstance(target_profiles, list):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PROFILE_STALE")
    expected_profiles = [{
        "customer_id": target_id,
        "profile_version_id": by_id[target_id].current_profile_version_id,
        "profile_input_seq": int(by_id[target_id].profile_input_seq),
    } for target_id in payload["target_customer_ids"]]
    if target_profiles != expected_profiles or (
        payload.get("source_profile_version_id")
        != by_id[proposal.customer_id].current_profile_version_id
        or payload.get("source_profile_input_seq")
        != by_id[proposal.customer_id].profile_input_seq
        or proposal.profile_version_id != payload.get("source_profile_version_id")
    ):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PROFILE_STALE")
    return accounts


def _lock_profiles_and_projections(
    db: Session, proposal: models.CustomerChangeProposal,
    payload: Mapping[str, Any], customer_ids: set[int],
) -> None:
    target_profiles = payload["target_profile_versions"]
    profile_ids = sorted({payload["source_profile_version_id"], *(
        item["profile_version_id"] for item in target_profiles)})
    profiles = db.query(models.CustomerProfileVersion).filter(
        models.CustomerProfileVersion.id.in_(profile_ids)
    ).order_by(models.CustomerProfileVersion.id).with_for_update().all()
    if {int(row.id) for row in profiles} != set(profile_ids):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PROFILE_STALE")
    profile_owners = {int(row.id): int(row.customer_id) for row in profiles}
    if profile_owners[payload["source_profile_version_id"]] != proposal.customer_id or any(
        profile_owners[item["profile_version_id"]] != item["customer_id"]
        for item in target_profiles
    ):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PROFILE_STALE")
    for model in (
        models.CustomerAgentContext, models.CustomerListProjection,
        models.CustomerTargetMatch,
    ):
        db.query(model).filter(model.customer_id.in_(customer_ids)).order_by(
            *model.__table__.primary_key.columns
        ).with_for_update().all()


def _lock_roots_and_transitions(db: Session) -> None:
    db.query(models.CustomerObjectOwnership).order_by(
        models.CustomerObjectOwnership.object_type,
        models.CustomerObjectOwnership.object_id,
    ).with_for_update().all()
    for model in ROOT_MODELS.values():
        db.query(model).order_by(model.id).with_for_update().all()
    transition_models = (
        models.CustomerAssignment,
        models.CustomerContactRelationship,
        models.CustomerRelationship,
        models.CustomerAnnotation,
        models.CustomerQualificationReview,
        models.CustomerResearchTask,
    )
    for model in transition_models:
        db.query(model).order_by(model.id).with_for_update().all()


def _lock_other_proposals(db: Session, proposal_id: int, customer_ids: set[int]) -> None:
    db.query(models.CustomerChangeProposal).filter(
        models.CustomerChangeProposal.id != proposal_id,
        (models.CustomerChangeProposal.customer_id.in_(customer_ids))
        | (models.CustomerChangeProposal.target_customer_id.in_(customer_ids))
    ).order_by(models.CustomerChangeProposal.id).with_for_update().all()


def _open_proposal_plan(
    db: Session, proposal: models.CustomerChangeProposal, payload: Mapping[str, Any],
) -> list[dict[str, object]]:
    affected = {proposal.customer_id, *payload["target_customer_ids"]}
    redirected = {int(item["proposal_id"]) for item in payload["proposal_redirects"]}
    rows = db.query(models.CustomerChangeProposal.id).filter(
        models.CustomerChangeProposal.id != proposal.id,
        models.CustomerChangeProposal.status.in_(("draft", "pending", "approved")),
        (models.CustomerChangeProposal.customer_id.in_(affected))
        | (models.CustomerChangeProposal.target_customer_id.in_(affected)),
    ).order_by(models.CustomerChangeProposal.id).all()
    return [
        {"proposal_id": int(row[0]), "next_status": "superseded"}
        for row in rows if int(row[0]) not in redirected
    ]


def _append_events(
    db: Session, proposal: models.CustomerChangeProposal, payload: Mapping[str, Any],
    actor_id: int, customer_ids: list[int], open_plan: Mapping[str, Any], now,
) -> None:
    event_type = "customer.merged" if proposal.action_type == "merge" else "customer.split"
    for customer_id in customer_ids:
        db.add(models.CustomerEvent(
            customer_id=customer_id, event_type=event_type, event_source="manual",
            source_ref_type="change_proposal", source_ref_id=str(proposal.id),
            event_title="客户合并" if proposal.action_type == "merge" else "客户拆分",
            event_summary=payload["reason_text"],
            event_payload={
                "schema_version": f"customer_{proposal.action_type}_executed_v1",
                "proposal_id": proposal.id, "source_customer_id": proposal.customer_id,
                "target_customer_ids": payload["target_customer_ids"],
                "reason_code": payload["reason_code"],
                "open_proposal_plan": dict(open_plan),
            },
            importance="critical", data_classification="restricted_internal",
            visibility_scope="management", classification_reason="high_impact_customer_change",
            evidence_fact_ids=payload["evidence_fact_ids"], actor_user_id=actor_id,
            occurred_at=now, ingested_at=now,
            event_fingerprint=_digest(event_type, proposal.id, customer_id), created_at=now,
        ))


def _execute(
    db: Session, *, proposal_id: int, actor_user_id: int, idempotency_key: str,
) -> OwnershipExecutionResult:
    if not _valid_idempotency_key(idempotency_key):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_KEY_INVALID")
    proposal = db.query(models.CustomerChangeProposal).filter_by(
        id=proposal_id
    ).with_for_update().one_or_none()
    if proposal is None:
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PROPOSAL_NOT_FOUND")
    payload = proposal.payload_json if isinstance(proposal.payload_json, Mapping) else {}
    if (
        payload.get("source_customer_id") != proposal.customer_id
        or payload.get("target_customer_ids") != [proposal.target_customer_id]
    ):
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_SCOPE_INVALID")
    if proposal.status == "executed":
        if not proposal.execution_idempotency_key or not secrets.compare_digest(
            proposal.execution_idempotency_key, idempotency_key
        ):
            raise OwnershipExecutionError("OWNERSHIP_EXECUTION_KEY_MISMATCH")
        if proposal.executed_by != actor_user_id:
            raise OwnershipExecutionError("OWNERSHIP_EXECUTION_ACTOR_MISMATCH")
        return _frozen_result(db, proposal, payload)
    if proposal.expires_at <= beijing_now():
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_APPROVAL_EXPIRED")
    accounts = _lock_accounts(db, proposal, payload)
    _require_actor(db, actor_user_id)
    affected = {int(row.id) for row in accounts}
    _lock_roots_and_transitions(db)
    _lock_profiles_and_projections(db, proposal, payload, affected)
    _lock_other_proposals(db, proposal.id, affected)
    try:
        payload, parsed = validate_execution_contract(db, proposal)
    except ExecutionContractError as exc:
        raise OwnershipExecutionError(exc.error_code) from exc
    result = _result(proposal, payload, supersede=_open_proposal_plan(db, proposal, payload))
    now = beijing_now()
    apply_transition_plan(db, parsed["transition_plan"], actor_user_id, now)
    for partition in payload["ownership_partitions"]:
        if set(partition) != PARTITION_KEYS:
            raise OwnershipExecutionError("OWNERSHIP_EXECUTION_PARTITION_INVALID")
        try:
            compare_and_set_effective_owner(
                db, object_type=partition["object_type"], object_id=partition["object_id"],
                storage_customer_id=partition["expected_storage_customer_id"],
                expected_current_customer_id=partition["expected_current_customer_id"],
                current_customer_id=partition["target_customer_id"],
                expected_version=partition["expected_ownership_version"],
                change_proposal_id=proposal.id, action_type=proposal.action_type,
            )
        except (CustomerOwnershipError, CustomerOwnershipRetryRequired) as exc:
            raise OwnershipExecutionError(exc.error_code) from exc
    by_id = {int(row.id): row for row in accounts}
    source = by_id[proposal.customer_id]
    if proposal.action_type == "merge":
        source.record_status = "merged"
        source.merged_into_customer_id = payload["keep_customer_id"]
    elif not payload["retain_source"]:
        source.record_status = "archived"
        source.merged_into_customer_id = None
    for account in accounts:
        account.profile_input_seq += 1
        account.current_profile_version_id = None
        account.profile_compiled_at = None
        account.updated_by = actor_user_id
        account.updated_at = now
    invalidate_projections(db, affected)
    try:
        validate_postconditions(db, payload, parsed["transition_plan"], proposal.action_type)
    except (ExecutionPostconditionError, ExecutionContractError) as exc:
        raise OwnershipExecutionError(exc.error_code) from exc
    _append_events(
        db, proposal, payload, actor_user_id, sorted(affected),
        result.open_proposal_plan, now,
    )
    proposal.status = "executed"
    proposal.execution_idempotency_key = idempotency_key
    proposal.executed_by = actor_user_id
    proposal.executed_at = now
    proposal.updated_at = now
    db.flush()
    return result


def execute_customer_ownership_change(db: Session, **kwargs) -> OwnershipExecutionResult:
    """Execute one approved merge/split atomically; caller owns successful commit."""
    try:
        return _execute(db, **kwargs)
    except OwnershipExecutionError:
        db.rollback()
        raise
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise OwnershipExecutionError("OWNERSHIP_EXECUTION_CONFLICT") from exc
    except Exception:
        db.rollback()
        raise


__all__ = [
    "OwnershipExecutionError",
    "OwnershipExecutionResult",
    "build_execution_basis",
    "execute_customer_ownership_change",
]
