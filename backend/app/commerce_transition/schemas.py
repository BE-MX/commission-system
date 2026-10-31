"""Explicit administrative receipts; no general confirmed-order route switch."""
from typing import Any, Literal
from pydantic import BaseModel, Field

Route = Literal["legacy", "local"]


class DraftRouteChange(BaseModel):
    route: Route
    expected_authority_epoch: int = Field(ge=1)
    evidence: dict[str, Any] = Field(min_length=1)


class PolicyChange(BaseModel):
    phase: Literal["legacy_only", "transition", "local_only"]
    expected_version: int = Field(ge=1)
    min_writer_version: int = Field(default=1, ge=1)
    inventory_evidence: dict[str, Any] | None = Field(default=None, min_length=1)


class WriterAttestation(BaseModel):
    writer_key: str = Field(min_length=1, max_length=128)
    protocol_version: int = Field(ge=1)
    state: Literal["compatible", "revoked", "unknown"]
    evidence: dict[str, Any] = Field(min_length=1)


class ResourceRegistration(BaseModel):
    route: Route
    resource_kind: Literal["sku", "material", "production"]
    resource_key: str = Field(min_length=1, max_length=128)
    warehouse_key: str = Field(min_length=1, max_length=128)
    evidence: dict[str, Any] = Field(min_length=1)


class BankDomainRegistration(BaseModel):
    subject_key: str = Field(min_length=1, max_length=96)
    account_key: str = Field(min_length=1, max_length=96)
    channel: str = Field(min_length=1, max_length=64)
    legacy_identity_complete: bool
    enforced: bool
    exclusive_route: Route | None = None
    evidence: dict[str, Any] = Field(min_length=1)
    bank_account_ids: list[int] = Field(default_factory=list, max_length=500)


class LegacyBankReconciliation(BaseModel):
    domain_id: int = Field(gt=0)
    transaction_id: str = Field(min_length=1, max_length=128)
    receipt_id: int | None = Field(default=None, gt=0)
    batch_id: int | None = Field(default=None, gt=0)
    statement_reference: str = Field(min_length=1, max_length=500)
