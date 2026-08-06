"""社保/公积金导入落库与档案匹配的口径测试（M2-c）。

测的重点不是「能不能存进去」，而是**存错的时候钱会不会错**：

- 参保 ⊋ 发薪：8 个只参保不发薪的人必须落库但不能进减项；
- 身份证撞号：两行一起作废，不许挑一行放行（挑错人扣钱，且总数还对得上）；
- 锁定批次：并发下 SELECT 与 INSERT 之间被人锁定，整批必须回滚干净；
- 覆盖重导：旧行删净，不留幽灵行让合计翻倍。

数据用 openpyxl 现造（复用解析器测试的造表工具），不依赖 HR 原件。
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base
from app.salary import import_persist as ip
from app.salary import period_service as ps
from app.salary import pii
from app.salary.import_service import SalaryImportError
from app.salary.models import (
    SalaryEmployeeProfile,
    SalaryFundImport,
    SalaryInsuranceImport,
    SalaryPeriod,
    SalaryPeriodEvent,
)
from tests.test_salary_import_parser import (
    FUND_HEADER,
    INS_HEADER,
    build,
    fund_row,
    ins_row,
)

_TEST_ENC_KEY = "dGVzdC1zYWxhcnktZW5jLWtleS0zMi1ieXRlcy0hIQ=="
_TEST_HASH_KEY = "test-salary-hash-key"

# 三张身份证：孙/王在档案里，赵没有档案（模拟新入职未建档）
ID_SUN = "370213199103125218"
ID_WANG = "220284199911103423"
ID_ZHAO = "370213198805061234"


@pytest.fixture(autouse=True)
def salary_keys(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_ENCRYPTION_KEY", _TEST_ENC_KEY)
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", _TEST_HASH_KEY)


@pytest.fixture()
def engine_and_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SalaryPeriod.__table__,
            SalaryPeriodEvent.__table__,
            SalaryEmployeeProfile.__table__,
            SalaryInsuranceImport.__table__,
            SalaryFundImport.__table__,
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


def make_profile(db, name, id_card, *, emp_no, payroll_included=1):
    row = SalaryEmployeeProfile(
        emp_no=emp_no,
        name=name,
        id_card_hash=pii.hash_pii(pii.normalize_id_card(id_card)),
        id_card_cipher=pii.encrypt_pii(pii.normalize_id_card(id_card)),
        payroll_included=payroll_included,
        fund_included=1,
        status="active",
    )
    db.add(row)
    db.commit()
    return row


def ins_file(rows, total_col=19):
    return build(INS_HEADER, rows, total_col=total_col)


def fund_file(rows):
    return build(FUND_HEADER, rows, sheet_name="公积金", title="2026年3月公积金", total_col=10)


# ---------------------------------------------------------------------------
# 匹配分类
# ---------------------------------------------------------------------------

def test_matches_by_id_card_hash_not_by_name(db):
    """匹配键是身份证哈希，不是姓名。

    源表姓名与档案姓名对不上是常态（曾用名、录入笔误、同名同姓），按姓名匹配
    要么匹配不上要么匹配错人。这里故意让源表姓名与档案姓名不同，验证仍能匹配。
    """
    profile = make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")

    summary = ip.persist(db, period, "insurance",
                         ins_file([ins_row(1, "孙正華", ID_SUN, 5345)]))

    assert summary["match_counts"][ip.MATCH_MATCHED] == 1
    row = db.query(SalaryInsuranceImport).one()
    assert row.employee_id == profile.id
    assert row.match_status == ip.MATCH_MATCHED
    assert row.name == "孙正華", "落库存的是源表姓名，便于 HR 核对差异"
    assert row.personal_total == Decimal("550.54")


def test_payroll_whitelist_lands_but_stays_out_of_deductions(db):
    """参保 ⊋ 发薪：只参保的人必须落库，但不能进减项（§2.2 的 8 个人）。

    判定只认档案 payroll_included。曹其宽/张传明在社保表里挂着「外贸部」，
    按部门文本判会把他们算进工资表——这正是设计文档点名要避免的做法，
    所以这里给白名单的人一个正常的业务部门文本。
    """
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    make_profile(db, "曹其宽", ID_WANG, emp_no="2", payroll_included=0)
    period = ps.create_period(db, "2026-03")

    summary = ip.persist(db, period, "insurance", ins_file([
        ins_row(1, "孙正华", ID_SUN, 5345),
        ins_row(2, "曹其宽", ID_WANG, 4504, dept="外贸部"),
    ]))

    assert summary["match_counts"] == {
        ip.MATCH_MATCHED: 1, ip.MATCH_NOT_PAYROLL: 1,
        ip.MATCH_UNMATCHED: 0, ip.MATCH_DUPLICATE: 0,
    }
    # 两个合计必须不同：全量对源表的账，matched 才是进工资表的钱
    assert summary["personal_total_matched"] == "550.54"
    assert summary["personal_total_all"] == "1014.45"

    row = db.query(SalaryInsuranceImport).filter_by(match_status=ip.MATCH_NOT_PAYROLL).one()
    assert row.employee_id is not None, "白名单的人也要挂上档案，否则异常面板没法说清是谁"
    assert ip.MATCH_NOT_PAYROLL not in ip.DEDUCTIBLE_STATUSES


def test_unmatched_row_is_kept_with_null_employee(db):
    """匹配不上的行照样落库。删掉它等于让「社保合计比工资表多 1200」永远查不清。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")

    summary = ip.persist(db, period, "insurance", ins_file([
        ins_row(1, "孙正华", ID_SUN, 5345),
        ins_row(2, "赵未建档", ID_ZHAO, 4000),
    ]))

    assert summary["match_counts"][ip.MATCH_UNMATCHED] == 1
    row = db.query(SalaryInsuranceImport).filter_by(match_status=ip.MATCH_UNMATCHED).one()
    assert row.employee_id is None
    assert row.name == "赵未建档"
    assert row.personal_total is not None, "未匹配不代表金额不要——对账要用"


