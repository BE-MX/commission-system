"""Strict payload contracts for approved customer governance actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from app.core.time import to_beijing_naive


DNC_SCOPE_TYPES = frozenset({
    "global", "target_profile", "product", "market", "source", "channel",
})
MATERIAL_RISK_TYPES = frozenset({"fraud", "sanctions", "material_legal"})
RISK_SOURCE_FACT_KEYS = {
    item: f"risk.source.{item}" for item in MATERIAL_RISK_TYPES
}
RISK_CONFIRMED_FACT_KEYS = {
    item: f"risk.confirmed.{item}" for item in MATERIAL_RISK_TYPES
}


class GovernanceContractError(ValueError):
    pass


def _exact(payload: Mapping, fields: frozenset[str]) -> dict:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return dict(payload)


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return value


def _text(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return value.strip()


def _scope(scope_type: object, scope_ref_id: object) -> tuple[str, str | None]:
    if scope_type not in DNC_SCOPE_TYPES:
        raise GovernanceContractError("GOVERNANCE_SCOPE_INVALID")
    if scope_type == "global":
        if scope_ref_id is not None:
            raise GovernanceContractError("GOVERNANCE_SCOPE_INVALID")
        return "global", None
    return str(scope_type), _text(scope_ref_id)


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
        return to_beijing_naive(parsed)
    except (TypeError, ValueError) as exc:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID") from exc


@dataclass(frozen=True, slots=True)
class SetDncPayload:
    customer_id: int
    profile_version_id: int
    expected_profile_input_seq: int
    scope_type: str
    scope_ref_id: str | None
    reason_code: str
    reason_text: str | None
    policy_effective_at: datetime
    expected_active_annotation_id: None
    evidence_fact_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RemoveDncPayload:
    customer_id: int
    profile_version_id: int
    expected_profile_input_seq: int
    scope_type: str
    scope_ref_id: str | None
    annotation_id: int
    expected_active_annotation_id: int
    removal_reason: str
    evidence_fact_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ConfirmMaterialRiskPayload:
    customer_id: int
    profile_version_id: int
    expected_profile_input_seq: int
    risk_type: str
    source_fact_id: int
    source_fact_fingerprint: str
    source_value_hash: str
    confirmation_reason: str
    evidence_fact_ids: tuple[int, ...]


def _evidence_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise GovernanceContractError("GOVERNANCE_EVIDENCE_INVALID")
    if any(type(item) is not int or item <= 0 for item in value):
        raise GovernanceContractError("GOVERNANCE_EVIDENCE_INVALID")
    normalized = tuple(sorted(set(value)))
    if list(normalized) != value:
        raise GovernanceContractError("GOVERNANCE_EVIDENCE_INVALID")
    return normalized


def parse_set_dnc(payload: Mapping) -> SetDncPayload:
    row = _exact(payload, frozenset({
        "customer_id", "profile_version_id", "expected_profile_input_seq",
        "scope_type", "scope_ref_id", "reason_code", "reason_text",
        "policy_effective_at", "expected_active_annotation_id",
        "evidence_fact_ids",
    }))
    scope_type, scope_ref_id = _scope(row["scope_type"], row["scope_ref_id"])
    if row["expected_active_annotation_id"] is not None:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return SetDncPayload(
        customer_id=_positive_int(row["customer_id"]),
        profile_version_id=_positive_int(row["profile_version_id"]),
        expected_profile_input_seq=_nonnegative_int(row["expected_profile_input_seq"]),
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        reason_code=_text(row["reason_code"]),
        reason_text=_text(row["reason_text"], nullable=True),
        policy_effective_at=_time(row["policy_effective_at"]),
        expected_active_annotation_id=None,
        evidence_fact_ids=_evidence_ids(row["evidence_fact_ids"]),
    )


def parse_remove_dnc(payload: Mapping) -> RemoveDncPayload:
    row = _exact(payload, frozenset({
        "customer_id", "profile_version_id", "expected_profile_input_seq",
        "scope_type", "scope_ref_id", "annotation_id",
        "expected_active_annotation_id", "removal_reason",
        "evidence_fact_ids",
    }))
    scope_type, scope_ref_id = _scope(row["scope_type"], row["scope_ref_id"])
    annotation_id = _positive_int(row["annotation_id"])
    expected = _positive_int(row["expected_active_annotation_id"])
    if annotation_id != expected:
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return RemoveDncPayload(
        customer_id=_positive_int(row["customer_id"]),
        profile_version_id=_positive_int(row["profile_version_id"]),
        expected_profile_input_seq=_nonnegative_int(row["expected_profile_input_seq"]),
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        annotation_id=annotation_id,
        expected_active_annotation_id=expected,
        removal_reason=_text(row["removal_reason"]),
        evidence_fact_ids=_evidence_ids(row["evidence_fact_ids"]),
    )


def parse_confirm_material_risk(payload: Mapping) -> ConfirmMaterialRiskPayload:
    row = _exact(payload, frozenset({
        "customer_id", "profile_version_id", "expected_profile_input_seq",
        "risk_type", "source_fact_id", "source_fact_fingerprint",
        "source_value_hash", "confirmation_reason",
        "evidence_fact_ids",
    }))
    if row["risk_type"] not in MATERIAL_RISK_TYPES:
        raise GovernanceContractError("GOVERNANCE_RISK_TYPE_INVALID")
    fingerprint = _text(row["source_fact_fingerprint"])
    value_hash = _text(row["source_value_hash"])
    if any(len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
           for value in (fingerprint, value_hash)):
        raise GovernanceContractError("GOVERNANCE_PAYLOAD_INVALID")
    return ConfirmMaterialRiskPayload(
        customer_id=_positive_int(row["customer_id"]),
        profile_version_id=_positive_int(row["profile_version_id"]),
        expected_profile_input_seq=_nonnegative_int(row["expected_profile_input_seq"]),
        risk_type=str(row["risk_type"]),
        source_fact_id=_positive_int(row["source_fact_id"]),
        source_fact_fingerprint=fingerprint,
        source_value_hash=value_hash,
        confirmation_reason=_text(row["confirmation_reason"]),
        evidence_fact_ids=_evidence_ids(row["evidence_fact_ids"]),
    )


def canonical_value_hash(value_json: object) -> str:
    encoded = json.dumps(
        value_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
