"""Strict, round-trippable public-pool selection configuration."""

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRule(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommerceRule(StrictRule):
    min_orders: int = Field(2, ge=1, le=10000)
    total_usd_gt: float = Field(1500, ge=0, le=1_000_000_000, allow_inf_nan=False)
    single_usd_gt: float = Field(1000, ge=0, le=1_000_000_000, allow_inf_nan=False)
    allow_sample_only: bool = True
    sample_requires_product: bool = True


class PoolRules(StrictRule):
    schema_version: Literal["public_pool_selection_v2"] = "public_pool_selection_v2"
    commerce: CommerceRule = Field(default_factory=CommerceRule)
    countries: list[str] = Field(default_factory=lambda: ["US", "CA", "DE", "NL", "BE", "GB", "AU", "NZ", "IE", "PR", "CZ", "SK", "FR"], min_length=1, max_length=250)
    contact_channels: list[Literal["instagram", "facebook", "phone"]] = Field(default_factory=lambda: ["instagram", "facebook", "phone"], min_length=1, max_length=3)
    prefer_instagram: bool = True
    product_terms: list[str] = Field(default_factory=lambda: ["genius weft", "天才", "flat tip", "flatip", "平型", "tape in", "贴发"], min_length=1, max_length=50)
    product_exclusions: list[str] = Field(default_factory=lambda: ["glue", "remover", "胶", "卸"], max_length=50)
    no_order_days: int = Field(180, ge=1, le=3650)
    no_followup_days: int = Field(30, ge=1, le=3650)
    missing_followup: Literal["exclude", "include"] = "exclude"

    @field_validator("countries")
    @classmethod
    def country_codes(cls, values):
        values = [v.strip().upper() for v in values]
        if any(len(v) != 2 or not v.isascii() or not v.isalpha() for v in values):
            raise ValueError("国家须使用两位字母代码")
        return list(dict.fromkeys(values))

    @field_validator("product_terms", "product_exclusions")
    @classmethod
    def terms(cls, values):
        values = [v.strip() for v in values]
        if any(not re.sub(r"[\s_\-]+", "", v) or len(v) > 80 for v in values):
            raise ValueError("产品词须为1至80字的非空文本")
        return list(dict.fromkeys(values))


class PoolQuotas(StrictRule):
    schema_version: Literal["public_pool_quotas_v1"] = "public_pool_quotas_v1"
    tiers: dict[str, int] = Field(default_factory=lambda: {"T1": 20, "T2": 20, "T3": 20})
    team_scope: Literal["all"] = "all"
    total_limit: int = Field(60, ge=1, le=1500)

    @field_validator("tiers")
    @classmethod
    def tiers_valid(cls, values):
        if set(values) != {"T1", "T2", "T3"} or any(type(v) is not int or v < 0 or v > 500 for v in values.values()):
            raise ValueError("T1/T2/T3配额须为0至500的整数")
        if not sum(values.values()):
            raise ValueError("至少一个档位配额须大于0")
        return values


class PoolRuleInput(StrictRule):
    rules: PoolRules
    quotas: PoolQuotas


class PoolRuleSave(PoolRuleInput):
    expected_version: int = Field(..., ge=0)


class PoolConfiguredBatch(StrictRule):
    expected_version: int = Field(..., ge=1)
