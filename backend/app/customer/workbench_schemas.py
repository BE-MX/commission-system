"""Customer workbench v2 request contracts."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class WorkbenchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(WorkbenchInput):
    type: Literal["fact", "event", "message", "customer_message"]
    id: int = Field(ge=1)
    revision: str = Field(min_length=1, max_length=64)


class ItemTransition(WorkbenchInput):
    operation: Literal["start", "wait", "decide", "block", "pause", "resume", "cancel", "reopen", "resolve", "revalidate", "reverify", "snooze", "record_delivery_plan"]
    expected_item_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    review_at: datetime | None = None
    waiting_kind: Literal["customer", "colleague", "source"] | None = None
    resume_condition: str | None = Field(None, max_length=1000)
    cancel_remaining: bool = False
    delivery_plan: str | None = Field(None, min_length=1, max_length=2000)
    delivery_decision: Literal["alternative", "original_schedule"] | None = None
    customer_decision: Literal["accepted", "declined", "unclear"] | None = None


class AdmissionCreate(WorkbenchInput):
    item_id: int = Field(ge=1)
    expected_plan_version: int = Field(ge=1)
    allow_one_extra: bool = False
    reason: str | None = Field(None, max_length=1000)


class ItemFeedback(WorkbenchInput):
    target_id: str = Field(min_length=1, max_length=64)
    target_revision: int = Field(ge=1)
    dimension: Literal["accuracy", "applicability", "adoption"]
    decision: Literal["yes", "no"]
    reason: str | None = Field(None, max_length=1000)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=50)


class DelegationCreate(WorkbenchInput):
    goal: str = Field(min_length=1, max_length=2000)
    scope: Literal["prepare"] = "prepare"
    expected_item_version: int = Field(ge=1)


class DelegationTransition(WorkbenchInput):
    operation: Literal["pause", "resume", "cancel"]
    expected_delegation_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ActionCorrection(WorkbenchInput):
    operation: Literal["correct", "undo"] = "correct"
    expected_action_version: int = Field(ge=1)
    expected_work_item_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    correction: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=50)


class DependencyCreate(WorkbenchInput):
    expected_item_version: int = Field(ge=1)
    source_domain: Literal["action", "shipment", "design"]
    source_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    required: bool = True
    reason: str = Field(min_length=1, max_length=1000)


class ServiceAssetCreate(WorkbenchInput):
    asset_type: Literal["customer_website", "selection_page", "purchase_entry", "material_service", "other"]
    entry_url: str = Field(min_length=8, max_length=1024)
    purpose: str = Field(min_length=1, max_length=500)
    owner_user_id: int | None = Field(None, ge=1)
    known_issue: str | None = Field(None, max_length=1000)


class ServiceAssetRevoke(WorkbenchInput):
    expected_asset_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