def test_duplicate_id_card_voids_both_rows(db):
    """撞号的两行一起作废，不许挑能匹配上的那一行放行。

    3 月公积金表刘也/姜婷即此（§2.5 错误 3）：其中一行的身份证是从另一个人那里
    抄错来的，所以它**确实能匹配上档案**。先判匹配再判撞号的话，那一行会被
    放行——真正的主人拿到别人的扣款，另一个人凭空消失，而个人合计还对得上，
    对账根本发现不了。所以撞号判定必须排在匹配之前。
    """
    make_profile(db, "刘也", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")

    summary = ip.persist(db, period, "fund", fund_file([
        fund_row(1, "刘也", ID_SUN),
        fund_row(2, "姜婷", ID_SUN),  # 誊抄错误：抄成了刘也的身份证
    ]))

    assert summary["match_counts"][ip.MATCH_DUPLICATE] == 2
    assert summary["match_counts"][ip.MATCH_MATCHED] == 0
    assert summary["personal_total_matched"] == "0.00", "撞号的钱一分都不能进工资表"
    for row in db.query(SalaryFundImport).all():
        assert row.match_status == ip.MATCH_DUPLICATE
        assert row.employee_id is None
    assert any("身份证重复" in w for w in summary["warnings"])


def test_duplicate_beats_unmatched_when_no_profile_exists(db):
    """撞号判定必须排在档案查找**之前**，哪怕这个哈希一条档案都匹配不上。

    先查档案再判撞号的话，这两行会被标成「未匹配档案」。文案差别不是措辞问题，
    是把 HR 引向相反的动作：「未匹配」告诉他去建档，于是他真给姜婷建一条挂着
    刘也身份证的档案——错误从一份月度表格永久固化进了主数据；
    「撞号」告诉他去改源表，那才是错误的出处。
    """
    period = ps.create_period(db, "2026-03")  # 库里一条档案都没有

    summary = ip.persist(db, period, "fund", fund_file([
        fund_row(1, "刘也", ID_ZHAO),
        fund_row(2, "姜婷", ID_ZHAO),
    ]))

    assert summary["match_counts"][ip.MATCH_DUPLICATE] == 2
    assert summary["match_counts"][ip.MATCH_UNMATCHED] == 0


# ---------------------------------------------------------------------------
# 事务与替换语义
# ---------------------------------------------------------------------------

def test_reimport_replaces_previous_rows(db):
    """同批次同类型重导 = 全量替换。留下旧行会让社保合计翻倍。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    make_profile(db, "王天", ID_WANG, emp_no="2")
    period = ps.create_period(db, "2026-03")

    ip.persist(db, period, "insurance", ins_file([
        ins_row(1, "孙正华", ID_SUN, 5345),
        ins_row(2, "王天", ID_WANG, 4504),
    ]))
    summary = ip.persist(db, period, "insurance",
                         ins_file([ins_row(1, "孙正华", ID_SUN, 6000)]))

    assert summary["replaced"] == 2
    rows = db.query(SalaryInsuranceImport).all()
    assert len(rows) == 1, "旧行没删净，合计会翻倍"
    assert rows[0].base_amount == Decimal("6000.00")


def test_insurance_and_fund_do_not_clobber_each_other(db):
    """两类导入互不影响——它们是两张表，重导公积金不该把社保删掉。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")

    ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    ip.persist(db, period, "fund", fund_file([fund_row(1, "孙正华", ID_SUN)]))
    ip.persist(db, period, "fund", fund_file([fund_row(1, "孙正华", ID_SUN, base=3000)]))

    assert db.query(SalaryInsuranceImport).count() == 1
    assert db.query(SalaryFundImport).count() == 1


def test_locked_period_rejects_import(db):
    """锁定后导不进去（快速失败路径）。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    period = ps.transition(db, period, ps.STATUS_ATTENDANCE,
                           expected_version=period.status_version)
    period = ps.transition(db, period, ps.STATUS_IMPORTED,
                           expected_version=period.status_version)
    period = ps.transition(db, period, ps.STATUS_CALCULATED,
                           expected_version=period.status_version)
    period = ps.transition(db, period, ps.STATUS_REVIEWING,
                           expected_version=period.status_version)
    period = ps.confirm(db, period, expected_version=period.status_version)

    with pytest.raises(ps.SalaryPeriodError, match="已锁定"):
        ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    assert db.query(SalaryInsuranceImport).count() == 0


def test_concurrent_lock_rolls_back_the_whole_batch(engine_and_session):
    """并发：A 正在导入，B 中途锁定了批次 —— A 的整批数据必须一行都不留。

    这才是真正的守卫。`assert_writable` 在 A 开工时读的是它手上那份快照，
    那时批次还没锁；导入跑几十秒，窗口大得很。守卫是最后那条
    `UPDATE ... WHERE status != 'confirmed'`：rowcount==0 → rollback，
    前面所有 insert 一起作废。

    注入点选 `_load_profiles`（在删除+插入之前调用），B 在那一刻完成锁定，
    A 后续的写就全落在一个已锁定的批次上。

    **不要靠改 A 手里的 `pa.status` 伪造快照**：A 的 session 开着 autoflush，
    第一次查询就会把这个内存改动刷回库，B 反而读到被 A 改过的状态。让 B 真的
    把批次推到 confirmed 才是这个场景本身。
    """
    _, Session = engine_and_session
    sa_, sb = Session(), Session()
    try:
        make_profile(sa_, "孙正华", ID_SUN, emp_no="1")
        period = ps.create_period(sa_, "2026-03")
        pid = period.id

        # 开工时批次停在「已计算」：可写、不在复核中，导入完全合法。
        pb = ps.get_period(sb, pid)
        for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED):
            pb = ps.transition(sb, pb, s, expected_version=pb.status_version)
        sb.commit()

        pa = ps.get_period(sa_, pid)
        sa_.refresh(pa)
        assert pa.status == ps.STATUS_CALCULATED

        real_load = ip._load_profiles
        fired = []

        def intercept(db_, hashes):
            out = real_load(db_, hashes)
            if not fired:
                fired.append(True)
                # B 在 A 解析完、写库前的这一刻走完复核并锁定
                pb2 = ps.get_period(sb, pid)
                sb.refresh(pb2)
                pb2 = ps.transition(sb, pb2, ps.STATUS_REVIEWING,
                                    expected_version=pb2.status_version)
                ps.confirm(sb, pb2, expected_version=pb2.status_version, operator_id=200)
            return out

        monkey = pytest.MonkeyPatch()
        monkey.setattr(ip, "_load_profiles", intercept)
        try:
            with pytest.raises(ps.SalaryStaleVersion):
                ip.persist(sa_, pa, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
        finally:
            monkey.undo()
        assert fired, "注入点没触发，这个测试没测到东西"

        sa_.rollback()
        assert sa_.query(SalaryInsuranceImport).count() == 0, (
            "批次在导入途中被锁定，但数据还是进去了——已发工资的批次被改了"
        )
    finally:
        sa_.close()
        sb.close()


def test_reviewing_period_refuses_import(db):
    """复核中不许重导：复核者手上的结论会静默失效，必须先明确退回。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED, ps.STATUS_REVIEWING):
        period = ps.transition(db, period, s, expected_version=period.status_version)

    with pytest.raises(SalaryImportError, match="复核"):
        ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    assert db.query(SalaryInsuranceImport).count() == 0


