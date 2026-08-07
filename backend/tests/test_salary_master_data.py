"""薪资主数据的口径测试：种子幂等 / 底薪与大部门推导 / PII 哈希与脱敏。

这些是 M3 计算引擎依赖的地基口径——地基错了，594 个数据点的复算全错。
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.salary import pii, service
from app.salary.models import (
    SalaryChangeLog,
    SalaryDeptMapping,
    SalaryEmployeeProfile,
    SalaryGradeTable,
    SalaryRuleParam,
)
from app.salary.seed import EFFECTIVE_FROM, seed_salary_master_data

# 测试用固定密钥。真钥在 backend/.env，绝不进仓库；这里写死是为了让哈希在
# 测试进程内可复现（同一张卡两次跑出同一摘要），与生产口径无关。
_TEST_ENC_KEY = "dGVzdC1zYWxhcnktZW5jLWtleS0zMi1ieXRlcy0hIQ=="
_TEST_HASH_KEY = "test-salary-hash-key"


@pytest.fixture(autouse=True)
def salary_keys(monkeypatch):
    """给整个测试模块注入 PII 密钥。

    pii._keys() 现在未配置就抛 SalaryKeyNotConfigured（不再回落占位密钥），
    所以任何碰 hash/encrypt 的测试都必须先配上，否则测的是异常路径而不是口径。
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_ENCRYPTION_KEY", _TEST_ENC_KEY)
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", _TEST_HASH_KEY)


