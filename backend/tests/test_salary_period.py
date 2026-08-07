"""批次工作流与状态机的口径测试（M2-a）。

重点测的是**并发与锁定**，不是 CRUD：
- 状态跃迁必须走白名单，跳级/倒退要被拦
- 两个人同时改同一批次，只能有一个赢（乐观锁）
- confirmed 之后一切写操作被 assert_writable 拦掉
- 解锁必须留原因、必须留痕（A4 作废水印的依据）

CRUD 部分只测到「能建、月份唯一、参数落对」为止——那些出错会立刻被发现，
而并发和锁定出错是静默的：钱已经发出去了才发现历史批次被改过。
"""

import datetime as dt
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser
from app.core.database import Base
from app.salary import period_service as ps
from app.salary.models import (
    SalaryDeptMapping,
    SalaryGradeTable,
    SalaryPeriod,
    SalaryPeriodEvent,
    SalaryRuleParam,
)
from app.salary.seed import seed_rule_params


@pytest.fixture()
def engine_and_session():
    """共享内存库 + session 工厂。并发测试要开两个 session 指向同一个库。

    普通 "sqlite://" 每个连接一个独立库，两个 session 会各看各的；
    StaticPool + shared cache 才能让它们真正撞在同一张表上。
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SalaryPeriod.__table__,
            SalaryPeriodEvent.__table__,
            SalaryRuleParam.__table__,
            SalaryGradeTable.__table__,
            SalaryDeptMapping.__table__,
            # 事件时间线要把 created_by 换成真实姓名，得有用户表可 JOIN
            ArkUser.__table__,
        ],
    )
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


@pytest.fixture()
def db(engine_and_session):
    _, Session = engine_and_session
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_params_from(db, effective_from):
    """种参数并把生效日改到指定日期。

    seed 的 EFFECTIVE_FROM 是 2026-04-01，而 P1 验收目标是 3 月——测 3 月场景必须
    先把生效日前移，否则测的是「参数取不到」的异常路径而不是真实口径。
    """
    seed_rule_params(db)
    db.query(SalaryRuleParam).update({SalaryRuleParam.effective_from: effective_from})
    db.commit()


def advance(db, period, *statuses):
    """连续跃迁，每步带正确版本号。测试里搭场景用。"""
    for s in statuses:
        period = ps.transition(db, period, s, expected_version=period.status_version)
    return period


# ---------------------------------------------------------------------------
# 月份与天数
# ---------------------------------------------------------------------------

def test_parse_year_month_rejects_garbage():
    for bad in ("2026-13", "2026-0", "26-03", "2026/03", "", None):
        with pytest.raises(ps.SalaryPeriodError):
            ps.parse_year_month(bad)
    assert ps.parse_year_month("2026-03") == (2026, 3)


def test_natural_days_follows_calendar():
    assert ps.natural_days_of(2026, 3) == 31
    assert ps.natural_days_of(2026, 2) == 28
    assert ps.natural_days_of(2024, 2) == 29  # 闰年


def test_workday_derivation_matches_march_2026():
    """2026-03 无法定节假日，纯工作日推算应得 22 天（设计文档 §3 实证值）。"""
    count, source = ps.derive_workday_count(2026, 3)
    assert count == 22
    assert source == "weekday_auto"


def test_holiday_months_are_flagged_for_review():
    """含法定节假日的月份标 needs_review，没有的月份**必须不标**。

    两个方向都要断言。只测「该标的标了」的话，把月份表改成全 12 个月照样绿——
    那样每个月都提示待复核，HR 学会无视角标，机制就废了。
    2026 年只有 3/7/8/11/12 月无节假日（国办发明电〔2025〕7 号）。
    """
    for month in (1, 2, 4, 5, 6, 9, 10):
        _, source = ps.derive_workday_count(2026, month)
        assert source == "needs_review", f"{month} 月含节假日，应标记待复核"
    for month in (3, 7, 8, 11, 12):
        _, source = ps.derive_workday_count(2026, month)
        assert source == "weekday_auto", f"{month} 月无节假日，不该标待复核"


def test_workday_source_reaches_the_api(db):
    """来源标记必须出现在序列化结果里，不能只躺在事件 payload。

    只落 payload 的话前端要翻 /events 解 JSON 才拿得到，实际上就是发不出去：
    2 月批次的 20 天会静默成为应出基准，而它是月中入离职人员缺勤扣款的分母。
    """
    feb = ps.create_period(db, "2026-02")
    data = ps.serialize_period(feb)
    assert data["workday_source"] == "needs_review"
    assert data["workday_needs_review"] is True
    assert "待复核" in data["workday_source_label"]

    mar = ps.create_period(db, "2026-03")
    assert ps.serialize_period(mar)["workday_needs_review"] is False


def test_manual_workday_marks_source_manual(db):
    """人工填过的值不该再提示待复核——HR 已经核过了。"""
    p = ps.create_period(db, "2026-02", workday_count=18)
    assert ps.serialize_period(p)["workday_source"] == "manual"
    p2 = ps.create_period(db, "2026-01")
    p2 = ps.update_workday_count(db, p2, 20)
    assert ps.serialize_period(p2)["workday_needs_review"] is False


# ---------------------------------------------------------------------------
# 批次 CRUD
# ---------------------------------------------------------------------------

def test_create_period_fills_days(db):
    p = ps.create_period(db, "2026-03")
    assert p.status == ps.STATUS_DRAFT
    assert p.status_version == 0
    assert p.natural_days == 31
    assert p.workday_count == 22


def test_february_natural_days_differ_from_full_month_base(db):
    """2 月 natural_days=28，但 B1 的应出基准仍是 full_month_days=31。

    两个数是两回事，混用会让 2 月所有人的日薪算错。这里把它们同时钉住。
    """
    _seed_params_from(db, dt.date(2026, 1, 1))
    p = ps.create_period(db, "2026-02")
    assert p.natural_days == 28
    params = ps.freeze_params(db, p)
    assert params["full_month_days"] == "31"


def test_duplicate_year_month_rejected(db):
    ps.create_period(db, "2026-03")
    with pytest.raises(ps.SalaryPeriodError, match="已存在"):
        ps.create_period(db, "2026-03")


def test_manual_workday_override(db):
    p = ps.create_period(db, "2026-03", workday_count=20)
    assert p.workday_count == 20
    p = ps.update_workday_count(db, p, 21)
    assert p.workday_count == 21


def test_workday_override_out_of_range_rejected(db):
    p = ps.create_period(db, "2026-02")
    with pytest.raises(ps.SalaryPeriodError, match="1~28"):
        ps.update_workday_count(db, p, 30)


def test_create_validates_workday_same_as_update(db):
    """建批次时的工作日数也要校验，且上限是当月自然日不是常量 31。

    两个入口口径必须一致。之前 create 不校验：同一个 31 在 create 存得下、在 update
    被拒——2 月批次应出 31 天，所有按天折算的缺勤扣款分母都错，往少了扣。
    """
    with pytest.raises(ps.SalaryPeriodError, match="1~28"):
        ps.create_period(db, "2026-02", workday_count=31)
    with pytest.raises(ps.SalaryPeriodError, match="1~31"):
        ps.create_period(db, "2026-03", workday_count=0)
    assert ps.create_period(db, "2026-02", workday_count=28).workday_count == 28


def test_freeze_params_uses_period_month_not_today(db):
    """8 月补算 3 月工资时，要取 3 月生效的参数版本，不是今天的。"""
    _seed_params_from(db, dt.date(2026, 1, 1))
    p = ps.create_period(db, "2026-03")
    snap = ps.freeze_params(db, p)
    assert snap["day_hours"] == "7.83"
    assert p.param_snapshot["full_month_days"] == "31"


def test_freeze_params_refuses_empty_snapshot(db):
    """快照为空必须抛错，不能静默放行。

    这是真踩到的坑：seed 的 EFFECTIVE_FROM=2026-04-01，而 P1 验收目标是复算 2026-03。
    3 月批次一个参数都取不到，而 service.param_decimal 取不到 key 时会回落硬编码默认值——
    整个 3 月会用「代码里的影子参数」算完，HR 在规则页改的值全部不生效，且不报错。
    """
    seed_rule_params(db)  # 默认生效日 2026-04-01
    p = ps.create_period(db, "2026-03")
    with pytest.raises(ps.SalaryPeriodError, match="没有生效的规则参数版本"):
        ps.freeze_params(db, p)


def test_freeze_params_works_once_effective_date_covers_month(db):
    """把生效日调到 3 月即可正常冻结——报错给的指引是可执行的。"""
    _seed_params_from(db, dt.date(2026, 3, 1))
    p = ps.create_period(db, "2026-03")
    assert ps.freeze_params(db, p)["full_month_days"] == "31"


def test_resolve_params_raises_instead_of_falling_back_to_hardcoded(db):
    """**`resolve_params` 必须和 `freeze_params` 对「参数缺失」同一个态度。**

    这里静默返回 `{}` 的话，`param_decimal(params, "full_month_days", Decimal("31"))`
    就拿代码里的 31 顶上，同步 summary 里一个告警都没有——「影子参数」那道防线
    就只在 M3 有效，考勤同步照旧用硬编码分母算 due_days。
    真库 14 个参数的 effective_from 全是 2026-04-01，3 月批次（验收基准月）必然命中。
    """
    seed_rule_params(db)  # 默认生效日 2026-04-01，3 月取不到
    p = ps.create_period(db, "2026-03")
    with pytest.raises(ps.SalaryPeriodError, match="没有生效的规则参数版本"):
        ps.resolve_params(db, p)


def test_resolve_params_prefers_snapshot_even_when_table_is_empty(db):
    """已冻结的批次不受参数表影响——快照就是它的真相，参数表被清空也照旧。"""
    p = ps.create_period(db, "2026-03")
    p.param_snapshot = {"full_month_days": "31"}
    db.commit()
    assert ps.resolve_params(db, p)["full_month_days"] == "31"


# ---------------------------------------------------------------------------
# 状态机：白名单
# ---------------------------------------------------------------------------

def test_happy_path_transitions(db):
    p = ps.create_period(db, "2026-03")
    p = advance(db, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)
    assert p.status == ps.STATUS_REVIEWING
    assert p.status_version == 4  # 每次跃迁 +1


def test_skipping_a_step_is_rejected(db):
    """draft 直接跳 calculated：考勤没同步、社保没导入就算，算出来必错。"""
    p = ps.create_period(db, "2026-03")
    with pytest.raises(ps.SalaryPeriodError, match="不允许"):
        ps.transition(db, p, ps.STATUS_CALCULATED, expected_version=0)


def test_rework_edges_allowed(db):
    """重新导入社保要能退回 imported，复核发现口径错要能退回 calculated。"""
    p = ps.create_period(db, "2026-03")
    p = advance(db, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED)
    p = ps.transition(db, p, ps.STATUS_IMPORTED, expected_version=p.status_version)
    assert p.status == ps.STATUS_IMPORTED
    p = advance(db, p, ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)
    p = ps.transition(db, p, ps.STATUS_CALCULATED, expected_version=p.status_version)
    assert p.status == ps.STATUS_CALCULATED


def test_repeat_sync_and_import_allowed(db):
    """重复同步考勤 / 重复导入是常态操作，不该被状态机拦。"""
    p = ps.create_period(db, "2026-03")
    p = advance(db, p, ps.STATUS_ATTENDANCE, ps.STATUS_ATTENDANCE)
    assert p.status == ps.STATUS_ATTENDANCE
    p = advance(db, p, ps.STATUS_IMPORTED, ps.STATUS_IMPORTED)
    assert p.status == ps.STATUS_IMPORTED


def test_unknown_target_rejected(db):
    p = ps.create_period(db, "2026-03")
    with pytest.raises(ps.SalaryPeriodError):
        ps.transition(db, p, "whatever", expected_version=0)


# ---------------------------------------------------------------------------
# 乐观锁
# ---------------------------------------------------------------------------

def test_stale_version_rejected(db):
    """拿旧版本号提交 = 中间有人改过，必须拒绝而不是覆盖。"""
    p = ps.create_period(db, "2026-03")
    p = ps.transition(db, p, ps.STATUS_ATTENDANCE, expected_version=0)
    with pytest.raises(ps.SalaryStaleVersion):
        ps.transition(db, p, ps.STATUS_IMPORTED, expected_version=0)


def test_concurrent_transition_only_one_wins(engine_and_session):
    """两个**独立 session** 同时读到 version=1 各自提交：只能有一个成功。

    必须用两个 session 才测得准。同一个 session 里手工改属性会被 autoflush 写回库，
    等于把「并发」演成了「自己改自己」——那样即使去掉乐观锁测试也照过。
    这里 B 会话持有的是真正过期的快照。
    """
    engine, Session = engine_and_session
    sa, sb = Session(), Session()
    try:
        p = ps.create_period(sa, "2026-03")
        p = ps.transition(sa, p, ps.STATUS_ATTENDANCE, expected_version=0)
        seen = p.status_version

        # B 会话在 A 提交前读到同一版本
        pb = ps.get_period(sb, p.id)
        assert pb.status_version == seen

        ps.transition(sa, p, ps.STATUS_IMPORTED, expected_version=seen)  # A 赢
        with pytest.raises(ps.SalaryStaleVersion):
            ps.transition(sb, pb, ps.STATUS_IMPORTED, expected_version=seen)  # B 输
    finally:
        sa.close()
        sb.close()


def test_transition_without_version_still_works(db):
    """内部串行流程允许不传版本号（比如刚建完就跃迁）。"""
    p = ps.create_period(db, "2026-03")
    p = ps.transition(db, p, ps.STATUS_ATTENDANCE)
    assert p.status_version == 1


def test_repeat_transition_does_not_burn_version(db):
    """自环（重复同步考勤/重复导入）不消耗版本号。

    这两件事是设计里的常态操作。每做一次就 +1 的话，所有已打开批次页的客户端
    版本立刻作废：HR 甲重跑一次考勤同步，HR 乙正在填的工作日数提交就吃 409
    「已被他人修改」——而批次状态压根没变。M2-c/M2-d 落地后 409 会变成常态噪音，
    用户学会「刷新一下再来」，乐观锁的告警价值就归零了。
    """
    p = ps.create_period(db, "2026-03")
    p = ps.transition(db, p, ps.STATUS_ATTENDANCE, expected_version=0)
    v = p.status_version
    for _ in range(5):
        p = ps.transition(db, p, ps.STATUS_ATTENDANCE, expected_version=p.status_version)
    assert p.status_version == v, "重复同步不该推进版本号"
    assert p.status == ps.STATUS_ATTENDANCE
    # 但真跃迁照常 +1
    p = ps.transition(db, p, ps.STATUS_IMPORTED, expected_version=v)
    assert p.status_version == v + 1
    # 自环仍然留痕——「同步了几次」在时间线上要看得见
    assert [e.event_type for e in ps.list_events(db, p.id)].count("transition") == 7


# ---------------------------------------------------------------------------
# 锁定与解锁
# ---------------------------------------------------------------------------

def _to_reviewing(db, ym="2026-03"):
    p = ps.create_period(db, ym)
    return advance(db, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                   ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)


def test_confirm_stamps_who_and_when(db):
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version, operator_id=7)
    assert p.status == ps.STATUS_CONFIRMED
    assert p.confirmed_by == 7
    assert p.confirmed_at is not None


def test_confirmed_blocks_writes(db):
    """锁定后一切写操作都要被拦——这正是 §2.5 想消灭的错误类型。"""
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version)
    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ps.assert_writable(p)
    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ps.update_workday_count(db, p, 20)


def test_confirmed_cannot_be_reopened_by_plain_transition(db):
    """confirmed → reviewing 只允许 unlock() 走，直接 transition 绕过留痕不行。"""
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version)
    with pytest.raises(ps.SalaryPeriodError, match="解锁流程"):
        ps.transition(db, p, ps.STATUS_REVIEWING, expected_version=p.status_version)


def test_unlock_requires_reason(db):
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version)
    for bad in ("", "   ", None):
        with pytest.raises(ps.SalaryPeriodError, match="解锁必须填写原因"):
            ps.unlock(db, p, bad, expected_version=p.status_version)


def test_unlock_returns_to_reviewing_and_leaves_trace(db):
    """A4：解锁留痕，unlocked_at 有值 = 导出侧要给前次文件打作废水印。"""
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version)
    p = ps.unlock(db, p, "社保基数报错，需重算", expected_version=p.status_version, operator_id=9)

    assert p.status == ps.STATUS_REVIEWING
    assert p.unlocked_at is not None
    assert p.unlock_reason == "社保基数报错，需重算"
    assert ps.serialize_period(p)["writable"] is True


def test_unlock_on_unconfirmed_rejected(db):
    p = _to_reviewing(db)
    with pytest.raises(ps.SalaryPeriodError, match="只有已锁定"):
        ps.unlock(db, p, "随便", expected_version=p.status_version)


def test_unlock_respects_optimistic_lock(db):
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version)
    with pytest.raises(ps.SalaryStaleVersion):
        ps.unlock(db, p, "原因", expected_version=p.status_version - 1)


def test_confirm_stamp_cannot_land_on_an_unlocked_row(engine_and_session):
    """confirmed_at/by 必须跟状态同一条 UPDATE 落库。

    分两次写会开一个窗口：A 的 confirm 提交后、补时间戳前，B 完成一次 unlock，
    A 的第二条裸 UPDATE（WHERE 只有主键）就把 confirmed_at 盖到已解锁的行上，
    造出 confirmed_at > unlocked_at 的假象。而 M4 正是靠这两个时间戳的先后判断
    前次导出要不要打作废水印（A4）——判成「无需作废」，工资表就带着假的锁定戳发出去。

    要测出这个窗口，B 的解锁必须**恰好落在两次写之间**——顺序执行的话 A 早就写完了，
    怎么测都是绿的。这里拿 log_event 当注入点：它在 transition 提交之后调用，正是那个窗口。
    """
    engine, Session = engine_and_session
    sa_, sb = Session(), Session()
    try:
        p = ps.create_period(sa_, "2026-03")
        p = advance(sa_, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                    ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)

        real_log = ps.log_event
        fired = []

        def intercept(db_, period_, event_type, **kw):
            real_log(db_, period_, event_type, **kw)
            if event_type == "transition" and kw.get("to_status") == ps.STATUS_CONFIRMED:
                # ← 窗口正中：A 的状态已提交，若还要补第二次写，就会盖到下面这行解锁之后
                time.sleep(0.01)
                pb = ps.get_period(sb, period_.id)
                real_unlock(sb, pb, "社保基数错了",
                            expected_version=pb.status_version, operator_id=200)
                fired.append(True)

        real_unlock = ps.unlock
        monkey = pytest.MonkeyPatch()
        monkey.setattr(ps, "log_event", intercept)
        try:
            ps.confirm(sa_, p, expected_version=p.status_version, operator_id=100)
        finally:
            monkey.undo()
        assert fired, "注入点没触发，这个测试没测到东西"

        fresh = ps.get_period(sb, p.id)
        sb.refresh(fresh)
        assert fresh.status == ps.STATUS_REVIEWING, "B 的解锁应该生效"
        # 解锁晚于锁定：M4 据此判定「前次导出要作废」。
        # 若 confirmed_at 被第二次裸 UPDATE 盖成更晚的时间，M4 会误判「无需作废」，
        # 工资表就带着一个假的「已锁定」戳发出去。
        assert fresh.unlocked_at >= fresh.confirmed_at, (
            "confirmed_at 盖到了已解锁的行上，M4 会漏打作废水印"
        )
    finally:
        sa_.close()
        sb.close()


def test_confirmed_row_rejects_writes_from_a_stale_session(engine_and_session):
    """锁定判定必须在 DB 谓词里，不能只靠内存里那份 status 快照。

    时序：HR 打开批次页（后端读到 reviewing）→ admin 点锁定 → HR 提交「工作日数改 15」。
    HR 那边的 assert_writable 看到的是自己那份 reviewing 快照，会放行；
    如果写又是裸 ORM 脏刷新，已锁定批次的应出基准就被悄悄改掉了——
    status 还是 confirmed、版本号也没动，审计上完全看不出被动过。
    """
    engine, Session = engine_and_session
    sa_, sb = Session(), Session()
    try:
        p = ps.create_period(sa_, "2026-03")
        p = advance(sa_, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                    ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)

        stale = ps.get_period(sb, p.id)          # B 读到 reviewing
        assert stale.status == ps.STATUS_REVIEWING
        ps.confirm(sa_, p, expected_version=p.status_version)   # A 锁定

        with pytest.raises(ps.SalaryPeriodError):  # Stale 也是它的子类
            ps.update_workday_count(sb, stale, 15)

        fresh = ps.get_period(sa_, p.id)
        sa_.refresh(fresh)
        assert fresh.status == ps.STATUS_CONFIRMED
        assert fresh.workday_count == 22, "已锁定批次的应出天数被改掉了"
    finally:
        sa_.close()
        sb.close()


def test_freeze_params_refuses_confirmed_period(db):
    """锁定后禁止重新冻结参数快照。

    param_snapshot 的全部意义就是让已发的批次可复算；能被覆盖的快照不是快照。
    否则锁定后有人在规则页把 full_month_days 从 31 改成 26，任何触发重算的入口
    都会把快照悄悄换掉，拿这批数复算跟当初发出去的对不上，事件时间线上还一片空白。
    """
    _seed_params_from(db, dt.date(2026, 1, 1))
    p = _to_reviewing(db)
    ps.freeze_params(db, p)
    before = dict(p.param_snapshot)

    p = ps.confirm(db, p, expected_version=p.status_version)
    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ps.freeze_params(db, p)

    db.refresh(p)
    assert p.param_snapshot == before, "已锁定批次的参数快照被覆盖了"


def test_freeze_params_leaves_a_trace(db):
    """冻结参数要留痕——「这批数用的哪版参数、什么时候定的」得查得到。"""
    _seed_params_from(db, dt.date(2026, 1, 1))
    p = ps.create_period(db, "2026-03")
    ps.freeze_params(db, p)
    assert "freeze_params" in [e.event_type for e in ps.list_events(db, p.id)]


# ---------------------------------------------------------------------------
# 留痕
# ---------------------------------------------------------------------------

def test_events_form_a_timeline(db):
    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version, operator_id=3)
    p = ps.unlock(db, p, "重算", expected_version=p.status_version, operator_id=3)

    events = ps.list_events(db, p.id)
    types = [e.event_type for e in events]
    assert types[0] == "unlock"          # 倒序，最新在前
    assert types[-1] == "create"
    assert "transition" in types

    unlock_ev = events[0]
    assert unlock_ev.from_status == ps.STATUS_CONFIRMED
    assert unlock_ev.to_status == ps.STATUS_REVIEWING
    assert unlock_ev.reason == "重算"
    assert unlock_ev.created_by == 3


def test_operator_names_resolve_in_one_batch(db):
    """时间线要显示「谁改的」，而 created_by 只是个 id。

    一并锁住「查不到的 id 不进结果」：前端靠 key 缺失来 fallback 显示 id，
    这里若返回「未知用户」之类的占位，界面看上去有答案实际没有。
    """
    db.add(ArkUser(id=77, username="liang", password_hash="x", real_name="亮哥"))
    db.flush()

    p = _to_reviewing(db)
    p = ps.confirm(db, p, expected_version=p.status_version, operator_id=77)
    p = ps.unlock(db, p, "重算", expected_version=p.status_version, operator_id=999)

    events = ps.list_events(db, p.id)
    names = ps.operator_names(db, events)
    assert names[77] == "亮哥"
    assert 999 not in names


def test_operator_names_handles_empty_timeline(db):
    """没有操作人的事件（脚本/调度写的）不该触发一条 IN () 空查询。"""
    p = ps.create_period(db, "2026-03")
    events = ps.list_events(db, p.id)
    assert ps.operator_names(db, events) == {}


def test_event_log_failure_does_not_break_transition(db, monkeypatch):
    """留痕写挂了不能回滚已完成的状态跃迁——状态已经改完，丢日志好过丢一致性。"""
    p = ps.create_period(db, "2026-03")

    def boom(*args, **kwargs):
        raise RuntimeError("event table gone")

    monkeypatch.setattr(db, "add", boom)
    p = ps.transition(db, p, ps.STATUS_ATTENDANCE, expected_version=0)
    assert p.status == ps.STATUS_ATTENDANCE


def test_event_log_failure_does_not_swallow_caller_data(db, monkeypatch):
    """留痕失败只回滚事件本身，不能连累调用方未提交的数据。

    M2-c/M2-d 的典型形态是「循环 add 一批导入行 → 最后 log_event」。裸 db.rollback()
    会把那批行一起丢掉，而调用方只看到一行「留痕失败」，不知道数据没了。
    """
    p = ps.create_period(db, "2026-03")
    db.add(SalaryPeriod(year_month="2026-09", status=ps.STATUS_DRAFT, status_version=0,
                        natural_days=30, workday_count=22))

    real_add = db.add

    def boom(obj, *args, **kwargs):
        if isinstance(obj, SalaryPeriodEvent):
            raise RuntimeError("event table gone")
        return real_add(obj, *args, **kwargs)

    monkeypatch.setattr(db, "add", boom)
    ps.log_event(db, p, "import", payload={"rows": 68})
    monkeypatch.undo()

    db.commit()
    assert ps.get_by_year_month(db, "2026-09") is not None, "调用方未提交的数据被留痕失败带走了"


def test_serialize_exposes_next_steps(db):
    """next_steps 要带上端点与权限，不能只给状态码。

    confirmed 那一步走 /confirm（salary:admin），其余走 /transition（salary:write）。
    前端照状态码循环渲染按钮的话，锁定按钮会打到 /transition 拿 400——
    这条特例后端知道就该通过契约传出去，而不是让前端各自硬编码一份。
    """
    p = ps.create_period(db, "2026-03")
    data = ps.serialize_period(p)
    assert data["status_label"] == "草稿"
    assert data["writable"] is True
    assert data["next_steps"] == [{
        "status": ps.STATUS_ATTENDANCE, "label": "考勤已同步",
        "endpoint": "transition", "permission": "salary:write",
    }]

    p = advance(db, p, ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED,
                ps.STATUS_CALCULATED, ps.STATUS_REVIEWING)
    steps = {s["status"]: s for s in ps.serialize_period(p)["next_steps"]}
    assert steps[ps.STATUS_CONFIRMED]["endpoint"] == "confirm"
    assert steps[ps.STATUS_CONFIRMED]["permission"] == "salary:admin"
    assert steps[ps.STATUS_CALCULATED]["endpoint"] == "transition"
    # 自环不进步骤条（重复同步由功能按钮触发，不是「下一步」）
    assert ps.STATUS_REVIEWING not in steps

    p = ps.confirm(db, p, expected_version=p.status_version)
    assert ps.serialize_period(p)["next_steps"] == [], "锁定后无下一步，解锁走独立表单"
