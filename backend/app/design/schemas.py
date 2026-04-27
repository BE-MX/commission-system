"""设计预约 — Pydantic 数据模式"""

from datetime import date, datetime
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, model_validator


# ── 写入模式 ──────────────────────────────────────────────


class DesignRequestCreate(BaseModel):
    customer_name: str
    salesperson_id: int
    salesperson_name: str
    shoot_type: str
    shoot_type_remark: Optional[str] = None
    expect_start_date: date
    expect_end_date: date
    priority: str = "normal"
    remark: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self):
        today = date.today()
        if self.expect_start_date > self.expect_end_date:
            raise ValueError("期望开始日期不能晚于结束日期")
        if self.expect_start_date < today:
            raise ValueError("期望开始日期不能早于今天")
        delta = (self.expect_end_date - self.expect_start_date).days
        if delta > 30:
            raise ValueError("日期范围不能超过30天")
        return self


class DesignRequestAudit(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = None


class DesignRequestAction(BaseModel):
    action: Literal["confirm", "start", "complete", "cancel"]
    designer_id: Optional[int] = None
    plan_start_date: Optional[date] = None
    plan_end_date: Optional[date] = None
    comment: Optional[str] = None


class TaskReschedule(BaseModel):
    plan_start_date: date
    plan_end_date: date
    designer_id: Optional[int] = None
    comment: Optional[str] = None


class UnavailableDateCreate(BaseModel):
    dates: list[date]
    reason: str


class CapacityEntry(BaseModel):
    config_date: Optional[date] = None
    designer_id: Optional[int] = None
    max_parallel_tasks: int


class CapacityUpdate(BaseModel):
    entries: list[CapacityEntry]


class ModeUpdate(BaseModel):
    scheduling_mode: Literal["pool", "individual"]


# ── 读取模式 ──────────────────────────────────────────────


class DesignRequestListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_no: str
    customer_name: str
    salesperson_id: int
    salesperson_name: str
    shoot_type: str
    shoot_type_remark: Optional[str] = None
    expect_start_date: date
    expect_end_date: date
    priority: str
    remark: Optional[str] = None
    status: str
    conflict_detail: Optional[dict] = None
    assigned_designer_id: Optional[int] = None
    actual_start_date: Optional[date] = None
    actual_end_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class DesignTaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    task_no: str
    designer_id: int
    task_name: Optional[str] = None
    customer_name: Optional[str] = None
    salesperson_name: Optional[str] = None
    shoot_type: Optional[str] = None
    priority: Optional[str] = None
    plan_start_date: Optional[date] = None
    plan_end_date: Optional[date] = None
    actual_start_date: Optional[date] = None
    actual_end_date: Optional[date] = None
    status: str
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class GanttDesigner(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tasks: list[DesignTaskListItem] = []


class GanttResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    designers: list[GanttDesigner] = []
    unavailable_dates: list[date] = []