@pytest.fixture()
def db():
    """独立的内存 SQLite session。薪资表不含 MySQL 专有类型，可直接建。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            SalaryEmployeeProfile.__table__,
            SalaryDeptMapping.__table__,
            SalaryGradeTable.__table__,
            SalaryRuleParam.__table__,
            SalaryChangeLog.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# 种子
# ---------------------------------------------------------------------------

def test_seed_is_idempotent(db):
    """重复执行不产生重复行——启动期每次都会跑，翻倍就等于职级表报废。"""
    seed_salary_master_data(db)
    counts = (
        db.query(SalaryGradeTable).count(),
        db.query(SalaryRuleParam).count(),
        db.query(SalaryDeptMapping).count(),
    )
    seed_salary_master_data(db)
    seed_salary_master_data(db)
    assert counts == (
        db.query(SalaryGradeTable).count(),
        db.query(SalaryRuleParam).count(),
        db.query(SalaryDeptMapping).count(),
    )


def test_seed_does_not_overwrite_hr_edits(db):
    """HR 改过的参数值不被种子改回默认——种子只保证「有」，不保证「等于默认」。"""
    seed_salary_master_data(db)
    row = db.query(SalaryRuleParam).filter(SalaryRuleParam.param_key == "attendance_bonus").one()
    row.param_value = "150"
    db.commit()

    seed_salary_master_data(db)
    row = db.query(SalaryRuleParam).filter(SalaryRuleParam.param_key == "attendance_bonus").one()
    assert row.param_value == "150"


def test_full_month_days_and_weight_base_are_different(db):
    """B1=31 与 B2=30 是两个不同用途的参数，不是笔误。写死这条防后人「顺手统一」。"""
    seed_salary_master_data(db)
    params = service.load_params(db, on_date=EFFECTIVE_FROM)
    assert params["full_month_days"] == "31"
    assert params["mid_month_weight_base"] == "30"


def test_grade_seed_key_values(db):
    """抽查四条赛道的锚点值，防规则图录入串行。"""
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    assert gm[("resource", "P1")].base_salary == Decimal("3500.00")
    assert gm[("develop", "P1")].base_salary == Decimal("4000.00")
    assert gm[("develop", "P10")].base_salary == Decimal("12000.00")
    assert gm[("manage", "M6")].std_salary == Decimal("10000.00")
    assert gm[("merch", "F6")].base_salary == Decimal("6500.00")
    assert gm[("merch_manage", "M3")].base_salary == Decimal("8000.00")


# ---------------------------------------------------------------------------
# 推导口径
# ---------------------------------------------------------------------------

def test_resolve_base_salary_override_wins(db):
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    p = SalaryEmployeeProfile(
        emp_no="1", name="甲", grade_scheme="resource", grade_code="P1",
        base_salary_override=Decimal("9999.00"),
    )
    assert service.resolve_base_salary(p, gm) == Decimal("9999.00")


def test_resolve_base_salary_manage_uses_std_salary(db):
    """管理岗取 std_salary 列而非 base_salary——管理岗规则图上没有「底薪」这一栏。"""
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    p = SalaryEmployeeProfile(emp_no="2", name="乙", grade_scheme="manage", grade_code="M1")
    assert service.resolve_base_salary(p, gm) == Decimal("5000.00")


def test_resolve_base_salary_returns_none_when_unknown(db):
    """无职级也无手动定薪 → None，不是 0。M3 必须报异常而不是算出 0 元工资。"""
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    p = SalaryEmployeeProfile(emp_no="3", name="丙")
    assert service.resolve_base_salary(p, gm) is None


def test_resolve_base_salary_none_when_grade_code_not_in_table(db):
    """填了职级但表里查无此码 → None，不能静默回落 0 或抛 KeyError。

    这条比「没填职级」更险：HR 手打一个 P99 看着像正常档案，
    若返回 0 就会安静地发出一份 0 元底薪的工资。
    """
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    p = SalaryEmployeeProfile(emp_no="8", name="辛", grade_scheme="resource", grade_code="P99")
    assert service.resolve_base_salary(p, gm) is None


def test_merch_manage_reads_base_salary_not_std_salary(db):
    """跟单管理岗名字里带 manage，但取的是 base_salary 列。

    _STD_SALARY_SCHEMES 只含 "manage" 一个赛道；写成前缀匹配就会把
    merch_manage 一起吃掉、取到 NULL 的 std_salary，全员跟单管理岗底薪变空。
    """
    seed_salary_master_data(db)
    gm = service.load_grade_map(db, on_date=EFFECTIVE_FROM)
    row = gm[("merch_manage", "M3")]
    assert row.std_salary is None or row.base_salary is not None
    p = SalaryEmployeeProfile(emp_no="9", name="壬", grade_scheme="merch_manage", grade_code="M3")
    assert service.resolve_base_salary(p, gm) == row.base_salary == Decimal("8000.00")


def test_resolve_dept_group_override_wins(db):
    """3 月表实证：跟单1部多数归后综部，吕德洋（业务总监）归业务部。"""
    seed_salary_master_data(db)
    dm = service.load_dept_group_map(db)
    normal = SalaryEmployeeProfile(emp_no="4", name="丁", dept_detail="跟单1部")
    director = SalaryEmployeeProfile(
        emp_no="5", name="戊", dept_detail="跟单1部", dept_group_override="业务部"
    )
    assert service.resolve_dept_group(normal, dm) == "后综部"
    assert service.resolve_dept_group(director, dm) == "业务部"


def test_grade_map_respects_effective_window(db):
    """生效日之前查不到当前版本——版本化不是摆设，历史批次要按当时口径算。"""
    seed_salary_master_data(db)
    before = service.load_grade_map(db, on_date=EFFECTIVE_FROM - dt.timedelta(days=1))
    assert ("resource", "P1") not in before


def test_grade_map_later_version_wins_on_same_key(db):
    """同键多版本时晚生效的胜出。

    load_grade_map 按 effective_from 升序遍历、后写覆盖先写。换版当天
    新旧两行同时命中窗口（旧行 effective_to 是闭区间、当天仍生效），
    此时靠的就是这个顺序——排序方向写反了，全员会按旧底薪发一个月。
    """
    seed_salary_master_data(db)
    switch_day = EFFECTIVE_FROM + dt.timedelta(days=90)
    old = db.query(SalaryGradeTable).filter(
        SalaryGradeTable.scheme == "resource",
        SalaryGradeTable.grade_code == "P1",
        SalaryGradeTable.effective_from == EFFECTIVE_FROM,
    ).one()
    old.effective_to = switch_day  # 闭区间：换版当天新旧同时命中
    db.add(SalaryGradeTable(
        scheme="resource", grade_code="P1",
        base_salary=Decimal("3800.00"), effective_from=switch_day,
    ))
    db.commit()

    assert service.load_grade_map(db, on_date=switch_day)[("resource", "P1")].base_salary \
        == Decimal("3800.00")
    # 换版前一天仍是老口径
    assert service.load_grade_map(db, on_date=switch_day - dt.timedelta(days=1))[
        ("resource", "P1")
    ].base_salary == Decimal("3500.00")


def test_grade_map_effective_to_is_inclusive(db):
    """effective_to 是闭区间：当天仍生效，次日才失效。

    写成开区间会让换版当天出现一天的真空——那天所有人查不到底薪，
    resolve_base_salary 返回 None，整批算不出来。
    """
    seed_salary_master_data(db)
    last_day = EFFECTIVE_FROM + dt.timedelta(days=30)
    row = db.query(SalaryGradeTable).filter(
        SalaryGradeTable.scheme == "resource",
        SalaryGradeTable.grade_code == "P1",
    ).one()
    row.effective_to = last_day
    db.commit()

    assert ("resource", "P1") in service.load_grade_map(db, on_date=last_day)
    assert ("resource", "P1") not in service.load_grade_map(
        db, on_date=last_day + dt.timedelta(days=1)
    )


# ---------------------------------------------------------------------------
# 参数读取
# ---------------------------------------------------------------------------

def test_param_decimal_falls_back_on_garbage(db):
    """坏值回落默认并告警，不能抛错让整批次算不出来，也不能静默变 0。"""
    params = {"day_hours": "abc"}
    assert service.param_decimal(params, "day_hours", Decimal("7.83")) == Decimal("7.83")
    assert service.param_decimal({}, "missing", Decimal("1")) == Decimal("1")


def test_param_bool_reads_seed_value(db):
    """B3：年假不破全勤。"""
    seed_salary_master_data(db)
    params = service.load_params(db, on_date=EFFECTIVE_FROM)
    assert service.param_bool(params, "annual_leave_breaks_attendance") is False


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------

def test_hash_is_deterministic_and_cipher_is_not():
    """哈希确定（能做唯一约束与匹配），密文随机（同一卡号两次入库不同）。"""
    card = "6217000000000009734"
    assert pii.hash_pii(card) == pii.hash_pii(card)
    assert pii.encrypt_pii(card) != pii.encrypt_pii(card)
    assert pii.decrypt_pii(pii.encrypt_pii(card)) == card


def test_id_card_normalization_before_hash():
    """末位 x 大小写与空格不应导致同一人算成两个身份证。"""
    assert pii.normalize_id_card(" 37010119900101123x ") == "37010119900101123X"
    a = pii.hash_pii(pii.normalize_id_card("37010119900101123x"))
    b = pii.hash_pii(pii.normalize_id_card("37010119900101123X"))
    assert a == b


def test_bank_card_normalization_strips_non_digits():
    assert pii.normalize_bank_card("'6217 0000 0000 0009734") == "6217000000000009734"


def test_mask_keeps_head_and_tail():
    assert pii.mask_pii("6217000000000009734", 4, 4) == "6217***********9734"
    assert pii.mask_pii("123", 4, 4) == "***"
    assert pii.mask_pii(None) == ""


def test_serialize_profile_never_leaks_plaintext(db):
    """出站响应里不得出现明文或密文——这是合规红线，不是风格问题。"""
    seed_salary_master_data(db)
    card = "6217000000000009734"
    idc = "370101199001011234"
    p = SalaryEmployeeProfile(emp_no="6", name="己", dept_detail="开发部")
    service._apply_pii(p, id_card=idc, bank_card=card)
    db.add(p)
    db.commit()

    data = service.serialize_profile(p, service.load_dept_group_map(db), service.load_grade_map(db))
    blob = repr(data)
    assert card not in blob
    assert idc not in blob
    assert p.bank_card_cipher not in blob
    assert data["bank_card_masked"] == "6217***********9734"
    assert data["dept_group"] == "业务部"


def test_find_by_id_card_matches_via_hash(db):
    """M2 导入靠明文身份证接档案，走 hash 列——密文列 IV 随机，JOIN 不了。"""
    p = SalaryEmployeeProfile(emp_no="7", name="庚")
    service._apply_pii(p, id_card="370101199001011234", bank_card=None)
    db.add(p)
    db.commit()

    assert service.find_by_id_card(db, " 370101199001011234 ").id == p.id
    assert service.find_by_id_card(db, "370101199001019999") is None


def test_missing_keys_raise_instead_of_falling_back(monkeypatch):
    """密钥没配就抛错，不许用占位密钥写库。

    开发机与生产共用同一套 RDS：占位密钥写进去的行，等生产配上真钥后
    既解不开、哈希也全变，唯一约束与 M2 导入匹配会静默失灵。
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", "")
    with pytest.raises(pii.SalaryKeyNotConfigured):
        pii.hash_pii("370101199001011234")


