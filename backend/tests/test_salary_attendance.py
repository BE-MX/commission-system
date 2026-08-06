"""考勤同步、全勤判定与人工覆盖的口径测试（M2-d）。

测的重点同样不是「能不能存」，而是**存错的时候钱会不会错**：

- 人工录的病假不能被「同步考勤」清掉（清掉 = 少扣缺勤 + 白发全勤奖）；
- 钉钉的「应出勤天数」（3 月给 22）不许进 due_days，满月基准是 31；
- 请假小时没录时 actual_days 必须是 None、全勤必须判 0，不许当满勤；
- 锁定批次并发下整批回滚；
- 年假不破全勤（决策 B3），参数可切回去。
"""

from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.salary import attendance_service as ats
from app.salary import attendance_source as asrc
from app.salary import period_service as ps
from app.salary import pii
from app.core.config import get_settings
from app.salary.models import (
    Base,
    SalaryAttendance,
    SalaryEmployeeProfile,
    SalaryPeriod,
    SalaryPeriodEvent,
    SalaryRuleParam,
)

_TEST_ENC_KEY = "dGVzdC1zYWxhcnktZW5jLWtleS0zMi1ieXRlcy0hIQ=="
_TEST_HASH_KEY = "test-salary-hash-key"


@pytest.fixture(autouse=True)
def salary_keys(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_ENCRYPTION_KEY", _TEST_ENC_KEY)
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", _TEST_HASH_KEY)


@pytest.fixture()
def engine_and_session(tmp_path):
    """**文件库 + 每 session 独立连接 + pysqlite 事务修正。**

    三处都不是洁癖，是这套测试里踩出来的：

    1. **不能用 `sqlite://` + `StaticPool`。** StaticPool 全局只有一条 DBAPI 连接，
       两个 session 共用它——「并发」测试里的 A 和 B 其实在同一个事务里，
       测不到任何并发。改文件库 + 默认连接池，两个 session 才真的是两条连接。

    2. **pysqlite 不会为纯 SELECT 隐式 BEGIN**（SQLAlchemy 官方已知问题）。
       同步流程在写之前只有 SELECT，于是第一条 `SAVEPOINT` 跑在 autocommit 模式下，
       savepoint 里的 INSERT 当场落盘，`rollback()` 撤不掉。M2-c 的 persist 恰好在
       savepoint 循环前先发了一条 DELETE，误打误撞开了事务，所以那边没暴露。

    3. MySQL/InnoDB 两个问题都不存在（连接上永远有事务、连接天然独立），所以这是
       **测试床失真**而不是业务 bug。但失真方向是「让回滚保证测不出来」——
       靠它绿灯就等于把真 bug 放进生产，必须修，不能绕。
    """
    db_file = tmp_path / "salary_test.db"
    engine = create_engine(f"sqlite:///{db_file}",
                           connect_args={"check_same_thread": False, "timeout": 5})

    @event.listens_for(engine, "connect")
    def _no_implicit_begin(dbapi_conn, _rec):
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _explicit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine, tables=[
        SalaryPeriod.__table__, SalaryPeriodEvent.__table__,
        SalaryEmployeeProfile.__table__, SalaryAttendance.__table__,
        SalaryRuleParam.__table__,
    ])
    try:
        # autoflush=False 对齐生产（app/core/database.py:18）。测试床跟生产的 session
        # 配置不一致本身就是个定时装置——今天行为恰好一致不代表明天还一致。
        yield engine, sessionmaker(bind=engine, autoflush=False)
    finally:
        engine.dispose()


@pytest.fixture()
def db(engine_and_session):
    _, Session = engine_and_session
    s = Session()
    try:
        yield s
    finally:
        s.close()


PARAMS = {
    "day_hours": "7.83",
    "full_month_days": "31",
    "attendance_sick_hours_max": "8",
    "annual_leave_breaks_attendance": "false",
    "sick_pay_deduct_ratio": "0.30",
}


def make_profile(db, name, *, emp_no, userid="", payroll_included=1):
    plain = f"37021319910312{emp_no:0>4}"
    row = SalaryEmployeeProfile(
        emp_no=emp_no, name=name,
        id_card_hash=pii.hash_pii(plain), id_card_cipher=pii.encrypt_pii(plain),
        payroll_included=payroll_included, fund_included=1, status="active",
        dingtalk_userid=userid or None,
    )
    db.add(row); db.commit(); return row


def make_period(db, ym="2026-03"):
    p = ps.create_period(db, ym)
    p.param_snapshot = dict(PARAMS)
    db.commit()
    return p


def person(userid, **values):
    return asrc.PersonAttendance(
        userid=userid,
        values={k: Decimal(str(v)) for k, v in values.items()},
    )


# ---------------------------------------------------------------------------
# 全勤判定
# ---------------------------------------------------------------------------

