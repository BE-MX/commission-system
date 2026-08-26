"""薪资模块 — 计算引擎（M3）。

## 分层

- `calc_record`：**纯函数**。不碰 session，全部输入由调用方备齐（档案、考勤行、
  匹配到的社保/公积金导入行、参数快照、当月调薪记录、批次上下文、手动列现值）。
  管钱逻辑 100% 可单测是 DoD 硬要求，所以这里一个 `db` 参数都不许出现。
- `calculate_period`：批次编排。取数 → 逐人 `calc_record` → upsert `salary_record`
  → 推进状态机。事务边界与留痕只在这一层。
- `edit_record_manual`：复核期手动列行内编辑。改完用与引擎**同一套** `assemble_totals`
  重算该行小计/实发——两套公式各写一遍迟早漂，而漂的那次就是算错钱。

## 口径锚点（全部经 3 月真值逐人验证，见 tests/test_salary_calc.py）

- **符号约定**：社保/公积金/缺勤扣款/减项小计**存负数**（与 HR 原表同构），
  其他款带符号（正=加钱）。实发 = round(底薪 + 增项小计 + 减项小计 + 补贴)。
  谷振尧 10000+4000−1864.23 → 12136；刘德明其他款 +1000 → 减项小计 +283.12。
- **月中转正/调薪加权**（决策 B2）：固定 30 天基数，**生效当日新旧各半**。
  陈佳乐 3/14 转正：(3500×13.5 + 4000×16.5)/30 = 3775.00，与 3 月表分毫不差。
  加权**只作用于底薪**；工龄/全勤/绩效目标按月末档案取，不加权——这不是疏漏，
  是 B2 原文，维护者不要「修正」它。
- **应出天数两阶段**：手动钉值 > 月中入离职 → 工作日数 > 阶段一实出 <15 → 工作日数
  > 满月 31（B1）。「两阶段显式」指先按 31 算出阶段一实出再判定，不做循环依赖。
  张甜甜 3/2（当月首个工作日）入职算满月 31；王槐竹 3/9 入职 → 22。
- **保底补足**：补贴 auto = max(0, 保底 − |缺勤扣款| − 保底前实发)，生效区间外不补
  （徐瑞萍/张紫娟保底 2026-04 起，3 月不补——负例同样验证过）。
- **实发舍入**：四舍五入到元（ROUND_HALF_UP，不是 Python 默认的银行家舍入）。
  张紫娟 1113.64 → 1114。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from app.core.time import beijing_now
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.salary import attendance_service, period_service, service
from app.salary.models import (
    SalaryAttendance,
    SalaryChangeLog,
    SalaryEmployeeProfile,
    SalaryFundImport,
    SalaryGradeTable,
    SalaryInsuranceImport,
    SalaryPeriod,
    SalaryRecord,
)

logger = logging.getLogger("commission")

CENT = Decimal("0.01")

# calc_flags 取值（写进 salary_record.calc_flags，异常面板按它出记录级待办）
FLAG_NEGATIVE_NET = "negative_net"            # 实发 < 0：拦 confirm，强制人工决策
FLAG_GUARANTEED_TOPUP = "guaranteed_topup"    # 保底补足触发
FLAG_MID_MONTH_WEIGHTED = "mid_month_weighted"  # 月中转正/调薪，底薪按 B2 加权
FLAG_BASE_MISSING = "base_missing"            # 拿不到底薪（前置异常面板也该已报）
FLAG_ATTENDANCE_MISSING = "attendance_missing"  # 无考勤行，按 0 缺勤算
FLAG_INSURANCE_MISSING = "insurance_missing"  # 应参保但无匹配导入行 → 社保 0
FLAG_FUND_MISSING = "fund_missing"            # 应缴公积金但无匹配导入行 → 公积金 0
FLAG_ABSENCE_CLAMPED = "absence_clamped"      # 缺勤天数超过应出，已按应出截断

# 行内编辑允许的手动列 → 记录列名。白名单以外的字段一律拒绝。
MANUAL_EDIT_FIELDS = {
    "bonus": "bonus_manual",
    "performance": "performance_manual",
    "other": "other_manual",
    "subsidy": "subsidy_manual",
    "income_tax": "income_tax_amount",
}


class CalcError(ValueError):
    """计算流程错误（状态不对、有 blocking 异常未处理）。文案直接给 HR 看。"""


@dataclass
class PeriodContext:
    """批次上下文：月份边界与工作日数。由编排层从 period 推出，纯函数只读。"""

    year: int
    month: int
    month_start: date
    month_end: date
    workday_count: Decimal
    first_workday: date
    last_workday: date


def build_period_context(period: SalaryPeriod, params: dict[str, str]) -> PeriodContext:
    """从批次行推出月份上下文。workday_count 用批次上的人工确认值，不自己猜。"""
    y, m = period_service.parse_year_month(period.year_month)
    natural = period.natural_days or period_service.natural_days_of(y, m)
    month_start = date(y, m, 1)
    month_end = date(y, m, natural)
    workdays = [d for d in range(1, natural + 1) if date(y, m, d).weekday() < 5]
    if period.workday_count is None:
        raise CalcError(f"{period.year_month} 批次缺工作日数，请先在批次页填写")
    return PeriodContext(
        year=y,
        month=m,
        month_start=month_start,
        month_end=month_end,
        workday_count=Decimal(period.workday_count),
        first_workday=date(y, m, workdays[0]),
        last_workday=date(y, m, workdays[-1]),
    )


# ---------------------------------------------------------------------------
# 纯函数：各列
# ---------------------------------------------------------------------------

def _q2(v: Decimal) -> Decimal:
    """量化到分，显式 HALF_UP。Decimal 默认是银行家舍入：33.325 → 33.32，
    而 HR 的 Excel 是四舍五入（33.33）——下次复算会对出 1 分差。"""
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def triple_final(auto: Optional[Decimal], manual: Optional[Decimal]) -> Optional[Decimal]:
    """三元组生效值：人工覆盖优先（决策 A2）。None 参与求和时按 0。"""
    return manual if manual is not None else auto


def _nz(v: Optional[Decimal]) -> Decimal:
    return v if v is not None else Decimal("0")


def _base_from_snapshot(
    snap: Optional[dict[str, Any]],
    grade_map: dict[tuple[str, str], SalaryGradeTable],
) -> Optional[Decimal]:
    """从 change_log 的 old/new_value JSON 还原底薪。还原不出返回 None（调用方兜底）。"""
    if not snap:
        return None
    override = snap.get("base_salary_override")
    if override is not None:
        return Decimal(str(override))
    scheme, code = snap.get("grade_scheme"), snap.get("grade_code")
    if scheme and code:
        row = grade_map.get((scheme, code))
        if row is not None:
            return row.std_salary if scheme == "manage" else row.base_salary
    return None


def calc_base_salary(
    profile: SalaryEmployeeProfile,
    grade_map: dict[tuple[str, str], SalaryGradeTable],
    changes: list[SalaryChangeLog],
    ctx: PeriodContext,
    params: dict[str, str],
) -> tuple[Optional[Decimal], bool]:
    """底薪。返回 (金额, 是否月中加权)。

    分段规则（优先级从上到下）：
    1. 试用期整月（无转正日或转正日晚于本月）→ 试用期底薪；
    2. 转正日落在本月 → 试用期底薪 × 旧段 + 转正后底薪 × 新段，30 天基数（B2）；
    3. 当月有调薪/调级记录（change_log）→ 同样按 30 天基数分段加权；
    4. 其余 → 当前定薪（手动定薪 > 职级表）。

    **生效当日新旧各半**：生效日 d 的旧段天数 = d − 0.5。这是让陈佳乐
    (3500×13.5+4000×16.5)/30 = 3775.00 与 3 月表分位一致的口径，钉死。

    转正段的费率取「其后首个调薪记录的 old_value」而不是一味用当前定薪：
    转正 3/14 转正到 4000、3/20 又调到 4500 时，中间段必须是 4000——
    当前定薪（4500）会把中间段也算高。没有后续调薪时才回落当前定薪。
    """
    weight_base = service.param_decimal(params, "mid_month_weight_base", Decimal("30"))
    if weight_base <= 0:
        raise CalcError("规则参数 mid_month_weight_base 必须大于 0，请到规则配置页修正")

    regular_base = service.resolve_base_salary(profile, grade_map)
    in_month = sorted(
        (c for c in changes
         if c.effective_date and ctx.month_start < c.effective_date <= ctx.month_end),
        key=lambda x: x.effective_date,
    )
    regular_in_month = (
        profile.regular_date is not None
        and ctx.month_start < profile.regular_date <= ctx.month_end
    )
    probation_at_start = profile.probation_salary is not None and (
        profile.regular_date is None or profile.regular_date > ctx.month_start
    )

    # 整月无变化：直取（试用期整月 / 正式整月）
    if not regular_in_month and not in_month:
        if probation_at_start:
            return _q2(profile.probation_salary), False
        return (_q2(regular_base) if regular_base is not None else None), False

    # 拼分段边界：(生效日−0.5, 新费率)。还原不出费率的记录跳过（费率延续）。
    boundaries: list[tuple[Decimal, Decimal]] = []
    if regular_in_month and profile.probation_salary is not None:
        later_old = next(
            (r for c in in_month
             if c.effective_date >= profile.regular_date
             for r in [_base_from_snapshot(c.old_value, grade_map)]
             if r is not None),
            None,
        )
        rate_after = later_old if later_old is not None else regular_base
        if rate_after is not None:
            boundaries.append(
                (Decimal(profile.regular_date.day) - Decimal("0.5"), Decimal(rate_after)))
    for c in in_month:
        new_rate = _base_from_snapshot(c.new_value, grade_map)
        if new_rate is not None:
            boundaries.append(
                (Decimal(c.effective_date.day) - Decimal("0.5"), Decimal(new_rate)))

    if not boundaries:
        # 有变化记录但还原不出费率——退回定薪，不加权。**但试用期员工必须仍按
        # 试用期底薪**：HR 只改了保底/转正日这类噪音也会写 change_log，若不查
        # probation_at_start，试用期 3000 会被静默按正式 4000 发出（三轮审查 P0-1）。
        if probation_at_start:
            return _q2(profile.probation_salary), False
        return (_q2(regular_base) if regular_base is not None else None), False

    # 起点费率：试用期底薪 > 首条变化的 old_value > 当前定薪
    if probation_at_start:
        start_rate: Optional[Decimal] = profile.probation_salary
    elif in_month:
        start_rate = _base_from_snapshot(in_month[0].old_value, grade_map) or regular_base
    else:
        start_rate = regular_base
    if start_rate is None:
        return None, True

    boundaries.sort(key=lambda b: b[0])
    total = Decimal("0")
    cursor = Decimal("0")
    rate = Decimal(start_rate)
    for boundary, new_rate in boundaries:
        b = min(max(boundary, Decimal("0")), weight_base)
        total += rate * (b - cursor)
        cursor = b
        rate = new_rate
    total += rate * (weight_base - cursor)
    return _q2(total / weight_base), True


def calc_seniority(
    profile: SalaryEmployeeProfile, ctx: PeriodContext, params: dict[str, str]
) -> Decimal:
    """工龄工资 = min(200 × 周年数, 2000)。周年数 = 纪念日在当月末之前的个数。

    「按工资月所在月份过周年即上调」：纪念日落在本月也算。刘也 2025-03-03 入职，
    2026-03-03 满一年，3 月表当月即给 200——纪念日 ≤ 当月末即计入。
    （谷振尧 2016-03-28 入职 → 2026-03-28 满 10 年 → 2000 撞上限，同样验证过。）
    """
    if profile.seniority_override is not None:
        return _q2(profile.seniority_override)
    if profile.special_calc:
        # 特殊计薪（姜妮妮/刘德明类）：工龄不发，除非上面钉了值
        return Decimal("0.00")
    if not profile.hire_date:
        return Decimal("0.00")
    step = service.param_decimal(params, "seniority_step", Decimal("200"))
    cap = service.param_decimal(params, "seniority_cap", Decimal("2000"))
    years = 0
    for k in range(1, 100):
        try:
            anniversary = profile.hire_date.replace(year=profile.hire_date.year + k)
        except ValueError:
            # 2 月 29 日入职：平年纪念日按 2/28 计
            anniversary = profile.hire_date.replace(year=profile.hire_date.year + k, day=28)
        if anniversary > ctx.month_end:
            break
        years = k
    return _q2(min(step * years, cap))


def calc_attendance_bonus(
    profile: SalaryEmployeeProfile,
    attendance: Optional[SalaryAttendance],
    params: dict[str, str],
) -> Decimal:
    """全勤奖。全勤判定在考勤落库时已做（含 B3 年假不破全勤），这里只读结果。

    特殊计薪人员不发（姜妮妮/刘德明 3 月表 31/31 出勤但全勤奖为 0，§9.5）。
    """
    if profile.special_calc:
        return Decimal("0.00")
    bonus = service.param_decimal(params, "attendance_bonus", Decimal("100"))
    if attendance is not None and attendance.full_attendance:
        return _q2(bonus)
    return Decimal("0.00")


def calc_social_fund(
    profile: SalaryEmployeeProfile,
    insurance_amount: Optional[Decimal],
    fund_amount: Optional[Decimal],
    flags: set[str],
) -> tuple[Decimal, Decimal]:
    """社保/公积金个人部分，**存负数**（与 HR 原表同构）。

    匹配不到 → 0 并打旗进异常面板，绝不报错阻断——3 月就有新入职未参保
    （王槐竹社保 0）与公积金 0（牟亮亮）的正常形态。
    """
    social = Decimal("0.00")
    if insurance_amount is not None:
        social = _q2(-abs(Decimal(insurance_amount)))
    elif (profile.insurance_entity or "").strip():
        flags.add(FLAG_INSURANCE_MISSING)

    fund_amt = Decimal("0.00")
    if not profile.fund_included:
        pass  # 不缴公积金：直接 0，不报警（牟亮亮形态）
    elif fund_amount is not None:
        fund_amt = _q2(-abs(Decimal(fund_amount)))
    else:
        flags.add(FLAG_FUND_MISSING)
    return social, fund_amt


def resolve_final_due_days(
    profile: SalaryEmployeeProfile,
    attendance: Optional[SalaryAttendance],
    ctx: PeriodContext,
    params: dict[str, str],
) -> Decimal:
    """应出天数终值。两阶段显式（设计文档 M3，不做循环依赖）：

    1. 手动钉值（李晓雨 21.75——规则复原不了的按真值钉）；
    2. 月中入职（入职日晚于当月首个工作日）或月中离职 → 当月工作日数。
       张甜甜 3/2（首个工作日）入职算满月 31；王槐竹 3/9 入职 → 22；
    3. 阶段一实出（31 基准）< min_actual_days_for_full_base → 工作日数；
    4. 其余 → full_month_days（B1，固定 31）。
    """
    full_base = service.param_decimal(params, "full_month_days", Decimal("31"))
    if attendance is not None and attendance.due_days_manual is not None:
        return Decimal(attendance.due_days_manual)
    if profile.hire_date and profile.hire_date > ctx.first_workday and \
            ctx.month_start <= profile.hire_date <= ctx.month_end:
        return ctx.workday_count
    if profile.leave_date and ctx.month_start <= profile.leave_date < ctx.last_workday:
        return ctx.workday_count
    stage1_actual = attendance.actual_days if attendance is not None else None
    if stage1_actual is not None:
        min_actual = service.param_decimal(
            params, "min_actual_days_for_full_base", Decimal("15"))
        if Decimal(stage1_actual) < min_actual:
            return ctx.workday_count
    return full_base


def calc_absence(
    base_salary: Decimal,
    due_final: Decimal,
    attendance: Optional[SalaryAttendance],
    flags: set[str],
) -> tuple[Decimal, Decimal]:
    """缺勤扣款 = −底薪 / 应出 × 缺勤天数。返回 (扣款负数, 实出天数终值)。

    缺勤天数 = 考勤行的 应出 − 实出（阶段一 31 基准口径，含事假/病假折算），
    与应出终值解耦：王槐竹阶段一 31−5=26，终值基准 22，扣款按 22 算 5 天。
    缺勤天数 > 应出终值时按应出截断（最多扣满整月底薪），并打旗。
    """
    if attendance is None or attendance.actual_days is None or attendance.due_days is None:
        # 没考勤行 / 请假小时没录：按 0 缺勤算，但打旗（前置异常面板同样会拦）
        if attendance is None:
            flags.add(FLAG_ATTENDANCE_MISSING)
        due_row = Decimal(attendance.due_days) if attendance is not None and attendance.due_days else due_final
        return Decimal("0.00"), due_row
    absence_days = max(Decimal(attendance.due_days) - Decimal(attendance.actual_days),
                       Decimal("0"))
    if absence_days > due_final:
        flags.add(FLAG_ABSENCE_CLAMPED)
        absence_days = due_final
    if due_final <= 0:
        raise CalcError("应出勤天数必须大于 0，请检查批次工作日数或考勤钉值")
    deduction = -(Decimal(base_salary) * absence_days / due_final)
    actual_final = max(due_final - absence_days, Decimal("0"))
    return _q2(deduction), actual_final.quantize(Decimal("0.01"))


def guaranteed_subsidy(
    profile: SalaryEmployeeProfile,
    absence_deduction: Decimal,
    net_before_subsidy: Decimal,
    ctx: PeriodContext,
) -> Optional[Decimal]:
    """保底补足：实发 = max(计算实发, 保底 − |缺勤扣款|)，差额进补贴项。

    生效区间外返回 None（不触发）——徐瑞萍/张紫娟保底 2026-04 起，3 月表补贴为空。
    刘也：5000 − 0 − 3321.09 = 1678.91；隋晓茹：5000 − 795.45 − 2734.55 = 1470.00。
    """
    g = profile.guaranteed_salary
    if g is None:
        return None
    if profile.guaranteed_from and profile.guaranteed_from > ctx.month_end:
        return None
    if profile.guaranteed_to and profile.guaranteed_to < ctx.month_start:
        return None
    floor = Decimal(g) + Decimal(absence_deduction)  # absence 为负 → floor = 保底 − |缺勤|
    topup = floor - Decimal(net_before_subsidy)
    if topup <= 0:
        return None
    return _q2(topup)


def assemble_totals(
    *,
    base_salary: Decimal,
    seniority_pay: Decimal,
    attendance_bonus: Decimal,
    social_insurance: Decimal,
    housing_fund: Decimal,
    absence_deduction: Decimal,
    bonus_final: Optional[Decimal],
    performance_final: Optional[Decimal],
    other_final: Optional[Decimal],
    subsidy_final: Optional[Decimal],
    income_tax: Optional[Decimal],
    rounding_unit: Decimal,
) -> dict[str, Decimal]:
    """小计与实发。引擎与行内编辑共用同一套，禁止再抄一份。

    增项小计 = 奖励 + 绩效 + 工龄 + 全勤（谷振尧 0+2000+2000+0=4000）
    减项小计 = 社保 + 公积金 + 缺勤 + 其他款（带符号；刘德明 −716.88+1000=+283.12）
    实发     = round(底薪 + 增项 + 减项 + 补贴) 到 rounding_unit（3 月口径=1 元，HALF_UP）
    """
    add = _nz(bonus_final) + _nz(performance_final) + seniority_pay + attendance_bonus
    deduct = social_insurance + housing_fund + absence_deduction + _nz(other_final)
    net = (base_salary + add + deduct + _nz(subsidy_final)).quantize(
        rounding_unit, rounding=ROUND_HALF_UP)
    return {
        "add_subtotal": _q2(add),
        "deduct_subtotal": _q2(deduct),
        "net_salary": net,
        "net_after_tax": net - _nz(income_tax),
    }


# ---------------------------------------------------------------------------
# 纯函数：整行
# ---------------------------------------------------------------------------

def calc_record(
    *,
    profile: SalaryEmployeeProfile,
    attendance: Optional[SalaryAttendance],
    insurance_amount: Optional[Decimal],
    fund_amount: Optional[Decimal],
    params: dict[str, str],
    changes: list[SalaryChangeLog],
    grade_map: dict[tuple[str, str], SalaryGradeTable],
    ctx: PeriodContext,
    manual: dict[str, Optional[Decimal]],
) -> dict[str, Any]:
    """算一个人的 23 列。返回 dict 键与 `salary_record` 列同名，编排层直接落库。

    `manual` 给手动列现值：bonus/performance/other/subsidy 的 manual 与 income_tax。
    final = coalesce(manual, auto)（A2）；手动列参与增/减项小计与实发。
    """
    flags: set[str] = set()

    base, weighted = calc_base_salary(profile, grade_map, changes, ctx, params)
    if base is None:
        # 底薪缺失：按 0 往下算让整行能出来，但打旗（blocking 异常面板同样会报）
        flags.add(FLAG_BASE_MISSING)
        base = Decimal("0.00")
    if weighted:
        flags.add(FLAG_MID_MONTH_WEIGHTED)

    seniority = calc_seniority(profile, ctx, params)
    att_bonus = calc_attendance_bonus(profile, attendance, params)
    social, fund_amt = calc_social_fund(profile, insurance_amount, fund_amount, flags)
    due_final = resolve_final_due_days(profile, attendance, ctx, params)
    absence, actual_final = calc_absence(base, due_final, attendance, flags)

    bonus_f = triple_final(None, manual.get("bonus"))
    perf_f = triple_final(None, manual.get("performance"))
    other_f = triple_final(None, manual.get("other"))

    # 保底前实发：含手动列生效值，不含补贴（刘也 3321.09）。
    # **按分舍入，不按元**——净额最终才四舍五入到元；这里先按元会让补贴差出
    # 几毛（刘也 auto 实测 1679.00 vs 真值口径 1678.91）。
    pre = assemble_totals(
        base_salary=base, seniority_pay=seniority, attendance_bonus=att_bonus,
        social_insurance=social, housing_fund=fund_amt, absence_deduction=absence,
        bonus_final=bonus_f, performance_final=perf_f, other_final=other_f,
        subsidy_final=None, income_tax=None, rounding_unit=CENT,
    )
    subsidy_auto = guaranteed_subsidy(profile, absence, pre["net_salary"], ctx)
    if subsidy_auto is not None:
        flags.add(FLAG_GUARANTEED_TOPUP)
    subsidy_f = triple_final(subsidy_auto, manual.get("subsidy"))

    unit = service.param_decimal(params, "net_salary_rounding", Decimal("1"))
    if unit <= 0:
        raise CalcError("规则参数 net_salary_rounding 必须大于 0")
    totals = assemble_totals(
        base_salary=base, seniority_pay=seniority, attendance_bonus=att_bonus,
        social_insurance=social, housing_fund=fund_amt, absence_deduction=absence,
        bonus_final=bonus_f, performance_final=perf_f, other_final=other_f,
        subsidy_final=subsidy_f, income_tax=manual.get("income_tax"),
        rounding_unit=unit,
    )
    if totals["net_salary"] < 0:
        flags.add(FLAG_NEGATIVE_NET)

    return {
        "due_days": due_final,
        "actual_days": actual_final,
        "base_salary": base,
        "seniority_pay": seniority,
        "attendance_bonus": att_bonus,
        "social_insurance": social,
        "housing_fund": fund_amt,
        "absence_deduction": absence,
        "bonus_auto": None,
        "performance_auto": None,
        "other_auto": None,
        "subsidy_auto": subsidy_auto,
        "bonus_final": bonus_f,
        "performance_final": perf_f,
        "other_final": other_f,
        "subsidy_final": subsidy_f,
        **totals,
        "calc_flags": sorted(flags),
    }


# ---------------------------------------------------------------------------
# 自动文案（汇总表两列，计算时生成——confirmed 后不能再回查活档案）
# ---------------------------------------------------------------------------

def _fmt_amount(v: Decimal) -> str:
    """553.32 → '553.32'；110.00 → '110'（与 3 月汇总表手写口径一致）。"""
    d = Decimal(v).quantize(CENT)
    s = format(d.normalize(), "f")
    return s


def build_remark_summary(social: Decimal, fund: Decimal) -> str:
    """汇总表备注：`扣社保XX元，公积金XX元。`（正数表述，与手写表一致）。

    消灭 §2.5 错误 1（孙正华/谷振尧/吕德洋三人备注错位）——由明细自动生成，
    不存在抄错行的可能。为 0 的列不写（牟亮亮不缴公积金，「公积金0元」是噪音）。
    """
    parts = []
    if social != 0:
        parts.append(f"扣社保{_fmt_amount(-social)}元")
    if fund != 0:
        parts.append(f"公积金{_fmt_amount(-fund)}元")
    return "，".join(parts) + "。" if parts else ""


def build_leave_remark(
    profile: SalaryEmployeeProfile,
    attendance: Optional[SalaryAttendance],
    ctx: PeriodContext,
) -> str:
    """汇总表「请假时间」列。

    - 月初仍在试用期（转正日晚于月初或未定）且有 probation_note → 底薪约定文案
      （陈佳乐 3/14 转正，3 月汇总表仍写「试用期3500底薪，转正后4000底薪」）；
    - 其余 → `本月年假X天，本年度剩余年假Y天`（考勤行没录年假按 0，与手写表
      「本月年假0天，本年度剩余年假0天」对齐）。
    """
    if profile.probation_note and (
        profile.regular_date is None or profile.regular_date > ctx.month_start
    ):
        return profile.probation_note
    used = attendance.annual_leave_days if attendance is not None else None
    remain = attendance.annual_leave_remain if attendance is not None else None
    used_txt = _fmt_amount(used) if used is not None else "0"
    remain_txt = _fmt_amount(remain) if remain is not None else "0"
    return f"本月年假{used_txt}天，本年度剩余年假{remain_txt}天"


# ---------------------------------------------------------------------------
# 批次编排（以下为 session 层）
# ---------------------------------------------------------------------------

def _matched_import_sums(db: Session, period_id: int, model, amount_col: str) -> dict[int, Decimal]:
    """employee_id → 匹配上的导入行个人金额合计。duplicate/unmatched/not_payroll 不进计算。

    返回纯 dict 而不是 ORM 行：一人多行时金额要相加，在 ORM 对象上累加会把对象
    标脏，后面 transition 的 commit 会把膨胀后的金额**写回导入行**——对账数据被
    计算过程污染，这是最不能接受的副作用。
    """
    rows = (
        db.query(model.employee_id, getattr(model, amount_col))
        .filter(model.period_id == period_id, model.match_status == "matched")
        .all()
    )
    out: dict[int, Decimal] = {}
    for emp_id, amount in rows:
        if emp_id is None or amount is None:
            continue
        out[emp_id] = out.get(emp_id, Decimal("0")) + Decimal(amount)
    return out


def calculate_period(
    db: Session,
    period: SalaryPeriod,
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> dict[str, Any]:
    """整批计算/重算。重算不冲手动列（A2），auto 变化但被 manual 覆盖的行进清单。

    门（按检查顺序）：
    1. 批次可写且状态允许进计算（imported/calculated/reviewing）；
    2. 前置异常面板无 blocking（ready_to_calculate 由 anomaly_service 回答）；
    3. 参数快照：没有就先冻结（ freeze_params 自带 guarded_write 与留痕）。
    """
    period_service.assert_writable(period)
    if period.status not in (
        period_service.STATUS_IMPORTED,
        period_service.STATUS_CALCULATED,
        period_service.STATUS_REVIEWING,
    ):
        label = period_service.STATUS_LABELS.get(period.status, period.status)
        raise CalcError(f"批次当前是「{label}」，请先完成考勤同步与社保导入再计算")

    from app.salary import anomaly_service  # 避免环：anomaly 不依赖 calc
    gate = anomaly_service.collect(db, period, include_records=False)
    if not gate["ready_to_calculate"]:
        raise CalcError(
            f"还有 {gate['blocking_count']} 条待办异常未处理，不能进计算。"
            "请先在异常面板逐条处理（未匹配社保/考勤缺失/底薪缺失等）。"
        )

    if not period.param_snapshot:
        period_service.freeze_params(db, period)
        db.refresh(period)
    params = period.param_snapshot
    ctx = build_period_context(period, params)

    grade_map = service.load_grade_map(db, period_service.period_on_date(period))
    # 计算口径名单 = 在职 ∪ 本月内离职（末月工资照发）。payroll_profiles 只数在职，
    # 月中离职者会整人蒸发：无记录、无告警、无合计（三轮审查 P1-4）。
    profiles = attendance_service.payroll_scope(db, period)
    attendance_map = {
        r.employee_id: r
        for r in db.query(SalaryAttendance).filter(SalaryAttendance.period_id == period.id)
    }
    # 本月离职者不在前置异常面板的考勤检查里（面板只看在职），这里补一道：
    # 没有考勤行就按全勤发末月工资，错得无声无息。名单门已放行他们的手工录入。
    leavers_without_att = [
        p for p in profiles
        if p.status == "left" and p.id not in attendance_map
    ]
    if leavers_without_att:
        names = "、".join(p.name for p in leavers_without_att)
        raise CalcError(
            f"以下本月离职员工没有考勤记录：{names}。请先在考勤页手工录入（末月按实际出勤），"
            "再重新计算。"
        )
    insurance_map = _matched_import_sums(db, period.id, SalaryInsuranceImport, "personal_total")
    fund_map = _matched_import_sums(db, period.id, SalaryFundImport, "personal_amount")
    change_rows = (
        db.query(SalaryChangeLog)
        .filter(SalaryChangeLog.effective_date > ctx.month_start)
        .filter(SalaryChangeLog.effective_date <= ctx.month_end)
        .all()
    )
    changes_by_emp: dict[int, list[SalaryChangeLog]] = {}
    for c in change_rows:
        changes_by_emp.setdefault(c.employee_id, []).append(c)

    existing = {
        r.employee_id: r
        for r in db.query(SalaryRecord).filter(SalaryRecord.period_id == period.id)
    }

    now = beijing_now()
    override_changed: list[dict[str, Any]] = []
    negative_net: list[dict[str, Any]] = []
    guaranteed: list[dict[str, Any]] = []
    weighted: list[dict[str, Any]] = []
    total_net = Decimal("0")

    for seq, profile in enumerate(profiles, start=1):
        old = existing.get(profile.id)
        manual = {
            "bonus": old.bonus_manual if old else None,
            "performance": old.performance_manual if old else None,
            "other": old.other_manual if old else None,
            "subsidy": old.subsidy_manual if old else None,
            "income_tax": old.income_tax_amount if old else None,
        }
        draft = calc_record(
            profile=profile,
            attendance=attendance_map.get(profile.id),
            insurance_amount=insurance_map.get(profile.id),
            fund_amount=fund_map.get(profile.id),
            params=params,
            changes=changes_by_emp.get(profile.id, []),
            grade_map=grade_map,
            ctx=ctx,
            manual=manual,
        )

        if old is not None:
            # A2 重算语义：manual 保留，auto 更新；auto 变了但 manual 盖着 → 点名
            for label, col in (("奖励", "bonus"), ("绩效", "performance"),
                               ("其他款", "other"), ("补贴", "subsidy")):
                m = getattr(old, f"{col}_manual")
                a_old, a_new = getattr(old, f"{col}_auto"), draft[f"{col}_auto"]
                if m is not None and a_old != a_new:
                    override_changed.append({
                        "employee_id": profile.id, "name": profile.name, "field": col,
                        "field_label": label,
                        "auto_old": str(a_old), "auto_new": str(a_new),
                        "manual": str(m),
                    })

        if old is None:
            row = SalaryRecord(period_id=period.id, employee_id=profile.id)
            row.seq_no = seq
            for key, value in draft.items():
                setattr(row, key, value)
            row.remark_summary = build_remark_summary(
                draft["social_insurance"], draft["housing_fund"])
            row.leave_remark = build_leave_remark(
                profile, attendance_map.get(profile.id), ctx)
            row.calculated_at = now
            db.add(row)
            db.flush()  # 逐人 flush：66 行里某行炸约束时错误能定位到人
        else:
            # 存量行走带 row_version 谓词的原子 UPDATE：重算读 manual 之后、写回之前
            # 有人行内编辑过的话 rowcount=0，整批失败回滚——否则 final 会按旧 manual
            # 覆盖新 manual，列脱节且没有任何信号（三轮审查 P1-3）。
            values = {
                **draft,
                "seq_no": seq,
                "remark_summary": build_remark_summary(
                    draft["social_insurance"], draft["housing_fund"]),
                "leave_remark": build_leave_remark(
                    profile, attendance_map.get(profile.id), ctx),
                "calculated_at": now,
                "updated_at": now,
            }
            stmt = (
                update(SalaryRecord)
                .where(SalaryRecord.id == old.id,
                       SalaryRecord.row_version == old.row_version)
                .values(**values)
            )
            if db.execute(stmt).rowcount == 0:
                db.rollback()
                raise period_service.SalaryStaleVersion(
                    f"计算期间「{profile.name}」的明细行被他人修改，本次计算未生效，请重算"
                )

        flags = set(draft["calc_flags"])
        if FLAG_NEGATIVE_NET in flags:
            negative_net.append({"employee_id": profile.id, "name": profile.name,
                                 "net_salary": str(draft["net_salary"])})
        if FLAG_GUARANTEED_TOPUP in flags:
            guaranteed.append({"employee_id": profile.id, "name": profile.name,
                               "subsidy_auto": str(draft["subsidy_auto"])})
        if FLAG_MID_MONTH_WEIGHTED in flags:
            weighted.append({"employee_id": profile.id, "name": profile.name,
                             "base_salary": str(draft["base_salary"])})
        total_net += draft["net_salary"]

    # 库里有人已不在发薪名单（离职/改成仅参保）但本批次还有记录行：不删行
    # （历史留痕），但要在摘要里点名，导出前必须处理。
    payroll_ids = {p.id for p in profiles}
    stale_rows = [r for emp_id, r in existing.items() if emp_id not in payroll_ids]

    from_status = period.status
    if from_status == period_service.STATUS_CALCULATED:
        # 自环重算（calculated→calculated）：不能让 transition 的自环留痕先提交——
        # log_event 的 commit 会把已写入的明细行一起落库，而此刻还没过锁定门，
        # 并发 confirm 时已锁批次的记录会被重写（三轮审查 P1-1 实证）。
        # 顺序钉死：先 guarded_write（status != confirmed + 版本谓词，一条 commit
        # 收拢全部明细行写），过了门才留痕。
        period_service.guarded_write(
            db, period, {"calculated_at": now},
            expected_version=expected_version if expected_version is not None
            else period.status_version,
            conflict_message="批次已被锁定或被他人修改，本次计算未生效，请刷新后重试",
        )
    else:
        # 非自环：transition 的原子 UPDATE 把明细行与状态跃迁一次 commit，安全
        period_service.transition(
            db, period, period_service.STATUS_CALCULATED,
            expected_version=expected_version, operator_id=operator_id,
            extra={"calculated": len(profiles)},
            extra_values={"calculated_at": now},
        )

    summary = {
        "calculated": len(profiles),
        "total_net": str(total_net.quantize(CENT)),
        "negative_net": negative_net,
        "guaranteed_topup": guaranteed,
        "mid_month_weighted": weighted,
        "override_changed": override_changed,
        "stale_records": [
            {"employee_id": r.employee_id, "record_id": r.id} for r in stale_rows
        ],
        "status": period.status,
        "status_version": period.status_version,
    }
    period_service.log_event(
        db, period, "calculate",
        from_status=from_status, to_status=period_service.STATUS_CALCULATED,
        payload={"calculated": len(profiles), "total_net": str(total_net.quantize(CENT)),
                 "negative_net": len(negative_net),
                 "override_changed": len(override_changed)},
        operator_id=operator_id,
    )
    logger.info("薪资批次计算 period=%s ym=%s 人数=%s 实发合计=%s 负数=%s",
                period.id, period.year_month, len(profiles), total_net, len(negative_net))
    return summary


def assert_confirmable(db: Session, period: SalaryPeriod) -> None:
    """锁定前两道门（设计文档 §6 + 三轮审查 P1-4/5/6）。

    1. **负数拦截**：`net_salary < 0` 或 `net_after_tax < 0` 的行禁止 confirmed。
       个税是手动列、无上限校验，只查 net_salary 会让「个税填得比实发大」的
       行溜进银行盘（负金额）。低底薪 + 大额缺勤 + 社保可算出负数（3 月最低
       1114 元，再差一点就穿零），强制人工决策：清零挂账 / 其他款冲抵。
    2. **名单覆盖**：计算口径名单（在职 ∪ 本月离职）与记录集合必须相等。
       计算后新加入发薪名单的人没有记录行（漏发），算完后离职/改仅参保的人
       留着记录行（错发）——两个方向都点名，不静默。
    """
    neg_rows = (
        db.query(SalaryRecord.employee_id, SalaryRecord.net_salary,
                 SalaryRecord.net_after_tax)
        .filter(SalaryRecord.period_id == period.id)
        .filter(
            (SalaryRecord.net_salary < 0)
            | (SalaryRecord.net_after_tax < 0)
        )
        .all()
    )
    if neg_rows:
        names = {
            p.id: p.name
            for p in db.query(SalaryEmployeeProfile)
            .filter(SalaryEmployeeProfile.id.in_([r.employee_id for r in neg_rows]))
        }
        detail = "、".join(
            f"{names.get(r.employee_id, r.employee_id)}"
            f"（实发{r.net_salary}，税后{r.net_after_tax}）"
            for r in neg_rows
        )
        raise CalcError(f"存在负数实发的行，不能锁定：{detail}。请先在明细表处理（清零/冲抵）。")

    scope = attendance_service.payroll_scope(db, period)
    scope_ids = {p.id for p in scope}
    records = (
        db.query(SalaryRecord.employee_id)
        .filter(SalaryRecord.period_id == period.id)
        .all()
    )
    record_ids = {r.employee_id for r in records}
    missing = scope_ids - record_ids
    stale = record_ids - scope_ids
    if missing or stale:
        names_of = {
            p.id: p.name
            for p in db.query(SalaryEmployeeProfile)
            .filter(SalaryEmployeeProfile.id.in_(missing | stale))
        }
        parts = []
        if missing:
            parts.append("没有工资记录："
                         + "、".join(names_of.get(i, str(i)) for i in sorted(missing)))
        if stale:
            parts.append("已不在发薪名单但仍有记录行："
                         + "、".join(names_of.get(i, str(i)) for i in sorted(stale)))
        raise CalcError(
            "；".join(parts) + "。请退回「已计算」重算，或先处理档案状态再锁定。"
        )


def edit_record_manual(
    db: Session,
    period: SalaryPeriod,
    employee_id: int,
    updates: dict[str, Optional[Decimal]],
    *,
    expected_row_version: Optional[int] = None,
    reason: Optional[str] = None,
    operator_id: Optional[int] = None,
) -> SalaryRecord:
    """复核期改手动列。行级乐观锁 + 改完用引擎同一套公式重算该行。

    只允许 calculated/reviewing 状态：记录行是算出来的，没算过没有行可改；
    confirmed 由 assert_writable 拦。改手动列会联动补贴 auto 重判定（保底
    看的是生效值），再重算小计/实发——与整批重算同一条代码路径。
    """
    period_service.assert_writable(period)
    if period.status not in (period_service.STATUS_CALCULATED,
                             period_service.STATUS_REVIEWING):
        label = period_service.STATUS_LABELS.get(period.status, period.status)
        raise CalcError(f"批次当前是「{label}」，计算之后才能改手动列")

    unknown = set(updates) - set(MANUAL_EDIT_FIELDS)
    if unknown:
        raise CalcError(f"不允许修改字段 {sorted(unknown)}（只允许 {sorted(MANUAL_EDIT_FIELDS)}）")

    row = (
        db.query(SalaryRecord)
        .filter(SalaryRecord.period_id == period.id)
        .filter(SalaryRecord.employee_id == employee_id)
        .first()
    )
    if row is None:
        raise CalcError("该员工在本批次没有工资记录，请先计算")
    if expected_row_version is not None and expected_row_version != row.row_version:
        raise period_service.SalaryStaleVersion(
            "该行已被他人修改，请刷新查看最新值后重试"
        )

    # 全部在局部变量上算完，最后一次原子 UPDATE 落库。setattr + commit 的写法
    # 在「读 row_version → 写回」之间有一个窗口：两个复核人同时提交会双双成功、
    # 后写覆盖先写，而两边都以为自己赢了。把 row_version 放进 UPDATE 谓词，
    # 由数据库保证「比对 + 自增」原子——与 period_service.guarded_write 同构。
    manual_values = {MANUAL_EDIT_FIELDS[k]: v for k, v in updates.items()}
    merged = {
        "bonus_manual": manual_values.get("bonus_manual", row.bonus_manual),
        "performance_manual": manual_values.get("performance_manual", row.performance_manual),
        "other_manual": manual_values.get("other_manual", row.other_manual),
        "subsidy_manual": manual_values.get("subsidy_manual", row.subsidy_manual),
        "income_tax_amount": manual_values.get("income_tax_amount", row.income_tax_amount),
    }

    params = period_service.resolve_params(db, period)
    profile = db.query(SalaryEmployeeProfile).filter(
        SalaryEmployeeProfile.id == employee_id).first()
    if profile is None:
        raise CalcError("员工档案不存在")
    ctx = build_period_context(period, params)

    finals = {
        "bonus": triple_final(row.bonus_auto, merged["bonus_manual"]),
        "performance": triple_final(row.performance_auto, merged["performance_manual"]),
        "other": triple_final(row.other_auto, merged["other_manual"]),
    }
    pre = assemble_totals(
        base_salary=row.base_salary, seniority_pay=row.seniority_pay,
        attendance_bonus=row.attendance_bonus, social_insurance=row.social_insurance,
        housing_fund=row.housing_fund, absence_deduction=row.absence_deduction,
        bonus_final=finals["bonus"], performance_final=finals["performance"],
        other_final=finals["other"], subsidy_final=None, income_tax=None,
        rounding_unit=CENT,  # 保底前按分舍入——见 calc_record 同名注释
    )
    subsidy_auto = guaranteed_subsidy(profile, row.absence_deduction, pre["net_salary"], ctx)
    subsidy_f = triple_final(subsidy_auto, merged["subsidy_manual"])

    unit = service.param_decimal(params, "net_salary_rounding", Decimal("1"))
    totals = assemble_totals(
        base_salary=row.base_salary, seniority_pay=row.seniority_pay,
        attendance_bonus=row.attendance_bonus, social_insurance=row.social_insurance,
        housing_fund=row.housing_fund, absence_deduction=row.absence_deduction,
        bonus_final=finals["bonus"], performance_final=finals["performance"],
        other_final=finals["other"], subsidy_final=subsidy_f,
        income_tax=merged["income_tax_amount"], rounding_unit=unit,
    )

    flags = set(row.calc_flags or [])
    flags.discard(FLAG_GUARANTEED_TOPUP)
    if subsidy_auto is not None:
        flags.add(FLAG_GUARANTEED_TOPUP)
    flags.discard(FLAG_NEGATIVE_NET)
    if totals["net_salary"] < 0:
        flags.add(FLAG_NEGATIVE_NET)

    values: dict[str, Any] = {
        **manual_values,
        "bonus_final": finals["bonus"],
        "performance_final": finals["performance"],
        "other_final": finals["other"],
        "subsidy_auto": subsidy_auto,
        "subsidy_final": subsidy_f,
        **totals,
        "calc_flags": sorted(flags),
        "modified_by": operator_id,
        "modify_reason": (reason or "")[:255] or None,
        "row_version": row.row_version + 1,
        "updated_at": beijing_now(),
    }
    stmt = (
        update(SalaryRecord)
        .where(SalaryRecord.id == row.id, SalaryRecord.row_version == row.row_version)
        .values(**values)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise period_service.SalaryStaleVersion(
            "该行已被他人修改，请刷新查看最新值后重试"
        )
    # 批次锁定门与考勤侧对齐：confirm 穿插时这条空写的谓词失败，
    # 连同行编辑一起回滚（三轮审查 P1-2：少了这道门，编辑能落进已锁批次）。
    period_service.guarded_write(
        db, period, {"status": period.status},
        conflict_message="批次已被锁定或被他人修改，本次修改未生效，请刷新后重试",
    )
    db.refresh(row)

    period_service.log_event(
        db, period, "record_edit",
        payload={"employee_id": employee_id, "name": profile.name,
                 "fields": sorted(updates), "reason": (reason or "")[:255]},
        operator_id=operator_id,
    )
    return row


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def serialize_record(
    row: SalaryRecord, profile: Optional[SalaryEmployeeProfile],
) -> dict[str, Any]:
    """明细行出站形态。confirmed 后快照列优先——锁定后换卡不污染历史批次。"""
    snap_frozen = row.snapshot_at is not None
    return {
        "id": row.id,
        "period_id": row.period_id,
        "employee_id": row.employee_id,
        "seq_no": row.seq_no,
        "emp_no": row.snap_emp_no if snap_frozen else (profile.emp_no if profile else None),
        "name": row.snap_name if snap_frozen else (profile.name if profile else None),
        "dept_detail": row.snap_dept_detail if snap_frozen else (
            profile.dept_detail if profile else None),
        "position": row.snap_position if snap_frozen else (
            profile.position if profile else None),
        "due_days": row.due_days,
        "actual_days": row.actual_days,
        "base_salary": row.base_salary,
        "seniority_pay": row.seniority_pay,
        "attendance_bonus": row.attendance_bonus,
        "social_insurance": row.social_insurance,
        "housing_fund": row.housing_fund,
        "absence_deduction": row.absence_deduction,
        "add_subtotal": row.add_subtotal,
        "deduct_subtotal": row.deduct_subtotal,
        "net_salary": row.net_salary,
        "income_tax_amount": row.income_tax_amount,
        "net_after_tax": row.net_after_tax,
        "bonus": {"auto": row.bonus_auto, "manual": row.bonus_manual,
                  "final": row.bonus_final},
        "performance": {"auto": row.performance_auto, "manual": row.performance_manual,
                        "final": row.performance_final},
        "other": {"auto": row.other_auto, "manual": row.other_manual,
                  "final": row.other_final},
        "subsidy": {"auto": row.subsidy_auto, "manual": row.subsidy_manual,
                    "final": row.subsidy_final},
        "remark_summary": row.remark_summary,
        "leave_remark": row.leave_remark,
        "calc_flags": row.calc_flags or [],
        "row_version": row.row_version,
        "snapshot_frozen": snap_frozen,
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
        "modified_by": row.modified_by,
        "modify_reason": row.modify_reason,
    }


def list_records(
    db: Session, period_id: int, *, keyword: str = "", limit: int = 500,
) -> dict[str, Any]:
    """整批明细行（66 人一页看完，不分页）。带合计行给表格底部。"""
    q = (
        db.query(SalaryRecord, SalaryEmployeeProfile)
        .outerjoin(SalaryEmployeeProfile,
                   SalaryEmployeeProfile.id == SalaryRecord.employee_id)
        .filter(SalaryRecord.period_id == period_id)
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (SalaryEmployeeProfile.name.like(like))
            | (SalaryEmployeeProfile.emp_no.like(like))
        )
    pairs = q.order_by(SalaryRecord.seq_no, SalaryRecord.id).limit(limit).all()

    sum_cols = ("base_salary", "add_subtotal", "deduct_subtotal", "net_salary",
                "net_after_tax")
    totals = {c: Decimal("0") for c in sum_cols}
    items = []
    for row, profile in pairs:
        items.append(serialize_record(row, profile))
        for c in sum_cols:
            v = getattr(row, c)
            if v is not None:
                totals[c] += Decimal(v)
    return {
        "items": items,
        "total": len(items),
        "totals": {c: str(totals[c].quantize(CENT)) for c in sum_cols},
        "truncated": len(pairs) >= limit,
    }