# ---------------------------------------------------------------------------
# 状态推进
# ---------------------------------------------------------------------------

def test_draft_import_keeps_data_without_advancing(db):
    """draft 期导入：数据落库，状态不动。

    财务给社保表常常早于钉钉考勤定版。为了「必须先同步考勤」把人挡在门外
    是流程洁癖，不是数据安全。
    """
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")

    summary = ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))

    assert summary["status"] == ps.STATUS_DRAFT
    assert period.status_version == 0, "状态没变就不该消耗版本号"
    assert db.query(SalaryInsuranceImport).count() == 1


def test_import_advances_from_attendance_to_imported(db):
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    period = ps.transition(db, period, ps.STATUS_ATTENDANCE,
                           expected_version=period.status_version)

    summary = ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    assert summary["status"] == ps.STATUS_IMPORTED
    assert period.status == ps.STATUS_IMPORTED


def test_reimport_after_calculation_rolls_status_back(db):
    """已计算后重新导入 → 退回 imported。不退的话步骤条在骗人（数已经变了）。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED):
        period = ps.transition(db, period, s, expected_version=period.status_version)

    ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    assert period.status == ps.STATUS_IMPORTED


def test_repeat_import_does_not_burn_version(db):
    """imported 状态下重复导入不涨版本号。

    重导是常态操作（HR 拿到修正版文件）。每导一次就让所有打开批次页的客户端
    版本作废，409 变成背景噪音，用户学会「刷新一下再来」，乐观锁的告警价值归零。
    """
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED):
        period = ps.transition(db, period, s, expected_version=period.status_version)
    before = period.status_version

    for _ in range(3):
        ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))
    assert period.status_version == before


# ---------------------------------------------------------------------------
# 留痕与出站
# ---------------------------------------------------------------------------

def test_import_leaves_an_event(db):
    """导入进批次时间线。缺了它，「这批社保数哪来的」在批次页拼不出来。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]),
               filename="26年3月社保.xls", operator_id=7)

    ev = [e for e in ps.list_events(db, period.id) if e.event_type == "import"]
    assert len(ev) == 1
    assert ev[0].created_by == 7
    assert ev[0].payload["filename"] == "26年3月社保.xls"
    assert ev[0].payload["match_counts"][ip.MATCH_MATCHED] == 1


