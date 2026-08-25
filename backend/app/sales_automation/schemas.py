"""智能获客 HTTP 输入模型。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.sales_automation.identity import normalize_source_url


class ProfileUpsert(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    company_website: str | None = Field(None, max_length=512)
    products: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    target_countries: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    default_language: str = Field("en", min_length=2, max_length=16)


class SearchJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    target_count: int = Field(20, ge=1, le=500)
    keywords: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    adapter: str = Field("agent", min_length=1, max_length=64)
    idempotency_key: str | None = Field(None, max_length=64)


class AgentClaim(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)


class AgentLease(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)
    lease_token: str = Field(..., min_length=32, max_length=128)


class AgentFailure(AgentLease):
    error_message: str = Field(..., min_length=1, max_length=2000)


class CandidateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    website: str = Field(..., min_length=4, max_length=512)
    country: str | None = Field(None, max_length=128)
    industry: str | None = Field(None, max_length=255)
    description: str | None = None
    source_url: str = Field(..., min_length=4, max_length=1024)
    source_provider: str = Field("agent", max_length=64)
    captured_at: datetime


class CandidateBatch(AgentLease):
    request_key: str = Field(..., min_length=1, max_length=64)
    candidates: list[CandidateInput] = Field(..., min_length=1, max_length=500)


class ContactInput(BaseModel):
    name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=320)
    email_status: Literal["unknown", "valid", "risky", "invalid"] | None = None
    verified_at: datetime | None = None
    source_provider: str = Field("agent", max_length=64)
    source_url: str = Field(..., min_length=4, max_length=1024)
    captured_at: datetime
    confidence: float | None = Field(None, ge=0, le=1)

    @field_validator("email")
    @classmethod
    def _email_or_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "@" not in normalized:
            raise ValueError("email 格式无效")
        return normalized


class ContactBatch(BaseModel):
    contacts: list[ContactInput] = Field(..., min_length=1, max_length=200)


class ResearchFactInput(BaseModel):
    fact_type: str = Field("general", max_length=64)
    claim: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=4, max_length=1024)
    captured_at: datetime
    confidence: float = Field(..., ge=0, le=1)


class ResearchUpsert(BaseModel):
    summary: str = Field(..., min_length=1)
    facts: list[ResearchFactInput] = Field(..., min_length=1, max_length=100)
    outreach_angles: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    provider: str = Field("agent", max_length=64)
    model: str | None = Field(None, max_length=128)
    idempotency_key: str | None = Field(None, max_length=64)


class PublicPoolValueRules(BaseModel):
    min_order_count: int | None = Field(2, ge=1, le=1000)
    total_amount_over_usd: Decimal | None = Field(Decimal("1500"), ge=0, le=Decimal("1000000000"))
    single_order_over_usd: Decimal | None = Field(Decimal("1000"), ge=0, le=Decimal("1000000000"))
    sample_only_orders: bool = True

    @model_validator(mode="after")
    def validate_value_rules(self):
        paired = (self.min_order_count is not None, self.total_amount_over_usd is not None)
        if paired[0] != paired[1]:
            raise ValueError("成交单数与累计金额条件必须同时启用或同时关闭")
        if not (all(paired) or self.single_order_over_usd is not None or self.sample_only_orders):
            raise ValueError("至少启用一条成交画像条件")
        return self


class PublicPoolProfileConditions(BaseModel):
    value_rules: PublicPoolValueRules = Field(default_factory=PublicPoolValueRules)
    top_country_limit: int | None = Field(10, ge=1, le=50)
    contact_channels: list[Literal["instagram", "facebook", "phone"]] = Field(
        default_factory=lambda: ["instagram", "facebook", "phone"], max_length=3,
    )
    product_keywords: list[str] = Field(
        default_factory=lambda: ["天才", "平型", "贴发"], max_length=20,
    )
    inactive_order_days: int | None = Field(60, ge=1, le=3650)
    stale_followup_days: int | None = Field(30, ge=1, le=3650)

    @field_validator("contact_channels")
    @classmethod
    def unique_contact_channels(cls, value: list[str]) -> list[str]:
        priority = {"instagram": 0, "facebook": 1, "phone": 2}
        return sorted(set(value), key=priority.__getitem__)

    @field_validator("product_keywords")
    @classmethod
    def clean_product_keywords(cls, value: list[str]) -> list[str]:
        cleaned = sorted(set(item.strip() for item in value if item.strip()))
        if any(len(item) > 64 for item in cleaned):
            raise ValueError("产品关键词不能超过 64 个字符")
        return cleaned


class PublicPoolBatchCreate(BaseModel):
    batch_date: date | None = None
    quota_per_tier: int = Field(20, ge=1, le=100)
    policy_version: str = Field("v3", min_length=1, max_length=32)
    profile_conditions: PublicPoolProfileConditions | None = None

    @field_validator("policy_version")
    @classmethod
    def reject_reserved_policy_version(cls, value: str) -> str:
        if value == "lead-score-70-v1":
            raise ValueError("该策略版本为系统保留值")
        return value


class DealScoreComponents(BaseModel):
    industry_fit: float = Field(0, ge=0, le=25)
    pain_switch_trigger: float = Field(0, ge=0, le=20)
    intent_reactivation: float = Field(0, ge=0, le=20)
    buying_capacity: float = Field(0, ge=0, le=15)
    reachability: float = Field(0, ge=0, le=10)
    timing: float = Field(0, ge=0, le=10)
    risk_penalty: float = Field(0, ge=0, le=30)
    reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reasons_for_nonzero_scores(self):
        scored_fields = (
            "industry_fit", "pain_switch_trigger", "intent_reactivation",
            "buying_capacity", "reachability", "timing", "risk_penalty",
        )
        missing = [key for key in scored_fields if getattr(self, key) and not str(self.reasons.get(key) or "").strip()]
        if missing:
            raise ValueError(f"非零评分项必须提供证据化理由: {', '.join(missing)}")
        return self


class PublicPoolSocialProfile(BaseModel):
    platform: str = Field(..., min_length=1, max_length=32)
    profile_url: str = Field(..., min_length=4, max_length=1024)
    handle: str | None = Field(None, max_length=255)
    account_name: str | None = Field(None, max_length=255)
    activity_level: Literal["active", "recent", "dormant", "unknown"] = "unknown"
    latest_activity_at: datetime | None = None
    follower_count: int | None = Field(None, ge=0)
    business_signals: list[str] = Field(default_factory=list, max_length=10)
    captured_at: datetime
    confidence: float = Field(..., ge=0, le=1)

    @field_validator("profile_url")
    @classmethod
    def validate_profile_url(cls, value: str) -> str:
        return normalize_source_url(value)


class PublicPoolKnowledgeReference(BaseModel):
    document_id: int = Field(..., gt=0)
    revision_id: int = Field(..., gt=0)
    version_no: int = Field(..., gt=0)


class PublicPoolQualificationDimension(BaseModel):
    score: int | None = Field(None, ge=1, le=5)
    reason: str = Field(..., min_length=1, max_length=1000)


class PublicPoolQualificationDimensions(BaseModel):
    authenticity_maturity: PublicPoolQualificationDimension
    purchase_potential: PublicPoolQualificationDimension
    demand_readiness: PublicPoolQualificationDimension
    industry_professionalism: PublicPoolQualificationDimension
    product_market_fit: PublicPoolQualificationDimension
    growth_brand_potential: PublicPoolQualificationDimension
    decision_authority: PublicPoolQualificationDimension
    transaction_compliance: PublicPoolQualificationDimension
    engagement_momentum: PublicPoolQualificationDimension
    strategic_value: PublicPoolQualificationDimension


class PublicPoolCommercialProfile(BaseModel):
    customer_type: Literal[
        "salon", "stylist", "educator", "brand_owner", "ecommerce",
        "distributor", "wholesaler", "salon_chain", "end_consumer", "other", "unclear",
    ] = "unclear"
    professional_level: Literal["beginner", "experienced", "expert", "unclear"] = "unclear"
    purchase_stage: Literal[
        "first_purchase", "first_cross_border", "supplier_exploration", "supplier_switching",
        "supplier_addition", "sample_testing", "regular_buying", "expansion", "dormant_lost", "unclear",
    ] = "unclear"
    volume_band: Literal["small_trial", "stable_medium", "high_volume", "unclear"] = "unclear"
    scale_stage: Literal[
        "solo_professional", "small_team", "multi_location", "regional_operation", "expansion_stage", "unclear",
    ] = "unclear"
    educator_influence: Literal["yes", "no", "unknown"] = "unknown"
    usage_scenarios: list[Literal[
        "brand_retail", "salon_install", "distribution", "education", "personal_use", "supplier_testing", "unknown",
    ]] = Field(default_factory=list, max_length=10)
    product_directions: list[Literal[
        "extension_focused", "excluded_hair_focused", "textured_hair_focused", "mixed_portfolio", "unknown",
    ]] = Field(default_factory=list, max_length=10)
    exclusion_status: Literal["not_excluded", "review_required", "excluded", "unknown"] = "unknown"
    development_difficulty: int = Field(3, ge=1, le=5)
    qualification_dimensions: PublicPoolQualificationDimensions | None = None
    positive_signals: list[str] = Field(default_factory=list, max_length=20)
    negative_signals: list[str] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=20)
    next_validation_questions: list[str] = Field(default_factory=list, max_length=10)


class PublicPoolIndustryGateSubmit(AgentLease):
    """Low-cost first pass. Only a passed gate authorizes commercial deep research."""

    summary: str = Field(..., min_length=1, max_length=5000)
    identity_decision: Literal["confirmed", "candidate", "unverifiable", "rejected"]
    facts: list[ResearchFactInput] = Field(default_factory=list, max_length=20)
    industry_relevance: Literal["core", "adjacent", "uncertain", "irrelevant"]
    industry_relevance_reason: str = Field(..., min_length=1, max_length=2000)
    stop_reason: str | None = Field(None, max_length=2000)
    knowledge_references: list[PublicPoolKnowledgeReference] = Field(default_factory=list, max_length=10)
    provider: str = Field("openclaw_public_pool_gate", max_length=64)
    model: str | None = Field(None, max_length=128)

    @model_validator(mode="after")
    def validate_gate(self):
        if self.industry_relevance == "irrelevant" and not self.stop_reason:
            raise ValueError("行业无关客户必须填写停止原因")
        if self.industry_relevance != "irrelevant" and self.identity_decision == "rejected":
            raise ValueError("主体已拒绝时不能签发深入背调")
        return self


class PublicPoolResearchSubmit(AgentLease):
    summary: str = Field(..., min_length=1, max_length=10000)
    identity_decision: Literal["confirmed", "candidate", "unverifiable", "rejected"]
    facts: list[ResearchFactInput] = Field(default_factory=list, max_length=100)
    contacts: list[ContactInput] = Field(default_factory=list, max_length=100)
    outreach_angles: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)
    score_components: DealScoreComponents
    supplier_status: Literal["unknown", "stable", "looking", "switching"] = "unknown"
    pain_points: list[str] = Field(default_factory=list, max_length=20)
    product_fit: list[str] = Field(default_factory=list, max_length=20)
    industry_relevance: Literal["core", "adjacent", "uncertain", "irrelevant"] = "uncertain"
    industry_relevance_reason: str = Field("尚未提供行业门控说明", min_length=1, max_length=2000)
    research_depth: Literal["gate_only", "focused", "deep"] = "focused"
    stop_reason: str | None = Field(None, max_length=2000)
    social_profiles: list[PublicPoolSocialProfile] = Field(default_factory=list, max_length=20)
    knowledge_references: list[PublicPoolKnowledgeReference] = Field(default_factory=list, max_length=20)
    commercial_profile: PublicPoolCommercialProfile = Field(default_factory=PublicPoolCommercialProfile)
    recommended_strategy: str = Field(..., min_length=1, max_length=10000)
    outreach_type: Literal["reactivation", "new_development", "intent_probe", "no_outreach"]
    opening_message_en: str | None = Field(None, max_length=10000)
    provider: str = Field("openclaw_public_pool_research", max_length=64)
    model: str | None = Field(None, max_length=128)
    idempotency_key: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def validate_research_gate(self):
        if self.commercial_profile.exclusion_status == "excluded" and self.industry_relevance != "irrelevant":
            raise ValueError("已排除客户必须按行业无关止损提交")
        if self.industry_relevance != "irrelevant":
            return self
        forbidden_scores = (
            self.score_components.industry_fit,
            self.score_components.pain_switch_trigger,
            self.score_components.intent_reactivation,
            self.score_components.buying_capacity,
            self.score_components.reachability,
            self.score_components.timing,
        )
        if self.research_depth != "gate_only" or not self.stop_reason:
            raise ValueError("行业无关客户必须在初筛后停止，并填写停止原因")
        if self.contacts or self.pain_points or self.product_fit or any(forbidden_scores):
            raise ValueError("行业无关客户不得继续联系人、痛点、产品匹配或成交加分调研")
        profile = self.commercial_profile
        if (
            self.social_profiles or self.outreach_angles or self.risks
            or profile.qualification_dimensions
            or profile.positive_signals or profile.negative_signals
            or profile.next_validation_questions
        ):
            raise ValueError("行业无关客户不得携带社媒关系、风险、触达角度或深度资格研判")
        if self.supplier_status != "unknown" or self.opening_message_en or self.outreach_type != "no_outreach":
            raise ValueError("行业无关客户不得研判供应商或生成触达草稿")
        return self


class PublicPoolTaskReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
