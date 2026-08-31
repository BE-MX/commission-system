"""Validated HTTP inputs for the human Customer Hub."""

from datetime import datetime
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "contacted", "replied", "quoted", "won", "lost", "dismissed"]
    reason: str = Field(..., min_length=1, max_length=1000)
    close_reason_code: str | None = Field(None, max_length=32)
    close_reason_text: str | None = Field(None, max_length=1000)
    linked_order_id: int | None = Field(None, gt=0)
    evidence_event_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence_fact_ids: list[int] = Field(default_factory=list, max_length=100)


class ActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["complete", "dismiss", "snooze", "feedback"]
    outcome_code: str | None = Field(None, max_length=32)
    channel: str | None = Field(None, max_length=16)
    occurred_at: datetime | None = None
    summary: str | None = Field(None, max_length=1000)
    next_step: str | None = Field(None, max_length=1000)
    reason_code: str | None = Field(None, max_length=32)
    note: str | None = Field(None, max_length=1000)
    snoozed_until: datetime | None = None
    feedback: str | None = Field(None, max_length=32)


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(..., gt=0)
    target_customer_id: int | None = Field(None, gt=0)
    action_type: Literal[
        "merge", "split", "assign_primary", "transfer_primary",
        "set_dnc", "remove_dnc", "confirm_material_risk",
    ]
    payload_schema_version: str = Field(..., min_length=1, max_length=32)
    payload_json: dict[str, Any]
    profile_version_id: int = Field(..., gt=0)
    evidence_fact_ids: list[int] = Field(..., min_length=1, max_length=200)
    risk_level: Literal["high", "critical"]
    expires_at: datetime


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, max_length=1000)


class ProposalExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(..., min_length=16, max_length=64)


class ProposalRebase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_version_id: int = Field(..., gt=0)
    evidence_fact_ids: list[int] = Field(..., min_length=1, max_length=200)


def _invalid() -> None:
    raise ValueError("PROPOSAL_PAYLOAD_INVALID")


def _validate_governance(
    *, action_type, payload_schema_version, payload_json, customer_id,
    target_customer_id, profile_version_id, evidence_fact_ids,
) -> None:
    from app.customer.governance_policy_contract import (
        parse_confirm_material_risk, parse_remove_dnc, parse_set_dnc,
    )

    schemas = {
        "set_dnc": "customer_set_dnc_v1",
        "remove_dnc": "customer_remove_dnc_v1",
        "confirm_material_risk": "customer_confirm_material_risk_v1",
    }
    parsers = {
        "set_dnc": parse_set_dnc,
        "remove_dnc": parse_remove_dnc,
        "confirm_material_risk": parse_confirm_material_risk,
    }
    parsed = parsers[action_type](payload_json)
    if (
        payload_schema_version != schemas[action_type]
        or target_customer_id is not None
        or parsed.customer_id != customer_id
        or parsed.profile_version_id != profile_version_id
        or list(parsed.evidence_fact_ids) != evidence_fact_ids
    ):
        _invalid()


def _validate_ownership(
    db, *, account, action_type, payload_schema_version, payload_json,
    customer_id, target_customer_id, profile_version_id, evidence_fact_ids,
) -> None:
    from app.customer.models import CustomerAccount
    from app.customer.ownership_execution_contract import COMMON_PAYLOAD_KEYS

    action_key = "keep_customer_id" if action_type == "merge" else "retain_source"
    if (
        payload_schema_version != f"customer_{action_type}_v1"
        or target_customer_id is None or target_customer_id == customer_id
        or not isinstance(payload_json, Mapping)
        or set(payload_json) != COMMON_PAYLOAD_KEYS | {action_key}
        or payload_json.get("source_customer_id") != customer_id
        or payload_json.get("target_customer_ids") != [target_customer_id]
        or payload_json.get("source_profile_version_id") != profile_version_id
        or payload_json.get("source_profile_input_seq") != account.profile_input_seq
        or payload_json.get("evidence_fact_ids") != evidence_fact_ids
    ):
        _invalid()
    if (
        action_type == "merge" and payload_json[action_key] != target_customer_id
    ) or (
        action_type == "split" and type(payload_json[action_key]) is not bool
    ):
        _invalid()
    targets = payload_json.get("target_profile_versions")
    if not isinstance(targets, list) or len(targets) != 1:
        _invalid()
    target = targets[0]
    target_account = db.query(CustomerAccount).filter(
        CustomerAccount.id == target_customer_id,
        CustomerAccount.record_status == "active",
    ).one_or_none()
    if (
        not isinstance(target, Mapping)
        or set(target) != {"customer_id", "profile_version_id", "profile_input_seq"}
        or target_account is None
        or target != {
            "customer_id": target_customer_id,
            "profile_version_id": target_account.current_profile_version_id,
            "profile_input_seq": target_account.profile_input_seq,
        }
        or target_account.current_profile_version_id is None
    ):
        _invalid()
    redirects = payload_json.get("proposal_redirects")
    allowed_targets = {target_customer_id}
    redirect_profiles = {
        target_customer_id: target_account.current_profile_version_id,
    }
    if action_type == "split" and payload_json[action_key]:
        allowed_targets.add(customer_id)
        redirect_profiles[customer_id] = profile_version_id
    if not isinstance(redirects, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {
            "proposal_id", "target_customer_id", "target_profile_version_id",
        }
        or any(type(item[key]) is not int or item[key] <= 0 for key in item)
        or item["target_customer_id"] not in allowed_targets
        or item["target_profile_version_id"]
        != redirect_profiles.get(item["target_customer_id"])
        for item in redirects
    ) or len({item["proposal_id"] for item in redirects}) != len(redirects):
        _invalid()


def validate_proposal_action_payload(
    db, *, account, action_type, payload_schema_version, payload_json,
    customer_id, target_customer_id, profile_version_id, evidence_fact_ids,
) -> None:
    """Validate immutable action bindings; full ownership inventory stays execute-time."""
    if action_type in {"assign_primary", "transfer_primary"}:
        if (
            payload_schema_version != f"customer_{action_type}_v1"
            or target_customer_id is not None
            or not isinstance(payload_json, Mapping)
            or set(payload_json) != {"user_id", "reason"}
            or type(payload_json["user_id"]) is not int
            or payload_json["user_id"] <= 0
            or not isinstance(payload_json["reason"], str)
            or not payload_json["reason"].strip()
        ):
            _invalid()
    elif action_type in {"set_dnc", "remove_dnc", "confirm_material_risk"}:
        _validate_governance(
            action_type=action_type, payload_schema_version=payload_schema_version,
            payload_json=payload_json, customer_id=customer_id,
            target_customer_id=target_customer_id,
            profile_version_id=profile_version_id,
            evidence_fact_ids=evidence_fact_ids,
        )
    else:
        _validate_ownership(
            db, account=account, action_type=action_type,
            payload_schema_version=payload_schema_version,
            payload_json=payload_json, customer_id=customer_id,
            target_customer_id=target_customer_id,
            profile_version_id=profile_version_id,
            evidence_fact_ids=evidence_fact_ids,
        )
