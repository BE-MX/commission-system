"""Validated command contracts. All business datetimes are Beijing wall time."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import to_beijing_naive

Name = Annotated[str, Field(min_length=1, max_length=100)]
Money = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemberInput(Command):
    ark_user_id: int = Field(gt=0)
    team: Name
    is_captain: bool = False


class ReportInput(Command):
    name: Name
    start_date: date
    end_date: date
    target_deadline: datetime
    visibility: Literal["activity", "team", "self"] = "activity"
    members: list[MemberInput] = Field(min_length=1, max_length=200)

    @field_validator("target_deadline")
    @classmethod
    def normalize_deadline(cls, value):
        return to_beijing_naive(value)

    @model_validator(mode="after")
    def check_period(self):
        if self.start_date > self.end_date:
            raise ValueError("结束日期不得早于开始日期")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("单个战报最多支持 366 天")
        if self.target_deadline.date() > self.end_date:
            raise ValueError("目标填报截止时间不得晚于活动结束日")
        ids = [m.ark_user_id for m in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("同一个业务员只能加入一个活动小组")
        return self


class ReportUpdate(ReportInput):
    version: int = Field(gt=0)
    reason: str = Field(default="", max_length=500)


class StateChange(Command):
    action: Literal["publish", "archive", "restore"]
    version: int = Field(gt=0)


class TargetInput(Command):
    member_id: int = Field(gt=0)
    version: int = Field(gt=0)
    target_usd: Money


class TargetUpdate(Command):
    targets: list[TargetInput] = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def unique_members(self):
        ids = [t.member_id for t in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("目标列表不能重复提交同一业务员")
        return self
