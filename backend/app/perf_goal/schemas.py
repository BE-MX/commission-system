"""Validated command contracts. All business datetimes are Beijing wall time."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.battle_report.schemas import OrderDecision
from app.perf_goal.models import GRANULARITIES, METRICS

Metric = Literal["gmv", "new_sign", "repeat_customers", "repeat_amount"]
Granularity = Literal["year", "quarter", "month"]
Target = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PeriodInput(Command):
    year: int = Field(ge=2020, le=2100)
    name: Annotated[str, Field(min_length=1, max_length=100)]


class GoalRow(Command):
    user_id: int = Field(gt=0)
    metric: Metric
    granularity: Granularity
    quarter: int | None = Field(default=None, ge=1, le=4)
    month: int | None = Field(default=None, ge=1, le=12)
    target_value: Target

    @model_validator(mode="after")
    def check_slot(self):
        if self.granularity == "year" and (self.quarter is not None or self.month is not None):
            raise ValueError("年度目标不允许填写季度或月份")
        if self.granularity == "quarter" and (self.quarter is None or self.month is not None):
            raise ValueError("季度目标必须填写季度且不允许填写月份")
        if self.granularity == "month" and (self.quarter is None or self.month is None):
            raise ValueError("月度目标必须同时填写季度与月份")
        if self.month is not None and self.quarter is not None:
            if (self.month - 1) // 3 + 1 != self.quarter:
                raise ValueError("月份与季度不一致")
        return self


class GoalsUpdate(Command):
    rows: list[GoalRow] = Field(max_length=2000)
    reason: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [(r.user_id, r.metric, r.granularity, r.quarter, r.month) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("同一批次内目标行重复")
        return self


class SplitInput(Command):
    metric: Metric
    source: Literal["year", "quarter"]
    target: Literal["quarter", "month"]
    weights: list[Decimal] = Field(min_length=3, max_length=4)
    user_ids: list[int] | None = Field(default=None, max_length=500)
    apply: bool = False

    @model_validator(mode="after")
    def check_split(self):
        if (self.source, self.target) not in (("year", "quarter"), ("quarter", "month")):
            raise ValueError("仅支持 年→季度 或 季度→月 拆分")
        expected = 4 if self.target == "quarter" else 3
        if len(self.weights) != expected:
            raise ValueError(f"拆分到{('季度' if self.target == 'quarter' else '月')}需要 {expected} 个权重")
        if any(w < 0 for w in self.weights):
            raise ValueError("拆分权重不能为负")
        if sum(self.weights) <= 0:
            raise ValueError("拆分权重之和必须大于 0")
        return self


class TeamGoalRow(Command):
    department_id: int = Field(gt=0)
    metric: Metric
    granularity: Granularity
    quarter: int | None = Field(default=None, ge=1, le=4)
    month: int | None = Field(default=None, ge=1, le=12)
    factor: Annotated[Decimal, Field(gt=0, le=10, max_digits=8, decimal_places=4)] | None = None
    override_value: Target | None = None
    clear_override: bool = False

    @model_validator(mode="after")
    def check_slot(self):
        if self.granularity == "year" and (self.quarter is not None or self.month is not None):
            raise ValueError("年度战队目标不允许填写季度或月份")
        if self.granularity == "quarter" and (self.quarter is None or self.month is not None):
            raise ValueError("季度战队目标必须填写季度且不允许填写月份")
        if self.granularity == "month" and (self.quarter is None or self.month is None):
            raise ValueError("月度战队目标必须同时填写季度与月份")
        if self.month is not None and self.quarter is not None and (self.month - 1) // 3 + 1 != self.quarter:
            raise ValueError("月份与季度不一致")
        return self


class TeamGoalsUpdate(Command):
    rows: list[TeamGoalRow] = Field(min_length=1, max_length=500)
    reason: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [(r.department_id, r.metric, r.granularity, r.quarter, r.month) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("同一批次内战队目标行重复")
        return self


class ConfigUpdate(Command):
    metrics_enabled: dict[Metric, bool] | None = None
    delivery_channel_mode: Literal["worknotice_first", "webhook_only"] | None = None
    ai_preset: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    default_factor: Annotated[Decimal, Field(gt=0, le=10, max_digits=8, decimal_places=4)] | None = None
    order_decisions: list[OrderDecision] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def unique_decisions(self):
        if self.order_decisions is not None:
            ids = [d.order_id for d in self.order_decisions]
            if len(ids) != len(set(ids)):
                raise ValueError("订单裁定不能重复提交同一订单")
        return self


__all__ = [
    "Command", "ConfigUpdate", "GoalRow", "GoalsUpdate", "Granularity", "Metric",
    "PeriodInput", "SplitInput", "TeamGoalRow", "TeamGoalsUpdate", "Target",
    "GRANULARITIES", "METRICS",
]
