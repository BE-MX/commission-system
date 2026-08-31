"""Versioned governance contracts for logical customer ownership changes."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Mapping

from app.core.time import beijing_now
from app.customer.contracts import (
    OBJECT_OWNERSHIP_REGISTRY,
    OBJECT_OWNERSHIP_REGISTRY_VERSION,
)
from app.customer.models import (
    CustomerAnnotation,
    CustomerChangeProposal,
    CustomerResearchTask,
)
from app.customer.proposal_service import canonical_action_hash


PARTITION_KEYS = frozenset({
    "object_type",
    "object_id",
    "expected_storage_customer_id",
    "expected_current_customer_id",
    "expected_ownership_version",
    "target_customer_id",
})
TERMINAL_RESEARCH_TASK_STATUSES = frozenset({
    "completed",
    "failed",
    "skipped",
    "cancelled",
})


class OwnershipContractError(ValueError):
    def __init__(self, error_code: str, message: str = "Ownership contract rejected"):
        super().__init__(error_code)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True, slots=True)
class OwnershipPartition:
    object_type: str
    object_id: int
    expected_storage_customer_id: int
    expected_current_customer_id: int
    expected_ownership_version: int
    target_customer_id: int


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _parse_partition(value: object) -> OwnershipPartition:
    if not isinstance(value, Mapping) or set(value) != PARTITION_KEYS:
        raise OwnershipContractError("OWNERSHIP_PARTITION_INVALID")
    object_type = value.get("object_type")
    object_id = value.get("object_id")
    storage_customer_id = value.get("expected_storage_customer_id")
    current_customer_id = value.get("expected_current_customer_id")
    expected_version = value.get("expected_ownership_version")
    target_customer_id = value.get("target_customer_id")
    if (
        not isinstance(object_type, str)
        or object_type not in OBJECT_OWNERSHIP_REGISTRY
        or not _positive_int(object_id)
        or not _positive_int(storage_customer_id)
        or not _positive_int(current_customer_id)
        or type(expected_version) is not int
        or expected_version < 0
        or not _positive_int(target_customer_id)
    ):
        raise OwnershipContractError("OWNERSHIP_PARTITION_INVALID")
    return OwnershipPartition(
        object_type=object_type,
        object_id=object_id,
        expected_storage_customer_id=storage_customer_id,
        expected_current_customer_id=current_customer_id,
        expected_ownership_version=expected_version,
        target_customer_id=target_customer_id,
    )


def require_approved_partition(
    proposal: CustomerChangeProposal,
    *,
    object_type: str,
    object_id: int,
    expected_storage_customer_id: int,
    expected_current_customer_id: int,
    expected_ownership_version: int,
    target_customer_id: int,
) -> OwnershipPartition:
    """Bind one CAS exactly to the action-hashed approved partition inventory."""
    if (
        proposal.status != "approved"
        or not proposal.approved_action_hash
        or not secrets.compare_digest(proposal.approved_action_hash, proposal.action_hash)
        or proposal.expires_at <= beijing_now()
    ):
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_APPROVAL_INVALID")
    if proposal.action_type not in {"merge", "split"}:
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_ACTION_MISMATCH")
    expected_schema = f"customer_{proposal.action_type}_v1"
    if proposal.payload_schema_version != expected_schema:
        raise OwnershipContractError("OWNERSHIP_PARTITION_SCHEMA_INVALID")
    payload = proposal.payload_json
    if not isinstance(payload, Mapping):
        raise OwnershipContractError("OWNERSHIP_PARTITION_SCHEMA_INVALID")
    recomputed_hash = canonical_action_hash(
        action_type=proposal.action_type,
        customer_id=proposal.customer_id,
        target_customer_id=proposal.target_customer_id,
        payload_json=dict(payload),
        profile_version_id=proposal.profile_version_id,
        evidence_fact_ids=list(proposal.evidence_fact_ids or []),
    )
    if not secrets.compare_digest(recomputed_hash, proposal.action_hash):
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_ACTION_HASH_INVALID")
    if payload.get("ownership_registry_version") != OBJECT_OWNERSHIP_REGISTRY_VERSION:
        raise OwnershipContractError("OWNERSHIP_REGISTRY_VERSION_MISMATCH")
    if payload.get("source_customer_id") != proposal.customer_id:
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_SCOPE_INVALID")
    targets = payload.get("target_customer_ids")
    if (
        not isinstance(targets, list)
        or not targets
        or any(not _positive_int(item) for item in targets)
        or len(set(targets)) != len(targets)
        or proposal.target_customer_id not in targets
        or (proposal.action_type == "merge" and targets != [proposal.target_customer_id])
    ):
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_SCOPE_INVALID")
    raw_partitions = payload.get("ownership_partitions")
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise OwnershipContractError("OWNERSHIP_PARTITION_SCHEMA_INVALID")
    partitions = [_parse_partition(value) for value in raw_partitions]
    keys = [(item.object_type, item.object_id) for item in partitions]
    if len(set(keys)) != len(keys):
        raise OwnershipContractError("OWNERSHIP_PARTITION_DUPLICATE")
    scope = {proposal.customer_id, *targets}
    if any(
        item.expected_current_customer_id not in scope
        or item.target_customer_id not in scope
        for item in partitions
    ):
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_SCOPE_INVALID")
    used_targets = {
        item.target_customer_id
        for item in partitions
        if item.target_customer_id != proposal.customer_id
    }
    if used_targets != set(targets):
        raise OwnershipContractError("OWNERSHIP_PROPOSAL_SCOPE_INVALID")
    matches = [
        item
        for item in partitions
        if item.object_type == object_type and item.object_id == object_id
    ]
    if len(matches) != 1:
        raise OwnershipContractError("OWNERSHIP_PARTITION_NOT_APPROVED")
    partition = matches[0]
    if (
        partition.expected_storage_customer_id != expected_storage_customer_id
        or partition.expected_current_customer_id != expected_current_customer_id
        or partition.expected_ownership_version != expected_ownership_version
        or partition.target_customer_id != target_customer_id
    ):
        raise OwnershipContractError("OWNERSHIP_PARTITION_MISMATCH")
    return partition


def require_overlay_eligibility(object_type: str, row: object) -> None:
    """Reject roots whose current state must be ended and rebuilt instead."""
    policy = OBJECT_OWNERSHIP_REGISTRY[object_type]
    if policy.eligibility == "non_policy_annotation":
        if (
            isinstance(row, CustomerAnnotation)
            and row.annotation_type == "do_not_contact"
            and row.status == "active"
        ):
            raise OwnershipContractError("OWNERSHIP_POLICY_REBUILD_REQUIRED")
    elif policy.eligibility == "terminal_research_task":
        if (
            isinstance(row, CustomerResearchTask)
            and row.task_status not in TERMINAL_RESEARCH_TASK_STATUSES
        ):
            raise OwnershipContractError("OWNERSHIP_RESEARCH_REBUILD_REQUIRED")


__all__ = [
    "OwnershipContractError",
    "OwnershipPartition",
    "require_approved_partition",
    "require_overlay_eligibility",
]
