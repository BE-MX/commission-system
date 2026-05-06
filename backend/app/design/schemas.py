"""设计预约 — Pydantic 数据模式"""

from datetime import date, datetime
from typing import Optional, Literal, Union

from pydantic import BaseModel, ConfigDict, model_validator

PeriodType = Optional[Literal["am", "pm"]]


# ── 操作人混入 ─────────────────────────────────────────────


class OperatorMixin(BaseModel):
    operator_id: int = 1
    operator_name: str = "管理员"
    operator_role: str = "salesperson"


# ── 写入模式 ──────────────────────────────────────────────


class DesignRequestCreate(OperatorMixin):
    customer_name: str
    customer_level: Optional[str] = None
    salesperson_id: int
    salesperson_name: str
    shoot_type: str
    shoot_type_remark: Optional[str] = None
    expect_start_date: date
    expect_start_period: PeriodType = "am"
    expect_end_date: date
    expect_end_period: PeriodType = "pm"
    priority: str = "normal"
    remark: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self):
        today = date.today()
        if not self.shoot_type or not self.shoot_type.strip():
            raise ValueError("请选择拍摄类型")
        if self.expect_start_date > self.expect_end_date:
            raise ValueError("期望开始日期不能晚于结束日期")
        if self.expect_start_date == self.expect_end_date:
            sp = 0 if (self.expect_start_period or "am") == "am" else 1
            ep = 0 if (self.expect_end_period or "pm") == "am" else 1
            if sp > ep:
                raise ValueError("同一天内开始时段不能晚于结束时段")
        if self.expect_start_date < today:
            raise ValueError("期望开始日期不能早于今天")
        delta = (self.expect_end_date - self.expect_start_date).days
        if delta > 30:
            raise ValueError("日期范围不能超过30天")
        return self


class DesignRequestAudit(OperatorMixin):
    action: Literal["approve", "reject"]
    comment: Optional[str] = None


class DesignRequestAction(OperatorMixin):
    action: Literal["confirm", "start", "complete", "cancel"]
    designer_id: Optional[int] = None
    plan_start_date: Optional[date] = None
    plan_start_period: PeriodType = "am"
    plan_end_date: Optional[date] = None
    plan_end_period: PeriodType = "pm"
    comment: Optional[str] = None


class TaskReschedule(OperatorMixin):
    plan_start_date: date
    plan_start_period: PeriodType = "am"
    plan_end_date: date
    plan_end_period: PeriodType = "pm"
    designer_id: Optional[int] = None
    comment: Optional[str] = None


class UnavailableDateCreate(OperatorMixin):
    dates: list[date]
    period: PeriodType = None
    reason: str


class CapacityEntry(BaseModel):
    config_date: Optional[date] = None
    designer_id: Optional[int] = None
    period: PeriodType = None
    max_parallel_tasks: int


class CapacityUpdate(OperatorMixin):
    entries: list[CapacityEntry]


class ModeUpdate(OperatorMixin):
    scheduling_mode: Literal["pool", "individual"]


# ── 读取模式 ──────────────────────────────────────────────


class DesignRequestListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_no: str
    customer_name: str
    customer_level: Optional[str] = None
    salesperson_id: int
    salesperson_name: str
    shoot_type: str
    shoot_type_remark: Optional[str] = None
    expect_start_date: date
    expect_start_period: PeriodType = None
    expect_end_date: date
    expect_end_period: PeriodType = None
    priority: str
    remark: Optional[str] = None
    status: str
    conflict_detail: Optional[dict] = None
    assigned_designer_id: Optional[int] = None
    actual_start_date: Optional[date] = None
    actual_start_period: PeriodType = None
    actual_end_date: Optional[date] = None
    actual_end_period: PeriodType = None
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
    plan_start_period: PeriodType = None
    plan_end_date: Optional[date] = None
    plan_end_period: PeriodType = None
    actual_start_date: Optional[date] = None
    actual_start_period: PeriodType = None
    actual_end_date: Optional[date] = None
    actual_end_period: PeriodType = None
    status: str
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class GanttDesigner(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tasks: list[DesignTaskListItem] = []


class UnavailableDateItem(BaseModel):
    date: date
    period: PeriodType = None


class GanttResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    designers: list[GanttDesigner] = []
    unavailable_dates: list[UnavailableDateItem] = []
