"""考勤三个端点的 HTTP 层契约（M2-d）。

**为什么要单独测路由层**：service 层的测试（test_salary_attendance.py）已经把口径
钉死了，但有两件事只在 HTTP 层存在，service 测试永远碰不到：

1. **「没传」和「传 null」的区别在 Pydantic 手里。** service 用 `if fname in payload`
   判断，路由必须用 `exclude_unset=True` 才能把这个区别传下去。用 `model_dump()`
   默认值的话，HR 改一格迟到 → 未传的 sick_leave_hours 变成 payload 里的 None
   → 刚录的病假被清空 → 少扣缺勤 + 白发 100 元全勤奖。这是本模块最贵的一个 bug，
   而且在 service 测试里**完全测不出来**（service 收到的已经是干净的 dict）。
2. **异常翻译的顺序。** SalaryStaleVersion 是 SalaryPeriodError 的子类，
   except 顺序写反的话 409 会被 400 吞掉，前端就分不出「你没权限/参数错」和
   「别人改过了，刷新重试」——后者是可自愈的，前者不是。

M2-c 的对抗性审查第 8 条正是「导入端点零路由测试」，这里不再重复同一个洞。
"""

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.core.database import Base, get_db
from app.salary import attendance_source
from app.salary import router as salary_router
from app.salary import period_service as ps
from app.salary.models import (
    SalaryAttendance,
    SalaryDeptMapping,
    SalaryEmployeeProfile,
    SalaryGradeTable,
    SalaryPeriod,
    SalaryPeriodEvent,
    SalaryRuleParam,
)
from app.salary.seed import seed_rule_params

_TABLES = [
    SalaryPeriod.__table__,
    SalaryPeriodEvent.__table__,
    SalaryRuleParam.__table__,
    SalaryGradeTable.__table__,
    SalaryDeptMapping.__table__,
    SalaryEmployeeProfile.__table__,
    SalaryAttendance.__table__,
]


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False：TestClient 在工作线程里跑 handler。
    # 这里不需要 test_salary_attendance.py 那套文件库 + 显式 BEGIN 的修正——
    # 那是为了测「回滚」，这里测的是请求/响应契约，单连接反而更简单。
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    session = sessionmaker(bind=engine, autoflush=False)()
    seed_rule_params(session)
    # **flush 不能省。** session 是 autoflush=False，seed 出来的 14 行还在 identity
    # map 里没进库，紧跟的 bulk UPDATE 是直发 SQL——打在空表上，一行都没改到，
    # 生效日仍是 2026-04-01。于是 2026-03 的批次取不到任何参数版本，
    # 以前靠 param_decimal 回落硬编码默认值蒙对，测试全绿而分母是代码里写死的 31。
    session.flush()
    session.query(SalaryRuleParam).update(
        {SalaryRuleParam.effective_from: dt.date(2026, 1, 1)}
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(db, permissions=("salary:write",), roles=()):
    app = FastAPI()
    app.include_router(salary_router.router, prefix="/api/salary")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": list(roles), "permissions": list(permissions),
    }
    return TestClient(app)


def _profile(db, emp_no="A01", name="王京花", userid="U01", included=1):
    p = SalaryEmployeeProfile(
        emp_no=emp_no, name=name, dingtalk_userid=userid,
        payroll_included=included, status="active",
        position="设计师", hire_date=dt.date(2020, 1, 1),
    )
    db.add(p)
    db.commit()
    return p


def _period(db, ym="2026-03"):
    """新建批次即 draft，考勤同步就是从 draft 出发的第一步，不需要先跃迁。"""
    return ps.create_period(db, ym, operator_id=7)


def _confirm(db, period):
    """推到 confirmed（已锁定）。状态名以 period_service 的常量为准，别手写字面量。"""
    for s in (ps.STATUS_ATTENDANCE, ps.STATUS_IMPORTED, ps.STATUS_CALCULATED,
              ps.STATUS_REVIEWING, ps.STATUS_CONFIRMED):
        period = ps.transition(db, period, s, expected_version=period.status_version)
    return period


# ---------------------------------------------------------------------------
# 人工录入：不传 ≠ 清空（本模块最贵的一个 bug）
# ---------------------------------------------------------------------------

def test_partial_update_does_not_wipe_untouched_leave(db):
    """只改迟到次数，已录的病假必须原样保留。

    这就是 schema docstring 里那句「不传 = 不动」的可执行版本。若路由写成
    `payload.model_dump()`（不带 exclude_unset），未传字段会以 None 落进 payload，
    service 的 `if fname in payload` 判定成立 → 病假被设成 None → 实出天数按满勤算、
    100 元全勤奖照发。少扣的钱没人会来投诉，所以这个 bug 能活很久。
    """
    p = _profile(db)
    period = _period(db)
    c = _client(db)

    r = c.put(f"/api/salary/periods/{period.id}/attendance/{p.id}", json={
        "sick_leave_hours": "7.83", "personal_leave_hours": "0",
        "expected_version": period.status_version,
    })
    assert r.status_code == 200, r.text
    db.refresh(period)

    r2 = c.put(f"/api/salary/periods/{period.id}/attendance/{p.id}", json={
        "late_count": 2, "expected_version": period.status_version,
    })
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert data["late_count"] == 2
    assert Decimal(str(data["sick_leave_hours"])) == Decimal("7.83"), (
        "只改了迟到次数，病假却被清空了——缺勤少扣 + 全勤奖白发"
    )