def test_annual_leave_does_not_break_full_attendance(db):
    """年假不破全勤（决策 B3）。反推自 3 月真值：王京花年假 5.5 天仍拿到全勤 100。"""
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal("0"),
        annual_leave_days=Decimal("5.5"),
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("0"),
    )
    assert ats.judge_full_attendance(row, PARAMS) is True


def test_annual_leave_can_be_switched_to_break_attendance(db):
    """参数是给 HR 反悔的口子，切回 true 就该立刻生效——不是装饰。"""
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal("0"),
        annual_leave_days=Decimal("5.5"),
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("0"),
    )
    switched = {**PARAMS, "annual_leave_breaks_attendance": "true"}
    assert ats.judge_full_attendance(row, switched) is False


def test_missing_leave_hours_is_not_full_attendance(db):
    """请假小时没录 ≠ 没请假。

    钉钉拿不到请假小时（attendance_source 约束 2/3），NULL 的含义是「HR 还没填」。
    当成 0 处理 = 给一个可能有事假的人白发 100 元全勤奖，而且错误要到对账才浮现。
    """
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=None, sick_leave_hours=None,
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("0"),
    )
    assert ats.judge_full_attendance(row, PARAMS) is False


def test_sick_leave_within_cap_keeps_full_attendance(db):
    for hours, expected in [("8", True), ("8.01", False)]:
        row = SalaryAttendance(
            period_id=1, employee_id=1,
            personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal(hours),
            late_count=0, early_leave_count=0, miss_punch_count=0,
            absent_count=Decimal("0"),
        )
        assert ats.judge_full_attendance(row, PARAMS) is expected, hours


def test_any_late_or_miss_punch_kills_full_attendance(db):
    for field in ("late_count", "early_leave_count", "miss_punch_count"):
        row = SalaryAttendance(
            period_id=1, employee_id=1,
            personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal("0"),
            late_count=0, early_leave_count=0, miss_punch_count=0,
            absent_count=Decimal("0"),
        )
        setattr(row, field, 1)
        assert ats.judge_full_attendance(row, PARAMS) is False, field


# ---------------------------------------------------------------------------
# 实出天数折算
# ---------------------------------------------------------------------------

def test_actual_days_uses_783_and_sick_ratio(db):
    """实出 = 应出 − 事假/7.83 − 病假/7.83×0.30（§5.2）。"""
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("7.83"),   # 正好 1 天
        sick_leave_hours=Decimal("7.83"),       # 1 天 × 30% = 0.3 天
        absent_count=Decimal("0"),
    )
    got = ats.compute_actual_days(row, Decimal("31"), PARAMS)
    assert got == Decimal("29.70"), got


def test_actual_days_is_none_when_leave_not_entered(db):
    """没录请假 → None，不是等于应出。算成满勤会让工资偏高。"""
    row = SalaryAttendance(period_id=1, employee_id=1,
                           personal_leave_hours=None, sick_leave_hours=None)
    assert ats.compute_actual_days(row, Decimal("31"), PARAMS) is None


def test_actual_days_never_goes_negative(db):
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("999"), sick_leave_hours=Decimal("0"),
        absent_count=Decimal("0"),
    )
    assert ats.compute_actual_days(row, Decimal("31"), PARAMS) == Decimal("0")


def test_zero_day_hours_is_rejected_not_divided(db):
    """day_hours=0 必须报错。除零静默变成 0 天缺勤 = 全员少扣钱。"""
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("8"), sick_leave_hours=Decimal("0"),
        absent_count=Decimal("0"),
    )
    with pytest.raises(ats.AttendanceError, match="day_hours"):
        ats.compute_actual_days(row, Decimal("31"), {**PARAMS, "day_hours": "0"})


# ---------------------------------------------------------------------------
# 同步落库
# ---------------------------------------------------------------------------

def test_due_days_comes_from_rule_not_from_dingtalk(db):
    """**钉钉的「应出勤天数」不许进 due_days。**

    实测 2026-03 钉钉给 22（工作日口径），而满月基准按决策 B1 是 31。
    接错了，缺勤扣款 `底薪/应出×缺勤` 的分母就全员错——3 月谷振尧那条
    10000/31×4=1290.32 会变成 10000/22×4=1818.18，一个人多扣 500 多。
    """
    profile = make_profile(db, "谷振尧", emp_no="1", userid="U1")
    period = make_period(db)

    ats.sync_from_dingtalk(db, period, {"results": [
        person("U1", dingtalk_should_days=22, actual_days_raw=22,
               late_count=0, early_leave_count=0, miss_punch_on=0,
               miss_punch_off=0, absent_days=0),
    ]})

    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.due_days == Decimal("31"), "钉钉的 22 天被当成应出天数了"
    assert row.raw_payload["dingtalk_should_days"] == "22", "钉钉原值该留档供核对"


