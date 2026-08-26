"""Strict request schemas for external-system credential administration."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.time import to_beijing_naive


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IntegrationAppCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=100)
    owner_user_id: int = Field(ge=1)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def normalize_expires_at(cls, value: datetime | None) -> datetime | None:
        return to_beijing_naive(value)


class IntegrationAppRotate(StrictSchema):
    current_token_suffix: str = Field(min_length=6, max_length=6)
