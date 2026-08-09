"""请假自动拉取的口径测试（2026-08-07 权限开通后接入）。

两层：
- 取数层（attendance_source）：类型映射解析、分批/分页/批次隔离、跨月折算、
  单位换算（percent_day↔percent_hour）、未知类型不进扣款——全部 mock client 测；
- 落库层（attendance_service）：同步只写「归同步管」的行、人工改过的让路、
  重同步刷新、「本月无请假」填 0——这是把「HR 还没录」和「确认没请假」分开的关键。
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base
from app.dingtalk.client import DingTalkError
from app.salary import attendance_service as ats
from app.salary import attendance_source as asrc
from app.salary import period_service as ps
from app.salary import pii
from app.salary.models import (
    SalaryAttendance,
    SalaryEmployeeProfile,
    SalaryPeriod,
    SalaryPeriodEvent,
    SalaryRuleParam,
)

D = Decimal

_TEST_ENC_KEY = "dGVzdC1zYWxhcnktZW5jLWtleS0zMi1ieXRlcy0hIQ=="
_TEST_HASH_KEY = "test-salary-hash-key"

# 2026-03 的毫秒窗口：3/1 00:00:00 → 3/31 23:59:59.999（本地时区无关，取数层只看相对重叠）
FROM_MS = int(dt.datetime(2026, 3, 1).timestamp() * 1000)
TO_MS = int(dt.datetime(2026, 3, 31, 23, 59, 59).timestamp() * 1000) + 999

TYPE_MAP = {
    "code-personal": {"name": "事假", "unit": "percent_hour"},
    "code-sick": {"name": "病假", "unit": "percent_day"},
    "code-annual": {"name": "年假", "unit": "percent_day"},
    "code-comp": {"name": "调休", "unit": "percent_hour"},
}


class FakeClient:
    """按端点路由的假钉钉 client。值可以是 dict、callable(json_data)->dict、异常。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    async def post(self, endpoint, json_data=None, params=None):
        self.calls.append((endpoint, json_data or {}))
        r = self.routes[endpoint]
        if isinstance(r, Exception):
            raise r
        return r(json_data) if callable(r) else r


def leave_rec(userid, code, start, end, duration_percent, unit):
    return {
        "userid": userid, "leave_code": code,
        "start_time": start, "end_time": end,
        "duration_percent": duration_percent, "duration_unit": unit,
    }


def ms(y, m, d, h=0, minute=0):
    return int(dt.datetime(y, m, d, h, minute).timestamp() * 1000)


# ---------------------------------------------------------------------------
# 取数层
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leave_types_parse_and_permission_degrade():
    client = FakeClient({
        "topapi/attendance/vacation/type/list": {
            "result": [{"leave_code": "c1", "leave_name": "事假", "unit": "percent_hour"}]
        },
    })
    assert await asrc.fetch_leave_types(client) == {
        "c1": {"name": "事假", "unit": "percent_hour"}}

    denied = FakeClient({
        "topapi/attendance/vacation/type/list":
            DingTalkError(88, "subcode=60011 应用尚未开通所需的权限"),
    })
    assert await asrc.fetch_leave_types(denied) == {}, "权限未开必须降级成 {} 而不是炸掉同步"


@pytest.mark.asyncio
async def test_leave_records_batching_pagination_and_isolation():
    userids = [f"U{i:02d}" for i in range(21)]  # 21 人 → 2 批

    def route(payload):
        uids = payload["userid_list"].split(",")
        if uids[0] == "U20":
            raise DingTalkError(-1, "系统繁忙")  # 第二批整批失败
        offset = payload["offset"]
        if offset == 0:
            return {"result": {
                "has_more": True,
                "leave_status": [leave_rec(uids[0], "code-personal",
                                           ms(2026, 3, 6, 9), ms(2026, 3, 6, 11, 30),
                                           250, "percent_hour")],
            }}
        return {"result": {"has_more": False, "leave_status": []}}

    client = FakeClient({"topapi/attendance/getleavestatus": route})
    out, failed = await asrc.fetch_leave_records(userids, FROM_MS, TO_MS, client=client)

    assert len([c for c in client.calls
                if c[0] == "topapi/attendance/getleavestatus"]) == 3  # 批1两页 + 批2一次失败
    assert out[userids[0]][0]["duration_percent"] == 250
    assert out["U19"] == [], "没记录的人也要在结果里（空 list = 确认无请假）"
    assert failed == ["U20"], "第二批失败只丢这一批"