def test_sync_does_not_wipe_manually_entered_leave(db):
    """**同步不能清掉人工录的请假小时。**

    钉钉根本给不了这两个字段（那五列没有列 id）。如果同步把它们置空，
    HR 前脚录完病假、后脚点一下「同步考勤」，数据就没了——而且没有任何提示，
    直接反映成少扣缺勤 + 多发一个 100 元全勤奖。
    """
    profile = make_profile(db, "王京花", emp_no="2", userid="U2")
    period = make_period(db)
    ats.manual_upsert(db, period, profile.id, {
        "personal_leave_hours": Decimal("4"),
        "sick_leave_hours": Decimal("16"),
        "annual_leave_days": Decimal("5.5"),
    })

    ats.sync_from_dingtalk(db, period, {"results": [
        person("U2", late_count=1, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})

    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.personal_leave_hours == Decimal("4.00"), "人工录的事假被同步清掉了"
    assert row.sick_leave_hours == Decimal("16.00"), "人工录的病假被同步清掉了"
    assert row.annual_leave_days == Decimal("5.50")
    assert row.late_count == 1, "钉钉字段该被同步刷新"
    assert row.sync_source == ats.SOURCE_MIXED


def test_sync_recomputes_full_attendance_from_dingtalk_signals(db):
    """钉钉带回迟到 → 全勤必须立刻掉，不能等下一步再判。"""
    profile = make_profile(db, "李晓雨", emp_no="3", userid="U3")
    period = make_period(db)
    ats.manual_upsert(db, period, profile.id, {
        "personal_leave_hours": Decimal("0"), "sick_leave_hours": Decimal("0"),
    })
    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.full_attendance == 1

    ats.sync_from_dingtalk(db, period, {"results": [
        person("U3", late_count=2, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})
    db.refresh(row)
    assert row.full_attendance == 0


def test_miss_punch_sums_both_directions(db):
    """漏打卡 = 上班缺卡 + 下班缺卡，钉钉分两列给。只取一列会漏判全勤。"""
    profile = make_profile(db, "张三", emp_no="4", userid="U4")
    period = make_period(db)
    ats.sync_from_dingtalk(db, period, {"results": [
        person("U4", late_count=0, early_leave_count=0,
               miss_punch_on=1, miss_punch_off=2, absent_days=0),
    ]})
    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.miss_punch_count == 3


def test_non_payroll_profile_is_not_synced(db):
    """参保未发薪的 8 个人不进考勤（与 M2-c 的 payroll_included 口径一致）。"""
    profile = make_profile(db, "曹其宽", emp_no="5", userid="U5", payroll_included=0)
    period = make_period(db)
    summary = ats.sync_from_dingtalk(db, period, {"results": [
        person("U5", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})
    assert db.query(SalaryAttendance).filter_by(employee_id=profile.id).count() == 0
    assert summary["synced"] == 0


def test_failed_person_does_not_block_the_rest(db):
    """单人取数失败不阻塞其余人（红线 6）。"""
    ok = make_profile(db, "甲", emp_no="6", userid="U6")
    bad = make_profile(db, "乙", emp_no="7", userid="U7")
    period = make_period(db)

    summary = ats.sync_from_dingtalk(db, period, {"results": [
        person("U6", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
        asrc.PersonAttendance(userid="U7", error="钉钉取数失败：DingTalkError(88)"),
    ]})

    assert summary["synced"] == 1 and summary["failed"] == 1
    assert db.query(SalaryAttendance).filter_by(employee_id=ok.id).count() == 1
    assert db.query(SalaryAttendance).filter_by(employee_id=bad.id).count() == 0
    assert summary["failures"][0]["name"] == "乙"


def test_summary_exposes_source_and_failed_counts(db):
    """失败必须是**可见的数字**，不是 warnings 里的一句话。

    只报 synced 的话，「钉钉回了 2 人、落库 1 人」在界面上跟一切正常长得一样，
    而少的那人当月考勤全空 → 缺勤按 0 算 → 多发钱。前端靠 source_count != synced
    做红色阻断。（对抗性审查 2026-08-07 第 3 条）
    """
    make_profile(db, "甲", emp_no="21", userid="U21")
    make_profile(db, "乙", emp_no="22", userid="U22")
    period = make_period(db)
    summary = ats.sync_from_dingtalk(db, period, {"results": [
        person("U21", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
        asrc.PersonAttendance(userid="U22", error="钉钉取数失败"),
    ]})
    assert summary["source_count"] == 2
    assert summary["synced"] == 1
    assert summary["failed"] == 1
    assert summary["source_count"] != summary["synced"], "前端的阻断判据"


def test_unbound_profiles_are_listed(db):
    """没绑钉钉的人考勤永远是空的，必须逐个点名而不是静默缺席。"""
    make_profile(db, "未绑定", emp_no="8", userid="")
    make_profile(db, "已绑定", emp_no="9", userid="U9")
    period = make_period(db)
    summary = ats.sync_from_dingtalk(db, period, {"results": []})
    names = [u["name"] for u in summary["unbound"]]
    assert names == ["未绑定"]


def test_sync_is_upsert_not_delete_and_recreate(db):
    """重复同步不该换掉行 id——前端刚打开的编辑框会指向不存在的行。"""
    profile = make_profile(db, "甲", emp_no="10", userid="U10")
    period = make_period(db)
    payload = {"results": [person("U10", late_count=0, early_leave_count=0,
                                  miss_punch_on=0, miss_punch_off=0, absent_days=0)]}
    ats.sync_from_dingtalk(db, period, payload)
    first_id = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one().id
    ats.sync_from_dingtalk(db, period, payload)
    rows = db.query(SalaryAttendance).filter_by(employee_id=profile.id).all()
    assert len(rows) == 1 and rows[0].id == first_id


# ---------------------------------------------------------------------------
# 状态机与并发
# ---------------------------------------------------------------------------

def test_sync_advances_draft_to_attendance_synced(db):
    make_profile(db, "甲", emp_no="11", userid="U11")
    period = make_period(db)
    assert period.status == ps.STATUS_DRAFT
    ats.sync_from_dingtalk(db, period, {"results": [
        person("U11", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0)]})
    assert period.status == ps.STATUS_ATTENDANCE


def test_repeat_sync_does_not_burn_version(db):
    """重复同步是常态（HR 会反复拉几次核对），每次 +1 会把 409 变成背景噪音。"""
    make_profile(db, "甲", emp_no="12", userid="U12")
    period = make_period(db)
    payload = {"results": [person("U12", late_count=0, early_leave_count=0,
                                  miss_punch_on=0, miss_punch_off=0, absent_days=0)]}
    ats.sync_from_dingtalk(db, period, payload)
    v = period.status_version
    ats.sync_from_dingtalk(db, period, payload)
    ats.sync_from_dingtalk(db, period, payload)
    assert period.status_version == v


def test_locked_period_rejects_sync(db):
    make_profile(db, "甲", emp_no="13", userid="U13")
    period = make_period(db)
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED,
              ps.STATUS_REVIEWING):
        period = ps.transition(db, period, s, expected_version=period.status_version)
    ps.confirm(db, period, expected_version=period.status_version, operator_id=1)

    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ats.sync_from_dingtalk(db, period, {"results": []})


def test_locked_period_rejects_manual_entry(db):
    profile = make_profile(db, "甲", emp_no="14", userid="U14")
    period = make_period(db)
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED,
              ps.STATUS_REVIEWING):
        period = ps.transition(db, period, s, expected_version=period.status_version)
    ps.confirm(db, period, expected_version=period.status_version, operator_id=1)

    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ats.manual_upsert(db, period, profile.id, {"sick_leave_hours": Decimal("8")})


def test_concurrent_lock_rolls_back_the_whole_batch(engine_and_session):
    """并发：A 手上的批次快照过期（B 已锁定），A 的整批考勤必须一行都不留。

    `assert_writable` 读的是 A 开工时那份 ORM 快照，那时批次还没锁；同步 66 个人
    要跑一分钟，窗口大得很。真正的守卫是末尾那条
    `UPDATE ... WHERE status != 'confirmed' AND status_version = ?`——
    rowcount==0 → rollback，前面所有 insert 一起作废。

    **怎么造这个场景，踩了两次**：

    1. 一开始用 `sqlite://` + StaticPool 开两个 session 做「真并发」。StaticPool
       全局只有一条连接，两个 session 其实在同一个事务里，测不到并发。
    2. 改文件库后确实是两条连接了，但 SQLite 是整库单写锁——B 在 A 的事务中途
       写 period 会直接 `database is locked`。那是 SQLite 的限制，不是业务语义。

    所以这里改成**造过期快照**而不是造真并发：B 先在自己的连接上锁定并提交，
    A 再拿着一份开工前的旧 period（status/version 都是旧值）去同步。对
    `guarded_write` 来说，这跟「跑到一半被人锁了」是同一个输入，而且它才是
    这个测试真正要钉的东西。MySQL 上行锁不会有这个问题，真并发由生产环境保证。
    """
    _, Session = engine_and_session
    sa_, sb = Session(), Session()
    try:
        p = SalaryEmployeeProfile(
            emp_no="90", name="甲",
            id_card_hash=pii.hash_pii("370213199103129000"),
            id_card_cipher=pii.encrypt_pii("370213199103129000"),
            payroll_included=1, fund_included=1, status="active",
            dingtalk_userid="U90",
        )
        sa_.add(p)
        period = ps.create_period(sa_, "2026-03")
        period.param_snapshot = dict(PARAMS)
        sa_.commit()
        pid = period.id

        # A 开工：拿到一份「可写」的快照，此刻批次确实没锁
        pa = ps.get_period(sa_, pid)
        sa_.refresh(pa)
        stale_status, stale_version = pa.status, pa.status_version
        assert pa.status != ps.STATUS_CONFIRMED
        sa_.expunge(pa)          # 脱离 session，模拟「手上这份不会自动刷新」
        sa_.commit()

        # B 在另一条连接上走完复核并锁定
        pb = ps.get_period(sb, pid)
        for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                  ps.STATUS_CALCULATED, ps.STATUS_REVIEWING):
            pb = ps.transition(sb, pb, s, expected_version=pb.status_version)
        ps.confirm(sb, pb, expected_version=pb.status_version, operator_id=200)
        sb.close()

        # A 拿着过期快照继续干活：assert_writable 看的是旧 status，放行；
        # 一路写到末尾才被 guarded_write 的谓词拦下
        assert pa.status == stale_status and pa.status_version == stale_version
        with pytest.raises(ps.SalaryStaleVersion):
            ats.sync_from_dingtalk(sa_, pa, {"results": [
                person("U90", late_count=0, early_leave_count=0,
                       miss_punch_on=0, miss_punch_off=0, absent_days=0)]})

        # 判据要挑对，否则测了个寂寞。前两版都不咬人：
        #   ①（M2-c 的写法）测试自己先 `sa_.rollback()` 再断言 —— 替被测代码
        #     做了那件事，把 `guarded_write` 的 `db.rollback()` 删掉照样绿；
        #   ② 换个全新 session 查 count==0 —— 未提交的数据本来就跨 session 不可见，
        #     有没有 rollback 都是 0，同样删掉照样绿（我自己也踩了这一版）。
        #
        # 真正的风险是：**没 rollback 的话，session 里那批 insert 还挂着**，
        # 后面任何一次 commit（重试、log_event、或者 get_db 收尾）都会把它们带进库。
        # 所以判据是「让 A 的 session 继续走下去，数据仍然不能出现」。
        sa_.commit()
        checker = Session()
        try:
            assert checker.query(SalaryAttendance).count() == 0, (
                "批次在同步途中被锁定，考勤却在后续 commit 时溜进了库——"
                "已发工资的批次被改了"
            )
        finally:
            checker.close()
    finally:
        sa_.close(); sb.close()


# ---------------------------------------------------------------------------
# 人工录入
# ---------------------------------------------------------------------------

def test_manual_entry_recomputes_immediately(db):
    """填完病假立刻重算，不要求 HR 再点一次「重新判定」。"""
    profile = make_profile(db, "甲", emp_no="15", userid="U15")
    period = make_period(db)
    row = ats.manual_upsert(db, period, profile.id, {
        "personal_leave_hours": Decimal("0"), "sick_leave_hours": Decimal("7.83"),
    })
    assert row.due_days == Decimal("31")
    assert row.actual_days == Decimal("30.70")   # 31 − 7.83/7.83×0.3
    assert row.full_attendance == 1              # 病假 7.83 ≤ 8h 上限


def test_manual_entry_on_unknown_employee_is_rejected(db):
    period = make_period(db)
    with pytest.raises(ats.AttendanceError, match="不存在"):
        ats.manual_upsert(db, period, 99999, {"sick_leave_hours": Decimal("1")})


def test_manual_upsert_does_not_burn_version(db):
    """录入是高频动作，每次 +1 会让批次页疯狂 409。"""
    profile = make_profile(db, "甲", emp_no="16", userid="U16")
    period = make_period(db)
    v = period.status_version
    ats.manual_upsert(db, period, profile.id, {"sick_leave_hours": Decimal("1")})
    ats.manual_upsert(db, period, profile.id, {"sick_leave_hours": Decimal("2")})
    assert period.status_version == v


def test_pending_manual_is_surfaced(db):
    """没录请假的人要能被挑出来——否则 HR 只看到「全员非全勤」而不知道是缺输入。"""
    a = make_profile(db, "已录", emp_no="17", userid="U17")
    b = make_profile(db, "未录", emp_no="18", userid="U18")
    period = make_period(db)
    ats.sync_from_dingtalk(db, period, {"results": [
        person("U17", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
        person("U18", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})
    ats.manual_upsert(db, period, a.id, {
        "personal_leave_hours": Decimal("0"), "sick_leave_hours": Decimal("0")})

    listed = ats.list_rows(db, period.id)
    assert listed["pending_manual_count"] == 1
    only = ats.list_rows(db, period.id, only_pending=True)
    assert [i["name"] for i in only["items"]] == ["未录"]
    assert only["items"][0]["pending_manual"] == [
        "personal_leave_hours", "sick_leave_hours"]
    _ = b


def test_sync_leaves_an_event(db):
    make_profile(db, "甲", emp_no="19", userid="U19")
    period = make_period(db)
    ats.sync_from_dingtalk(db, period, {"results": [
        person("U19", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0)]})
    events = ps.list_events(db, period.id)
    assert any(e.event_type == "attendance_sync" for e in events)


def test_missing_leave_columns_are_reported(db):
    """钉钉那五列取不到，必须明说——否则 HR 以为请假是自动的。"""
    make_profile(db, "甲", emp_no="20", userid="U20")
    period = make_period(db)
    summary = ats.sync_from_dingtalk(db, period, {
        "results": [], "missing_leave": ["年假", "事假", "病假"]})
    assert summary["missing_leave_columns"] == ["年假", "事假", "病假"]


# ---------------------------------------------------------------------------
# 取数层（纯函数，不打网络）
# ---------------------------------------------------------------------------

def test_aggregate_column_sums_daily_values():
    """钉钉给的是逐日值，月度值要自己加。"""
    days = [{"date": "2026-03-01", "value": "0.0"},
            {"date": "2026-03-02", "value": "1.0"},
            {"date": "2026-03-03", "value": "1.0"}]
    assert asrc.aggregate_column(days) == Decimal("2.0")


def test_aggregate_column_tolerates_dirty_values():
    """空串/脏值不能让整个人的同步炸掉。"""
    days = [{"date": "d", "value": ""}, {"date": "d", "value": None},
            {"date": "d", "value": "abc"}, {"date": "d", "value": "1.5"}]
    assert asrc.aggregate_column(days) == Decimal("1.5")


def test_column_chunking_respects_the_measured_limit():
    """实测上限 20：21 个列 id 就 errcode=41。分片必须切在 20 以内。"""
    assert asrc.MAX_COLUMNS_PER_CALL <= 20
    chunks = asrc._chunk([str(i) for i in range(38)], asrc.MAX_COLUMNS_PER_CALL)
    assert all(len(c) <= 20 for c in chunks)
    assert sum(len(c) for c in chunks) == 38


def test_month_range_format():
    assert asrc.month_range(2026, 3, 31) == (
        "2026-03-01 00:00:00", "2026-03-31 23:59:59")


def test_dirty_values_are_reported_not_silently_zeroed():
    """**脏值必须回报条数。** 危险的不是全列坏掉（聚合出 0，一眼看得出），
    而是 31 天里坏 11 天：聚合出 20.0，看起来完全正常，只是少了 11 天。
    """
    days = ([{"date": "d", "value": "1.0"}] * 20
            + [{"date": "d", "value": "N/A"}] * 11)
    total, dirty = asrc.aggregate_column_detail(days)
    assert total == Decimal("20.0")
    assert dirty == 11, "11 天脏值被静默算成 0 且没有任何回报（红线 6）"


def test_empty_string_is_not_dirty():
    """钉钉对「那天没这一项」就是给 ""，这是正常语义，不该刷成告警把真问题淹掉。"""
    total, dirty = asrc.aggregate_column_detail(
        [{"date": "d", "value": ""}, {"date": "d", "value": None},
         {"date": "d", "value": "1.5"}])
    assert (total, dirty) == (Decimal("1.5"), 0)


# ---------------------------------------------------------------------------
# 对抗性审查 2026-08-07 的回归钉子
#
# 这一组每条都对应一个实测出来的多发钱路径。断言里写的是「钱会怎么错」，
# 不是「函数返回什么」——后者改个实现就得重写，前者是口径本身。
# ---------------------------------------------------------------------------

def test_params_come_from_the_batch_month_not_today(db):
    """**P0-1：参数按批次月取，不按 today。**

    8 月跑 3 月批次时，`load_params(db)` 的默认 today 会取到 8 月生效的版本。
    实测：param_snapshot 说 31、落库的 due_days 是 26，同一批次两个分母，
    底薪 10000 缺勤 4 天差 248.14 元/人，66 人同向偏。
    """
    from datetime import date as _date
    # 3 月生效版本：满月 31；4 月起改成 26。批次是 2026-03，就该拿 31。
    db.add(SalaryRuleParam(param_key="full_month_days", param_value="31",
                           effective_from=_date(2026, 1, 1),
                           effective_to=_date(2026, 3, 31)))
    db.add(SalaryRuleParam(param_key="full_month_days", param_value="26",
                           effective_from=_date(2026, 4, 1)))
    db.add(SalaryRuleParam(param_key="day_hours", param_value="7.83",
                           effective_from=_date(2026, 1, 1)))
    db.commit()

    profile = make_profile(db, "谷振尧", emp_no="1", userid="U1")
    period = make_period(db)
    period.param_snapshot = None  # 还没冻结，走现查这条路
    db.commit()

    ats.sync_from_dingtalk(db, period, {"results": [
        person("U1", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})

    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.due_days == Decimal("31"), (
        f"取到了 {row.due_days}，说明参数按今天而不是按批次月 2026-03 取的")


def test_frozen_snapshot_wins_over_current_param_table(db):
    """**P0-1 的另一半：快照优先。** 已冻结的批次要能原样复算，
    哪怕 HR 事后把参数表改了——不然「当初发的那个数」永远复算不出来。
    """
    from datetime import date as _date
    db.add(SalaryRuleParam(param_key="full_month_days", param_value="26",
                           effective_from=_date(2020, 1, 1)))
    db.commit()
    profile = make_profile(db, "冻结", emp_no="9", userid="U9")
    period = make_period(db)  # make_period 里已经冻了 full_month_days=31

    ats.sync_from_dingtalk(db, period, {"results": [
        person("U9", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
    ]})
    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.due_days == Decimal("31"), "快照被当前参数表覆盖了，已发批次复算不出原值"


def test_duplicate_dingtalk_userid_blocks_the_whole_sync(db):
    """**P0-2：userid 撞号必须整批拒绝。**

    两份档案共用一个 userid 时，钉钉只回一条、落库也只有一条，于是
    source_count == synced、failed == 0、unbound 为空——**所有告警指标全绿**，
    而被覆盖的那个人当月考勤是空的，M3 按全勤给他发钱。
    唯一能救的时机是同步开始前，所以拒绝整批而不是「跳过重复的继续跑」。
    """
    # 096 之后数据库自己就会拒掉撞号，所以这里显式拆掉唯一索引来造出**存量**状态：
    # 096 之前建的档案、或任何绕过 ORM 的写入路径都可能留下这种数据。
    # service 层那道门不是数据库约束的重复，是它的补集。
    db.execute(sa.text("DROP INDEX IF EXISTS uk_salary_profile_dingtalk"))
    db.commit()
    a = make_profile(db, "甲", emp_no="1", userid="U1")
    b = make_profile(db, "乙", emp_no="2", userid="U1")
    period = make_period(db)

    with pytest.raises(ats.AttendanceError) as exc:
        ats.sync_from_dingtalk(db, period, {"results": [
            person("U1", late_count=5, early_leave_count=0,
                   miss_punch_on=0, miss_punch_off=0, absent_days=3),
        ]})
    assert "甲" in str(exc.value) and "乙" in str(exc.value), "报错要点出是哪两个人撞的"
    assert db.query(SalaryAttendance).filter_by(period_id=period.id).count() == 0, (
        "撞号时不该落任何考勤行——落一半比不落更难发现")
    assert {a.id, b.id}  # 两人都还在名单里，等 HR 去改绑定


def test_calculated_period_rejects_resync(db):
    """**P0-3：已计算的批次不许重新同步。**

    状态机没有 calculated → attendance_synced 这条边，于是重同步时状态和版本号
    都不动，界面继续显示「已计算」而底下的考勤被改了，导出的是过期数字。
    """
    make_profile(db, "李晓雨", emp_no="3", userid="U3")
    period = make_period(db)
    period.status = ps.STATUS_CALCULATED
    db.commit()

    with pytest.raises(ats.AttendanceError) as exc:
        ats.sync_from_dingtalk(db, period, {"results": [
            person("U3", late_count=5, early_leave_count=0,
                   miss_punch_on=0, miss_punch_off=0, absent_days=3),
        ]})
    assert "已计算" in str(exc.value)
    assert "退回" in str(exc.value), "报错要告诉 HR 下一步怎么做，不是只说不行"


def test_reviewing_period_rejects_resync(db):
    """复核中同理：数已经被人在看了，底下不能变。"""
    make_profile(db, "复核", emp_no="4", userid="U4")
    period = make_period(db)
    period.status = ps.STATUS_REVIEWING
    db.commit()
    with pytest.raises(ats.AttendanceError):
        ats.sync_from_dingtalk(db, period, {"results": [
            person("U4", late_count=0, early_leave_count=0,
                   miss_punch_on=0, miss_punch_off=0, absent_days=0),
        ]})


def test_missing_dingtalk_column_does_not_zero_manual_counts(db):
    """**P1-4：钉钉少给一列，不能把人工补录的迟到/漏打卡清零。**

    钉钉考勤权限没开通时，这四个字段的唯一来源就是人工录入。报表被改名会让
    某列彻底取不到，`.get(k, 0)` 于是把 3 次迟到抹成 0，全勤判定从「不给」
    翻成「给」，白发 100 元。
    """
    profile = make_profile(db, "缺列", emp_no="5", userid="U5")
    period = make_period(db)
    ats.manual_upsert(db, period, profile.id, {
        "personal_leave_hours": Decimal("0"), "sick_leave_hours": Decimal("0"),
        "late_count": 3, "miss_punch_count": 2,
    })
    assert db.query(SalaryAttendance).filter_by(employee_id=profile.id).one().full_attendance == 0

    # 钉钉这次只回了旷工一列（迟到/漏打卡列被改名，取不到）
    ats.sync_from_dingtalk(db, period, {"results": [person("U5", absent_days=0)]})

    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.late_count == 3, "钉钉没给这一列，人工录的 3 次迟到被清成 0 了"
    assert row.miss_punch_count == 2, "同上，漏打卡被清零"
    assert row.full_attendance == 0, "清零的后果就是这个：全勤从不给翻成给，白发 100 元"


def test_missing_lists_people_without_attendance_rows(db):
    """**P1-5：取数失败的人要有持久出口。**

    failures 只活在那一次 HTTP 响应里，刷新就没了；而考勤列表只列「已有行」的人，
    失败的人在列表里也查无此人。missing = 名单 LEFT JOIN 考勤，谁没落上行都在这。
    """
    ok_p = make_profile(db, "成功", emp_no="1", userid="U1")
    bad_p = make_profile(db, "失败", emp_no="2", userid="U2")
    period = make_period(db)

    summary = ats.sync_from_dingtalk(db, period, {"results": [
        person("U1", late_count=0, early_leave_count=0,
               miss_punch_on=0, miss_punch_off=0, absent_days=0),
        asrc.PersonAttendance(userid="U2", error="钉钉限流 850015"),
    ]})

    assert summary["payroll_headcount"] == 2, "分母该是发薪名单人数，不是钉钉回了几条"
    ids = {m["employee_id"] for m in summary["missing"]}
    assert bad_p.id in ids and ok_p.id not in ids
    # 刷新之后（不带 summary）仍然查得到
    assert bad_p.id in {m["employee_id"] for m in ats.list_missing(db, period.id)}


def test_manual_entry_rejects_people_off_the_payroll(db):
    """**P1-6：人工录入要有名单门。**

    同步和 router 都按「在职 + payroll_included」筛人，只有人工录入是按 id 直取。
    缺这道门，给只参保不发薪或已离职的人录考勤会建出考勤行并判出全勤，
    M3 顺着行把工资和 100 元全勤奖一起发出去。
    """
    outsider = make_profile(db, "仅参保", emp_no="1", userid="U1", payroll_included=0)
    left = make_profile(db, "已离职", emp_no="2", userid="U2")
    left.status = "left"
    db.commit()
    period = make_period(db)

    for p, word in ((outsider, "仅参保"), (left, "已离职")):
        with pytest.raises(ats.AttendanceError) as exc:
            ats.manual_upsert(db, period, p.id, {
                "personal_leave_hours": Decimal("0"),
                "sick_leave_hours": Decimal("0"),
            })
        assert word in str(exc.value)
    assert db.query(SalaryAttendance).filter_by(period_id=period.id).count() == 0


def test_fractional_counts_round_up_not_down(db):
    """次数向上取整：`int()` 朝零截断会把 0.5 次漏打卡抹成 0，异常直接消失。"""
    profile = make_profile(db, "半次", emp_no="6", userid="U6")
    period = make_period(db)
    ats.sync_from_dingtalk(db, period, {"results": [
        person("U6", miss_punch_on=0.6, miss_punch_off=0.6, absent_days=0),
    ]})
    row = db.query(SalaryAttendance).filter_by(employee_id=profile.id).one()
    assert row.miss_punch_count == 2, f"0.6+0.6=1.2 被截断成 {row.miss_punch_count} 了"


# --- 口径参数化是真的在生效吗 ---

def test_params_are_actually_read_not_hardcoded(db):
    """**用非默认值测参数化。**

    原来的 PARAMS 里 sick_max=8 / full_month_days=31 / sick_ratio=0.30 恰好等于
    代码里的兜底默认值，于是「参数被读到了」和「参数被忽略、走了硬编码」两种情况
    测出来一模一样——覆盖率是假的。这条全用非默认值。
    """
    tweaked = {"day_hours": "8", "full_month_days": "26",
               "attendance_sick_hours_max": "4", "sick_pay_deduct_ratio": "0.50",
               "annual_leave_breaks_attendance": "false"}
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal("5"),
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("0"),
    )
    # 病假 5h > 上限 4h → 不全勤（若走硬编码上限 8，5 会被判成全勤）
    assert ats.judge_full_attendance(row, tweaked) is False
    # 26 − 5/8×0.50 = 26 − 0.3125 = 25.6875 → 25.69。
    # 特意避开 .xx5 的平局：那种数会把这条测试变成在测 ROUND_HALF_EVEN，
    # 而这里要测的是「参数到底有没有被读进去」。
    assert ats.compute_actual_days(row, Decimal("26"), tweaked) == Decimal("25.69")


def test_personal_leave_breaks_full_attendance(db):
    """事假破全勤。原测试集里**没有一条把事假设成非零**，这条判定其实没被覆盖。"""
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("4"), sick_leave_hours=Decimal("0"),
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("0"),
    )
    assert ats.judge_full_attendance(row, PARAMS) is False


def test_absence_breaks_full_attendance_and_cuts_actual_days(db):
    """旷工既破全勤，也要从实出天数里扣掉。

    少扣的话：3 天 × 10000/31 = 967.74 元白发，而全勤奖还照给。
    """
    row = SalaryAttendance(
        period_id=1, employee_id=1,
        personal_leave_hours=Decimal("0"), sick_leave_hours=Decimal("0"),
        late_count=0, early_leave_count=0, miss_punch_count=0,
        absent_count=Decimal("3"),
    )
    assert ats.judge_full_attendance(row, PARAMS) is False
    assert ats.compute_actual_days(row, Decimal("31"), PARAMS) == Decimal("28.00")
