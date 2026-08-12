"""Response schemas for the operations center."""

from typing import Any, Literal, Optional

from pydantic import BaseModel


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


class OperationsOverview(BaseModel):
    instance: dict[str, Any]
    scheduler: SchedulerView
    services: list[RuntimeServiceView]
    summary: dict[str, int]
    generated_at: str


class JobActionResult(BaseModel):
    job_id: str
    action: Literal["run", "pause", "resume"]
    accepted: bool = True
    message: str