def test_explicit_null_clears_the_field(db):
    """显式传 null 才是清空。HR 录错了要能撤回，否则只能去数据库改。"""
    p = _profile(db)
    period = _period(db)
    c = _client(db)
    c.put(f"/api/salary/periods/{period.id}/attendance/{p.id}", json={
        "sick_leave_hours": "8", "personal_leave_hours": "0",
        "expected_version": period.status_version,
    })
    db.refresh(period)
    r = c.put(f"/api/salary/periods/{period.id}/attendance/{p.id}", json={
        "sick_leave_hours": None, "expected_version": period.status_version,
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sick_leave_hours"] is None
    # 请假小时缺失 → 不能判全勤（与 service 层同一条红线，这里确认端点没绕过它）
    assert r.json()["data"]["full_attendance"] is False


def test_empty_body_is_rejected_not_silently_ok(db):
    """一个字段都没传要报错，不能回 200。

    回 200 的话前端会显示「保存成功」，HR 以为改动生效了——实际什么都没发生，
    而且白烧一个 status_version。
    """
    p = _profile(db)
    period = _period(db)
    r = _client(db).put(f"/api/salary/periods/{period.id}/attendance/{p.id}",
                        json={"expected_version": period.status_version})
    assert r.status_code == 400
    assert "没有需要修改" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 异常翻译：409 不能被 400 吞掉
# ---------------------------------------------------------------------------

def test_stale_version_returns_409_not_400(db):
    """版本过期回 409。

    SalaryStaleVersion 是 SalaryPeriodError 的子类，except 顺序写反就会被 400 吞掉。
    409 对前端是「刷新后重试」（可自愈），400 是「你填错了」（要人改）——
    混成一种，HR 会对着一条正确的录入反复修改参数。
    """
    p = _profile(db)
    period = _period(db)
    r = _client(db).put(f"/api/salary/periods/{period.id}/attendance/{p.id}",
                        json={"late_count": 1,
                              "expected_version": period.status_version + 5})
    assert r.status_code == 409, r.text


def test_confirmed_period_rejects_manual_edit(db):
    """已确认批次不许再改考勤——钱已经发了。"""
    p = _profile(db)
    period = _confirm(db, _period(db))
    r = _client(db).put(f"/api/salary/periods/{period.id}/attendance/{p.id}",
                        json={"late_count": 1,
                              "expected_version": period.status_version})
    assert r.status_code == 400
    assert r.json()["detail"]


def test_unknown_employee_returns_400_with_reason(db):
    _profile(db)
    period = _period(db)
    r = _client(db).put(f"/api/salary/periods/{period.id}/attendance/99999",
                        json={"late_count": 1,
                              "expected_version": period.status_version})
    assert r.status_code == 400
    assert "不存在" in r.json()["detail"]


def test_period_404(db):
    p = _profile(db)
    r = _client(db).put(f"/api/salary/periods/99999/attendance/{p.id}",
                        json={"late_count": 1, "expected_version": 0})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("perm", ["salary:read", "asset:read"])
def test_write_endpoints_reject_read_only(db, perm):
    """考勤直接决定缺勤扣款和全勤奖，read 权限不能改。"""
    p = _profile(db)
    period = _period(db)
    c = _client(db, permissions=(perm,))
    assert c.put(f"/api/salary/periods/{period.id}/attendance/{p.id}",
                 json={"late_count": 1,
                       "expected_version": period.status_version}).status_code == 403
    assert c.post(f"/api/salary/periods/{period.id}/attendance/sync",
                  json={"expected_version": period.status_version}).status_code == 403


def test_list_accepts_any_read_permission(db):
    period = _period(db)
    for perm in ("salary:read", "salary:write", "salary:admin"):
        r = _client(db, permissions=(perm,)).get(
            f"/api/salary/periods/{period.id}/attendance")
        assert r.status_code == 200, f"{perm}: {r.text}"


# ---------------------------------------------------------------------------
# 同步端点
# ---------------------------------------------------------------------------

def test_sync_without_any_bound_userid_fails_loudly(db):
    """名单里没人绑钉钉 → 明确报错，不能回一个「同步了 0 人」的成功。

    回成功的话考勤全表为空，缺勤天数按 0 算，66 个人全额发——
    而界面上显示的是绿色的「同步完成」。
    """
    _profile(db, userid=None)
    period = _period(db)
    r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                         json={"expected_version": period.status_version})
    assert r.status_code == 400
    assert "钉钉" in r.json()["detail"]


def test_sync_maps_source_error_to_502_not_500(db):
    """钉钉那边的问题回 502 + 原文案，不是 500。

    500 在前端只会显示「服务器错误，请联系管理员」——而这里 HR 自己就能处理
    （报表被改名、限流了等一会儿再来）。把可自愈的错误包装成不可自愈的，
    等于凭空制造一张工单。
    """
    _profile(db)
    period = _period(db)
    with patch.object(attendance_source, "fetch_many",
                      side_effect=attendance_source.AttendanceSourceError("报表列不见了")):
        r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                             json={"expected_version": period.status_version})
    assert r.status_code == 502
    assert "报表列不见了" in r.json()["detail"]


