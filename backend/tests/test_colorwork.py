"""colorwork 集成模块测试：SSO 签发门禁、视图清单、okki 库存状态计算口径。"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.colorwork import service
from app.colorwork.constants import TEMPLATE_MATCH, VIEW_PERMISSIONS
from app.colorwork.service import (
    allowed_views_for,
    compute_template_statuses,
    issue_sso_token,
)
from app.core.database import get_db


@pytest.fixture
def colorwork_db(db, monkeypatch):
    class S:
        BUSINESS_DB_NAME = "lsordertest"
        COLORWORK_GATEWAY_ORIGIN = ""
        COLORWORK_SSO_SECRET = "test-sso-secret"
        COLORWORK_BASE_URL = "http://localhost:8787"
        COLORWORK_SYNC_KEY = "test-sync-key"
        JWT_SECRET_KEY = "test-jwt-secret"

    monkeypatch.setattr(service, "get_settings", lambda: S())
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_products ("
        "product_id TEXT PRIMARY KEY, name TEXT, color TEXT, size TEXT, disable_flag INTEGER DEFAULT 0)"
    ))
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory ("
        "product_id TEXT, enable_count REAL, disable_flag INTEGER DEFAULT 0)"
    ))
    products = [
        # 20g Genius Weft（Regular → Standard 命名）
        ("p1", "Standard Double Drawn Genius Weft/16/#1/20g", "#1", "16", 0),
        ("p2", "Standard Double Drawn Genius Weft/16/#1B/20g", "#1B", "16", 0),
        # 同发色同尺寸但 50g → 不应混入 20g 模板
        ("p3", "Standard Double Drawn Genius Weft/16/#1/50g", "#1", "16", 0),
        # 已停用产品不参与
        ("p4", "Standard Double Drawn Genius Weft/18/#1/20g", "#1", "18", 1),
        ("p5", "Standard Double Drawn Genius Weft/16/#2/20g", "#2", "16", 0),
        ("p6", "Standard Double Drawn Genius Weft/16/#3/20g", "#3", "16", 0),
        ("p7", "Standard Double Drawn Genius Weft/16/#4/20g", "#4", "16", 0),
    ]
    for pid, name, color, size, flag in products:
        db.execute(
            text("INSERT INTO lsordertest.okki_products VALUES (:a, :b, :c, :d, :e)"),
            {"a": pid, "b": name, "c": color, "d": size, "e": flag},
        )
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p1', 57, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p2', 0, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p3', 99, 0)"))
    # p4 库存存在但产品已停用
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p4', 30, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p5', 19, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p6', 20, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p7', 1, 0)"))
    db.commit()
    return db


def test_statuses_normal_and_restocking(colorwork_db):
    result = compute_template_statuses(colorwork_db, "20g-genius-weft-regular")
    assert result["unmapped"] is False
    assert result["statuses"]["#1|16"] == "normal"        # 57 > 0
    assert result["statuses"]["#1B|16"] == "restocking"   # 0 → 正在补货
    assert result["statuses"]["#2|16"] == "low_stock"    # 19 → 低库存
    assert result["statuses"]["#3|16"] == "normal"        # 20 → 无提醒
    assert result["statuses"]["#4|16"] == "low_stock"    # 1 → 低库存
    # 50g 产品不混入 20g 模板：#1|16 只统计 p1
    assert result["matched_products"] == 5


def test_weight_suffix_separates_50g_template(colorwork_db):
    result = compute_template_statuses(colorwork_db, "50g-genius-weft-regular")
    assert result["statuses"] == {"#1|16": "normal"}
    assert result["matched_products"] == 1


def test_unmapped_template_keeps_manual_status(colorwork_db, monkeypatch):
    # unmapped 分支兜底：映射表里 prefixes 为空时不做自动覆盖（当前 23 个模板均已映射，
    # 用 monkeypatch 构造该形态）
    monkeypatch.setitem(TEMPLATE_MATCH, "flex-weft-regular", {"prefixes": [], "weight": None})
    result = compute_template_statuses(colorwork_db, "flex-weft-regular")
    assert result["unmapped"] is True
    assert result["statuses"] == {}


def test_unknown_template_404(colorwork_db):
    with pytest.raises(Exception) as exc:
        compute_template_statuses(colorwork_db, "no-such-template")
    assert getattr(exc.value, "status_code", None) == 404


def test_all_23_templates_have_rules():
    expected = {
        "20g-genius-weft-regular", "20g-genius-weft-super", "20g-genius-weft-ultra",
        "50g-genius-weft-regular", "50g-genius-weft-super", "50g-genius-weft-ultra",
        "butterfly-weft-genius-genius-regular", "butterfly-weft-genius-genius-super",
        "flex-weft-regular", "i-tip-hair-regular", "i-tip-hair-ultra",
        "injection-tape-hair-super", "invisible-tape-weft-super",
        "k-tip-hair-regular", "k-tip-hair-super", "k-tip-hair-ultra",
        "nano-tip-hair-regular", "nano-tip-hair-super", "nano-tip-hair-ultra",
        "silk-genius-weft-regular", "tape-hair-regular", "tape-hair-super", "tape-hair-ultra",
    }
    assert set(TEMPLATE_MATCH.keys()) == expected


def test_allowed_views_respect_permissions():
    user = {"roles": [], "permissions": ["colorwork_download:read", "colorwork_edit:read"]}
    assert allowed_views_for(user) == ["library", "inventory"]
    super_admin = {"roles": ["super_admin"], "permissions": []}
    assert allowed_views_for(super_admin) == list(VIEW_PERMISSIONS.keys())


def test_sso_token_roundtrip(monkeypatch):
    from jose import jwt

    class S:
        COLORWORK_SSO_SECRET = "test-sso-secret"
        JWT_SECRET_KEY = "test-jwt-secret"

    monkeypatch.setattr(service, "get_settings", lambda: S())
    token = issue_sso_token(
        {"sub": "7", "username": "sales01", "real_name": "销售一"},
        ["library", "inventory"],
    )
    payload = jwt.decode(token, "test-sso-secret", algorithms=["HS256"], options={"verify_aud": False})
    assert payload["sub"] == "7"
    assert payload["name"] == "销售一"
    assert payload["views"] == ["library", "inventory"]
    assert payload["aud"] == "colorwork"
    assert payload["exp"] - payload["iat"] == 120


# ── 路由级：SSO 门禁与同步密钥 ──────────────────────────

def _user(db, username="cw-sales"):
    user = ArkUser(username=username, password_hash="x", real_name="销售", dingtalk_id=f"d-{username}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@contextmanager
def _client(db, user, permissions, monkeypatch):
    from app.colorwork.router import router

    class S:
        BUSINESS_DB_NAME = "lsordertest"
        COLORWORK_GATEWAY_ORIGIN = ""
        COLORWORK_SSO_SECRET = "test-sso-secret"
        COLORWORK_BASE_URL = "https://colorwork.example.com"
        COLORWORK_SYNC_KEY = "test-sync-key"
        JWT_SECRET_KEY = "test-jwt-secret"

    monkeypatch.setattr(service, "get_settings", lambda: S())

    app = FastAPI()
    app.include_router(router, prefix="/api/colorwork")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id), "username": user.username, "real_name": user.real_name,
        "roles": [], "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def test_sso_granted_for_permitted_view(db, monkeypatch):
    user = _user(db)
    with _client(db, user, ["colorwork_download:read"], monkeypatch) as client:
        resp = client.get("/api/colorwork/sso?view=library")
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("/api/colorwork/workbench/api/auth/ark?token=")
    assert body["url"].endswith("&view=library")
    assert body["views"] == ["library"]


def test_sso_denied_without_view_permission(db, monkeypatch):
    user = _user(db)
    with _client(db, user, ["colorwork_download:read"], monkeypatch) as client:
        resp = client.get("/api/colorwork/sso?view=master")
    assert resp.status_code == 403


def test_sso_rejects_unknown_view(db, monkeypatch):
    user = _user(db)
    with _client(db, user, list(VIEW_PERMISSIONS.values()), monkeypatch) as client:
        resp = client.get("/api/colorwork/sso?view=settings")
    assert resp.status_code == 400


def test_inventory_status_requires_sync_key(db, monkeypatch):
    user = _user(db)
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_products ("
        "product_id TEXT PRIMARY KEY, name TEXT, color TEXT, size TEXT, disable_flag INTEGER DEFAULT 0)"
    ))
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory ("
        "product_id TEXT, enable_count REAL, disable_flag INTEGER DEFAULT 0)"
    ))
    db.commit()
    with _client(db, user, ["colorwork_edit:read"], monkeypatch) as client:
        assert client.get("/api/colorwork/inventory-status?template_id=tape-hair-super").status_code == 401
        ok = client.get(
            "/api/colorwork/inventory-status?template_id=tape-hair-super",
            headers={"x-colorwork-sync-key": "test-sync-key"},
        )
    assert ok.status_code == 200
    assert ok.json()["template_id"] == "tape-hair-super"
