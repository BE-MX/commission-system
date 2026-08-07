"""Validated request schemas for the customer image portal."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.customer_image.datetime_utils import as_utc_naive


class CustomerImageInviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: str = Field(min_length=1, max_length=64)
    product_ids: list[int] = Field(min_length=1)
    expires_at: datetime
    quota_total: int = Field(gt=0)

    @field_validator("product_ids")
    @classmethod
    def validate_product_ids(cls, value: list[int]) -> list[int]:
        if any(product_id <= 0 for product_id in value):
            raise ValueError("产品 ID 无效")
        if len(value) != len(set(value)):
            raise ValueError("产品不能重复")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiry(cls, value: datetime) -> datetime:
        value = as_utc_naive(value)
        now = datetime.now(UTC).replace(tzinfo=None)
        if value <= now:
            raise ValueError("失效时间必须晚于当前时间")
        return value


class CustomerImageGenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    selections: dict[str, str | bool]
    requirement: str = Field(default="", max_length=500)
