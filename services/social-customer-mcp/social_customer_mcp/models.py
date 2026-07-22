"""Validated MCP input and structured output models."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SocialCustomerSearchInput(BaseModel):
    """Exactly one lookup key is accepted to prevent accidental broad queries."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str | None = Field(
        default=None,
        min_length=3,
        max_length=300,
        description="客户邮箱或联系人邮箱，精确匹配，例如 sales@example.com",
    )
    social_account: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="联系人社交平台账号，精确匹配，例如 WhatsApp 号码或 Facebook 主页账号",
    )
    contact_phone: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
        description="联系人电话，按数据库保存格式精确匹配，例如 +1 202 555 0123",
    )
    limit: int = Field(default=20, ge=1, le=50, description="本次最多返回多少条，默认 20，最大 50")
    offset: int = Field(default=0, ge=0, le=1000, description="分页偏移量，默认 0，最大 1000")

    @model_validator(mode="after")
    def _exactly_one_lookup(self):
        provided = [self.email, self.social_account, self.contact_phone]
        if sum(value is not None for value in provided) != 1:
            raise ValueError("email、social_account、contact_phone 必须且只能填写一个")
        return self

    @property
    def matched_by(self) -> str:
        if self.email is not None:
            return "email"
        if self.social_account is not None:
            return "social_account"
        return "contact_phone"

    @property
    def lookup_value(self) -> str:
        return self.email or self.social_account or self.contact_phone or ""


class SocialCustomerRecord(BaseModel):
    customer_company: str | None = None
    customer_name: str | None = None
    contact_name: str | None = None
    customer_email: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    social_platform: str | None = None
    social_account: str | None = None
    owner_user_name: str


class SocialCustomerSearchResult(BaseModel):
    matched_by: str
    total: int
    count: int
    offset: int
    has_more: bool
    next_offset: int | None
    items: list[SocialCustomerRecord]
