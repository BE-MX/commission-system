"""异常面板 v1 的口径测试（M2-e）。

**这个面板本身就是一层安全网，所以它的测试要盯的是「网上有没有洞」**：
漏报一条 blocking，HR 就会在数据不全的情况下点「开始计算」，而计算不会报错——
它会拿 0 当社保、拿 0 当缺勤，算出一个看起来很正常的偏高金额。

所以每个用例的判据都是「这条异常必须出现」而不是「函数能跑通」。
反向的用例（不该报的别报）同样重要：面板一旦开始刷噪音，HR 就会整体忽略它，
那时候真异常和假异常一起沉底，等于面板不存在。
"""

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.salary import anomaly_service as ans
from app.salary import period_service as ps
from app.salary.models import (
    SalaryAttendance,
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

_TABLES = [
    SalaryPeriod.__table__, SalaryPeriodEvent.__table__, SalaryRuleParam.__table__,
    SalaryGradeTable.__table__, SalaryDeptMapping.__table__,
    SalaryEmployeeProfile.__table__, SalaryAttendance.__table__,
    SalaryInsuranceImport.__table__, SalaryFundImport.__table__,
    # M3 起异常面板含记录级检查（负数实发/保底触发/人工覆盖偏差），查 salary_record
    SalaryRecord.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=_TABLES)
    session = sessionmaker(bind=engine, autoflush=False)()
    seed_rule_params(session)
    # **flush 不能省。** session 是 autoflush=False，seed 出来的 14 行还在 identity
    # map 里没进库，紧跟的 bulk UPDATE 是直发 SQL——打在空表上，一行都没改到，
    # 生效日仍是 2026-04-01。于是 2026-03 的批次取不到任何参数版本，
    # 以前靠 param_decimal 回落硬编码默认值蒙对，测试全绿而分母是代码里写死的 31。
    session.flush()
    session.query(SalaryRuleParam).update(
        {SalaryRuleParam.effective_from: dt.date(2026, 1, 1)})
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def period(db):
    return ps.create_period(db, "2026-03", operator_id=7)


def mk_profile(db, emp_no="A01", name="王京花", **kw):
    """默认造一个「什么异常都没有」的人。

    默认值必须干净，否则每个用例都要先把无关异常一个个关掉，
    测试会变得没人愿意改。
    """
    defaults = dict(
        dingtalk_userid=f"U{emp_no}", payroll_included=1, status="active",
        position="设计师", hire_date=dt.date(2020, 1, 1),
        grade_code="P3", grade_scheme="professional",
        insurance_entity="丽丝发", fund_included=1,
        id_card_hash=f"hash-{emp_no}", bank_card_hash=f"bank-{emp_no}",
    )
    defaults.update(kw)
    p = SalaryEmployeeProfile(emp_no=emp_no, name=name, **defaults)
    db.add(p)
    db.commit()
    return p


def mk_attendance(db, period, profile, **kw):
    """默认造一条「已录全」的考勤：请假小时都填了 0。"""
    defaults = dict(due_days=Decimal("31"), actual_days=Decimal("31"),
                    personal_leave_hours=Decimal("0"),
                    sick_leave_hours=Decimal("0"), full_attendance=1)
    defaults.update(kw)
    row = SalaryAttendance(period_id=period.id, employee_id=profile.id, **defaults)
    db.add(row)
    db.commit()
    return row


def mk_insurance(db, period, profile=None, *, name="王京花",
                 match_status="matched", personal_total="800"):
    row = SalaryInsuranceImport(
        period_id=period.id,
        employee_id=profile.id if profile else None,
        name=name, match_status=match_status,
        personal_total=Decimal(personal_total), entity="丽丝发",
        id_card_hash=profile.id_card_hash if profile else "hash-unknown",
    )
    db.add(row)
    db.commit()
    return row


def mk_fund(db, period, profile=None, *, name="王京花", match_status="matched"):
    row = SalaryFundImport(
        period_id=period.id,
        employee_id=profile.id if profile else None,
        name=name, match_status=match_status,
        personal_amount=Decimal("200"),
        id_card_hash=profile.id_card_hash if profile else "hash-unknown",
    )
    db.add(row)
    db.commit()
    return row


def kinds(result, severity=None):
    return [it["kind"] for it in result["items"]
            if severity is None or it["severity"] == severity]


def allow_duplicate_userid(db):
    """拆掉 096 的唯一索引，造出**存量**撞号档案。

    096 之后数据库自己就会拒掉撞号，但面板这道检查是给存量数据用的：
    096 之前建的档案、或任何绕过 ORM 的写入路径都可能留下这种数据。
    与 test_salary_attendance.py 里同名的做法一致。
    """
    db.execute(sa.text("DROP INDEX IF EXISTS uk_salary_profile_dingtalk"))
    db.commit()


# ---------------------------------------------------------------------------
# 干净批次不该报噪音
# ---------------------------------------------------------------------------

def test_fully_prepared_period_is_ready(db, period):
    """全部就绪时面板必须是空的、ready_to_calculate 为真。

    这是最容易被忽略但最关键的一条：面板只要**稳定地刷几条无害提示**，
    HR 三个月后就会条件反射地忽略整个面板，那时候真的未匹配社保也会被一起忽略。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    r = ans.collect(db, period)
    assert r["items"] == [], f"干净批次刷出了噪音：{kinds(r)}"
    assert r["ready_to_calculate"] is True
    assert r["payroll_headcount"] == 1


def test_left_employee_is_not_counted_as_missing(db, period):
    """离职的人不进发薪名单，不该刷一堆「考勤缺失」。

    3 月这种有人员流动的月份，离职的人如果算进来，面板会被几十条
    早就走了的人刷满，真待办直接沉底。
    """
    mk_profile(db, emp_no="A02", name="已离职", status="left")
    r = ans.collect(db, period)
    assert r["items"] == []
    assert r["payroll_headcount"] == 0


def test_insurance_only_profile_is_not_asked_for_attendance(db, period):
    """「仅参保」的人（payroll_included=0）不发薪，不查考勤。"""
    mk_profile(db, emp_no="A03", name="仅参保", payroll_included=0)
    r = ans.collect(db, period)
    assert r["items"] == []


# ---------------------------------------------------------------------------
# 考勤类
# ---------------------------------------------------------------------------

def test_unbound_dingtalk_is_blocking(db, period):
    """没绑钉钉 = 考勤永远是空的 = 缺勤扣款按 0 算 = 多发钱。"""
    mk_profile(db, dingtalk_userid=None)
    r = ans.collect(db, period)
    assert ans.KIND_DINGTALK_UNBOUND in kinds(r, ans.BLOCKING)
    assert r["ready_to_calculate"] is False


def test_duplicate_userid_reports_one_item_per_group_not_per_person(db, period):
    """**一组撞号出一条，不是一人一条。**

    一人一条的话 10 组撞号刷出 20 条 blocking，而 `items.sort` 按 kind 字母序，
    `attendance_missing` / `dingtalk_duplicate` 全排在 `dingtalk_unbound` 前面——
    真正待办（那个未绑定的人）被压到清单末尾，确认弹窗还会说「还有 62 条」，
    而实际只有十几件事要做。面板一旦看起来像噪音，HR 就会整体忽略它。
    """
    allow_duplicate_userid(db)
    a = mk_profile(db, emp_no="A01", name="甲")
    b = mk_profile(db, emp_no="A02", name="乙", dingtalk_userid="UA01")
    r = ans.collect(db, period)

    dupes = [it for it in r["items"] if it["kind"] == ans.KIND_DINGTALK_DUPLICATE]
    assert len(dupes) == 1, f"一组撞号刷了 {len(dupes)} 条"
    assert dupes[0]["severity"] == ans.BLOCKING
    assert dupes[0]["employee_id"] == a.id
    assert [x["employee_id"] for x in dupes[0]["ref"]["peers"]] == [b.id]
    assert "乙" in dupes[0]["message"]
    assert dupes[0]["message"].count("甲") == 1, "当事人自己进了「与…共用」，像自己跟自己撞"
    assert r["ready_to_calculate"] is False


def test_duplicate_userid_does_not_also_report_attendance_missing(db, period):
    """撞号的人不再各报一条「考勤缺失」——一个根因刷 4 条待办是面板失效的开始。"""
    allow_duplicate_userid(db)
    mk_profile(db, emp_no="A01", name="甲")
    mk_profile(db, emp_no="A02", name="乙", dingtalk_userid="UA01")
    r = ans.collect(db, period)
    assert ans.KIND_ATTENDANCE_MISSING not in kinds(r)
    assert r["blocking_count"] == 1, f"一组撞号刷了 {r['blocking_count']} 条 blocking"


def test_duplicate_userid_still_reports_attendance_when_row_exists(db, period):
    """撞号但已有考勤行的人，其他检查照跑——撞号不是「跳过这个人」的通行证。"""
    allow_duplicate_userid(db)
    a = mk_profile(db, emp_no="A01", name="甲")
    mk_profile(db, emp_no="A02", name="乙", dingtalk_userid="UA01")
    mk_attendance(db, period, a, sick_leave_hours=None)
    r = ans.collect(db, period)
    assert ans.KIND_ATTENDANCE_PENDING in kinds(r), "请假小时没录仍要报，不能被撞号掩盖"


def test_unbound_does_not_also_report_attendance_missing(db, period):
    """没绑钉钉的人不该再报一条「考勤缺失」——同一件事说两遍。

    一个根因刷两条待办，HR 处理完第一条会发现第二条还在，
    然后开始怀疑面板是不是坏了。
    """
    mk_profile(db, dingtalk_userid="")
    r = ans.collect(db, period)
    assert ans.KIND_ATTENDANCE_MISSING not in kinds(r)


def test_missing_attendance_row_is_blocking(db, period):
    """绑了钉钉但没考勤行——同步失败或漏了这个人。"""
    mk_profile(db)
    r = ans.collect(db, period)
    assert ans.KIND_ATTENDANCE_MISSING in kinds(r, ans.BLOCKING)


def test_null_leave_hours_is_blocking_but_zero_is_not(db, period):
    """请假小时 NULL（没录）阻断，填了 0（确认无请假）放行。

    这是整个模块最贵的区分。NULL 当 0 处理的话：实出天数按满勤算、
    缺勤扣款为 0、100 元全勤奖照发——一个人错三处，而且全程无报错。
    """
    p1 = mk_profile(db, emp_no="A01", name="没录")
    mk_attendance(db, period, p1, personal_leave_hours=None, sick_leave_hours=None)
    r = ans.collect(db, period)
    pending = [it for it in r["items"] if it["kind"] == ans.KIND_ATTENDANCE_PENDING]
    assert len(pending) == 1
    assert pending[0]["severity"] == ans.BLOCKING
    assert set(pending[0]["ref"]["fields"]) == {
        "personal_leave_hours", "sick_leave_hours"}

    p2 = mk_profile(db, emp_no="A02", name="录了0")
    mk_attendance(db, period, p2)  # 默认就是 0
    r2 = ans.collect(db, period)
    assert [it for it in r2["items"]
            if it["kind"] == ans.KIND_ATTENDANCE_PENDING
            and it["employee_id"] == p2.id] == []


def test_partial_leave_entry_still_blocks(db, period):
    """只录了事假、病假还空着——仍然阻断，且文案要点名缺哪个。"""
    p = mk_profile(db)
    mk_attendance(db, period, p, sick_leave_hours=None)
    r = ans.collect(db, period)
    it = next(i for i in r["items"] if i["kind"] == ans.KIND_ATTENDANCE_PENDING)
    assert it["ref"]["fields"] == ["sick_leave_hours"]
    assert "病假" in it["message"] and "事假" not in it["message"]


def test_late_and_absent_are_info_not_blocking(db, period):
    """迟到旷工是提示不是阻断——金额算得出来，只是要人扫一眼。

    如果把它判成 blocking，3 月有几十个人迟到过，面板会永远红着，
    「blocking_count=0 才能计算」这条规则当场作废。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p, late_count=3, absent_count=Decimal("1"))
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    r = ans.collect(db, period)
    assert kinds(r) == [ans.KIND_ATTENDANCE_ABNORMAL]
    assert r["blocking_count"] == 0
    assert r["ready_to_calculate"] is True, "迟到不该挡住计算"
    assert "迟到 3" in r["items"][0]["message"]


