from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TemplateFieldIn(BaseModel):
    key: str = Field(..., max_length=50)
    label: str = Field(..., max_length=60)
    kind: str
    options: dict | None = None
    emphasis: str = "more"
    hint: str | None = Field(None, max_length=200)
    nature: str | None = None
    show_when: dict | None = None


class TemplateAvoidIn(BaseModel):
    rule: str = Field(..., min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=20)


class TemplateUpdateIn(BaseModel):
    version: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=60)
    prep_fields: list[TemplateFieldIn] = Field(default_factory=list, max_length=30)
    record_fields: list[TemplateFieldIn] = Field(default_factory=list, max_length=30)
    short_form: str | None = Field(None, max_length=300)
    guidance: str | None = Field(None, max_length=10000)
    params: dict = Field(default_factory=dict)
    avoid: list[TemplateAvoidIn] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("模板名称不能为空")
        return value.strip()
