"""PCW HTTP 输入校验（extra=forbid，严格拒绝未知字段）。"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool = False
    rule_version: str = Field("pcw_rules_v1", max_length=32)
    run_kind: Literal["manual", "dry_run"] = "manual"
    customer_ids: list[int] | None = None


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_business_key: str = Field(..., min_length=1, max_length=128)
    work_item_business_cycle: str = Field(..., min_length=1, max_length=64)
    work_type: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=500)
    action_type: Literal["call", "email", "message", "meeting", "research", "review"]
    thread_group: Literal["new_inquiry", "sample", "key_account", "reorder", "reactivation", "public_pool"]
    priority: Literal["urgent", "high", "normal", "low"]
    reason: str = Field(..., min_length=1, max_length=1000)
    next_action: str = Field(..., min_length=1, max_length=1000)
    channel: Literal["alibaba", "email", "whatsapp", "phone", "linkedin", "offline", "internal"] | None = None
    contact_id: int | None = Field(None, gt=0)
    opportunity_id: int | None = Field(None, gt=0)
    business_due_at: datetime | None = None
    original_due_at: datetime | None = None
    due_provenance: str | None = Field(None, max_length=24)
    suggested_message: str | None = Field(None, max_length=4000)
    source_event_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence_fact_ids: list[int] = Field(default_factory=list, max_length=100)


class ProfileRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_version_id: int = Field(..., gt=0)
    expected_profile_input_seq: int = Field(..., ge=0)
    field_key: str = Field(..., min_length=1, max_length=128)
    value_type: Literal["string", "number", "object"]
    value: Any
    reason: str = Field(..., min_length=1, max_length=1000)
    target_fact_id: int | None = Field(None, gt=0)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=50)
    supersedes_annotation_id: int | None = Field(None, gt=0)


class SuggestionDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["accept", "edit_accept", "reject", "defer"]
    expected_suggestion_version: int = Field(..., gt=0)
    expected_profile_version_id: int | None = Field(None, gt=0)
    expected_profile_input_seq: int | None = Field(None, ge=0)
    value: Any = None
    reason: str | None = Field(None, max_length=1000)
    defer_until: datetime | None = None


class PrivateNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=5000)


class ConversationBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_system: str = Field(..., min_length=1, max_length=24)
    source_account_key: str = Field(..., min_length=1, max_length=64)
    source_conversation_id: str = Field(..., min_length=1, max_length=128)
    customer_id: int = Field(..., gt=0)
    contact_id: int | None = Field(None, gt=0)
    expected_binding_version: int = Field(0, ge=0)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=50)
    share_scope: Literal["customer_team", "management"] = "customer_team"


class BindingGovernanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1, max_length=1000)
    new_customer_id: int | None = Field(None, gt=0)


class MonitorSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["website", "instagram", "facebook", "linkedin", "news"]
    url: str = Field(..., min_length=1, max_length=1000)
    interval_days: int = Field(7, ge=1, le=90)


class MonitorSubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_subscription_version: int = Field(..., gt=0)
    enabled: bool | None = None
    interval_days: int | None = Field(None, ge=1, le=90)


class MonitorEventDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["confirm", "ignore"]
    expected_event_version: int = Field(..., gt=0)
    reason: str | None = Field(None, max_length=1000)


class MaintenancePlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_type: Literal["manual", "birthday", "holiday", "campaign", "shipping", "sample"]
    title: str = Field(..., min_length=1, max_length=500)
    typed_payload: dict
    timezone: str = Field("Asia/Shanghai", max_length=64)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=50)
    owner_user_id: int | None = Field(None, gt=0)


class MaintenancePlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_plan_version: int = Field(..., gt=0)
    status: Literal["active", "paused", "closed"] | None = None
    # 实例改约分支（api-contracts §3：日期/暂停/版本；改约与行动更新同事务）
    occurrence_id: int | None = Field(None, gt=0)
    occurrence_date: date | None = None
    expected_occurrence_version: int | None = Field(None, gt=0)
    expected_action_version: int | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=1000)


class SampleCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_order_id: int = Field(..., gt=0)
    sample_item_ids: list[int] = Field(..., min_length=1, max_length=100)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=50)


class SampleCasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["reschedule", "start_test", "record_feedback", "close"]
    expected_sample_version: int = Field(..., gt=0)
    expected_occurrence_version: int | None = Field(None, gt=0)
    expected_action_version: int | None = Field(None, gt=0)
    test_planned_date: date | None = None
    reason: str | None = Field(None, max_length=1000)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=50)
    feedback_text: str | None = Field(None, max_length=2000)
    actual_date: date | None = None


class ShipmentOrderLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shipment_id: int = Field(..., gt=0)
    order_id: int = Field(..., gt=0)
    order_item_id: int | None = Field(None, gt=0)
    linked_quantity: str | None = Field(None, max_length=64)
    linked_unit: str | None = Field(None, max_length=32)
    link_role: Literal["full", "partial", "rest"] = "full"
    evidence_refs: list[dict] = Field(..., min_length=1, max_length=50)


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=200)
    campaign_type: Literal["new_product", "offer"]
    product_scope: dict
    effective_from: datetime
    effective_to: datetime
    market_scope: dict | None = None
    exclusions: dict | None = None
    content_refs: dict | None = None


class CampaignVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_campaign_version: int = Field(..., gt=0)


class CampaignTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_campaign_version: int = Field(..., gt=0)
    target_status: Literal["active", "paused", "closed"]


class CampaignActionsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_version: str = Field(..., min_length=1, max_length=64)
    customer_ids: list[int] = Field(..., min_length=1, max_length=500)