def test_zero_counts_do_not_produce_noise(db, period):
    """次数都是 0 时不刷「考勤异常」——0 次迟到不是异常。"""
    p = mk_profile(db)
    mk_attendance(db, period, p, late_count=0, absent_count=Decimal("0"))
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    assert ans.collect(db, period)["items"] == []


# ---------------------------------------------------------------------------
# 社保 / 公积金
# ---------------------------------------------------------------------------

def test_unmatched_insurance_row_is_blocking_and_carries_row_ref(db, period):
    """社保表里有人匹配不上档案。

    不处理的话这个人的社保个人部分（几百到一千多）不会进任何人的减项，
    等于白发那笔钱；而工资表上看不出任何异常。

    这条异常没有 employee_id（就是因为匹配不上），所以必须给 row_id，
    否则 HR 拿到一条无法定位的提示。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    ghost = mk_insurance(db, period, None, name="李四", match_status="unmatched")
    r = ans.collect(db, period)
    it = next(i for i in r["items"] if i["kind"] == ans.KIND_INSURANCE_UNMATCHED)
    assert it["severity"] == ans.BLOCKING
    assert it["ref"]["row_id"] == ghost.id
    assert "李四" in it["message"]


def test_profile_with_entity_but_no_insurance_row_is_blocking(db, period):
    """档案写了参保主体，社保表里却没有他——Excel 漏人了。

    漏的这个人减项为 0，多发几百到一千多；而已导入的其他人都正常，
    所以从总额上完全看不出来。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    other = mk_profile(db, emp_no="A99", name="别人")
    mk_attendance(db, period, other)
    mk_insurance(db, period, other)     # 只导了别人
    mk_fund(db, period, p)
    mk_fund(db, period, other)
    r = ans.collect(db, period)
    missing = [i for i in r["items"] if i["kind"] == ans.KIND_INSURANCE_MISSING]
    assert [i["employee_id"] for i in missing] == [p.id]


