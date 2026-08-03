"""采购节大屏登录态换 key 端点（/api/festival/screen-key）测试。

覆盖：独立 festival:read 权限 / 与展会权限隔离 / 未登录 / key 未配置 fail-closed / 多 key 取第一个。
"""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkPermission
from app.auth.service import seed_role_permissions
from app.auth.utils import create_access_token
from app.festival import router as festival_router_mod


@contextmanager
def _client(permissions, keys, with_token=True, roles=()):
    app = FastAPI()
    app.include_router(festival_router_mod.router, prefix="/api/festival")

    class FakeSettings:
        FESTIVAL_SCREEN_KEYS = keys

    import unittest.mock as mock
    headers = {}
    if with_token:
        token = create_access_token(
            {"sub": "1", "username": "u1", "roles": list(roles), "permissions": permissions})
        headers = {"Authorization": f"Bearer {token}"}
    with mock.patch.object(festival_router_mod, "get_settings", lambda: FakeSettings):
        with TestClient(app, headers=headers) as c:
            yield c


def test_screen_key_ok_first_of_many():
    """采购节独立权限可换 key；多 key 配置返回第一个。"""
    with _client(["festival:read"], "k1, k2") as c:
        r = c.get("/api/festival/screen-key")
        assert r.status_code == 200
        assert r.json()["data"]["key"] == "k1"


def test_screen_key_super_admin_bypass():
    """super_admin 无需任何权限码即可换 key（硬约定 8 的自动绕过）"""
    with _client([], "k1", roles=("super_admin",)) as c:
        r = c.get("/api/festival/screen-key")
        assert r.status_code == 200
        assert r.json()["data"]["key"] == "k1"


def test_screen_key_forbidden_with_expo_permission_only():
    """展会权限不再隐式授予采购节看板权限。"""
    with _client(["expo:read"], "k1") as c:
        assert c.get("/api/festival/screen-key").status_code == 403


def test_screen_key_requires_login():
    """无 token → 401/403，不泄露 key"""
    with _client([], "k1", with_token=False) as c:
        r = c.get("/api/festival/screen-key")
        assert r.status_code in (401, 403)
        assert "k1" not in r.text


def test_screen_key_fail_closed_when_unconfigured():
    """FESTIVAL_SCREEN_KEYS 空 → 503，与 public_router fail-closed 语义一致"""
    with _client(["festival:read"], "") as c:
        assert c.get("/api/festival/screen-key").status_code == 503


def test_festival_read_permission_is_seeded(db):
    seed_role_permissions(db)

    permission = db.query(ArkPermission).filter(ArkPermission.code == "festival:read").one()
    assert permission.module == "festival"
    assert permission.action == "read"
