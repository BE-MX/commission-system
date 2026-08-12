"""Request and response schemas for the operations center."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SchedulerJobView(BaseModel):
    id: str
    name: str
    domain: str
    owner: str
    trigger: str
    registered: bool = True
    next_run_at: Optional[str] = None
    paused: bool = False
    running_instances: int = 0
    last_started_at: Optional[str] = None
    last_finished_at: Optional[str] = None
    last_status: Literal["disabled", "never", "running", "success", "failed", "missed", "skipped"] = "never"
    last_error: Optional[str] = None


class SchedulerView(BaseModel):
    enabled: bool
    running: bool
    timezone: str
    expected_job_count: int
    registered_job_count: int
    jobs: list[SchedulerJobView]


class RuntimeServiceView(BaseModel):
    id: str
    name: str
    category: str
    environment: str
    owner: str
    management: Literal["managed", "observed", "unmanaged"]
    status: Literal["healthy", "degraded", "unconfigured", "unmanaged", "unknown"]
    detail: str
    endpoint: Optional[str] = None
    checked_at: Optional[str] = None
    latency_ms: Optional[int] = None


class RuntimeInstanceView(BaseModel):
    service_id: str
    instance_id: str
    service_name: str
    environment: str
    version: Optional[str] = None
    status: Literal["healthy", "degraded"]
    started_at: str
    last_activity_at: Optional[str] = None
    last_heartbeat_at: str
    heartbeat_age_seconds: int
    consecutive_misses: int
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class RuntimeHeartbeatPayload(BaseModel):
    service_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    instance_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    service_name: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=80)
    version: Optional[str] = Field(default=None, max_length=80)
    status: Literal["healthy", "degraded"] = "healthy"
    started_at: datetime
    last_activity_at: Optional[datetime] = None
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    dependencies: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("started_at", "last_activity_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须包含时区")
        return value

    @field_validator("service_name", "environment", "version")
    @classmethod
    def validate_display_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("显示字段不能为空或包含控制字符")
        return normalized

    @field_validator("capabilities", "dependencies")
    @classmethod
    def validate_names(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            text = str(value).strip()
            if not text or len(text) > 100:
                raise ValueError("能力与依赖名称长度必须为 1-100")
            if text not in normalized:
                normalized.append(text)
        return normalized


class RuntimeHeartbeatAck(BaseModel):
    service_id: str
    instance_id: str
    accepted_at: str
    next_heartbeat_within_seconds: int


class JobRunView(BaseModel):
    id: int
    job_id: str
    job_name: str
    domain: str
    instance_id: str
    planned_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: Literal["running", "success", "failed", "missed", "skipped"]
    duration_ms: Optional[int] = None
    error_digest: Optional[str] = None
    triggered_by: str


class OperationsOverview(BaseModel):
    instance: dict[str, Any]
    scheduler: SchedulerView
    services: list[RuntimeServiceView]
    runtime_instances: list[RuntimeInstanceView] = Field(default_factory=list)
    summary: dict[str, int]
    generated_at: str


class JobActionResult(BaseModel):
    job_id: str
    action: Literal["run", "pause", "resume"]
    accepted: bool = True
    message: str