# ---------------------------------------------------------------------------
# 编辑档案：PII 清除契约 + 调薪留痕
# ---------------------------------------------------------------------------

def _profile(db, **kw):
    p = SalaryEmployeeProfile(emp_no=kw.pop("emp_no", "100"), name=kw.pop("name", "测试"), **kw)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_update_pii_absent_keeps_empty_string_clears(db):
    """字段缺席=不动，空串=清除。

    没有「清除」这条路，HR 录错一张银行卡后只能覆盖成另一张、永远清不掉；
    而如果空串被当成「不动」，前端的清除勾选就是个假按钮。
    """
    from app.salary.schemas import ProfileUpdate

    p = _profile(db)
    service._apply_pii(p, id_card="370101199001011234", bank_card="6217000000000009734")
    db.commit()

    # 字段缺席（exclude_unset 过滤掉）→ 两列都不动
    service.update_profile(db, p, ProfileUpdate(name="改名"))
    assert p.bank_card_cipher is not None
    assert p.id_card_hash is not None

    # 显式传空串 → 清除该列的密文与哈希
    service.update_profile(db, p, ProfileUpdate(bank_card=""))
    assert p.bank_card_cipher is None
    assert p.bank_card_hash is None
    assert p.id_card_cipher is not None  # 另一列不受影响