def test_serialize_row_masks_id_card(db):
    """出站只给脱敏串——明文与密文都不进响应，但尾号要给（HR 核对未匹配行的唯一依据）。"""
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    ip.persist(db, period, "insurance", ins_file([ins_row(1, "孙正华", ID_SUN, 5345)]))

    data = ip.list_rows(db, period.id, "insurance")
    item = data["items"][0]
    assert item["id_card_masked"].endswith(ID_SUN[-4:])
    assert ID_SUN not in str(item)
    assert "cipher" not in str(item)
    assert item["sheet"] == "社保"
    assert item["row_no"] == 3, "源表 1-based 行号：标题 1 + 表头 2 → 首个数据行是 3"


def test_list_counts_are_not_limited_by_the_page(db):
    """角标计数走独立 GROUP BY，不受 limit 影响。

    用返回列表统计的话，超过一页时「未匹配 12 人」会显示成「未匹配 1 人」，
    而这个数字正是 HR 判断能不能往下走的依据。
    """
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    ip.persist(db, period, "insurance", ins_file([
        ins_row(1, "孙正华", ID_SUN, 5345),
        ins_row(2, "赵未建档", ID_ZHAO, 4000),
        ins_row(3, "钱未建档", "370213197705061111", 4000),
    ]))

    data = ip.list_rows(db, period.id, "insurance", limit=1)
    assert len(data["items"]) == 1
    assert data["match_counts"][ip.MATCH_UNMATCHED] == 2
    assert data["total"] == 3
    assert data["truncated"] is True


def test_filter_by_match_status(db):
    make_profile(db, "孙正华", ID_SUN, emp_no="1")
    period = ps.create_period(db, "2026-03")
    ip.persist(db, period, "insurance", ins_file([
        ins_row(1, "孙正华", ID_SUN, 5345),
        ins_row(2, "赵未建档", ID_ZHAO, 4000),
    ]))

    data = ip.list_rows(db, period.id, "insurance", match_status=ip.MATCH_UNMATCHED)
    assert [i["name"] for i in data["items"]] == ["赵未建档"]
    assert data["match_counts"][ip.MATCH_MATCHED] == 1, "筛选不该影响角标计数"


def test_unknown_kind_is_rejected(db):
    period = ps.create_period(db, "2026-03")
    with pytest.raises(SalaryImportError):
        ip.persist(db, period, "bonus", b"whatever")
    with pytest.raises(SalaryImportError):
        ip.list_rows(db, period.id, "bonus")


def test_empty_parse_result_is_rejected(db):
    """解析成功但一个人都没有 = 传错了文件（比如传了汇总表）。

    静默导入 0 行会让批次页显示「导入成功」而社保全空，M3 算出来所有人都不扣社保。
    """
    period = ps.create_period(db, "2026-03")
    with pytest.raises(SalaryImportError, match="没有识别出任何人员行"):
        ip.persist(db, period, "insurance", ins_file([]))
