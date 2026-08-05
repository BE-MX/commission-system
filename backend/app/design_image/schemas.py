"""Validated inputs for Design Image Studio domain services."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VERIFIED_SIZES = ("1024x1024", "1024x1536", "1536x1024")
VERIFIED_QUALITIES = ("low", "medium", "high")
MAX_REFERENCE_ASSETS = 4


class TurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    prompt: str = Field(min_length=1, max_length=4000)
    session_id: int | None = Field(default=None, gt=0)
    base_asset_id: int | None = Field(default=None, gt=0)
    reference_asset_ids: list[int] = Field(
        default_factory=list, max_length=MAX_REFERENCE_ASSETS
    )
    size: str = Field(default="1024x1024")
    quality: str = Field(default="medium")

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if value not in VERIFIED_SIZES:
            raise ValueError("不支持的图片尺寸")
        return value

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, value: str) -> str:
        if value not in VERIFIED_QUALITIES:
            raise ValueError("不支持的质量档位")
        return value

    @field_validator("reference_asset_ids")
    @classmethod
    def validate_reference_ids(cls, value: list[int]) -> list[int]:
        if any(asset_id <= 0 for asset_id in value):
            raise ValueError("参考图 ID 无效")
        if len(value) != len(set(value)):
            raise ValueError("参考图不能重复")
        return value

    @model_validator(mode="after")
    def validate_base_is_not_a_reference(self):
        if self.base_asset_id in self.reference_asset_ids:
            raise ValueError("基准图不能同时作为额外参考图")
        return self


class RetryJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
