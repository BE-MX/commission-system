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


class AwardBaseline(Command):
    ark_user_id: int = Field(gt=0)
    hired_date: date
    gmv_2025_usd: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    target_gmv_usd: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class OrderDecision(Command):
    order_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[0-9]+$")]
    order_no: Name
    company_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[0-9]+$")]
    owner_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[0-9]+$")]
    account_date: date
    role: Literal["new_sign", "repeat", "exclude_metrics"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class AwardRules(Command):
    baselines: list[AwardBaseline] = Field(default_factory=list, max_length=200)
    push_start_date: date
    source_sha256: str = Field(default="", max_length=64)
    order_decisions: list[OrderDecision] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_order_decisions(self):
        ids = [decision.order_id for decision in self.order_decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("订单裁定不能重复提交同一订单")
        return self


class ReportInput(Command):
    name: Name
    start_date: date
    end_date: date
    target_deadline: datetime
    visibility: Literal["activity", "team", "self"] = "activity"
    members: list[MemberInput] = Field(min_length=1, max_length=200)
    award_kind: Literal["gmv", "annual_repurchase", "new_sign_pk"] = "gmv"
    award_rules: AwardRules | None = None

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
        if self.award_kind == "gmv":
            if self.award_rules is not None:
                raise ValueError("GMV战报不使用奖项规则")
            return self
        rules = self.award_rules
        if rules is None or not self.start_date <= rules.push_start_date <= self.end_date:
            raise ValueError("请配置奖项规则及周期内的推送开始日")
        if any(not self.start_date <= decision.account_date <= self.end_date
               for decision in rules.order_decisions):
            raise ValueError("订单裁定的核算日期须位于战报周期内")
        if self.visibility != "activity":
            raise ValueError("奖项战报须允许全活动查看，保证排名与PK完整")
        if self.award_kind == "annual_repurchase":
            if (self.start_date, self.end_date) != (date(2026, 1, 1), date(2026, 12, 31)):
                raise ValueError("年度奖统计周期为2026全年")
            baseline_ids = [b.ark_user_id for b in rules.baselines]
            if len(baseline_ids) != len(set(baseline_ids)) or set(baseline_ids) != set(ids):
                raise ValueError("每位参评人须有唯一的2025年GMV基数")
            cutoff = rules.push_start_date.replace(year=rules.push_start_date.year - 2)
            if any(b.hired_date > cutoff for b in rules.baselines):
                raise ValueError("参评人须在推送开始日已入职两年以上")
        else:
            if (self.start_date, self.end_date) != (date(2026, 11, 1), date(2026, 11, 30)):
                raise ValueError("新签PK奖统计周期为2026年11月")
            teams = {m.team for m in self.members}
            if len(teams) != 2 or any(sum(m.is_captain for m in self.members if m.team == t) != 1 for t in teams):
                raise ValueError("PK须有两个团队，每队恰好一位队长")
            if rules.baselines:
                raise ValueError("PK奖不使用年度GMV基数")
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


class PosterConfigUpdate(Command):
    version: int = Field(gt=0)
    work_dates: list[date] = Field(default_factory=list, max_length=366)
    push_enabled: bool = False

    @field_validator("work_dates")
    @classmethod
    def distinct_dates(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("工作日不能重复")
        return sorted(values)
