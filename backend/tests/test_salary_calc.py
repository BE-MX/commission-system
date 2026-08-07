"""计算引擎的口径测试（M3）。

分两层：

1. **纯函数分支**：`calc_record` 不碰 session，直接构造模型实例喂进去。
   每个分支用 2026 年 3 月**真人真值**做断言（设计文档 A1 的验收口径就是
   「66 人 × 9 引擎列分位一致」）：谷振尧的缺勤、陈佳乐的 3775、刘也的保底、
   李晓雨的 21.75、刘德明的 +1000 其他款……断言值全部来自 3 月工资表原件，
   不是「算出来是多少就写多少」。
2. **服务级流程**：计算门、整批落库、重算语义（A2）、行级乐观锁、负数拦 confirm。

金额一律 Decimal 断言到分。中间过程保留全精度、落库列量化到分、实发四舍五入
到元——三个精度层各有各的断言，混一个就会在某个人身上差 1 分钱。
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser
from app.core.database import Base
from app.salary import calc_service as cs
from app.salary import period_service as ps
from app.salary import attendance_service as ats
from app.salary.models import (
    SalaryAttendance,
    SalaryChangeLog,
    SalaryDeptMapping,
    SalaryEmployeeProfile,
    SalaryFundImport,
    SalaryGradeTable,
    SalaryInsuranceImport,
    SalaryPeriod,
    SalaryPeriodEvent,
    SalaryRecord,
    SalaryRuleParam,
)
from app.salary.seed import seed_rule_params

D = Decimal

# 与 seed._RULE_PARAMS 同值。引擎只走参数快照，不读代码默认值——测试也照此，
# 种子改了这里跟着红，比拿硬编码默认值蒙对安全。
PARAMS = {
    "day_hours": "7.83",
    "full_month_days": "31",
    "mid_month_weight_base": "30",
    "min_actual_days_for_full_base": "15",
    "attendance_bonus": "100",
    "attendance_sick_hours_max": "8",
    "annual_leave_breaks_attendance": "false",
    "sick_pay_deduct_ratio": "0.30",
    "seniority_step": "200",
    "seniority_cap": "2000",
    "net_salary_rounding": "1",
}

# 2026-03 批次上下文：3/1 周日，首个工作日 3/2，末个工作日 3/31，工作日 22 天
CTX = cs.PeriodContext(
    year=2026, month=3,
    month_start=dt.date(2026, 3, 1), month_end=dt.date(2026, 3, 31),
    workday_count=D("22"),
    first_workday=dt.date(2026, 3, 2), last_workday=dt.date(2026, 3, 31),
)


def mk_profile(**kw) -> SalaryEmployeeProfile:
    """瞬时档案（不落库）。显式给默认标记位——Column default 只在 INSERT 时生效，
    瞬时实例上是 None，而 `fund_included=None` 会被引擎当成「不缴公积金」。"""
    defaults = dict(
        emp_no="1", name="测试", status="active", payroll_included=1,
        fund_included=1, special_calc=0, hire_date=None, regular_date=None,
        leave_date=None, base_salary_override=None, probation_salary=None,
        probation_note=None, guaranteed_salary=None, guaranteed_from=None,
        guaranteed_to=None, insurance_entity=None, seniority_override=None,
        grade_scheme=None, grade_code=None,
    )
    defaults.update(kw)
    return SalaryEmployeeProfile(**defaults)


def mk_att(**kw) -> SalaryAttendance:
    """瞬时考勤行：默认满月全勤（31/31，请假 0，无异常）。"""
    defaults = dict(
        due_days=D("31"), due_days_manual=None, actual_days=D("31"),
        personal_leave_hours=D("0"), sick_leave_hours=D("0"),
        annual_leave_days=None, annual_leave_remain=None,
        late_count=0, early_leave_count=0, miss_punch_count=0, absent_count=D("0"),
        full_attendance=1,
    )
    defaults.update(kw)
    return SalaryAttendance(**defaults)


def run(profile, att=None, insurance=None, fund=None, changes=(), manual=None, params=None):
    """引擎统一入口。insurance/fund 给匹配到的个人金额（正数，引擎负责转负）。"""
    return cs.calc_record(
        profile=profile,
        attendance=att if att is not None else mk_att(),
        insurance_amount=insurance,
        fund_amount=fund,
        params=params or PARAMS,
        changes=list(changes),
        grade_map={},
        ctx=CTX,
        manual=manual or {},
    )


# ---------------------------------------------------------------------------
# 底薪：满月 / 试用期 / 月中加权（B2）
# ---------------------------------------------------------------------------

def test_full_month_base_plain():
    """满月无变化：直取定薪，不打加权旗。"""
    d = run(mk_profile(base_salary_override=D("8000")))
    assert d["base_salary"] == D("8000.00")
    assert "mid_month_weighted" not in d["calc_flags"]


def test_probation_full_month_uses_probation_salary():
    """转正日晚于本月 → 整月按试用期底薪（张桂云形态：试用期 3000）。"""
    d = run(mk_profile(
        probation_salary=D("3000"), base_salary_override=D("3500"),
        regular_date=dt.date(2026, 4, 1),
    ))
    assert d["base_salary"] == D("3000.00")
    assert "mid_month_weighted" not in d["calc_flags"]


def test_mid_month_regularization_chenjiale():
    """陈佳乐 3/14 转正：(3500×13.5 + 4000×16.5)/30 = 3775.00，分毫不差。

    这是 B2（30 天基数 + 生效当日新旧各半）的校准用例：31 天基数算出来是
    3774.19，30 天整数天是 3766.67/3783.33——只有 30 天 + 当日各半命中 3775。
    """
    d = run(
        mk_profile(
            hire_date=dt.date(2025, 12, 15),
            probation_salary=D("3500"), base_salary_override=D("4000"),
            regular_date=dt.date(2026, 3, 14),
            probation_note="试用期3500底薪，转正后4000底薪",
        ),
        insurance=D("463.91"), fund=D("110"),
        manual={"subsidy": D("3710.70")},
    )
    assert d["base_salary"] == D("3775.00")
    assert "mid_month_weighted" in d["calc_flags"]
    # 整行：3775 + 全勤100 − 463.91 − 110 + 补贴3710.70 → 7011.79 → 7012
    assert d["net_salary"] == D("7012")


def test_mid_month_raise_uses_change_log():
    """月中调薪：3/11 从 5000 调到 6000 → (5000×10.5 + 6000×19.5)/30 = 5650。"""
    change = SalaryChangeLog(
        employee_id=1, change_type="raise", effective_date=dt.date(2026, 3, 11),
        old_value={"base_salary_override": "5000"},
        new_value={"base_salary_override": "6000"},
    )
    d = run(mk_profile(base_salary_override=D("6000")), changes=[change])
    assert d["base_salary"] == D("5650.00")
    assert "mid_month_weighted" in d["calc_flags"]


def test_regularization_then_raise_stacked():
    """转正+调薪叠加：3/14 转正到 4000，3/20 再调 4500。

    (3500×13.5 + 4000×6 + 4500×10.5)/30 = 3950。中间段必须取调薪记录的
    old_value（4000），用当前定薪会把中间段也按 4500 算。
    """
    change = SalaryChangeLog(
        employee_id=1, change_type="raise", effective_date=dt.date(2026, 3, 20),
        old_value={"base_salary_override": "4000"},
        new_value={"base_salary_override": "4500"},
    )
    d = run(
        mk_profile(
            probation_salary=D("3500"), base_salary_override=D("4500"),
            regular_date=dt.date(2026, 3, 14),
        ),
        changes=[change],
    )
    assert d["base_salary"] == D("3950.00")


def test_manage_grade_uses_std_salary():
    """管理岗底薪取 std_salary 列（M6 → 10000，含 20% 绩效的标准工资口径）。"""
    grade = SalaryGradeTable(
        scheme="manage", grade_code="M6", std_salary=D("10000"),
        effective_from=dt.date(2026, 4, 1),
    )
    d = cs.calc_record(
        profile=mk_profile(grade_scheme="manage", grade_code="M6"),
        attendance=mk_att(), insurance_amount=None, fund_amount=None,
        params=PARAMS, changes=[], grade_map={("manage", "M6"): grade},
        ctx=CTX, manual={},
    )
    assert d["base_salary"] == D("10000.00")


def test_base_missing_flagged_not_zero_silently():
    """拿不到底薪：按 0 算让整行出来，但必须打旗——静默发 0 底薪查无可查。"""
    d = run(mk_profile())
    assert d["base_salary"] == D("0.00")
    assert "base_missing" in d["calc_flags"]


# ---------------------------------------------------------------------------
# 工龄：周年口径（刘也/王京花/谷振尧三个实证点）
# ---------------------------------------------------------------------------

def test_seniority_anniversary_in_salary_month_counts():
    """刘也 2025-03-03 入职：2026-03-03 满一年，3 月表当月即给 200。"""
    d = run(mk_profile(hire_date=dt.date(2025, 3, 3), base_salary_override=D("3500")))
    assert d["seniority_pay"] == D("200.00")


def test_seniority_cap_and_late_month_anniversary():
    """谷振尧 2016-03-28 入职：2026-03-28 满 10 年 → 2000 撞上限。

    同时钉住「纪念日在月末之前即计入」：3/28 的纪念日让 3 月就按 10 年算。
    """
    d = run(mk_profile(hire_date=dt.date(2016, 3, 28), base_salary_override=D("10000")))
    assert d["seniority_pay"] == D("2000.00")


def test_seniority_partial_year_not_counted():
    """王京花 2018-09-10 入职：最近纪念日 2025-09-10 → 7 年 → 1400。"""
    d = run(mk_profile(hire_date=dt.date(2018, 9, 10), base_salary_override=D("4000")))
    assert d["seniority_pay"] == D("1400.00")


# ---------------------------------------------------------------------------
# 应出天数两阶段 + 缺勤扣款
# ---------------------------------------------------------------------------

def test_mid_month_hire_switches_to_workday_base():
    """王槐竹 3/9 入职：应出 22（工作日基准），缺勤 5 天按 22 折算。

    6000/22×5 = 1363.64；实发 round(6000−1363.64) = 4636。
    注意她的阶段一实出是 26（31−5），≥15——是入职日而不是 <15 规则切的基准。
    """
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 9), base_salary_override=D("6000"),
                   fund_included=0),
        att=mk_att(actual_days=D("26"), full_attendance=0),
    )
    assert d["due_days"] == D("22")
    assert d["actual_days"] == D("17.00")
    assert d["absence_deduction"] == D("-1363.64")
    assert d["net_salary"] == D("4636")


def test_first_workday_hire_is_full_month():
    """张甜甜 3/2（当月首个工作日）入职 → 满月 31，不切工作日基准。"""
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 2), base_salary_override=D("3500"),
                   fund_included=0),
        manual={"performance": D("701")},
    )
    assert d["due_days"] == D("31")


def test_stage1_actual_below_15_switches_base():
    """满月员工重病/事假：阶段一实出 12 < 15 → 应出切 22，缺勤 19 天按 22 折。"""
    d = run(
        mk_profile(hire_date=dt.date(2020, 1, 1), base_salary_override=D("5000"),
                   fund_included=0),
        att=mk_att(actual_days=D("12"), full_attendance=0),
    )
    assert d["due_days"] == D("22")
    assert d["actual_days"] == D("3.00")
    assert d["absence_deduction"] == D("-4318.18")  # 5000×19/22


def test_absence_days_clamped_at_due():
    """缺勤天数 > 应出终值时按应出截断：最多扣满整月底薪，并打旗让人看见。"""
    d = run(
        mk_profile(hire_date=dt.date(2020, 1, 1), base_salary_override=D("5000"),
                   fund_included=0),
        att=mk_att(actual_days=D("4"), full_attendance=0),  # 缺勤 27 > 22
    )
    assert d["due_days"] == D("22")
    assert d["absence_deduction"] == D("-5000.00")
    assert "absence_clamped" in d["calc_flags"]


def test_manual_due_days_pin_lixiaoyu():
    """李晓雨应出 21.75：规则复原不了，手动钉值优先于一切推导（§8.3 第 10 条）。

    缺勤天数 = 阶段一 31 − 22.82 = 8.18，按钉值 21.75 折算：
    5000/21.75×8.18 = 1880.46；实出终值 13.57；实发 2486。
    """
    d = run(
        mk_profile(hire_date=dt.date(2025, 5, 26), base_salary_override=D("5000")),
        att=mk_att(actual_days=D("22.82"), due_days_manual=D("21.75"),
                   full_attendance=0),
        insurance=D("523.34"), fund=D("110"),
    )
    assert d["due_days"] == D("21.75")
    assert d["actual_days"] == D("13.57")
    assert d["absence_deduction"] == D("-1880.46")
    assert d["net_salary"] == D("2486")


def test_pure_absence_guzhenyao():
    """谷振尧：满月 31 实出 27，缺勤 4 天。10000/31×4 = 1290.32。

    整行：10000 + (绩效2000+工龄2000+全勤0) − 463.91 − 110 − 1290.32
    = 12135.77 → 12136。
    """
    d = run(
        mk_profile(hire_date=dt.date(2016, 3, 28), base_salary_override=D("10000")),
        att=mk_att(actual_days=D("27"), full_attendance=0),
        insurance=D("463.91"), fund=D("110"),
        manual={"performance": D("2000")},
    )
    assert d["absence_deduction"] == D("-1290.32")
    assert d["add_subtotal"] == D("4000.00")
    assert d["deduct_subtotal"] == D("-1864.23")
    assert d["net_salary"] == D("12136")


def test_full_month_row_wangjinghua():
    """王京花整行：年假 5.5 天不破全勤（B3），全勤 100 照发。

    4000 + (绩效1000+工龄1400+全勤100) − 463.91 − 110 = 5926。
    """
    d = run(
        mk_profile(hire_date=dt.date(2018, 9, 10), base_salary_override=D("4000")),
        att=mk_att(annual_leave_days=D("5.5"), annual_leave_remain=D("7")),
        insurance=D("463.91"), fund=D("110"),
        manual={"performance": D("1000")},
    )
    assert d["attendance_bonus"] == D("100.00")
    assert d["add_subtotal"] == D("2500.00")
    assert d["net_salary"] == D("5926")


# ---------------------------------------------------------------------------
# 社保 / 公积金
# ---------------------------------------------------------------------------

def test_insurance_unmatched_is_zero_with_flag():
    """应参保但没匹配到导入行：社保按 0 并打旗，不报错阻断（王槐竹新入职形态）。"""
    d = run(mk_profile(base_salary_override=D("6000"),
                       insurance_entity="青岛丽丝发贸易有限公司"),
            insurance=None)
    assert d["social_insurance"] == D("0.00")
    assert "insurance_missing" in d["calc_flags"]


def test_fund_excluded_no_flag_mouliangliang():
    """牟亮亮不缴公积金：fund_included=0 → 0 且不打旗（打了就是噪音）。

    30000/31×0.32 = 309.68；实发 round(30000 − 2319.35 − 309.68) = 27371。
    """
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 2), base_salary_override=D("30000"),
                   fund_included=0),
        att=mk_att(actual_days=D("30.68"), full_attendance=0),
        insurance=D("2319.35"),
    )
    assert d["housing_fund"] == D("0.00")
    assert d["absence_deduction"] == D("-309.68")
    assert "fund_missing" not in d["calc_flags"]
    assert d["net_salary"] == D("27371")


def test_fund_expected_but_missing_flagged():
    d = run(mk_profile(base_salary_override=D("5000"), fund_included=1), fund=None)
    assert d["housing_fund"] == D("0.00")
    assert "fund_missing" in d["calc_flags"]


# ---------------------------------------------------------------------------
# 保底补足
# ---------------------------------------------------------------------------

def test_guaranteed_topup_liuye():
    """刘也：保底 5000，保底前实发 3321.09 → 补贴 auto 1678.91，实发 5000。

    3 月表补贴列是 1679（HR 四舍五入到元填的）——那是手动列的值，验收时以
    真值填入 manual；引擎 auto 是 1678.91，两者都对得上实发 5000。
    """
    base = dict(
        hire_date=dt.date(2025, 3, 3), base_salary_override=D("3500"),
        guaranteed_salary=D("5000"), guaranteed_from=dt.date(2026, 1, 1),
    )
    d = run(mk_profile(**base), insurance=D("463.91"), fund=D("110"),
            manual={"performance": D("95")})
    assert d["add_subtotal"] == D("395.00")   # 绩效95 + 工龄200 + 全勤100
    assert d["deduct_subtotal"] == D("-573.91")
    assert d["subsidy_auto"] == D("1678.91")  # 5000 − 3321.09
    assert "guaranteed_topup" in d["calc_flags"]
    assert d["net_salary"] == D("5000")

    # 手动列以 3 月真值填入（1679）：final 走 manual，实发同样是 5000
    d2 = run(mk_profile(**base), insurance=D("463.91"), fund=D("110"),
             manual={"performance": D("95"), "subsidy": D("1679")})
    assert d2["subsidy_final"] == D("1679.00")
    assert d2["net_salary"] == D("5000")


def test_guaranteed_topup_exact_suixiaoru():
    """隋晓茹：floor = 5000 − 795.45，补贴恰为 1470.00（分位精确，不是约数）。"""
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 10), base_salary_override=D("3500"),
                   fund_included=0,
                   guaranteed_salary=D("5000"), guaranteed_from=dt.date(2026, 1, 1)),
        att=mk_att(actual_days=D("26"), full_attendance=0),  # 阶段一缺勤 5 天
        manual={"performance": D("30")},
    )
    assert d["due_days"] == D("22")
    assert d["absence_deduction"] == D("-795.45")  # 3500×5/22
    # 保底前 = 3500 + 30 − 795.45 = 2734.55；floor = 5000 − 795.45 = 4204.55
    assert d["subsidy_auto"] == D("1470.00")
    assert d["net_salary"] == D("4205")


def test_guarantee_not_effective_yet_xuruiping():
    """徐瑞萍：保底 2026-04-01 起生效，3 月不补（负例同样锁死，防「见保底就补」）。"""
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 16), base_salary_override=D("3500"),
                   fund_included=0,
                   guaranteed_salary=D("5000"), guaranteed_from=dt.date(2026, 4, 1)),
        att=mk_att(actual_days=D("21"), full_attendance=0),  # 阶段一缺勤 10 天
    )
    assert d["subsidy_auto"] is None
    assert d["absence_deduction"] == D("-1590.91")  # 3500×10/22
    assert d["net_salary"] == D("1909")


# ---------------------------------------------------------------------------
# 特殊人员 / 其他款 / 负数 / 舍入
# ---------------------------------------------------------------------------

def test_special_calc_liudeming():
    """刘德明：special_calc 砍掉全勤（31/31 也不发 100），工龄钉值 1000。

    其他款 +1000 让减项小计变 +283.12（带符号列的实证）；实发 24283。
    """
    d = run(
        mk_profile(base_salary_override=D("20000"), special_calc=1,
                   seniority_override=D("1000"), fund_included=0),
        insurance=D("716.88"),
        manual={"performance": D("3000"), "other": D("1000")},
    )
    assert d["attendance_bonus"] == D("0.00")
    assert d["seniority_pay"] == D("1000.00")
    assert d["add_subtotal"] == D("4000.00")
    assert d["deduct_subtotal"] == D("283.12")
    assert d["net_salary"] == D("24283")


def test_special_calc_jiangnini():
    """姜妮妮：special_calc 无钉值 → 工龄 0、全勤 0。4416 − 463.91 → 3952。"""
    d = run(
        mk_profile(hire_date=dt.date(2024, 5, 1), base_salary_override=D("4416"),
                   special_calc=1, fund_included=0),
        insurance=D("463.91"),
    )
    assert d["seniority_pay"] == D("0.00")
    assert d["attendance_bonus"] == D("0.00")
    assert d["net_salary"] == D("3952")


def test_other_amount_negative_reduces_pay():
    """其他款为负：从减项小计里再扣一笔（带符号列的另一个方向）。"""
    d = run(mk_profile(base_salary_override=D("5000"), fund_included=0),
            manual={"other": D("-200")})
    assert d["deduct_subtotal"] == D("-200.00")
    assert d["net_salary"] == D("4900")  # 5000 + 全勤100 − 200


def test_negative_net_flagged():
    """低底薪 + 满缺勤 + 社保 → 实发穿零：打 negative_net 旗，拦 confirm 不拦计算。

    不给 hire_date——给了会带出工龄工资（2020 入职 3 月已 1200），把穿零场景
    对冲掉。穿零场景的主角是底薪/缺勤/社保，不是工龄。
    """
    d = run(
        mk_profile(base_salary_override=D("2000"), fund_included=0),
        att=mk_att(actual_days=D("0"), full_attendance=0),
        insurance=D("500"),
    )
    assert d["net_salary"] == D("-500")
    assert "negative_net" in d["calc_flags"]


def test_net_rounding_half_up_zhangzijuan():
    """张紫娟：1113.64 → 1114。HALF_UP，不是 Python 默认的银行家舍入。"""
    d = run(
        mk_profile(hire_date=dt.date(2026, 3, 24), base_salary_override=D("3500"),
                   fund_included=0),
        att=mk_att(actual_days=D("16"), full_attendance=0),  # 阶段一缺勤 15 天
    )
    assert d["absence_deduction"] == D("-2386.36")  # 3500×15/22
    assert d["net_salary"] == D("1114")


# ---------------------------------------------------------------------------
# 自动文案（汇总表两列）
# ---------------------------------------------------------------------------

def test_remark_summary_formats_like_handwritten():
    assert cs.build_remark_summary(D("-553.32"), D("-110")) == "扣社保553.32元，公积金110元。"
    assert cs.build_remark_summary(D("0"), D("0")) == ""


def test_leave_remark_probation_note_wins():
    """陈佳乐 3/14 转正，3 月汇总表仍写底薪约定（月初他在试用期）。"""
    p = mk_profile(probation_note="试用期3500底薪，转正后4000底薪",
                   regular_date=dt.date(2026, 3, 14))
    assert cs.build_leave_remark(p, mk_att(), CTX) == "试用期3500底薪，转正后4000底薪"


def test_leave_remark_annual_leave_text():
    """王京花：本月年假5.5天，本年度剩余年假7天。"""
    p = mk_profile()
    att = mk_att(annual_leave_days=D("5.5"), annual_leave_remain=D("7"))
    assert cs.build_leave_remark(p, att, CTX) == "本月年假5.5天，本年度剩余年假7天"


# ---------------------------------------------------------------------------
# 服务级流程（落库 / 门 / 重算语义 / 行锁）
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SalaryEmployeeProfile.__table__, SalaryPeriod.__table__,
            SalaryPeriodEvent.__table__, SalaryAttendance.__table__,
            SalaryInsuranceImport.__table__, SalaryFundImport.__table__,
            SalaryRecord.__table__, SalaryChangeLog.__table__,
            SalaryRuleParam.__table__, SalaryGradeTable.__table__,
            SalaryDeptMapping.__table__, ArkUser.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    seed_rule_params(session)
    session.flush()
    # seed 生效日 2026-04-01，3 月批次取不到——前移（同 test_salary_period 的口径）
    session.query(SalaryRuleParam).update(
        {SalaryRuleParam.effective_from: dt.date(2026, 1, 1)})
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _profile(db, name, emp_no, **kw) -> SalaryEmployeeProfile:
    defaults = dict(status="active", payroll_included=1, fund_included=0,
                    special_calc=0, base_salary_override=D("5000"),
                    # 不绑钉钉会被异常面板判 blocking（计算门直接拒），
                    # 服务级测试的默认形态是「绑定 + 考勤齐」的干净人
                    dingtalk_userid=f"U{emp_no}")
    defaults.update(kw)
    p = SalaryEmployeeProfile(name=name, emp_no=emp_no, **defaults)
    db.add(p)
    db.commit()
    return p


def _attendance(db, period, profile, **kw) -> SalaryAttendance:
    defaults = dict(due_days=D("31"), actual_days=D("31"), full_attendance=1,
                    personal_leave_hours=D("0"), sick_leave_hours=D("0"))
    defaults.update(kw)
    row = SalaryAttendance(period_id=period.id, employee_id=profile.id, **defaults)
    db.add(row)
    db.commit()
    return row


def _period_at_imported(db) -> SalaryPeriod:
    period = ps.create_period(db, "2026-03", workday_count=22)
    period = ps.transition(db, period, ps.STATUS_ATTENDANCE,
                           expected_version=period.status_version)
    period = ps.transition(db, period, ps.STATUS_IMPORTED,
                           expected_version=period.status_version)
    return period


def test_calculate_period_end_to_end(db):
    """两人整批：落库、状态推进、快照冻结、事件留痕、合计正确。"""
    period = _period_at_imported(db)
    a = _profile(db, "甲", "1")
    b = _profile(db, "乙", "2", hire_date=dt.date(2018, 9, 10))  # 工龄 1400
    _attendance(db, period, a)
    _attendance(db, period, b)

    summary = cs.calculate_period(db, period, expected_version=period.status_version)
    assert summary["calculated"] == 2
    assert period.status == ps.STATUS_CALCULATED
    assert period.param_snapshot["full_month_days"] == "31"  # 计算时冻结

    rows = db.query(SalaryRecord).filter(SalaryRecord.period_id == period.id).all()
    assert len(rows) == 2
    by_emp = {r.employee_id: r for r in rows}
    assert by_emp[a.id].net_salary == D("5100")   # 5000 + 全勤100
    assert by_emp[b.id].net_salary == D("6500")   # 5000 + 1400 + 100
    assert summary["total_net"] == "11600.00"

    events = ps.list_events(db, period.id)
    assert any(e.event_type == "calculate" for e in events)


def test_calculate_gate_blocks_pending_attendance(db):
    """请假小时没录 → blocking 未清 → 计算门拒绝。不算出来比算错强。"""
    period = _period_at_imported(db)
    a = _profile(db, "甲", "1")
    _attendance(db, period, a, personal_leave_hours=None)  # 未录 = blocking
    with pytest.raises(cs.CalcError, match="待办异常"):
        cs.calculate_period(db, period, expected_version=period.status_version)
    assert period.status == ps.STATUS_IMPORTED  # 状态没动


def test_calculate_rejects_wrong_status(db):
    period = ps.create_period(db, "2026-03", workday_count=22)
    with pytest.raises(cs.CalcError, match="草稿"):
        cs.calculate_period(db, period, expected_version=period.status_version)


def test_recalc_preserves_manual_and_reports_override_change(db):
    """A2 重算语义：manual 不丢；auto 变了但 manual 盖着 → 进 override_changed。

    场景：底薪 4900 + 全勤 100 → 保底前 5000 = 保底，auto 不触发（None）。
    盖 manual 补贴 50；再录 16h 病假 → 全勤没了、缺勤出现，auto 变 100.00。
    manual 50 不动，重算后必须点名这一行。
    """
    period = _period_at_imported(db)
    p = _profile(db, "丙", "3", base_salary_override=D("4900"),
                 guaranteed_salary=D("5000"),
                 guaranteed_from=dt.date(2026, 1, 1))
    _attendance(db, period, p)

    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    assert row.subsidy_auto is None  # 4900 + 全勤100 = 5000 不触发

    cs.edit_record_manual(db, period, p.id, {"subsidy": D("50")},
                          expected_row_version=row.row_version, reason="测试")
    period = ps.transition(db, period, ps.STATUS_IMPORTED,
                           expected_version=period.status_version)
    ats.manual_upsert(db, period, p.id, {"sick_leave_hours": D("16")})

    summary = cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    assert row.subsidy_manual == D("50.00")           # manual 没被冲
    assert row.subsidy_final == D("50.00")            # final 走 manual
    # 病假 16h → 缺勤 0.61 天 → 全勤没了：auto = (5000−98.39) − (4900−98.39) = 100
    assert row.subsidy_auto == D("100.00")
    assert summary["override_changed"], "auto 变了 manual 盖着，必须点名"
    assert summary["override_changed"][0]["field"] == "subsidy"


def test_edit_record_recomputes_totals_with_engine_formulas(db):
    """行内编辑用引擎同一套公式：改其他款 −200，小计/实发当场重算。"""
    period = _period_at_imported(db)
    p = _profile(db, "丁", "4")
    _attendance(db, period, p)
    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    assert row.net_salary == D("5100")
    v0 = row.row_version

    updated = cs.edit_record_manual(
        db, period, p.id, {"other": D("-200")},
        expected_row_version=v0, reason="扣工服")
    assert updated.deduct_subtotal == D("-200.00")
    assert updated.net_salary == D("4900")
    assert updated.row_version == v0 + 1
    assert updated.modify_reason == "扣工服"


def test_edit_record_row_version_conflict(db):
    """两个人拿同一个 row_version 编辑：先提交者赢，后者 409 而不是静默覆盖。"""
    period = _period_at_imported(db)
    p = _profile(db, "戊", "5")
    _attendance(db, period, p)
    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    v0 = row.row_version  # 先记下——编辑成功后同一个 ORM 对象的版本会原地 +1

    cs.edit_record_manual(db, period, p.id, {"bonus": D("300")},
                          expected_row_version=v0)
    with pytest.raises(ps.SalaryStaleVersion):
        cs.edit_record_manual(db, period, p.id, {"bonus": D("500")},
                              expected_row_version=v0)  # 旧版本


def test_edit_record_rejected_before_calculate(db):
    period = _period_at_imported(db)
    p = _profile(db, "己", "6")
    with pytest.raises(cs.CalcError, match="计算之后"):
        cs.edit_record_manual(db, period, p.id, {"bonus": D("1")},
                              expected_row_version=0)


def test_negative_net_blocks_confirm(db):
    """实发为负的行在，confirm 必须拒（§6 拦截）；清零后放行。"""
    period = _period_at_imported(db)
    p = _profile(db, "庚", "7", base_salary_override=D("2000"),
                 insurance_entity="青岛丽丝发贸易有限公司")
    # 全月事假：实出 0 → 切 22 基准 → 缺勤 31 天截断到 22 → 扣满 2000
    _attendance(db, period, p, actual_days=D("0"), full_attendance=0)
    db.add(SalaryInsuranceImport(
        period_id=period.id, employee_id=p.id, name="庚",
        personal_total=D("500"), match_status="matched"))
    db.commit()

    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    assert row.net_salary == D("-500")
    assert "negative_net" in (row.calc_flags or [])

    period = ps.transition(db, period, ps.STATUS_REVIEWING,
                           expected_version=period.status_version)
    with pytest.raises(cs.CalcError, match="负数实发"):
        cs.assert_confirmable(db, period)

    # 用其他款冲抵 +500，重算行 → 实发 0，门放行
    cs.edit_record_manual(db, period, p.id, {"other": D("500")},
                          expected_row_version=row.row_version, reason="冲抵")
    cs.assert_confirmable(db, period)  # 不再抛


def test_list_records_totals_and_snapshot_fallback(db):
    """列表带合计行；未锁定时读活档案（快照列为空）。"""
    period = _period_at_imported(db)
    _profile(db, "甲", "1")
    _profile(db, "乙", "2")
    p_a = db.query(SalaryEmployeeProfile).filter_by(emp_no="1").one()
    p_b = db.query(SalaryEmployeeProfile).filter_by(emp_no="2").one()
    _attendance(db, period, p_a)
    _attendance(db, period, p_b)
    cs.calculate_period(db, period, expected_version=period.status_version)

    data = cs.list_records(db, period.id)
    assert data["total"] == 2
    assert data["totals"]["net_salary"] == "10200.00"  # (5000+100)×2
    assert data["items"][0]["name"] in ("甲", "乙")
    assert data["items"][0]["snapshot_frozen"] is False


# ---------------------------------------------------------------------------
# 三轮对抗性审查的回归测试（2026-08-07）
# ---------------------------------------------------------------------------

def test_probation_not_broken_by_noise_change_log():
    """**P0-1**：试用期员工当月有噪音 change_log（HR 只改了保底）→ 仍按试用期底薪。

    `_log_pay_changes` 对保底/转正日等 12 列的编辑都写台账，记录里不一定有底薪键。
    不查 probation_at_start 的话，试用期 3000 会被按正式 4000 发出，且无旗无告警。
    """
    noise = SalaryChangeLog(
        employee_id=1, change_type="raise", effective_date=dt.date(2026, 3, 10),
        old_value={"guaranteed_salary": None},
        new_value={"guaranteed_salary": "5000"},
    )
    d = run(
        mk_profile(probation_salary=D("3000"), base_salary_override=D("4000"),
                   regular_date=dt.date(2026, 4, 15)),
        changes=[noise],
    )
    assert d["base_salary"] == D("3000.00")
    assert "mid_month_weighted" not in d["calc_flags"]


def test_q2_rounds_half_up_not_bankers():
    """P2-1：33.325 必须是 33.33（Excel 口径），不是银行家舍入的 33.32。"""
    assert cs._q2(D("33.325")) == D("33.33")
    assert cs._q2(D("33.324")) == D("33.32")


def test_remark_summary_skips_zero_parts():
    """P2-8：单零场景不写 0 那列（牟亮亮不缴公积金，「公积金0元」是噪音）。"""
    assert cs.build_remark_summary(D("-2319.35"), D("0")) == "扣社保2319.35元。"
    assert cs.build_remark_summary(D("0"), D("-110")) == "公积金110元。"


def test_month_leaver_is_calculated_with_workday_base(db):
    """P1-4：本月离职者进计算口径，末月工资照发，应出走工作日基准。"""
    period = _period_at_imported(db)
    a = _profile(db, "在职", "1")
    leaver = _profile(db, "离职", "2", status="left",
                      leave_date=dt.date(2026, 3, 20))
    _attendance(db, period, a)
    _attendance(db, period, leaver)
    summary = cs.calculate_period(db, period, expected_version=period.status_version)
    assert summary["calculated"] == 2
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=leaver.id).one()
    assert row.due_days == D("22")  # 3/20 离职 < 末个工作日 3/31
    assert row.net_salary == D("5100")


def test_leaver_without_attendance_blocks_calc(db):
    """P1-4 另一半：本月离职者没有考勤行就按全勤发末月工资——必须拦。"""
    period = _period_at_imported(db)
    a = _profile(db, "在职", "1")
    _profile(db, "离职", "2", status="left", leave_date=dt.date(2026, 3, 20))
    _attendance(db, period, a)
    with pytest.raises(cs.CalcError, match="离职员工没有考勤"):
        cs.calculate_period(db, period, expected_version=period.status_version)


def test_manual_entry_allows_month_leaver(db):
    """本月离职者的考勤手工录入要放行——否则上面那道门永远无法解除。"""
    period = _period_at_imported(db)
    leaver = _profile(db, "离职", "2", status="left",
                      leave_date=dt.date(2026, 3, 20))
    row = ats.manual_upsert(db, period, leaver.id,
                            {"personal_leave_hours": D("0"), "sick_leave_hours": D("0")})
    assert row.employee_id == leaver.id


def test_manual_entry_rejects_non_month_leaver(db):
    """离职日不在本月的仍是「不在本月发薪名单」——例外只开当月这一条缝。"""
    period = _period_at_imported(db)
    old = _profile(db, "旧离职", "3", status="left",
                   leave_date=dt.date(2026, 1, 20))
    with pytest.raises(ats.AttendanceError, match="不在本月发薪名单"):
        ats.manual_upsert(db, period, old.id, {"sick_leave_hours": D("0")})


def test_confirm_gate_catches_negative_net_after_tax(db):
    """P1-5：个税手动填得比实发大 → 税后穿零，拦（只查 net_salary 会漏）。"""
    period = _period_at_imported(db)
    p = _profile(db, "辛", "8")
    _attendance(db, period, p)
    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    cs.edit_record_manual(db, period, p.id, {"income_tax": D("6000")},
                          expected_row_version=row.row_version)
    with pytest.raises(cs.CalcError, match="负数实发"):
        cs.assert_confirmable(db, period)


def test_confirm_gate_catches_roster_drift(db):
    """P1-6：计算后名单变了——新人没记录行（漏发）/ 老人留着记录行（错发），都拦。"""
    period = _period_at_imported(db)
    p = _profile(db, "甲", "1")
    _attendance(db, period, p)
    cs.calculate_period(db, period, expected_version=period.status_version)
    cs.assert_confirmable(db, period)  # 干净时放行

    _profile(db, "新人", "9")  # 计算后才进名单，没有记录行
    with pytest.raises(cs.CalcError, match="没有工资记录"):
        cs.assert_confirmable(db, period)

    newcomer = db.query(SalaryEmployeeProfile).filter_by(emp_no="9").one()
    newcomer.payroll_included = 0
    p.payroll_included = 0  # 甲算完后被改成仅参保，记录行变 stale
    db.commit()
    with pytest.raises(cs.CalcError, match="已不在发薪名单"):
        cs.assert_confirmable(db, period)


def test_recalc_with_stale_version_rejected(db):
    """P1-1：自环重算也过版本谓词——拿落后版本点重算必须 409，明细行不动。"""
    period = _period_at_imported(db)
    p = _profile(db, "甲", "1")
    _attendance(db, period, p)
    cs.calculate_period(db, period, expected_version=period.status_version)
    row = db.query(SalaryRecord).filter_by(
        period_id=period.id, employee_id=p.id).one()
    net_before = row.net_salary

    with pytest.raises(ps.SalaryStaleVersion):
        cs.calculate_period(db, period, expected_version=0)  # 明显落后
    db.refresh(row)
    assert row.net_salary == net_before, "被拒的重算不许落进明细行"

    summary = cs.calculate_period(db, period, expected_version=period.status_version)
    assert summary["calculated"] == 1  # 正确版本的自环重算照常放行
