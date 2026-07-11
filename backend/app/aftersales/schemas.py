"""客户售后管理接口契约。"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ISSUE_TYPES = (
    "断发",
    "褪色",
    "色差",
    "头发太直",
    "脱发",
    "分叉",
    "发干打结",
    "头发油",
    "贴发胶",
    "克重不够",
    "产品做工",
)


class CaseCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    customer_name_snapshot: str = Field(min_length=1, max_length=256)
    customer_grade: Literal["A", "B", "C", "D", "E"]
    order_id: str = Field(min_length=1, max_length=64)
    order_no_snapshot: str = Field(min_length=1, max_length=64)
    purchase_date: date
    feedback_date: date
    feedback_channel: str | None = Field(default=None, max_length=32)

    product_id: int | None = None
    product_name_snapshot: str = Field(min_length=1, max_length=256)
    is_custom_product: bool = False
    batch_no: str | None = Field(default=None, max_length=128)
    color_value: str = Field(min_length=1, max_length=128)
    length_value: str = Field(min_length=1, max_length=128)
    weight_value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    weight_unit: str = Field(min_length=1, max_length=16)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    primary_issue_type: Literal[
        "断发",
        "褪色",
        "色差",
        "头发太直",
        "脱发",
        "分叉",
        "发干打结",
        "头发油",
        "贴发胶",
        "克重不够",
        "产品做工",
    ]
    secondary_issue_types: list[str] = Field(default_factory=list, max_length=10)
    problem_description: str = Field(min_length=20, max_length=4000)
    occurred_stage: str = Field(min_length=1, max_length=32)
    care_storage_note: str = Field(min_length=20, max_length=4000)
    affects_end_customer: Literal["yes", "no", "unknown"]
    affected_goods_value: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    affected_goods_currency: str = Field(default="USD", min_length=3, max_length=8)
    sales_evidence_confirmed: bool | None = None
    sales_evidence_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_business_rules(self):
        if self.feedback_date < self.purchase_date:
            raise ValueError("反馈日期不得早于购买日期")
        if self.is_custom_product and self.product_id is not None:
            raise ValueError("定制产品不能同时提交标准产品 ID")
        if not self.is_custom_product and self.product_id is None:
            raise ValueError("标准产品必须选择产品 ID")
        return self


class AiEvidence(BaseModel):
    score: int = Field(ge=0, le=100)
    is_sufficient: bool
    missing_items: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AiResponsibility(BaseModel):
    class_: Literal["A", "B", "C", "D"] = Field(alias="class")
    label: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)
    reasoning: list[str] = Field(min_length=1, max_length=10)

    model_config = {"populate_by_name": True}


class AiSopCitation(BaseModel):
    section: str = Field(min_length=1, max_length=200)
    clause: str = Field(min_length=1, max_length=200)
    quote_digest: str = Field(min_length=1, max_length=500)


class AiRecommendedAction(BaseModel):
    code: Literal[
        "explanation",
        "care_guidance",
        "return_inspection",
        "paid_rework",
        "free_rework",
        "replacement",
        "resend",
        "cash_refund",
        "discount",
        "order_credit",
        "freight_subsidy",
        "custom",
    ]
    title: str = Field(min_length=1, max_length=100)
    has_compensation: bool
    rationale: str = Field(min_length=1, max_length=1000)


class AiCustomerReply(BaseModel):
    language: Literal["en"]
    content: str = Field(min_length=20, max_length=8000)


class AfterSalesAiResult(BaseModel):
    evidence: AiEvidence
    responsibility: AiResponsibility
    sop_citations: list[AiSopCitation] = Field(min_length=1, max_length=20)
    recommended_actions: list[AiRecommendedAction] = Field(min_length=1, max_length=10)
    customer_reply_draft: AiCustomerReply
    internal_follow_up: list[str] = Field(default_factory=list, max_length=20)


class DecisionRequest(BaseModel):
    responsibility_class: Literal["A", "B", "C", "D"]
    responsibility_reason: str = Field(min_length=1, max_length=4000)
    responsibility_override_reason: str | None = Field(default=None, max_length=2000)
    actions: list[dict] = Field(min_length=1, max_length=10)
    customer_reply_draft: str = Field(min_length=20, max_length=8000)
    requires_return: bool = False


class VersionedActionRequest(BaseModel):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=64)


class ReviewRequest(VersionedActionRequest):
    decision: Literal["approve", "return", "reject"]
    comment: str = Field(default="", max_length=4000)
    proxy_reason: str | None = Field(default=None, max_length=2000)


class EvidenceWaiverRequest(VersionedActionRequest):
    reason: str = Field(min_length=10, max_length=2000)


class EvidenceWaiverReviewRequest(VersionedActionRequest):
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=2000)


class TransferApprovalRequest(VersionedActionRequest):
    new_reviewer_user_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class ExecutionRequest(BaseModel):
    execution_result: str = Field(min_length=1, max_length=8000)
    customer_feedback: str | None = Field(default=None, max_length=8000)


class CloseRequest(BaseModel):
    customer_feedback: str = Field(min_length=1, max_length=8000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)
