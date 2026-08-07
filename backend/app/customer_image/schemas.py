"""Validated request schemas for the customer image portal."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.customer_image.datetime_utils import as_utc_naive


class CustomerImageOptionValueUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    prompt_fragment: str = Field(min_length=1)
    color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    pantone_code: str | None = Field(default=None, max_length=32)
    sort: int = 0
    is_active: bool = True


class CustomerImageProductOptionUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=100)
    control_type: str
    required: bool = False
    default_value: str | None = Field(default=None, max_length=200)
    sort: int = 0
    values: list[CustomerImageOptionValueUpsert] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.control_type not in {"single_choice", "color", "boolean"}:
            raise ValueError("unsupported product option control type")
        value_names = [item.value for item in self.values]
        if len(value_names) != len(set(value_names)):
            raise ValueError("product option values cannot be duplicated")
        active_names = {item.value for item in self.values if item.is_active}
        if self.required and self.default_value is None:
            raise ValueError("required product option must have a default value")
        if self.default_value is not None and self.default_value not in active_names:
            raise ValueError("product option default must be an active value")
        if self.control_type == "color" and any(item.color_hex is None for item in self.values):
            raise ValueError("color options require #RRGGBB values")
        if self.control_type == "boolean" and set(value_names) != {"true", "false"}:
            raise ValueError("boolean options require true and false values")
        return self


class CustomerImageProductUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = None
    fixed_prompt: str = Field(min_length=1)
    output_prompt: str = Field(min_length=1)
    sort: int = 0
    options: list[CustomerImageProductOptionUpsert] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def validate_unique_option_keys(cls, options):
        keys = [option.key for option in options]
        if len(keys) != len(set(keys)):
            raise ValueError("product option keys cannot be duplicated")
        return options


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
