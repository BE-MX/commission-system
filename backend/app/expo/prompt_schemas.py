"""Validated, non-executable prompt templates and version mutation payloads."""

from string import Formatter

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.expo.prompt_catalog import PARTS_BY_KEY, SCENE_KEYS


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: dict[str, str]
    scene_prompts: dict[str, str]
    outfit_options: list[str] = Field(max_length=80)
    jewelry_options: list[str] = Field(max_length=80)

    @field_validator("parts")
    @classmethod
    def validate_parts(cls, values):
        if values.keys() != PARTS_BY_KEY.keys():
            raise ValueError("提示词分区不完整或含未知分区，请刷新配置页面")
        for key, text in values.items():
            field = PARTS_BY_KEY[key]
            label = field["label"]
            if len(text) > 20000:
                raise ValueError(f"{label}不能超过 20000 字")
            if field.get("required") and not text.strip():
                raise ValueError(f"{label}不能为空")
            try:
                tokens = list(Formatter().parse(text))
            except ValueError as exc:
                raise ValueError(f"{label}的大括号不成对；普通大括号请写成双括号") from exc
            for _, variable, spec, conversion in tokens:
                if variable is not None and (variable not in field["variables"] or spec or conversion):
                    raise ValueError(f"{label}包含不支持的占位符 {{{variable}}}；请使用页面列出的占位符")
        return values

    @field_validator("scene_prompts")
    @classmethod
    def validate_scenes(cls, values):
        if set(values) != SCENE_KEYS:
            raise ValueError("场景描述不完整或含未知场景，请刷新配置页面")
        if any(not value.strip() or len(value) > 6000 for value in values.values()):
            raise ValueError("每个场景描述需填写 1 至 6000 字")
        return values

    @field_validator("outfit_options", "jewelry_options")
    @classmethod
    def validate_options(cls, values):
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("每个穿搭或首饰候选需填写 1 至 2000 字")
        return values


class PromptVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    hint: str = Field(default="", max_length=160)
    is_active: bool = True
    config: PromptConfig

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("版本名称不能为空")
        return value.strip()


class PromptVersionUpdate(PromptVersionCreate):
    expected_revision: int = Field(gt=0)


class PromptRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: PromptConfig
    mode: str = Field(default="tryon", pattern="^(tryon|scene)$")
    scene_key: str | None = Field(default=None, max_length=32)
    wig_id: int | None = Field(default=None, gt=0)
    hair_color_id: int | None = Field(default=None, gt=0)