def test_no_import_at_all_does_not_report_every_person_missing(db, period):
    """一行都没导入时不刷「每个人都缺社保」——那是「还没导」不是「导漏了」。

    流程第一步（考勤刚同步完、社保还没导）面板就红成一片的话，
    面板从第一眼就是噪音。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    r = ans.collect(db, period)
    assert ans.KIND_INSURANCE_MISSING not in kinds(r)
    assert ans.KIND_FUND_MISSING not in kinds(r)


def test_no_entity_means_not_required(db, period):
    """参保主体为空 = 这个人不参保，不该被要求有社保行。"""
    p = mk_profile(db, insurance_entity=None, fund_included=0)
    mk_attendance(db, period, p)
    other = mk_profile(db, emp_no="A99", name="别人")
    mk_attendance(db, period, other)
    mk_insurance(db, period, other)
    mk_fund(db, period, other)
    r = ans.collect(db, period)
    assert ans.KIND_INSURANCE_MISSING not in kinds(r)
    assert ans.KIND_FUND_MISSING not in kinds(r)


def test_whitelist_is_info_with_a_reversal_hint(db, period):
    """参保未发薪是预期内的，但必须列出来——万一是误标，这人一分钱没有。"""
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_fund(db, period, p)
    mk_insurance(db, period, p, match_status="not_payroll")
    r = ans.collect(db, period)
    it = next(i for i in r["items"] if i["kind"] == ans.KIND_INSURANCE_WHITELIST)
    assert it["severity"] == ans.INFO
    assert "参与发薪" in it["action"], "提示必须告诉 HR 怎么改回来"


def test_fund_not_included_is_not_required(db, period):
    p = mk_profile(db, fund_included=0)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    other = mk_profile(db, emp_no="A99", name="别人")
    mk_attendance(db, period, other)
    mk_insurance(db, period, other)
    mk_fund(db, period, other)
    r = ans.collect(db, period)
    assert ans.KIND_FUND_MISSING not in kinds(r)


# ---------------------------------------------------------------------------
# 档案自身
# ---------------------------------------------------------------------------

def test_duplicate_import_row_is_surfaced_with_its_amount(db, period):
    """导入表里被判 duplicate 的行必须上榜——**这条今天就在少扣钱**。

    import_persist 把同一身份证的第二行当誊写错误整行剔出计算。但补缴、
    跨主体参保都会让一个人合法地有两行（3 月社保表有「正常缴费/补缴」列）。
    被剔掉的那几百块没人扣，工资表上完全看不出来。

    金额要带上：HR 得知道这条值不值得处理，「重复了」和「重复了 623.45 元」
    是两种紧迫感。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_fund(db, period, p)
    mk_insurance(db, period, p)
    dup = mk_insurance(db, period, p, match_status="duplicate",
                       personal_total="623.45")
    r = ans.collect(db, period)
    it = next(i for i in r["items"] if i["kind"] == ans.KIND_IMPORT_DUPLICATE)
    assert it["severity"] == ans.BLOCKING
    assert it["ref"]["row_id"] == dup.id
    assert "623.45" in it["ref"]["personal_amount"]
    assert "补缴" in it["action"], "必须提示这可能是合法的多行，不能只说「录错了」"


