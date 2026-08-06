"""展会线索台门店数据范围隔离测试（2026-08-06）。

覆盖：
- 注册/建会话时按操作人绑定门店写入 store_id；
- GET /leads 默认只看本店，expo_lead:read_all 看全部并可按 store_id 过滤；
- GET /leads/{id} 跨店访问一律 404（不暴露存在性）。
"""

from contextlib import contextmanager

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.expo import ai_pipeline, service, store_service
from app.expo.models import ExpoCustomer, ExpoStore
from app.expo.router import router as expo_router
from app.expo.schemas import CustomerRegister

PERMS_LEAD_READ = ("expo_lead:read",)
PERMS_WRITE = ("expo:write",)


@pytest.fixture(autouse=True)
def _isolate_photo_dirs(tmp_path, monkeypatch):
    """create_session 会真实落盘照片，隔离到 tmp_path，不污染仓库 uploads/。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ai_pipeline, "PHOTO_DIR", tmp_path / "uploads" / "expo" / "photos")
    monkeypatch.setattr(ai_pipeline, "RESULT_DIR", tmp_path / "uploads" / "expo" / "results")


@contextmanager
def _client(db, user, permissions):
    app = FastAPI()
    app.include_router(expo_router, prefix="/api/expo")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "roles": [],
        "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


def _make_user(db, username: str) -> ArkUser:
    user = ArkUser(username=username, password_hash="x", real_name=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_store(db, name: str, code: str) -> ExpoStore:
    store = ExpoStore(name=name, code=code, status=1)
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _body(phone="13800138000") -> CustomerRegister:
    return CustomerRegister(name="试戴客", phone=phone, consent=True)


class TestStoreAttribution:
    """注册/建会话时的门店归属写入。"""

    def test_register_writes_store_id_for_bound_user(self, db):
        user = _make_user(db, "guide_a")
        store = _make_store(db, "广州店", "GZ001")
        store_service.bind_user_to_store(db, store.id, user.id, is_primary=True)
        db.commit()

        with _client(db, user, PERMS_WRITE) as c:
            resp = c.post("/api/expo/register", json={
                "name": "张女士", "phone": "13800138000", "consent": True,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 201
        customer = db.get(ExpoCustomer, resp.json()["data"]["customer_id"])
        assert customer.store_id == store.id

    def test_register_without_store_keeps_null(self, db):
        user = _make_user(db, "guide_nostore")
        with _client(db, user, PERMS_WRITE) as c:
            resp = c.post("/api/expo/register", json={
                "name": "李先生", "phone": "13900139000", "consent": True,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 201
        customer = db.get(ExpoCustomer, resp.json()["data"]["customer_id"])
        assert customer.store_id is None

    def test_create_session_writes_store_id(self, db):
        user = _make_user(db, "guide_b")
        store = _make_store(db, "深圳店", "SZ001")
        store_service.bind_user_to_store(db, store.id, user.id, is_primary=True)
        customer = service.register_customer(db, _body(), operator_user_id=user.id)

        buf = io.BytesIO()
        Image.new("RGB", (80, 120), (120, 90, 70)).save(buf, "JPEG")

        class _Upload:
            filename = "photo.jpg"
            file = io.BytesIO(buf.getvalue())

        session = service.create_session(db, customer.id, _Upload(), user.id, mode="scene")
        assert customer.store_id == store.id
        assert session.store_id == store.id


class TestLeadListScope:
    """GET /leads 数据范围。"""

    def _seed(self, db):
        store_a = _make_store(db, "门店A", "A001")
        store_b = _make_store(db, "门店B", "B001")
        cust_a = ExpoCustomer(name="甲客", phone="13800000001", store_id=store_a.id)
        cust_b = ExpoCustomer(name="乙客", phone="13800000002", store_id=store_b.id)
        cust_old = ExpoCustomer(name="老客", phone="13800000003", store_id=None)
        db.add_all([cust_a, cust_b, cust_old])
        db.commit()
        return store_a, store_b, cust_a, cust_b, cust_old

    def test_bound_user_sees_only_own_store(self, db):
        store_a, store_b, cust_a, cust_b, _ = self._seed(db)
        user = _make_user(db, "lead_guide")
        store_service.bind_user_to_store(db, store_a.id, user.id, is_primary=True)
        db.commit()

        with _client(db, user, PERMS_LEAD_READ) as c:
            resp = c.get("/api/expo/leads")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["id"] == cust_a.id

    def test_unbound_user_sees_nothing(self, db):
        self._seed(db)
        user = _make_user(db, "lead_nobind")
        with _client(db, user, PERMS_LEAD_READ) as c:
            resp = c.get("/api/expo/leads")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    def test_read_all_sees_everything_and_filters_by_store(self, db):
        store_a, store_b, cust_a, cust_b, cust_old = self._seed(db)
        user = _make_user(db, "lead_super")
        with _client(db, user, ("expo_lead:read", "expo_lead:read_all")) as c:
            resp = c.get("/api/expo/leads")
            assert resp.status_code == 200
            assert resp.json()["data"]["total"] == 3

            resp = c.get("/api/expo/leads", params={"store_id": store_b.id})
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 1
            assert data["items"][0]["id"] == cust_b.id

    def test_store_id_param_ignored_without_read_all(self, db):
        store_a, store_b, cust_a, cust_b, _ = self._seed(db)
        user = _make_user(db, "lead_guide2")
        store_service.bind_user_to_store(db, store_a.id, user.id, is_primary=True)
        db.commit()

        with _client(db, user, PERMS_LEAD_READ) as c:
            # 指定他店 store_id 不生效，仍只能看本店
            resp = c.get("/api/expo/leads", params={"store_id": store_b.id})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["id"] == cust_a.id


class TestLeadDetailScope:
    """GET /leads/{id} 与列表同一数据范围。"""

    def test_cross_store_detail_returns_404(self, db):
        store_a = _make_store(db, "门店A", "DA001")
        store_b = _make_store(db, "门店B", "DB001")
        cust_b = ExpoCustomer(name="乙客", phone="13800000002", store_id=store_b.id)
        db.add(cust_b)
        db.commit()

        user = _make_user(db, "detail_guide")
        store_service.bind_user_to_store(db, store_a.id, user.id, is_primary=True)
        db.commit()

        with _client(db, user, PERMS_LEAD_READ) as c:
            resp = c.get(f"/api/expo/leads/{cust_b.id}")
        assert resp.status_code == 404

    def test_read_all_can_view_any_detail(self, db):
        store_b = _make_store(db, "门店B", "DB002")
        cust_b = ExpoCustomer(name="乙客", phone="13800000002", store_id=store_b.id)
        db.add(cust_b)
        db.commit()

        user = _make_user(db, "detail_super")
        with _client(db, user, ("expo_lead:read", "expo_lead:read_all")) as c:
            resp = c.get(f"/api/expo/leads/{cust_b.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["customer"]["id"] == cust_b.id
