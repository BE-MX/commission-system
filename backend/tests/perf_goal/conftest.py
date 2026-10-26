"""绩效目标测试公共 fixtures：用户 + OKKI 绑定 + sys_dict 战队 + 订单 + 目标批次。

战队布局：
- 101 阿尔法队：队长 users[1]（毕晓珍/U1），成员 users[2]（代晴玉/U2）
- 102 贝塔队：队长 users[3]（尹德魁/U3），成员 users[4]（罗馨瑜/U4，无目标=未 listed）
- users[5]（张心茹/U5）：已绑定未入队（未编组）
- users[0]：管理员（supervisor 角色，不在名单）
"""
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user
from app.auth.models import ArkRole, ArkUser, ArkUserExternalBinding, ArkUserRole
from app.core.database import get_db
from app.perf_goal.models import PerfGoal, PerfGoalPeriod
from app.perf_goal.router import router
from app.system.models import SysDict

NAMES = ["管理员", "毕晓珍", "代晴玉", "尹德魁", "罗馨瑜", "张心茹"]
TODAY = date(2026, 6, 30)


@pytest.fixture
def perf(db, monkeypatch):
    monkeypatch.setattr("app.perf_goal.trend.beijing_today", lambda: TODAY)
    users = [ArkUser(username=f"perf-{i}", password_hash="test-only", real_name=name)
             for i, name in enumerate(NAMES)]
    users[1].dingtalk_id = "dt-u1"
    users[1].phone = "13800000001"
    db.add_all(users)
    db.flush()
    supervisor = ArkRole(name="supervisor", label="管理层")
    db.add(supervisor)
    db.flush()
    db.add(ArkUserRole(user_id=users[0].id, role_id=supervisor.id))
    for index in range(1, 6):
        db.add(ArkUserExternalBinding(ark_user_id=users[index].id, provider="okki",
                                      external_account_id=f"9000{index}", is_primary=True,
                                      binding_status="active"))
    now = TODAY
    db.add_all([
        SysDict(type="dingtalk_gmv_team", code="101", label="阿尔法队", remark="90001",
                sort=0, is_active=True, created_at=now, updated_at=now),
        SysDict(type="dingtalk_gmv_team", code="102", label="贝塔队", remark="90003",
                sort=1, is_active=True, created_at=now, updated_at=now),
    ])
    for sort, (okki_id, name, department_id) in enumerate([
            ("90001", "毕晓珍", 101), ("90002", "代晴玉", 101),
            ("90003", "尹德魁", 102), ("90004", "罗馨瑜", 102)]):
        db.add(SysDict(type="dingtalk_gmv_member", code=okki_id, label=name,
                       remark=json.dumps({"department_id": department_id}, ensure_ascii=False),
                       sort=sort, is_active=True, created_at=now, updated_at=now))
    period = PerfGoalPeriod(year=2026, name="2026 年度目标", status="active",
                            published_by=users[0].id, published_at=now,
                            created_by=users[0].id, created_at=now, updated_at=now)
    db.add(period)
    db.flush()
    for user_id, metric, value in [
            (users[1].id, "gmv", "3000"), (users[1].id, "new_sign", "10"),
            (users[2].id, "gmv", "2000"),
            (users[3].id, "gmv", "4000")]:
        db.add(PerfGoal(period_id=period.id, user_id=user_id, metric=metric,
                        granularity="year", quarter=None, month=None,
                        target_value=value, updated_by=users[0].id, updated_at=now))
    conn = db.get_bind().raw_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.customer_info (company_id, company_name, country_name)
        VALUES ('5001','客户一','美国'), ('5002','客户二','英国'), ('5003','客户三','德国'),
               ('5004','客户四','法国'), ('5005','客户五','日本')
    """)
    cur.executemany("""
        INSERT OR IGNORE INTO lsordertest.okki_orders
        (order_id, order_no, name, company_id, amount_usd, user_id, custom_fields,
         account_date, trail, status, status_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [
        ("1001", "NO1", "假发-A", "5001", 1000.00, "90001", '{"22595163468": "是"}', "2026-01-10", "公司", "13972831656", None),
        ("1002", "NO2", "假发-B", "5001", 500.00, "90001", '{"22595163468": "否"}', "2026-02-15", "公司", "13972831656", None),
        ("1003", "NO3", "假发-C", "5002", 800.00, "90002", '{"22595163468": "是"}', "2026-01-20", "公司", "13972831656", None),
        ("1004", "NO4", "假发-D", "5003", 300.00, "90002", "{}", "2026-03-05", "公司", "13972831654", "已结清"),
        ("1005", "NO5", "假发-E", "5004", 2000.00, "90003", '{"22595163468": "否"}', "2026-01-25", "公司", "13972831656", None),
        ("1006", "NO6", "假发-F", "5005", 400.00, "90004", '{"22595163468": "是"}', "2026-02-10", "公司", "13972831656", None),
        ("1007", "NO7", "取消单", "5001", 999.00, "90001", "{}", "2026-01-11", "公司", "cancelled", None),
        ("1008", "NO8", "个人单", "5001", 999.00, "90001", "{}", "2026-01-12", "个人", "13972831656", None),
    ])
    conn.commit()
    conn.close()
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/perf-goals")
    app.dependency_overrides[get_db] = lambda: db
    identity = {"sub": str(users[0].id), "roles": ["super_admin"]}
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app)
    yield SimpleNamespace(db=db, client=client, identity=identity, users=users,
                          period=period, url="/api/perf-goals")
    client.close()


def become(s, index, permissions=("perf_goal:read",), roles=()):
    s.identity.clear()
    s.identity.update(sub=str(s.users[index].id), roles=list(roles), permissions=list(permissions))