def test_profile_id_card_duplicate_is_not_checked(db, period):
    """档案身份证重复**不查**——数据库 UNIQUE 约束已经拦死了。

    这条测试锁的是「不要加回去」：加一个永远不触发的检查，会让人误以为
    这层防线存在，从而放松真正有风险的那一层（导入表）。
    """
    assert not hasattr(ans, "KIND_ID_CARD_DUPLICATE")
    from app.salary.models import SalaryEmployeeProfile as P
    cons = {c.name for c in P.__table__.constraints if c.name}
    assert "uk_salary_profile_id_card" in cons, (
        "档案身份证的 UNIQUE 约束没了——那异常面板必须把这个检查补回来"
    )


def test_duplicate_bank_card_is_blocking(db, period):
    """银行卡撞号：银行盘会把两个人的钱打进同一张卡。"""
    mk_profile(db, emp_no="A01", name="张三", bank_card_hash="same")
    mk_profile(db, emp_no="A02", name="李四", bank_card_hash="same")
    r = ans.collect(db, period)
    assert len([i for i in r["items"]
                if i["kind"] == ans.KIND_BANK_CARD_DUPLICATE]) == 2


def test_null_hashes_are_not_duplicates_of_each_other(db, period):
    """没录身份证的人互相之间不算撞号。

    NULL == NULL 判成重复的话，档案刚建时几十个人会凑成一个巨型「重复组」，
    刷出几十条 blocking，面板直接不可用。
    """
    mk_profile(db, emp_no="A01", name="甲", bank_card_hash=None)
    mk_profile(db, emp_no="A02", name="乙", bank_card_hash="")
    mk_profile(db, emp_no="A03", name="丙", bank_card_hash=None)
    r = ans.collect(db, period)
    assert ans.KIND_BANK_CARD_DUPLICATE not in kinds(r)