@pytest.mark.asyncio
async def test_annual_quota_parse_and_bad_shape():
    ok = FakeClient({"topapi/attendance/vacation/quota/list": {
        "result": {"leave_quota": {"remain_quota": 550}}}})
    assert await asrc.fetch_annual_quota("U1", "code-annual", client=ok) == D("5.5")

    weird = FakeClient({"topapi/attendance/vacation/quota/list": {"result": {}}})
    assert await asrc.fetch_annual_quota("U1", "code-annual", client=weird) is None

    denied = FakeClient({"topapi/attendance/vacation/quota/list":
                         DingTalkError(88, "60011")})
    assert await asrc.fetch_annual_quota("U1", "code-annual", client=denied) is None


# ---------------------------------------------------------------------------
# 拆分与折算（纯函数）
# ---------------------------------------------------------------------------

def test_split_leave_mouliangliang_calibration():
    """牟亮亮 3/6 事假 2.5h（percent_hour 250）→ 事假 2.50 小时，与工资表 0.32 天吻合。"""
    recs = [leave_rec("U1", "code-personal", ms(2026, 3, 6, 9), ms(2026, 3, 6, 11, 30),
                      250, "percent_hour")]
    out = asrc.split_leave(recs, TYPE_MAP, FROM_MS, TO_MS, D("7.83"))
    assert out["personal_hours"] == D("2.50")
    assert out["sick_hours"] == D("0.00")
    assert out["annual_days"] == D("0.00")
    assert out["unknown"] == []


def test_split_leave_day_unit_converts_via_day_hours():
    """percent_day 的病假 100 = 1 天 → 7.83 小时；年假 550 = 5.5 天（王京花口径）。"""
    recs = [
        leave_rec("U1", "code-sick", ms(2026, 3, 10, 9), ms(2026, 3, 11, 18), 100, "percent_day"),
        leave_rec("U1", "code-annual", ms(2026, 3, 16, 9), ms(2026, 3, 22, 18), 550, "percent_day"),
    ]
    out = asrc.split_leave(recs, TYPE_MAP, FROM_MS, TO_MS, D("7.83"))
    assert out["sick_hours"] == D("7.83")
    assert out["annual_days"] == D("5.5")


def test_split_leave_clamps_cross_month_records():
    """3/30–4/2 的 4 天年假，3 月只能算 2/4——duration 是整条的，不切就多算。"""
    recs = [leave_rec("U1", "code-annual",
                      ms(2026, 3, 30, 9), ms(2026, 4, 2, 18), 400, "percent_day")]
    out = asrc.split_leave(recs, TYPE_MAP, FROM_MS, TO_MS, D("7.83"))
    assert D("1.9") < out["annual_days"] < D("2.1"), out["annual_days"]


def test_split_leave_unknown_type_never_enters_deductions():
    """调休不扣钱：进 unknown 清单报出来，绝不塞进事假/病假。"""
    recs = [leave_rec("U1", "code-comp", ms(2026, 3, 6, 9), ms(2026, 3, 6, 18),
                      783, "percent_hour")]
    out = asrc.split_leave(recs, TYPE_MAP, FROM_MS, TO_MS, D("7.83"))
    assert out["personal_hours"] == D("0.00")
    assert out["sick_hours"] == D("0.00")
    assert out["unknown"] == [{"leave_name": "调休", "hours": "7.83"}]


