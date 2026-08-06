"""薪资模块 — Pydantic Schemas（M1：档案 / 职级表 / 规则参数 / 部门映射）。

PII 出站规则：身份证与银行卡**永不返回明文**。列表与详情一律返回
`id_card_masked` / `bank_card_masked`；需要明文的场景（银行代发盘）走
独立的 salary:admin 端点，不在这里开口子。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 职级赛道白名单：与 seed.py 的 scheme 取值同一套口径
GRADE_SCHEMES = {
    "resource": "外贸业务员-分配资源",
    "develop": "外贸业务员-开发",
    "manage": "业务员管理岗",
    "merch": "跟单",
    "merch_manage": "跟单管理岗",
    "none": "无职级（手动定薪）",
}

PROFILE_STATUSES = ("active", "left")


# ---------------------------------------------------------------------------
# 员工档案
# ---------------------------------------------------------------------------

class ProfileBase(BaseModel):
    emp_no: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    user_id: Optional[int] = None

    hire_date: Optional[date] = None
    regular_date: Optional[date] = None
    leave_date: Optional[date] = None
    status: str = "active"

    dept_detail: Optional[str] = Field(None, max_length=64)
    dept_group_override: Optional[str] = Field(None, max_length=64)
    position: Optional[str] = Field(None, max_length=64)
    grade_scheme: Optional[str] = None
    grade_code: Optional[str] = Field(None, max_length=16)

    base_salary_override: Optional[Decimal] = None
    probation_salary: Optional[Decimal] = None
    probation_note: Optional[str] = Field(None, max_length=255)
    guaranteed_salary: Optional[Decimal] = None
    guaranteed_from: Optional[date] = None
    guaranteed_to: Optional[date] = None

    insurance_entity: Optional[str] = Field(None, max_length=64)
    payroll_included: int = 1
    fund_included: int = 1

    bank_name: Optional[str] = Field(None, max_length=64)
    dingtalk_userid: Optional[str] = Field(None, max_length=64)
    mobile: Optional[str] = Field(None, max_length=32)
    remark: Optional[str] = None

    @field_validator("emp_no")
    @classmethod
    def _norm_emp_no(cls, v: str) -> str:
        """工号去空格并去前导零：源表里 3 与 003 是同一人（反导入实证的错误 1）。"""
        s = str(v).strip()
        return s.lstrip("0") or s

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in PROFILE_STATUSES:
            raise ValueError(f"status 只能是 {PROFILE_STATUSES}")
        return v

    @field_validator("grade_scheme")
    @classmethod
    def _check_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in GRADE_SCHEMES:
            raise ValueError(f"grade_scheme 只能是 {sorted(GRADE_SCHEMES)}")
        return v

    @field_validator("payroll_included", "fund_included")
    @classmethod
    def _check_flag(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("标记位只能是 0 或 1")
        return v


class ProfileCreate(ProfileBase):
    """新建档案。PII 传明文，服务端加密+哈希后入库，明文不落任何列。"""
    id_card: Optional[str] = Field(None, max_length=32)
    bank_card: Optional[str] = Field(None, max_length=32)


class ProfileUpdate(BaseModel):
    """编辑档案。全字段可选；PII 传空串=清除，传 None=不动。"""
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    user_id: Optional[int] = None
    id_card: Optional[str] = Field(None, max_length=32)
    bank_card: Optional[str] = Field(None, max_length=32)

    hire_date: Optional[date] = None
    regular_date: Optional[date] = None
    leave_date: Optional[date] = None
    status: Optional[str] = None

    dept_detail: Optional[str] = Field(None, max_length=64)
    dept_group_override: Optional[str] = Field(None, max_length=64)
    position: Optional[str] = Field(None, max_length=64)
    grade_scheme: Optional[str] = None
    grade_code: Optional[str] = Field(None, max_length=16)

    base_salary_override: Optional[Decimal] = None
    probation_salary: Optional[Decimal] = None
    probation_note: Optional[str] = Field(None, max_length=255)
    guaranteed_salary: Optional[Decimal] = None
    guaranteed_from: Optional[date] = None
    guaranteed_to: Optional[date] = None

    insurance_entity: Optional[str] = Field(None, max_length=64)
    payroll_included: Optional[int] = None
    fund_included: Optional[int] = None

    bank_name: Optional[str] = Field(None, max_length=64)
    dingtalk_userid: Optional[str] = Field(None, max_length=64)
    mobile: Optional[str] = Field(None, max_length=32)
    remark: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PROFILE_STATUSES:
            raise ValueError(f"status 只能是 {PROFILE_STATUSES}")
        return v

    @field_validator("grade_scheme")
    @classmethod
    def _check_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in GRADE_SCHEMES:
            raise ValueError(f"grade_scheme 只能是 {sorted(GRADE_SCHEMES)}")
        return v


class ProfileOut(BaseModel):
    """档案出站形态。PII 只出脱敏串，明文与密文都不出现在响应里。"""
    id: int
    emp_no: str
    name: str
    user_id: Optional[int] = None

    id_card_masked: str = ""
    bank_card_masked: str = ""
    bank_name: Optional[str] = None

    hire_date: Optional[date] = None
    regular_date: Optional[date] = None
    leave_date: Optional[date] = None
    status: str

    dept_detail: Optional[str] = None
    dept_group: Optional[str] = None  # 映射表推导 or override 后的生效值
    dept_group_override: Optional[str] = None
    position: Optional[str] = None
    grade_scheme: Optional[str] = None
    grade_code: Optional[str] = None

    base_salary_override: Optional[Decimal] = None
    base_salary_effective: Optional[Decimal] = None  # 职级表 or override 推导的生效底薪
    probation_salary: Optional[Decimal] = None
    probation_note: Optional[str] = None
    guaranteed_salary: Optional[Decimal] = None
    guaranteed_from: Optional[date] = None
    guaranteed_to: Optional[date] = None

    insurance_entity: Optional[str] = None
    payroll_included: int = 1
    fund_included: int = 1

    dingtalk_userid: Optional[str] = None
    mobile: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# 职级薪级表
# ---------------------------------------------------------------------------

class GradeUpsert(BaseModel):
    scheme: str
    grade_code: str = Field(..., max_length=16)
    base_salary: Optional[Decimal] = None
    perf_full: Optional[Decimal] = None
    std_salary: Optional[Decimal] = None
    perf_target_monthly: Optional[Decimal] = None
    new_sign_min: Optional[int] = None
    team_rate: Optional[Decimal] = None
    effective_from: date
    effective_to: Optional[date] = None

    @field_validator("scheme")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        if v not in GRADE_SCHEMES:
            raise ValueError(f"scheme 只能是 {sorted(GRADE_SCHEMES)}")
        return v


class GradeOut(GradeUpsert):
    id: int


# ---------------------------------------------------------------------------
# 规则参数
# ---------------------------------------------------------------------------

class RuleParamUpdate(BaseModel):
    """改参数值。key 与生效日不可改——改口径请新建版本，否则历史批次无从追溯。"""
    param_value: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=255)


class RuleParamOut(BaseModel):
    id: int
    param_key: str
    param_value: str
    value_type: str
    category: Optional[str] = None
    description: Optional[str] = None
    effective_from: date
    effective_to: Optional[date] = None


# ---------------------------------------------------------------------------
# 部门映射
# ---------------------------------------------------------------------------

class DeptMappingUpsert(BaseModel):
    dept_detail: str = Field(..., min_length=1, max_length=64)
    dept_group: str = Field(..., min_length=1, max_length=64)
    sort_order: int = 0


class DeptMappingOut(DeptMappingUpsert):
    id: int


# ---------------------------------------------------------------------------
# 月度批次（M2-a）
# ---------------------------------------------------------------------------

class PeriodCreate(BaseModel):
    """建批次。workday_count 留空则用自动推算的初值（HR 可在批次页改）。"""
    year_month: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
                            description="批次月份 YYYY-MM")
    workday_count: Optional[int] = Field(None, ge=1, le=31)
    remark: Optional[str] = Field(None, max_length=255)


class PeriodWorkdayUpdate(BaseModel):
    workday_count: int = Field(..., ge=1, le=31)


class PeriodTransition(BaseModel):
    """状态跃迁。expected_version 必填——不带版本就是放弃并发保护。

    前端从列表/详情里拿到 status_version 原样带回；版本不符时后端返回 409，
    提示「已被他人修改，请刷新」而不是静默覆盖。
    """
    target: str = Field(..., min_length=1, max_length=24)
    expected_version: int = Field(..., ge=0)


class PeriodConfirm(BaseModel):
    """锁定批次。独立 schema 而不是复用 PeriodTransition。

    复用的话 target 是必填字段，前端调 /confirm 得凭空塞一个值进去（不塞就 422），
    而后端根本不读它——第一次对接必然踩坑然后困惑「这个值到底有没有用」。
    目标状态由端点本身决定，不该再从 body 里传。
    """
    expected_version: int = Field(..., ge=0)


class PeriodUnlock(BaseModel):
    """管理员解锁（决策 A4）。reason 必填：前次导出要被标记作废，无理由无法审计。"""
    reason: str = Field(..., min_length=1, max_length=255)
    expected_version: int = Field(..., ge=0)


class AttendanceSync(BaseModel):
    """从钉钉同步考勤。expected_version 必填，同 PeriodTransition 的理由。"""
    expected_version: int = Field(..., ge=0)


class AttendanceManualUpsert(BaseModel):
    """人工录入/修正一个人的考勤。

    **请假小时只有这一个入口**：钉钉的年假/事假/病假五列没有列 id，
    `getcolumnval` 取不到（2026-08-07 实测），打卡明细与请假明细两个接口的
    权限企业侧也未开通。所以事假/病假必须人填，而它们直接决定实出天数、
    缺勤扣款和 100 元全勤奖。

    全部字段可选：HR 常常只改一格。**不传 = 不动**，传 null 才是清空——
    如果把「没传」当成「清零」，改一格迟到就会顺手把病假抹掉。
    """
    personal_leave_hours: Optional[Decimal] = Field(None, ge=0, le=744)
    sick_leave_hours: Optional[Decimal] = Field(None, ge=0, le=744)
    annual_leave_days: Optional[Decimal] = Field(None, ge=0, le=31)
    annual_leave_remain: Optional[Decimal] = Field(None, ge=0, le=365)
    late_count: Optional[int] = Field(None, ge=0, le=999)
    early_leave_count: Optional[int] = Field(None, ge=0, le=999)
    miss_punch_count: Optional[int] = Field(None, ge=0, le=999)
    absent_count: Optional[Decimal] = Field(None, ge=0, le=31)
    expected_version: int = Field(..., ge=0)