def test_no_grade_and_no_override_is_blocking(db, period):
    """既无职级又无手动定薪 → M3 算不出底薪，提前点名而不是等计算时崩。"""
    mk_profile(db, grade_code=None, base_salary_override=None)
    r = ans.collect(db, period)
    assert ans.KIND_BASE_SALARY_MISSING in kinds(r, ans.BLOCKING)


def test_manual_base_salary_satisfies_the_check(db, period):
    """非职级岗位走手动定薪，不该被判缺失（姜妮妮/刘德明那类人）。"""
    p = mk_profile(db, grade_code=None, base_salary_override=Decimal("4500"))
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    r = ans.collect(db, period)
    assert r["items"] == []


# ---------------------------------------------------------------------------
# 聚合形态
# ---------------------------------------------------------------------------

def test_blocking_sorts_before_info(db, period):
    """blocking 必须排在最前面——HR 从上往下处理。"""
    p = mk_profile(db)
    mk_attendance(db, period, p, late_count=1, sick_leave_hours=None)
    r = ans.collect(db, period)
    severities = [i["severity"] for i in r["items"]]
    assert severities == sorted(severities, key=lambda s: s != ans.BLOCKING)
    assert severities[0] == ans.BLOCKING


def test_counts_separate_blocking_from_info(db, period):
    """两个计数必须分开。

    合成一个 total 的话，8 条白名单提示 + 1 条未匹配社保 = 「9 条异常」，
    HR 看到 9 条会挨个点开，也可能干脆全忽略；而真正决定「能不能算」的
    只有那 1 条。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p, late_count=2, sick_leave_hours=None)
    r = ans.collect(db, period)
    assert r["blocking_count"] + r["info_count"] == r["total"]
    assert r["blocking_count"] >= 1 and r["info_count"] >= 1
    assert r["ready_to_calculate"] is False


def test_by_kind_summary_matches_items(db, period):
    """分组计数要和明细对得上——对不上说明有一边算漏了。"""
    mk_profile(db, emp_no="A01", name="甲", dingtalk_userid=None)
    mk_profile(db, emp_no="A02", name="乙", dingtalk_userid=None)
    r = ans.collect(db, period)
    from collections import Counter
    actual = Counter(i["kind"] for i in r["items"])
    assert {g["kind"]: g["count"] for g in r["by_kind"]} == dict(actual)
    assert sum(g["count"] for g in r["by_kind"]) == r["total"]


def test_by_kind_carries_severity_for_the_ui_badges(db, period):
    """**`by_kind[].severity` 是前端角标上色的唯一依据。**

    恒为 info 的话所有角标变灰，致命异常看起来像提示，HR 会跳过它们直接点计算
    （被 ready_to_calculate 挡住，但他不知道该修哪几条）。让前端照 kind 名
    再猜一次「这类算不算致命」必然会猜错——新增 kind 时前端不会同步。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p, late_count=2, sick_leave_hours=None)
    r = ans.collect(db, period)

    sev = {g["kind"]: g["severity"] for g in r["by_kind"]}
    assert sev[ans.KIND_ATTENDANCE_PENDING] == ans.BLOCKING
    assert sev[ans.KIND_ATTENDANCE_ABNORMAL] == ans.INFO
    # 分组的严重度必须和明细一致，不能各算一套
    for g in r["by_kind"]:
        actual = {i["severity"] for i in r["items"] if i["kind"] == g["kind"]}
        assert actual == {g["severity"]}, f"{g['kind']} 分组与明细的严重度不一致"