# ---------------------------------------------------------------------------
# 落库层（同步写请假 / 人工让路）
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def salary_keys(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_ENCRYPTION_KEY", _TEST_ENC_KEY)
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", _TEST_HASH_KEY)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        SalaryPeriod.__table__, SalaryPeriodEvent.__table__,
        SalaryEmployeeProfile.__table__, SalaryAttendance.__table__,
        SalaryRuleParam.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


PARAMS = {
    "day_hours": "7.83", "full_month_days": "31", "attendance_sick_hours_max": "8",
    "annual_leave_breaks_attendance": "false", "sick_pay_deduct_ratio": "0.30",
}


def _profile(db, name, emp_no, userid):
    plain = f"37021319910312{emp_no:0>4}"
    p = SalaryEmployeeProfile(
        emp_no=emp_no, name=name, id_card_hash=pii.hash_pii(plain),
        id_card_cipher=pii.encrypt_pii(plain), payroll_included=1, fund_included=1,
        status="active", dingtalk_userid=userid,
    )
    db.add(p)
    db.commit()
    return p


def _period(db):
    p = ps.create_period(db, "2026-03")
    p.param_snapshot = dict(PARAMS)
    db.commit()
    return p


def _person(userid, **values):
    return asrc.PersonAttendance(
        userid=userid, values={k: D(str(v)) for k, v in values.items()})


def _leave(personal="0", sick="0", annual="0", remain=None):
    out = {"personal_hours": D(personal), "sick_hours": D(sick),
           "annual_days": D(annual), "unknown": []}
    if remain is not None:
        out["annual_remain"] = D(remain)
    return out


def _sync(db, period, fetched):
    return ats.sync_from_dingtalk(
        db, period, fetched, expected_version=period.status_version)


def test_sync_fills_leave_and_recomputes_actual_days(db):
    """同步拉到事假 2.5h：落库 + 实出按 7.83 折算（31 − 0.32 = 30.68，牟亮亮校准）。"""
    period = _period(db)
    p = _profile(db, "牟亮亮", "320", "U320")
    summary = _sync(db, period, {
        "results": [_person("U320", late_count=0)],
        "leave": {"U320": _leave(personal="2.5", remain="5.5")},
        "leave_meta": {},
    })
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.personal_leave_hours == D("2.50")
    assert row.actual_days == D("30.68")
    assert row.leave_source == "dingtalk"
    assert row.annual_leave_remain == D("5.5")
    assert row.full_attendance == 0  # 有事假，无全勤
    assert summary["leave_filled"] == 1


def test_zero_leave_records_mean_confirmed_no_leave(db):
    """钉钉本月无记录 = 确认没请假：填 0、判全勤——这正是自动拉取的核心收益，
    把「HR 还没录」和「确认没请假」两种状态彻底分开。"""
    period = _period(db)
    p = _profile(db, "孙正华", "9", "U9")
    _sync(db, period, {
        "results": [_person("U9", late_count=0)],
        "leave": {"U9": _leave()},  # 空记录拆分出的全零
        "leave_meta": {},
    })
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.personal_leave_hours == D("0.00")
    assert row.sick_leave_hours == D("0.00")
    assert row.full_attendance == 1
    assert row.actual_days == D("31.00")


def test_manual_leave_is_never_overwritten(db):
    """人工改过的请假（leave_source=manual），同步让路——红线 1。"""
    period = _period(db)
    p = _profile(db, "测试", "1", "U1")
    ats.manual_upsert(db, period, p.id, {"sick_leave_hours": D("16")})
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.leave_source == "manual"

    summary = _sync(db, period, {
        "results": [_person("U1", late_count=0)],
        "leave": {"U1": _leave(sick="0")},  # 钉钉说没病假，也不能盖人工的 16h
        "leave_meta": {},
    })
    db.refresh(row)
    assert row.sick_leave_hours == D("16")
    assert summary["leave_kept_manual"] == 1


def test_resync_refreshes_dingtalk_owned_leave(db):
    """归同步管的行，重同步要刷新（钉钉侧假单改了是常态）。"""
    period = _period(db)
    p = _profile(db, "测试", "1", "U1")
    _sync(db, period, {"results": [_person("U1")],
                       "leave": {"U1": _leave(personal="2.5")}, "leave_meta": {}})
    _sync(db, period, {"results": [_person("U1")],
                       "leave": {"U1": _leave(personal="8")}, "leave_meta": {}})
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.personal_leave_hours == D("8.00")


def test_degraded_leave_pipeline_keeps_null_pending(db):
    """降级（没有 leave 数据）：请假列保持 NULL=「还没录」，pending 异常照报。"""
    period = _period(db)
    p = _profile(db, "测试", "1", "U1")
    summary = _sync(db, period, {"results": [_person("U1")],
                                 "leave_meta": {"degraded": "权限未开通"}})
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.personal_leave_hours is None
    assert row.leave_source is None
    assert summary["leave_degraded"] == "权限未开通"


def test_manual_upsert_marks_leave_source_only_for_leave_fields(db):
    """改迟到次数不算接管请假；动请假四列中的任何一个才算。"""
    period = _period(db)
    p = _profile(db, "测试", "1", "U1")
    ats.manual_upsert(db, period, p.id, {"late_count": 2})
    row = db.query(SalaryAttendance).filter_by(employee_id=p.id).one()
    assert row.leave_source is None
    ats.manual_upsert(db, period, p.id, {"personal_leave_hours": D("4")})
    db.refresh(row)
    assert row.leave_source == "manual"
