"""HTTP contracts for customer-id acquisition workflows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    policy_version: str = Field(..., min_length=1, max_length=32)
    policy_json: dict[str, Any]


class SearchJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    target_count: int = Field(20, ge=1, le=500)
    adapter: str = Field("agent", min_length=1, max_length=64)
    criteria_json: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(None, min_length=64, max_length=64)


class AgentClaim(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)


class AgentLease(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)
    lease_token: str = Field(..., min_length=32, max_length=128)


class AgentFailure(AgentLease):
    model_config = ConfigDict(extra="forbid")

    error_code: Literal[
        "provider_unavailable",
        "provider_rate_limited",
        "invalid_provider_response",
        "agent_execution_failed",
    ]


class CandidateInput(BaseModel):
    source_system: Literal["public_web", "official_registry", "okki"] = "public_web"
    source_account_key: str = Field("global", min_length=1, max_length=128)
    source_entity_type: Literal["company_page", "customer"] = "company_page"
    external_record_id: str = Field(..., min_length=1, max_length=255)
    external_context_id: str = Field(..., min_length=1, max_length=255)
    source_provider: str = Field(..., min_length=1, max_length=64)
    source_url: str | None = Field(None, max_length=2048)
    captured_at: datetime
    company_name: str | None = Field(None, max_length=255)
    website: str | None = Field(None, max_length=512)
    contact_name: str | None = Field(None, max_length=255)
    contact_email: str | None = Field(None, max_length=320)
    country: str | None = Field(None, max_length=128)
    industry: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=5000)
    rank: int | None = Field(None, ge=1)
    score: Decimal = Field(..., ge=0, le=100, max_digits=5, decimal_places=2)
    score_reasons: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    allocated_cost_usd: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=6)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return normalize_source_url(value) if value else None

    @model_validator(mode="after")
    def validate_registered_source_pair(self):
        allowed = {
            ("public_web", "company_page"),
            ("official_registry", "customer"),
            ("okki", "customer"),
        }
        if (self.source_system, self.source_entity_type) not in allowed:
            raise ValueError("source_system/source_entity_type 未注册")
        if self.source_system == "public_web" and not self.website:
            raise ValueError("公开网页候选必须提供官网用于商业上下文去重")
        return self


class CandidateBatch(AgentLease):
    request_key: str = Field(..., min_length=1, max_length=64)
    candidates: list[CandidateInput] = Field(..., min_length=1, max_length=500)


class PublicPoolBatchCreate(BaseModel):
    batch_date: date | None = None
    policy_version: str = Field(..., min_length=1, max_length=32)
    quotas_json: dict[str, Any]
    profile_conditions: dict[str, Any] = Field(default_factory=dict)


class PublicPoolIndustryGateSubmit(AgentLease):
    industry_relevance: Literal["core", "adjacent", "uncertain", "irrelevant"]
    reason: str = Field(..., min_length=1, max_length=2000)


class ResearchFactInput(BaseModel):
    fact_key: str = Field(..., min_length=1, max_length=128)
    value_type: Literal["string", "number", "boolean", "date", "datetime", "list", "object"]
    value: Any
    fact_layer: Literal["source", "inferred"]
    confidence: Decimal = Field(..., ge=0, le=1, max_digits=5, decimal_places=4)
    confidence_method_version: str = Field("research_evidence_v1", min_length=1, max_length=32)
    confidence_components: dict[str, Any] = Field(default_factory=dict)
    source_system: Literal["public_web", "agent"]
    source_entity_type: Literal["company_page", "research_report"]
    source_account_key: str = Field("global", min_length=1, max_length=128)
    external_record_id: str = Field(..., min_length=1, max_length=255)
    source_url: str | None = Field(None, max_length=2048)
    source_payload: dict[str, Any] = Field(default_factory=dict)
    publisher_key: str | None = Field(None, max_length=128)
    source_family_key: str | None = Field(None, max_length=128)
    observed_at: datetime
    captured_at: datetime | None = None
    supporting_fact_ids: list[int] = Field(default_factory=list, max_length=100)
    rule_version: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def validate_fact_provenance(self):
        if self.fact_layer == "source" and (self.source_system, self.source_entity_type) != (
            "public_web", "company_page"
        ):
            raise ValueError("source事实必须来自已注册公开公司页面")
        if self.fact_layer == "inferred":
            if (self.source_system, self.source_entity_type) != ("agent", "research_report"):
                raise ValueError("inferred事实必须来自受控research_report")
            if not self.supporting_fact_ids or not self.rule_version:
                raise ValueError("inferred事实必须引用支撑事实和rule_version")
        return self


class ResearchFactBatch(AgentLease):
    model_config = ConfigDict(extra="forbid")

    agent_run_id: int = Field(..., gt=0)
    facts: list[ResearchFactInput] = Field(..., min_length=1, max_length=100)


class ResearchKnowledgeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: int = Field(..., gt=0)
    revision_id: int = Field(..., gt=0)
    version_no: int = Field(..., gt=0)


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(..., pattern=r"^claim_[A-Za-z0-9_-]{1,48}$")
    section: Literal[
        "identity",
        "business_quality",
        "product_fit",
        "supplier_status",
        "risk",
        "strategy",
    ]
    statement: str = Field(..., min_length=1, max_length=2000)
    citation_ids: list[str] = Field(..., min_length=1, max_length=100)

    @field_validator("citation_ids")
    @classmethod
    def unique_citation_ids(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value]
        if any(not item for item in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("citation_ids 必须是非空且不重复的稳定ID")
        return cleaned


class ResearchCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(..., pattern=r"^citation_[A-Za-z0-9_-]{1,48}$")
    claim_id: str = Field(..., pattern=r"^claim_[A-Za-z0-9_-]{1,48}$")
    tool_call_id: str = Field(..., min_length=1, max_length=128)
    evidence_ref: str = Field(..., pattern=r"^fact:[1-9][0-9]*$")
    evidence_content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class CustomerResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["customer_research_v1"]
    input_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    claims: list[ResearchClaim] = Field(..., min_length=1, max_length=100)
    citations: list[ResearchCitation] = Field(..., min_length=1, max_length=500)
    knowledge_references: list[ResearchKnowledgeReference] = Field(default_factory=list, max_length=100)
    evidence_fact_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("evidence_fact_ids")
    @classmethod
    def unique_positive_evidence_fact_ids(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item <= 0 for item in value):
            raise ValueError("evidence_fact_ids 必须为正整数")
        if len(set(value)) != len(value):
            raise ValueError("evidence_fact_ids 不得重复")
        return sorted(value)

    @model_validator(mode="after")
    def validate_claim_citation_closure(self):
        claim_ids = [item.claim_id for item in self.claims]
        citation_ids = [item.citation_id for item in self.citations]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim_id 不得重复")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("citation_id 不得重复")
        citations = {item.citation_id: item for item in self.citations}
        referenced: set[str] = set()
        for claim in self.claims:
            for citation_id in claim.citation_ids:
                citation = citations.get(citation_id)
                if citation is None or citation.claim_id != claim.claim_id:
                    raise ValueError("claim引用的citation不存在或不属于该claim")
                referenced.add(citation_id)
        if referenced != set(citation_ids):
            raise ValueError("citations必须与claims形成完整闭包")
        cited_fact_ids = sorted({
            int(item.evidence_ref.split(":", 1)[1])
            for item in self.citations
        })
        if self.evidence_fact_ids and self.evidence_fact_ids != cited_fact_ids:
            raise ValueError("evidence_fact_ids必须与citations引用的事实完全一致")
        return self


class PublicPoolResearchSubmit(AgentLease):
    model_config = ConfigDict(extra="forbid")

    result_json: CustomerResearchResult
    agent_run_id: int = Field(..., gt=0)
    data_classification: Literal[
        "public_business", "internal_business", "personal_contact", "restricted_internal"
    ] = "internal_business"
    visibility_scope: Literal["all_authorized", "customer_team", "management"] = "customer_team"


class ResearchResultReview(BaseModel):
    review_status: Literal["accepted", "revision_requested", "rejected"]


class QualificationReviewSubmit(BaseModel):
    customer_id: int = Field(..., gt=0)
    review_source: Literal["search_result", "public_pool_research", "identity_conflict", "manual"]
    source_ref_id: str | None = Field(None, max_length=128)
    decision: Literal["approved", "rejected", "deferred"]
    reason_code: Literal[
        "qualified", "not_now", "poor_fit", "wrong_identity", "duplicate", "do_not_contact", "bad_data"
    ]
    reason_text: str | None = Field(None, max_length=2000)
    scope_type: Literal["global", "target_profile", "product", "market", "source", "channel"]
    scope_ref_id: str | None = Field(None, max_length=128)
    policy_version: str = Field(..., min_length=1, max_length=32)
    review_after: datetime | None = None
    review_snapshot: dict[str, Any] = Field(default_factory=dict)
    decision_request_key: str = Field(..., min_length=1, max_length=128)
    expected_current_review_id: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "global" and self.scope_ref_id is not None:
            raise ValueError("global范围不得提供scope_ref_id")
        if self.scope_type != "global" and not self.scope_ref_id:
            raise ValueError("非global范围必须提供scope_ref_id")
        return self


__all__ = [
    "AgentClaim",
    "AgentFailure",
    "AgentLease",
    "CandidateBatch",
    "CandidateInput",
    "ProfileUpsert",
    "PublicPoolBatchCreate",
    "PublicPoolIndustryGateSubmit",
    "PublicPoolResearchSubmit",
    "ResearchFactInput",
    "ResearchFactBatch",
    "QualificationReviewSubmit",
    "ResearchResultReview",
    "SearchJobCreate",
]