def test_ready_to_calculate_is_false_whenever_blocking_exists(db, period):
    """`ready_to_calculate` 恒为 True 只会被一个权限测试**偶然**碰到，专门钉一条。

    这是「能不能进计算」的唯一答案：恒 True 的话缺考勤、未匹配社保的批次
    照样能往下走，M3 拿着空考勤按全勤发钱。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p, sick_leave_hours=None)   # 请假小时没录 = blocking
    r = ans.collect(db, period)
    assert r["blocking_count"] >= 1
    assert r["ready_to_calculate"] is False

    # 补录后当场放行——判据是真在数 blocking，不是写死的
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    row.sick_leave_hours = Decimal("0")
    db.commit()
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    r2 = ans.collect(db, period)
    assert r2["blocking_count"] == 0
    assert r2["ready_to_calculate"] is True


def test_every_item_is_actionable(db, period):
    """每条异常都必须能定位 + 有下一步动作。

    「未匹配社保」这种既没 employee_id 又没 ref 的话，HR 拿到的是一句
    无法处理的抱怨。面板的价值在于「告诉我该做什么」，不是「告诉我出事了」。
    """
    mk_profile(db, emp_no="A01", name="甲", dingtalk_userid=None, grade_code=None)
    p = mk_profile(db, emp_no="A02", name="乙", bank_card_hash="dup")
    mk_profile(db, emp_no="A03", name="丙", bank_card_hash="dup")
    mk_attendance(db, period, p, late_count=1)
    mk_insurance(db, period, None, name="幽灵", match_status="unmatched")
    r = ans.collect(db, period)
    assert r["total"] >= 5
    for it in r["items"]:
        assert it["action"], f"{it['kind']} 没给下一步动作"
        assert it["message"]
        assert it["kind_label"] != it["kind"], f"{it['kind']} 缺中文标签"
        assert it["employee_id"] or it["ref"], f"{it['kind']} 无法定位到任何对象"


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

def test_endpoint_is_readable_by_any_read_permission(db, period):
    """看得见问题的人应该比能改的人多——三种 read 权限都放行，无关权限拒。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.salary import router as salary_router

    mk_profile(db, dingtalk_userid=None)

    def client(perms):
        app = FastAPI()
        app.include_router(salary_router.router, prefix="/api/salary")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": "7", "roles": [], "permissions": list(perms)}
        return TestClient(app)

    for perm in ("salary:read", "salary:write", "salary:admin"):
        r = client([perm]).get(f"/api/salary/periods/{period.id}/anomalies")
        assert r.status_code == 200, f"{perm}: {r.text}"
        data = r.json()["data"]
        assert data["blocking_count"] >= 1
        assert data["ready_to_calculate"] is False

    assert client(["asset:read"]).get(
        f"/api/salary/periods/{period.id}/anomalies").status_code == 403
    assert client(["salary:read"]).get(
        "/api/salary/periods/99999/anomalies").status_code == 404


