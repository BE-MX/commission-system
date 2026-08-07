"""薪资 M1 路由层契约：权限爆炸半径 / 409 翻译不泄 PII / 信封 / 生效版本过滤。

管钱模块按 DoD 第 2 条必须有测试。这里测的四件事各自对应一个真实事故形态：
- 权限：职级表改一行动 66 人的钱，不能与「改一个人档案」同权
- 409：入库失败的异常文本里带着身份证密文与 HMAC 摘要，不能回给前端或落日志
- 信封：前端拦截器按 {code,message,data} 解包，形状错了整页空白
- include_history：档案页职级下拉按 grade_code 做 key，混进历史版本会重键
"""

import ast
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.salary import router as salary_router
from app.salary import service
from app.salary.models import (
    SalaryChangeLog,
    SalaryDeptMapping,
    SalaryEmployeeProfile,
    SalaryGradeTable,
    SalaryRuleParam,
)
from app.salary.seed import EFFECTIVE_FROM, seed_salary_master_data

_TEST_ENC_KEY = "dGVzdC1zYWxhcnktZW5jLWtleS0zMi1ieXRlcy0hIQ=="
_TEST_HASH_KEY = "test-salary-hash-key"


@pytest.fixture(autouse=True)
def salary_keys(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ARK_SALARY_ENCRYPTION_KEY", _TEST_ENC_KEY)
    monkeypatch.setattr(settings, "ARK_SALARY_HASH_KEY", _TEST_HASH_KEY)


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False：TestClient 在工作线程里跑 handler，
    # 默认的 SQLite 连接不跨线程用（同 conftest 的 engine fixture）。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    seed_salary_master_data(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(db, permissions, roles=()):
    app = FastAPI()
    app.include_router(salary_router.router, prefix="/api/salary")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": list(roles), "permissions": list(permissions),
    }
    return TestClient(app)


# ---------------------------------------------------------------------------
# 权限：按爆炸半径分权
# ---------------------------------------------------------------------------

# (method, path, body, 需要的权限)。write 能改档案，但改不了全员发薪口径。
_ADMIN_ONLY = [
    ("post", "/api/salary/grades", {
        "scheme": "resource", "grade_code": "PX", "effective_from": "2026-04-01",
    }),
    ("put", "/api/salary/params/1", {"param_value": "999"}),
]


@pytest.mark.parametrize("method,path,body", _ADMIN_ONLY)
def test_pay_caliber_endpoints_reject_salary_write(db, method, path, body):
    """salary:write 改不了职级表与规则参数——这两处改一行动全员的钱。"""
    resp = getattr(_client(db, ["salary:write"]), method)(path, json=body)
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path,body", _ADMIN_ONLY)
def test_pay_caliber_endpoints_accept_salary_admin(db, method, path, body):
    resp = getattr(_client(db, ["salary:admin"]), method)(path, json=body)
    assert resp.status_code == 200, resp.text


def test_read_endpoints_accept_any_of_three_read_perms(db):
    for perm in ("salary:read", "salary:write", "salary:admin"):
        assert _client(db, [perm]).get("/api/salary/profiles").status_code == 200


def test_read_endpoints_reject_unrelated_permission(db):
    assert _client(db, ["invoice:read"]).get("/api/salary/profiles").status_code == 403


def test_super_admin_bypasses(db):
    """super_admin 自动绕过是全站约定，薪资不做例外。"""
    assert _client(db, [], roles=["super_admin"]).get("/api/salary/grades").status_code == 200


def test_every_route_declares_a_permission():
    """静态兜底：新加端点忘了挂权限 Depends 时立刻红。

    薪资模块没有机器对机器端点，所以这里不留白名单——一个都不许漏。
    """
    source = (Path(__file__).parents[1] / "app/salary/router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
            for d in node.decorator_list
        ):
            continue
        guards = [
            c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id in ("require_permission", "require_any_permission")
        ]
        assert len(guards) == 1, f"{node.name} 缺少权限 Depends 或挂了多个"


# ---------------------------------------------------------------------------
# 409 翻译：给人话，且不把 PII 带出去
# ---------------------------------------------------------------------------

def test_duplicate_emp_no_returns_409_with_human_message(db):
    client = _client(db, ["salary:write"])
    body = {"emp_no": "003", "name": "甲"}
    assert client.post("/api/salary/profiles", json=body).status_code == 200
    # 003 与 3 归一成同一个工号，第二条必冲突
    resp = client.post("/api/salary/profiles", json={"emp_no": "3", "name": "乙"})
    assert resp.status_code == 409
    assert "工号已存在" in resp.json()["detail"]