def test_update_logs_pay_affecting_change_only(db):
    """改到发薪金额的列才留痕；改手机号不留。

    留痕是为了回答「这个月为什么多发 500」。把无关列也记上，
    台账会被噪音淹没，M3 读它做月中加权时还得再过滤一遍。
    """
    from app.salary.schemas import ProfileUpdate

    p = _profile(db, emp_no="101", base_salary_override=Decimal("5000.00"))

    service.update_profile(db, p, ProfileUpdate(mobile="13800000000"), operator_user_id=7)
    assert db.query(SalaryChangeLog).count() == 0

    service.update_profile(
        db, p, ProfileUpdate(base_salary_override=Decimal("5500.00")), operator_user_id=7
    )
    log = db.query(SalaryChangeLog).one()
    assert log.employee_id == p.id
    assert log.change_type == "raise"
    assert log.created_by == 7
    # Decimal 不能直接进 JSON 列，_jsonable 转成字符串
    assert log.old_value == {"base_salary_override": "5000.00"}
    assert log.new_value == {"base_salary_override": "5500.00"}


def test_update_grade_change_is_typed_as_grade(db):
    """调级与调薪分开记 change_type——月中加权的口径不同，混成一类 M3 无从分辨。"""
    from app.salary.schemas import ProfileUpdate

    p = _profile(db, emp_no="102", grade_scheme="resource", grade_code="P1")
    service.update_profile(db, p, ProfileUpdate(grade_code="P2"), operator_user_id=7)
    assert db.query(SalaryChangeLog).one().change_type == "grade"


def test_emp_no_normalization_kills_3_vs_003():
    """反导入实证的错误 1：吕德洋工号 3、刘美美 003 是两个人被写成同号族。"""
    from app.salary.schemas import ProfileCreate

    a = ProfileCreate(emp_no="003", name="甲")
    b = ProfileCreate(emp_no=" 3 ", name="乙")
    assert a.emp_no == b.emp_no == "3"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_dingtalk_userid_becomes_null_not_empty_string(blank):
    """**096 唯一索引能不能用，全看这个归一。**

    UNIQUE 放过任意多个 NULL，但把多个 `''` 当成重复。不归一的话「第二个不打卡
    的员工」建不出来，HR 吃一个 500——而 66 人里必然有多个不打卡的人。
    Create 和 Update 两条路径都要测：Update 更常踩（HR 清空甲再清空乙）。
    """
    from app.salary.schemas import ProfileCreate, ProfileUpdate

    assert ProfileCreate(emp_no="1", name="甲", dingtalk_userid=blank).dingtalk_userid is None
    assert ProfileUpdate(dingtalk_userid=blank).dingtalk_userid is None


def test_real_dingtalk_userid_is_kept_but_trimmed():
    """归一只砍空白，不能顺手把真 userid 也弄没了。"""
    from app.salary.schemas import ProfileCreate, ProfileUpdate

    assert ProfileCreate(emp_no="1", name="甲", dingtalk_userid=" U01 ").dingtalk_userid == "U01"
    assert ProfileUpdate(dingtalk_userid=" U01 ").dingtalk_userid == "U01"


def test_two_profiles_without_dingtalk_can_coexist(db):
    """归一的真实后果：两个不绑钉钉的档案必须能同时存在（096 之后）。

    `exclude_unset` 那套在这里没用——service 是 `model_dump()` 直接 setattr，
    schema 归一是唯一的门。
    """
    from app.salary.schemas import ProfileCreate

    service.create_profile(db, ProfileCreate(emp_no="1", name="甲", dingtalk_userid=""))
    service.create_profile(db, ProfileCreate(emp_no="2", name="乙", dingtalk_userid=""))
    db.commit()

    rows = db.query(SalaryEmployeeProfile).all()
    assert len(rows) == 2
    assert all(r.dingtalk_userid is None for r in rows), "存成空串，第二个人就建不出来了"
