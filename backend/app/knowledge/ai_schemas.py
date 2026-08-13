"""Schemas for governed knowledge AI optimization."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AiProfileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    preset_id: int = Field(gt=0)
    format_prompt: str | None = Field(default=None, max_length=10000)
    enhance_prompt: str | None = Field(default=None, max_length=10000)
    source_library_ids: list[int] = Field(default_factory=list, max_length=100)
    target_library_ids: list[int] = Field(min_length=1, max_length=100)
    retrieval_limit: int = Field(default=5, ge=1, le=20)
    context_char_limit: int = Field(default=30000, ge=1000, le=100000)
    allow_cross_library: bool = False
    require_citations: bool = True
    max_document_chars: int = Field(default=30000, ge=1000, le=100000)
    daily_limit: int = Field(default=20, ge=1, le=1000)
    max_concurrent_per_user: int = Field(default=2, ge=1, le=10)
    is_enabled: bool = True

    @model_validator(mode="after")
    def _validate_libraries(self):
        if len(self.source_library_ids) != len(set(self.source_library_ids)):
            raise ValueError("source libraries must be unique")
        if len(self.target_library_ids) != len(set(self.target_library_ids)):
            raise ValueError("target libraries must be unique")
        return self


class AiJobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    mode: Literal["format", "enhance"]
    profile_id: int = Field(gt=0)
    base_revision_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class AiProfileTestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sample_text: str = Field(min_length=1, max_length=4000)
    target_library_id: int = Field(gt=0)
