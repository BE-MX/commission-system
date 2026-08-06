"""效果图生成端点的门店配额集成测试。"""

from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.expo import ai_pipeline, router as expo_router_module
from app.expo.models import (
    ExpoCustomer,
    ExpoResult,
    ExpoSession,
    ExpoStore,
    ExpoStoreUser,
    ExpoWig,
)
from app.expo.router import router as expo_router


@contextmanager
def _client(db, permissions=("expo:write",)):
    app = FastAPI()
    app.include_router(expo_router, prefix="/api/expo")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    user = ArkUser(username="u1", password_hash="x", real_name="导购")
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


def _make_store(db, user_id, total_quota=10, code="T001"):
    store = ExpoStore(name="测试店", code=code, total_quota=total_quota, used_quota=0)
    db.add(store)
    db.commit()
    db.refresh(store)
    db.add(ExpoStoreUser(store_id=store.id, user_id=user_id, is_primary=True))
    db.commit()
    return store


def _make_session(db, mode="tryon", status="analyzed"):
    customer = ExpoCustomer(
        name="客", phone="13800000000",
        consent_at=datetime.utcnow(), expo_code="t",
    )
    db.add(customer)
    db.flush()
    session = ExpoSession(
        customer_id=customer.id,
        photo_path="uploads/expo/photos/x.jpg",
        mode=mode,
        status=status,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _make_wig(db):
    wig = ExpoWig(model_no="LS-T1", name="测试发", is_active=1)
    db.add(wig)
    db.commit()
    db.refresh(wig)
    return wig


class TestGenerateQuota:
    def test_generate_rejects_without_store(self, db, monkeypatch):
        """未绑定门店的账号触发生成应被 400 拦截。"""
        session = _make_session(db)
        monkeypatch.setattr(expo_router_module, "launch_composite_threads", lambda *a, **k: None)

        with _client(db) as (c, _user):
            resp = c.post(f"/api/expo/sessions/{session.id}/generate", json={})

        assert resp.status_code == 400
        assert "未绑定" in resp.json()["detail"]

    def test_generate_rejects_insufficient_quota(self, db, monkeypatch):
        """余额小于计划生成张数时应被 400 拦截，且未扣额。"""
        with _client(db) as (c, user):
            store = _make_store(db, user.id, total_quota=0)
            session = _make_session(db)
            wig = _make_wig(db)
            monkeypatch.setattr(expo_router_module, "launch_composite_threads", lambda *a, **k: None)
            resp = c.post(
                f"/api/expo/sessions/{session.id}/generate",
                json={"wig_ids": [wig.id]},
            )

        assert resp.status_code == 400
        assert "额度不足" in resp.json()["detail"]
        db.expire_all()
        store = db.get(ExpoStore, store.id)
        assert store.used_quota == 0

    def test_generate_deducts_quota_and_attaches_store(self, db, monkeypatch):
        """余额充足时：创建 result、设置 session.store_id、扣减额度、启动后台线程。"""
        launched = {}

        def capture_launch(session_id, result_ids, start_strategy):
            launched["session_id"] = session_id
            launched["result_ids"] = result_ids
            launched["start_strategy"] = start_strategy

        with _client(db) as (c, user):
            store = _make_store(db, user.id, total_quota=10)
            session = _make_session(db)
            wig = _make_wig(db)
            monkeypatch.setattr(expo_router_module, "launch_composite_threads", capture_launch)
            resp = c.post(
                f"/api/expo/sessions/{session.id}/generate",
                json={"wig_ids": [wig.id]},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["wig_ids"] == [wig.id]

        db.expire_all()
        store = db.get(ExpoStore, store.id)
        session = db.get(ExpoSession, session.id)
        assert session.store_id == store.id
        assert store.used_quota == 1

        assert launched["session_id"] == session.id
        assert len(launched["result_ids"]) == 1
        result = db.get(ExpoResult, launched["result_ids"][0])
        assert result is not None
        assert result.session_id == session.id
        assert result.status == "generating"

    def test_generate_scene_mode_deducts_quota(self, db, monkeypatch):
        """scene 模式按场景数量扣减额度。"""
        launched = {}

        def capture_launch(session_id, result_ids, start_strategy):
            launched["result_ids"] = result_ids

        with _client(db) as (c, user):
            store = _make_store(db, user.id, total_quota=10)
            session = _make_session(db, mode="scene", status="ready")
            monkeypatch.setattr(expo_router_module, "launch_composite_threads", capture_launch)
            resp = c.post(
                f"/api/expo/sessions/{session.id}/generate",
                json={"scene_keys": ["cafe", "home"]},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert set(data["scene_keys"]) == {"cafe", "home"}

        db.expire_all()
        store = db.get(ExpoStore, store.id)
        session = db.get(ExpoSession, session.id)
        assert session.store_id == store.id
        assert store.used_quota == 2
        assert len(launched["result_ids"]) == 2

    def test_generate_rejects_cross_store_session(self, db, monkeypatch):
        """会话已归属其他门店时，当前账号不能占用其门店额度。"""
        with _client(db) as (c, user):
            store1 = _make_store(db, user.id, total_quota=10, code="S1")
            store2 = ExpoStore(name="其他店", code="S2", total_quota=10, used_quota=0)
            db.add(store2)
            db.commit()
            db.refresh(store2)
            session = _make_session(db)
            session.store_id = store2.id
            db.commit()
            wig = _make_wig(db)
            monkeypatch.setattr(
                expo_router_module, "launch_composite_threads", lambda *a, **k: None
            )
            resp = c.post(
                f"/api/expo/sessions/{session.id}/generate",
                json={"wig_ids": [wig.id]},
            )

        assert resp.status_code == 400
        assert "其他门店" in resp.json()["detail"]
        db.expire_all()
        store1 = db.get(ExpoStore, store1.id)
        assert store1.used_quota == 0