# ---------------------------------------------------------------------------
# 记录级检查（M3：依赖 salary_record，计算后才有数据）
# ---------------------------------------------------------------------------

def mk_record(db, period, profile, **kw):
    """造一条已计算的工资行。默认干净：无旗标、无手动覆盖。"""
    defaults = dict(
        seq_no=1, due_days=Decimal("31"), actual_days=Decimal("31"),
        base_salary=Decimal("5000"), seniority_pay=Decimal("0"),
        attendance_bonus=Decimal("100"), social_insurance=Decimal("-800"),
        housing_fund=Decimal("-200"), absence_deduction=Decimal("0"),
        add_subtotal=Decimal("100"), deduct_subtotal=Decimal("-1000"),
        net_salary=Decimal("4100"), calc_flags=[],
    )
    defaults.update(kw)
    row = SalaryRecord(period_id=period.id, employee_id=profile.id, **defaults)
    db.add(row)
    db.commit()
    return row


def test_negative_net_is_blocking_but_never_blocks_recalc(db, period):
    """负数实发拦的是 confirm，不是 calculate——不算出来根本不知道它是负的。

    如果把 negative_net 算进 ready_to_calculate 的分母，算出负数的那一刻批次
    就永远不能再重算：死锁。所以它是 blocking（面板置顶）但不进计算门。
    """
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    mk_record(db, period, p, net_salary=Decimal("-500"), calc_flags=["negative_net"])
    r = ans.collect(db, period)
    neg = [it for it in r["items"] if it["kind"] == ans.KIND_NEGATIVE_NET]
    assert len(neg) == 1 and neg[0]["severity"] == ans.BLOCKING
    assert neg[0]["ref"]["record_id"], "负数行必须能定位到记录"
    assert r["blocking_count"] == 1
    assert r["ready_to_calculate"] is True, "负数是计算的产物，不能反过来拦计算"


def test_record_flags_surface_as_info(db, period):
    """保底触发与月中加权是 info：让人看见，但不拦任何动作。"""
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    mk_record(db, period, p, subsidy_auto=Decimal("699"),
              calc_flags=["guaranteed_topup", "mid_month_weighted"])
    r = ans.collect(db, period)
    by_kind = {g["kind"]: g for g in r["by_kind"]}
    assert by_kind[ans.KIND_GUARANTEED_TOPUP]["severity"] == ans.INFO
    assert by_kind[ans.KIND_MID_MONTH_WEIGHTED]["severity"] == ans.INFO
    assert r["blocking_count"] == 0


def test_manual_override_diff_only_when_auto_and_manual_disagree(db, period):
    """A2：manual 盖着且 ≠ auto 才报。auto 是 None（引擎没产出）不报——
    P1 的绩效全靠手填，全报一遍等于面板噪音。"""
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    mk_record(db, period, p,
              subsidy_auto=Decimal("1678.91"), subsidy_manual=Decimal("1679"),
              performance_manual=Decimal("2000"))  # auto None：不报
    r = ans.collect(db, period)
    diffs = [it for it in r["items"] if it["kind"] == ans.KIND_MANUAL_OVERRIDE]
    assert len(diffs) == 1
    assert diffs[0]["ref"]["field"] == "subsidy"
    assert diffs[0]["severity"] == ans.INFO


def test_calc_gate_view_excludes_record_items(db, period):
    """计算门看的是 include_records=False 的视图：一条记录级异常都不该出现。"""
    p = mk_profile(db)
    mk_attendance(db, period, p)
    mk_insurance(db, period, p)
    mk_fund(db, period, p)
    mk_record(db, period, p, net_salary=Decimal("-500"), calc_flags=["negative_net"])
    r = ans.collect(db, period, include_records=False)
    assert r["total"] == 0
    assert r["ready_to_calculate"] is True
