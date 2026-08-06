"""Validated inputs for Design Image Studio domain services."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VERIFIED_SIZES = ("1024x1024", "1024x1536", "1536x1024")
VERIFIED_QUALITIES = ("low", "medium", "high")
MAX_REFERENCE_ASSETS = 4


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(default="新对话", min_length=1, max_length=200)


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


class PromptTemplateOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=32)
    choices: list[str] = Field(min_length=1, max_length=12)

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, value: list[str]) -> list[str]:
        if any(not choice or len(choice) > 100 for choice in value):
            raise ValueError("参数取值不能为空且不超过 100 字")
        if len(value) != len(set(value)):
            raise ValueError("参数取值不能重复")
        return value


class PromptTemplateUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=4000)
    options: list[PromptTemplateOption] = Field(default_factory=list, max_length=8)
    is_active: bool = True
    sort: int = Field(default=0, ge=0, le=9999)

    @model_validator(mode="after")
    def validate_placeholders_have_options(self):
        import re

        keys = {option.key for option in self.options}
        if len(keys) != len(self.options):
            raise ValueError("参数槽 key 不能重复")
        placeholders = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", self.content))
        missing = placeholders - keys
        if missing:
            raise ValueError(f"模板占位 {sorted(missing)} 缺少对应参数槽定义")
        return self


class LibraryAssetClone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: int = Field(gt=0)