def test_integrity_message_never_carries_sql_parameters():
    """把 IntegrityError 原文回给前端 = 把身份证密文和 HMAC 摘要一起回出去。

    SQLAlchemy 的 str(exc) 会展开 [SQL: INSERT ...] [parameters: (...)]，
    参数里就是 PII 列的值。身份证号空间小，摘要一旦外泄配合密钥即可反查。
    """
    leaky = (
        "(1062, \"Duplicate entry 'abc' for key 'uk_salary_profile_id_card'\")\n"
        "[SQL: INSERT INTO ark_salary_employee_profile ...]\n"
        "[parameters: ('370101199001011234', 'deadbeefhash', 'Y2lwaGVy')]"
    )
    exc = IntegrityError("stmt", {}, Exception(leaky))
    message, token = salary_router._integrity_context(exc)

    assert token == "uk_salary_profile_id_card"
    assert "身份证已被其他员工档案占用" == message
    for secret in ("370101199001011234", "deadbeefhash", "Y2lwaGVy", "parameters", "INSERT"):
        assert secret not in message
        assert secret not in token


def test_unknown_constraint_falls_back_without_leaking():
    exc = IntegrityError("stmt", {}, Exception("[parameters: ('370101199001011234',)]"))
    message, token = salary_router._integrity_context(exc)
    assert token == "unknown_constraint"
    assert "370101199001011234" not in message


# ---------------------------------------------------------------------------
# 信封与出站形状
# ---------------------------------------------------------------------------

def test_list_profiles_envelope_and_no_plaintext(db):
    client = _client(db, ["salary:write"])
    client.post("/api/salary/profiles", json={
        "emp_no": "10", "name": "丙", "dept_detail": "跟单1部",
        "id_card": "370101199001011234", "bank_card": "6217000000000009734",
    })
    payload = client.get("/api/salary/profiles").json()
    assert payload["code"] == 200
    assert set(payload["data"]) >= {"items", "total", "page", "page_size"}

    row = payload["data"]["items"][0]
    assert row["bank_card_masked"] == "6217***********9734"
    assert row["dept_group"] == "后综部"  # 映射表推导生效
    blob = repr(payload)
    assert "370101199001011234" not in blob
    assert "6217000000000009734" not in blob


def test_grades_returns_schemes_and_items(db):
    data = _client(db, ["salary:read"]).get("/api/salary/grades").json()["data"]
    assert {s["code"] for s in data["schemes"]} >= {"resource", "develop", "manage", "merch"}
    assert data["items"]


# ---------------------------------------------------------------------------
# include_history：下拉要唯一，规则页要历史
# ---------------------------------------------------------------------------

def test_grades_default_hides_future_versions(db):
    """默认只出当天生效的版本。

    HR 建一个未来生效的新 P1 后，档案页职级下拉若把两行都拿到，
    同一个 P1 出现两次且 key 重复，HR 无从判断该选哪个。
    """
    future = dt.date.today() + dt.timedelta(days=30)
    db.add(SalaryGradeTable(
        scheme="resource", grade_code="P1",
        base_salary=Decimal("3800.00"), effective_from=future,
    ))
    db.commit()
    client = _client(db, ["salary:read"])

    default_p1 = [
        r for r in client.get("/api/salary/grades?scheme=resource").json()["data"]["items"]
        if r["grade_code"] == "P1"
    ]
    assert len(default_p1) == 1
    assert default_p1[0]["effective_from"] == EFFECTIVE_FROM.isoformat()

    history_p1 = [
        r for r in client.get(
            "/api/salary/grades?scheme=resource&include_history=1"
        ).json()["data"]["items"]
        if r["grade_code"] == "P1"
    ]
    assert len(history_p1) == 2


# ---------------------------------------------------------------------------
# 参数改动留痕
# ---------------------------------------------------------------------------

def test_param_update_persists_and_is_idempotent_on_same_value(db, caplog):
    """改值落库；值没变时不刷告警日志（否则每次打开配置页都在报警）。"""
    row = db.query(SalaryRuleParam).filter(
        SalaryRuleParam.param_key == "attendance_bonus"
    ).one()
    client = _client(db, ["salary:admin"])

    with caplog.at_level("WARNING", logger="commission"):
        assert client.put(
            f"/api/salary/params/{row.id}", json={"param_value": "150"}
        ).json()["data"]["param_value"] == "150"
    assert any("attendance_bonus" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level("WARNING", logger="commission"):
        client.put(f"/api/salary/params/{row.id}", json={"param_value": "150"})
    assert not [r for r in caplog.records if "attendance_bonus" in r.message]


def test_update_param_404_on_missing(db):
    assert _client(db, ["salary:admin"]).put(
        "/api/salary/params/999999", json={"param_value": "1"}
    ).status_code == 404


def test_profile_update_writes_change_log_with_operator(db):
    """档案改到金额列 → 台账留痕并记下操作人（JWT sub）。"""
    client = _client(db, ["salary:write"])
    created = client.post("/api/salary/profiles", json={
        "emp_no": "11", "name": "丁", "base_salary_override": "5000.00",
    }).json()["data"]

    client.put(f"/api/salary/profiles/{created['id']}", json={"base_salary_override": "5500.00"})
    log = db.query(SalaryChangeLog).one()
    assert log.created_by == 7  # 覆盖里的 sub="7"
    assert log.change_type == "raise"


def test_profile_404(db):
    assert _client(db, ["salary:read"]).get("/api/salary/profiles/999999").status_code == 404
