"""Strict public text protocol and admin configuration."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Positive = Annotated[int, Field(strict=True, gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: Text


class ChatRequest(StrictModel):
    preset: Annotated[Text, Field(max_length=64)]
    messages: Annotated[list[Message], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_messages(self):
        if self.messages[-1].role != "user":
            raise ValueError("last message must be user")
        if sum(len(m.content) for m in self.messages) > 16000:
            raise ValueError("messages exceed 16000 characters")
        return self


class AppCreate(StrictModel):
    name: Annotated[Text, Field(max_length=100)]
    owner_user_id: Positive
    site_url: Annotated[str, Field(max_length=512)] = ""
    description: Annotated[str, Field(max_length=1000)] = ""
    preset_ids: Annotated[list[Positive], Field(min_length=1, max_length=100)]
    is_enabled: bool = True
    daily_limit: Annotated[Positive, Field(le=100000)] = 100
    rpm_limit: Annotated[Positive, Field(le=1000)] = 10
    concurrency_limit: Annotated[Positive, Field(le=20)] = 2
    max_output_tokens: Annotated[Positive, Field(le=4096)] = 2048


class AppPatch(StrictModel):
    name: Annotated[Text, Field(max_length=100)] | None = None
    owner_user_id: Positive | None = None
    site_url: Annotated[str, Field(max_length=512)] | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None
    preset_ids: Annotated[list[Positive], Field(min_length=1, max_length=100)] | None = None
    is_enabled: bool | None = None
    daily_limit: Annotated[Positive, Field(le=100000)] | None = None
    rpm_limit: Annotated[Positive, Field(le=1000)] | None = None
    concurrency_limit: Annotated[Positive, Field(le=20)] | None = None
    max_output_tokens: Annotated[Positive, Field(le=4096)] | None = None

    @model_validator(mode="after")
    def forbid_nulls(self):
        if any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("explicit null is not allowed")
        return self


class ResolveRequest(StrictModel):
    reason: Annotated[Text, Field(min_length=5, max_length=1000)]
