"""Strict request and response contracts for the translation domain."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings
from app.whatsapp_translation.constants import (
    SUPPORTED_SOURCE_LANGUAGES,
    SUPPORTED_TARGET_LANGUAGES,
    TRANSLATION_DIRECTIONS,
)


class PairingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    proposed_token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    device_name: str = Field(min_length=1, max_length=100)
    browser_name: str = Field(min_length=1, max_length=50)
    browser_version: str = Field(min_length=1, max_length=32)
    extension_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class PairingCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_code: str = Field(min_length=32, max_length=128)


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    direction: Literal["incoming", "outgoing"]
    source_language: Literal["auto", "en", "es", "fr", "ar", "ja", "de", "nl", "sv", "zh-CN"]
    target_language: Literal["en", "es", "fr", "ar", "ja", "de", "nl", "sv", "zh-CN"]
    text: str

    @field_validator("text")
    @classmethod
    def validate_text_code_points(cls, value: str) -> str:
        value = value.strip()
        limit = get_settings().WHATSAPP_TRANSLATION_MAX_TEXT_CHARS
        if not 1 <= len(value) <= limit:
            raise ValueError(f"text must contain 1-{limit} Unicode code points")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in TRANSLATION_DIRECTIONS:
            raise ValueError("unsupported translation direction")
        return value

    @field_validator("source_language")
    @classmethod
    def validate_source_language(cls, value: str) -> str:
        if value not in SUPPORTED_SOURCE_LANGUAGES:
            raise ValueError("unsupported source language")
        return value

    @field_validator("target_language")
    @classmethod
    def validate_target_language(cls, value: str) -> str:
        if value not in SUPPORTED_TARGET_LANGUAGES:
            raise ValueError("unsupported target language")
        return value


class PairingCreated(BaseModel):
    device_code: str
    expires_at: datetime
    authorize_url: str


class PairingExchangeResult(BaseModel):
    status: Literal["pending", "ready"]
    device_id: int | None = None
    expires_at: datetime | None = None


class TranslationModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translated_text: str = Field(min_length=1)
    detected_source_language: Literal["zh-CN", "en", "es", "fr", "ar", "ja", "de", "nl", "sv"]
    back_translation: str | None = None

    @field_validator("translated_text", "back_translation")
    @classmethod
    def validate_output_code_points(cls, value: str | None) -> str | None:
        if value is None:
            return value
        limit = get_settings().WHATSAPP_TRANSLATION_MAX_TEXT_CHARS
        if len(value) > limit:
            raise ValueError(f"translation must contain at most {limit} Unicode code points")
        return value


class TranslateResponse(BaseModel):
    request_id: UUID
    translated_text: str
    detected_source_language: Literal["zh-CN", "en", "es", "fr", "ar", "ja", "de", "nl", "sv"]
    back_translation: str | None = None
    model_log_id: int
