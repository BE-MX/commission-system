"""AI 接入模块 — Pydantic 模式"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Provider ──────────────────────────────────────────

class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    provider_type: str = Field(..., pattern="^(direct|accio_work)$")
    api_base: str = Field(..., min_length=1, max_length=512)
    api_key: Optional[str] = Field(None, max_length=2048)
    extra_headers: Optional[dict] = None
    is_enabled: bool = True
    timeout_sec: int = Field(60, ge=1, le=3600)
    remark: Optional[str] = Field(None, max_length=256)

    @field_validator("api_base")
    @classmethod
    def _check_api_base(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("API Base 必须是有效的 HTTP/HTTPS URL")
        return v


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    provider_type: Optional[str] = Field(None, pattern="^(direct|accio_work)$")
    api_base: Optional[str] = Field(None, min_length=1, max_length=512)
    api_key: Optional[str] = Field(None, max_length=2048)
    extra_headers: Optional[dict] = None
    is_enabled: Optional[bool] = None
    timeout_sec: Optional[int] = Field(None, ge=1, le=3600)
    remark: Optional[str] = Field(None, max_length=256)

    @field_validator("api_base")
    @classmethod
    def _check_api_base(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if v and not v.startswith(("http://", "https://")):
                raise ValueError("API Base 必须是有效的 HTTP/HTTPS URL")
        return v


class Provider(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    api_base: str
    api_key: str  # 前端返回 ****
    extra_headers: Optional[dict] = None
    is_enabled: bool
    timeout_sec: int
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class ProviderTestResult(BaseModel):
    latency_ms: int
    status: str  # ok | error
    detail: str


# ── Preset ────────────────────────────────────────────

class PresetCreate(BaseModel):
    preset_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    provider_id: int
    model: Optional[str] = Field(None, max_length=128)
    system_prompt: Optional[str] = None
    parameters: Optional[dict] = None
    description: Optional[str] = Field(None, max_length=512)


class PresetUpdate(BaseModel):
    preset_name: Optional[str] = Field(None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    provider_id: Optional[int] = None
    model: Optional[str] = Field(None, max_length=128)
    system_prompt: Optional[str] = None
    parameters: Optional[dict] = None
    description: Optional[str] = Field(None, max_length=512)
    is_enabled: Optional[bool] = None


class Preset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    preset_name: str
    provider_id: int
    provider_name: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    parameters: Optional[dict] = None
    description: Optional[str] = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class PresetTestRequest(BaseModel):
    test_message: str = Field(..., min_length=1, max_length=4000)


class PresetTestResult(BaseModel):
    status: str
    response: str
    tokens_used: Optional[int] = None
    duration_ms: int


# ── Call Log ──────────────────────────────────────────

class CallLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[str] = None
    caller_module: str
    caller_user_id: Optional[int] = None
    preset_name: str
    provider_type: str
    model: Optional[str] = None
    tokens_used: Optional[int] = None
    duration_ms: Optional[int] = None
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class CallLogDetail(CallLogItem):
    prompt_snapshot: Optional[str] = None
    response_snapshot: Optional[str] = None
    tokens_prompt: Optional[int] = None
    tokens_completion: Optional[int] = None


class LogSummary(BaseModel):
    tokens_total: int
    success_count: int
    error_count: int
    timeout_count: int
    avg_duration_ms: int


class CallLogList(BaseModel):
    total: int
    summary: LogSummary
    items: list[CallLogItem]


# ── Invoke ────────────────────────────────────────────

class ChatRequest(BaseModel):
    preset: str = Field(..., min_length=1, max_length=64)
    caller_module: str = Field(..., min_length=1, max_length=64)
    caller_user_id: Optional[int] = None
    messages: list[dict] = Field(..., min_length=1)


class ChatResponse(BaseModel):
    content: str
    tokens_used: Optional[int] = None
    duration_ms: int
    log_id: int


class DelegateRequest(BaseModel):
    preset: str = Field(..., min_length=1, max_length=64)
    caller_module: str = Field(..., min_length=1, max_length=64)
    caller_user_id: Optional[int] = None
    task: dict[str, Any]
    callback_url: Optional[str] = None


class DelegateResponse(BaseModel):
    task_id: str
    status: str
    log_id: int


class TaskResult(BaseModel):
    task_id: str
    status: str
    result: Optional[dict] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
