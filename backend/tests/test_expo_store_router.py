"""展会门店/展位管理路由端点测试（2026-08-05）。

覆盖：门店 CRUD、人员绑定、配额充值与流水查询。
权限由 JWT payload 注入，DB 依赖通过 dependency_overrides 替换为测试事务 session。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.expo import store_service
from app.expo.models import ExpoStore
from app.expo.quota_service import deduct_quota
from app.expo.router import router as expo_router


PERMS_ADMIN = ("expo_store:admin",)
PERMS_RECHARGE = ("expo_store:recharge",)
PERMS_BOTH = ("expo_store:admin", "expo_store:recharge")


@contextmanager
def _client(db, permissions=PERMS_ADMIN):
    app = FastAPI()
    app.include_router(expo_router, prefix="/api/expo")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    user = ArkUser(username="admin", password_hash="x", real_name="管理员")
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "roles": [],
        "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c, user


class TestStoreListAndCreate:
    def test_create_store_success(self, db):
        with _client(db) as (c, _):
            resp = c.post("/api/expo/stores", json={
                "name": "杭州展A1",
                "code": "HZ-A1",
                "contact_name": "小李",
                "contact_phone": "13800138000",
            })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "杭州展A1"
        assert data["code"] == "HZ-A1"
        assert data["status"] == 1
        assert data["remaining"] == 0

    def test_create_store_rejects_duplicate_code(self, db):
        db.add(ExpoStore(name="S1", code="DUP"))
        db.commit()
        with _client(db) as (c, _):
            resp = c.post("/api/expo/stores", json={"name": "S2", "code": "DUP"})
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    def test_list_stores_pagination(self, db):
        db.add(ExpoStore(name="门店一", code="L1"))
        db.add(ExpoStore(name="门店二", code="L2"))
        db.commit()
        with _client(db, PERMS_BOTH) as (c, _):
            resp = c.get("/api/expo/stores?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert len(data["items"]) == 1
        assert data["page"] == 1

    def test_list_stores_filter_by_status(self, db):
        db.add(ExpoStore(name="启用", code="ON", status=1))
        db.add(ExpoStore(name="停用", code="OFF", status=0))
        db.commit()
        with _client(db, PERMS_BOTH) as (c, _):
            resp = c.get("/api/expo/stores?status=0")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1
        assert resp.json()["data"]["items"][0]["code"] == "OFF"


class TestStoreDetailAndUpdate:
    def test_get_store(self, db):
        store = ExpoStore(name="S", code="G1")
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, PERMS_BOTH) as (c, _):
            resp = c.get(f"/api/expo/stores/{store.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == store.id

    def test_get_store_not_found(self, db):
        with _client(db, PERMS_BOTH) as (c, _):
            resp = c.get("/api/expo/stores/999999")
        assert resp.status_code == 404

    def test_update_store(self, db):
        store = ExpoStore(name="S", code="U1")
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db) as (c, _):
            resp = c.put(f"/api/expo/stores/{store.id}", json={"name": "新名字"})
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "新名字"

    def test_toggle_store_status(self, db):
        store = ExpoStore(name="S", code="T1", status=1)
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db) as (c, _):
            resp = c.post(f"/api/expo/stores/{store.id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == 0


class TestStoreUserBinding:
    def test_bind_and_list_users(self, db):
        store = ExpoStore(name="S", code="B1")
        db.add(store)
        db.commit()
        db.refresh(store)
        user = ArkUser(username="sales", password_hash="x", real_name="销售")
        db.add(user)
        db.commit()
        db.refresh(user)

        with _client(db) as (c, _):
            resp = c.post(f"/api/expo/stores/{store.id}/users", json={
                "user_id": user.id,
                "is_primary": True,
            })
            assert resp.status_code == 201
            assert resp.json()["data"]["is_primary"] is True

            resp = c.get(f"/api/expo/stores/{store.id}/users")
            assert resp.status_code == 200
            assert len(resp.json()["data"]) == 1
            assert resp.json()["data"][0]["username"] == "sales"

    def test_bind_already_bound_user(self, db):
        store = ExpoStore(name="S", code="B2")
        db.add(store)
        user = ArkUser(username="u", password_hash="x", real_name="U")
        db.add(user)
        db.commit()
        db.refresh(store)
        db.refresh(user)
        with _client(db) as (c, _):
            c.post(f"/api/expo/stores/{store.id}/users", json={"user_id": user.id})
            resp = c.post(f"/api/expo/stores/{store.id}/users", json={"user_id": user.id})
        assert resp.status_code == 400
        assert "绑定" in resp.json()["detail"]

    def test_unbind_user(self, db):
        store = ExpoStore(name="S", code="B3")
        db.add(store)
        user = ArkUser(username="u", password_hash="x", real_name="U")
        db.add(user)
        db.commit()
        db.refresh(store)
        db.refresh(user)
        with _client(db) as (c, _):
            c.post(f"/api/expo/stores/{store.id}/users", json={"user_id": user.id})
            resp = c.delete(f"/api/expo/stores/{store.id}/users/{user.id}")
            assert resp.status_code == 200

            resp = c.get(f"/api/expo/stores/{store.id}/users")
            assert resp.json()["data"] == []


class TestStoreQuota:
    def test_get_quota(self, db):
        store = ExpoStore(name="S", code="Q1", total_quota=100, used_quota=30)
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, PERMS_BOTH) as (c, _):
            resp = c.get(f"/api/expo/stores/{store.id}/quota")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_quota"] == 100
        assert data["used_quota"] == 30
        assert data["remaining"] == 70

    def test_recharge_persists(self, db):
        store = ExpoStore(name="S", code="Q2")
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, PERMS_RECHARGE) as (c, user):
            resp = c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={
                "amount": 50,
                "remark": "首充",
            })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["amount"] == 50
        assert data["balance_before"] == 0
        assert data["balance_after"] == 50
        assert data["operator_user_id"] == user.id

        # 落库持久化（router 负责 commit）
        db.refresh(store)
        assert store.total_quota == 50

    def test_recharge_invalid_amount(self, db):
        store = ExpoStore(name="S", code="Q3")
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, PERMS_RECHARGE) as (c, _):
            resp = c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 0})
        assert resp.status_code == 422  # Pydantic gt=0 校验

    def test_list_quota_records(self, db):
        store = ExpoStore(name="S", code="Q4", total_quota=100)
        db.add(store)
        user = ArkUser(username="u", password_hash="x", real_name="U")
        db.add(user)
        db.commit()
        db.refresh(store)
        db.refresh(user)
        with _client(db, PERMS_BOTH) as (c, _):
            c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 30})
            c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 20})
            resp = c.get(f"/api/expo/stores/{store.id}/quota/records")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        amounts = {r["amount"] for r in data["items"]}
        assert amounts == {20, 30}

    def test_list_quota_records_filter_by_type(self, db):
        store = ExpoStore(name="S", code="Q5", total_quota=100)
        db.add(store)
        user = ArkUser(username="u", password_hash="x", real_name="U")
        db.add(user)
        db.commit()
        db.refresh(store)
        db.refresh(user)

        with _client(db, PERMS_BOTH) as (c, _):
            c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 50})
            c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 30})
            # deduct 端点仅供内部生图调用，直接走服务写入一条扣减流水
            deduct_quota(db, store_id=store.id, amount=10, operator_user_id=user.id)

            resp = c.get(f"/api/expo/stores/{store.id}/quota/records?type=recharge")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 2
            assert all(r["type"] == "recharge" for r in data["items"])

            resp = c.get(f"/api/expo/stores/{store.id}/quota/records?type=deduct")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 1
            assert data["items"][0]["type"] == "deduct"
            assert data["items"][0]["amount"] == -10


class TestStorePermissions:
    def test_admin_only_create_rejected_by_recharge_only(self, db):
        with _client(db, PERMS_RECHARGE) as (c, _):
            resp = c.post("/api/expo/stores", json={"name": "S", "code": "P1"})
        assert resp.status_code == 403

    def test_recharge_only_rejected_by_admin_only(self, db):
        store = ExpoStore(name="S", code="P2")
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, PERMS_ADMIN) as (c, _):
            resp = c.post(f"/api/expo/stores/{store.id}/quota/recharge", json={"amount": 10})
        assert resp.status_code == 403


class TestMyStoreQuota:
    def test_bound_user_gets_quota_snapshot(self, db):
        store = ExpoStore(name="广州店", code="MQ1", total_quota=100, used_quota=30)
        db.add(store)
        db.commit()
        db.refresh(store)
        with _client(db, ("expo:write",)) as (c, user):
            store_service.bind_user_to_store(db, store.id, user.id, is_primary=True)
            db.commit()
            resp = c.get("/api/expo/stores/quota")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["bound"] is True
        assert data["store_id"] == store.id
        assert data["store_name"] == "广州店"
        assert data["remaining"] == 70

    def test_unbound_user_gets_bound_false(self, db):
        with _client(db, ("expo_lead:read",)) as (c, _):
            resp = c.get("/api/expo/stores/quota")
        assert resp.status_code == 200
        assert resp.json()["data"] == {"bound": False}

    def test_quota_rejects_without_flow_permission(self, db):
        with _client(db, ("expo_store:admin",)) as (c, _):
            resp = c.get("/api/expo/stores/quota")
        assert resp.status_code == 403


class TestStoreOptions:
    def test_options_returns_active_stores_only(self, db):
        db.add(ExpoStore(name="启用店", code="OP1", status=1))
        db.add(ExpoStore(name="停用店", code="OP2", status=0))
        db.commit()
        with _client(db, ("expo_lead:read_all",)) as (c, _):
            resp = c.get("/api/expo/stores/options")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["code"] == "OP1"

    def test_options_rejects_plain_lead_reader(self, db):
        with _client(db, ("expo_lead:read",)) as (c, _):
            resp = c.get("/api/expo/stores/options")
        assert resp.status_code == 403