def test_sync_only_requests_payroll_included_actives(db):
    """取数名单 = 在职 + 参与发薪 + 已绑 userid。

    多取一个离职的人只是浪费调用，但**把不参与发薪的人取进来**会让他在考勤表里
    出现，后面计算引擎按行遍历时就会给他算一份工资。
    """
    _profile(db, emp_no="A01", name="在职", userid="U01", included=1)
    _profile(db, emp_no="A02", name="不发薪", userid="U02", included=0)
    off = _profile(db, emp_no="A03", name="已离职", userid="U03", included=1)
    off.status = "left"
    db.commit()
    period = _period(db)

    seen = {}

    async def fake(userids, from_date, to_date, **kw):
        seen["ids"] = list(userids)
        seen["range"] = (from_date, to_date)
        return [], []

    with patch.object(attendance_source, "fetch_many", side_effect=fake):
        r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                             json={"expected_version": period.status_version})
    assert r.status_code == 200, r.text
    assert seen["ids"] == ["U01"]
    # 3 月要取满 31 天：取到 30 号的话，31 号那天的迟到/缺勤直接消失
    assert seen["range"] == ("2026-03-01 00:00:00", "2026-03-31 23:59:59")


def test_sync_response_carries_failure_counts(db):
    """响应里必须同时有 source_count 和 synced。

    只报 synced 的话，「钉钉回了 66 人、落库 65 人」跟「一切正常」在界面上
    长得一模一样，而少的那个人当月考勤全空 → 缺勤扣款按 0 算 → 多发钱。
    """
    _profile(db)
    period = _period(db)
    with patch.object(attendance_source, "fetch_many",
                      side_effect=_ok_fetch([])):
        r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                             json={"expected_version": period.status_version})
    assert r.status_code == 200, r.text
    summary = r.json()["data"]["summary"]
    for key in ("source_count", "synced", "failed", "unbound_count",
                "missing_leave_columns"):
        assert key in summary, f"summary 缺 {key}"


def _ok_fetch(results, missing=("年假", "事假", "病假")):
    async def fake(userids, from_date, to_date, **kw):
        return results, list(missing)
    return fake


def test_sync_stale_version_returns_409(db):
    _profile(db)
    period = _period(db)
    with patch.object(attendance_source, "fetch_many", side_effect=_ok_fetch([])):
        r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                             json={"expected_version": period.status_version + 3})
    assert r.status_code == 409, r.text


def test_sync_rejected_on_confirmed_period_before_calling_dingtalk(db):
    """已确认批次要在**发起钉钉调用之前**拒掉。

    不是洁癖：66 人 × 2 片 = 132 次调用跑一分钟，跑完再拒等于白等一分钟，
    还平白吃掉一次限流额度。
    """
    _profile(db)
    period = _confirm(db, _period(db))
    called = {"n": 0}

    async def counting(*a, **kw):
        called["n"] += 1
        return [], []

    with patch.object(attendance_source, "fetch_many", side_effect=counting):
        r = _client(db).post(f"/api/salary/periods/{period.id}/attendance/sync",
                             json={"expected_version": period.status_version})
    assert r.status_code == 400
    assert called["n"] == 0, "已锁定的批次仍然打了钉钉接口"


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

def test_list_surfaces_pending_and_unbound(db):
    """列表要能回答「还差谁」：请假小时没录的、没绑钉钉的。

    这两个数字是 HR 决定「能不能进计算」的唯一依据，藏在明细里等人自己数
    等于没有。
    """
    p = _profile(db)
    _profile(db, emp_no="A09", name="没绑钉钉", userid=None)
    period = _period(db)
    _client(db).put(f"/api/salary/periods/{period.id}/attendance/{p.id}",
                    json={"late_count": 1, "expected_version": period.status_version})

    r = _client(db, permissions=("salary:read",)).get(
        f"/api/salary/periods/{period.id}/attendance")
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["pending_manual_count"] == 1, "只填了迟到，请假小时仍缺，必须计入待办"
    assert [u["name"] for u in data["unbound"]] == ["没绑钉钉"]
    assert data["items"][0]["pending_manual"]
