"""工作台配置：roundtrip / upsert 幂等 / 用户隔离 / 重置 / 形状校验 / 并发兜底 / HTTP 层"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.dashboard import service
from app.dashboard.models import DashboardPreference
from app.dashboard.router import get_preference, reset_preference, save_preference
from app.dashboard.schemas import DashboardPrefs, SectionPrefs


def _user(db, username="worker"):
    user = ArkUser(username=username, password_hash="test-hash", real_name=username)
    db.add(user)
    db.flush()
    return user


def _claims(user):
    return {"sub": str(user.id), "roles": [], "permissions": []}


def _prefs(metric_hidden=(), action_order=()):
    return DashboardPrefs(
        metrics=SectionPrefs(hidden=list(metric_hidden), order=[]),
        actions=SectionPrefs(hidden=[], order=list(action_order)),
    )


# ---------------- roundtrip ----------------

def test_get_returns_none_before_first_save(db):
    user = _user(db)
    result = get_preference(db=db, current_user=_claims(user))
    assert result["code"] == 200
    assert result["data"] is None


def test_put_get_roundtrip_and_overwrite(db):
    user = _user(db)
    saved = save_preference(
        _prefs(metric_hidden=["employee_total"], action_order=["payment_sync", "batch"]),
        db=db, current_user=_claims(user),
    )
    assert saved["data"]["metrics"]["hidden"] == ["employee_total"]

    fetched = get_preference(db=db, current_user=_claims(user))
    assert fetched["data"]["actions"]["order"] == ["payment_sync", "batch"]
    assert fetched["data"]["version"] == 1

    # 再次 PUT 整体覆盖（不是合并）
    save_preference(_prefs(action_order=["tracking"]), db=db, current_user=_claims(user))
    fetched = get_preference(db=db, current_user=_claims(user))
    assert fetched["data"]["metrics"]["hidden"] == []
    assert fetched["data"]["actions"]["order"] == ["tracking"]
    # 一人一行，不产生第二行
    assert db.query(DashboardPreference).filter_by(user_id=user.id).count() == 1


def test_reset_deletes_row(db):
    user = _user(db)
    save_preference(_prefs(metric_hidden=["x"]), db=db, current_user=_claims(user))
    result = reset_preference(db=db, current_user=_claims(user))
    assert result["code"] == 200
    assert get_preference(db=db, current_user=_claims(user))["data"] is None
    # 空配置重置幂等（无行可删不报错）
    reset_preference(db=db, current_user=_claims(user))


# ---------------- 用户隔离 ----------------

def test_prefs_isolated_between_users(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    save_preference(_prefs(metric_hidden=["batch"]), db=db, current_user=_claims(alice))

    assert get_preference(db=db, current_user=_claims(bob))["data"] is None

    save_preference(_prefs(metric_hidden=["tracking"]), db=db, current_user=_claims(bob))
    assert get_preference(db=db, current_user=_claims(alice))["data"]["metrics"]["hidden"] == ["batch"]
    assert get_preference(db=db, current_user=_claims(bob))["data"]["metrics"]["hidden"] == ["tracking"]


# ---------------- 形状校验 ----------------

def test_schema_rejects_wrong_shapes():
    with pytest.raises(ValidationError):
        DashboardPrefs.model_validate({"metrics": {"hidden": "not-a-list", "order": []}})
    with pytest.raises(ValidationError):  # 条目超长
        DashboardPrefs.model_validate({"metrics": {"hidden": ["k" * 65], "order": []}})
    with pytest.raises(ValidationError):  # 数量超上限
        DashboardPrefs.model_validate({"actions": {"hidden": [], "order": [f"k{i}" for i in range(101)]}})


def test_schema_ignores_unknown_keys_for_forward_compat():
    prefs = DashboardPrefs.model_validate({
        "version": 1,
        "metrics": {"hidden": [], "order": [], "future_field": True},
        "future_section": {"hidden": []},
    })
    dumped = prefs.model_dump()
    assert "future_section" not in dumped
    assert "future_field" not in dumped["metrics"]


# ---------------- HTTP 层（真实鉴权 + 校验管道，直调函数测不到 401/422） ----------------

@contextmanager
def _client(db, user=None):
    from app.dashboard.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/dashboard")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    headers = {}
    if user is not None:
        token = create_access_token({
            "sub": str(user.id), "username": user.username,
            "real_name": user.real_name, "roles": [], "permissions": [],
        })
        headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, headers=headers) as client:
        yield client


def test_http_requires_token(db):
    with _client(db) as client:
        # HTTPBearer 缺 header 默认 403，token 无效为 401——两者都算拦住
        assert client.get("/api/dashboard/preference").status_code in (401, 403)
        assert client.put("/api/dashboard/preference", json={}).status_code in (401, 403)
        assert client.delete("/api/dashboard/preference").status_code in (401, 403)


def test_http_invalid_payload_422(db):
    user = _user(db, "http_user")
    with _client(db, user) as client:
        resp = client.put("/api/dashboard/preference", json={"metrics": {"hidden": "not-a-list", "order": []}})
        assert resp.status_code == 422


def test_http_roundtrip(db):
    user = _user(db, "http_user2")
    payload = {"version": 1, "metrics": {"hidden": ["batch"], "order": []}, "actions": {"hidden": [], "order": ["tracking_list"]}}
    with _client(db, user) as client:
        put_resp = client.put("/api/dashboard/preference", json=payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["data"]["metrics"]["hidden"] == ["batch"]

        get_resp = client.get("/api/dashboard/preference")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["actions"]["order"] == ["tracking_list"]


# ---------------- 并发兜底（cerebrum 2026-07-14：模拟竞态窗口断言不落 500） ----------------

def test_upsert_race_falls_back_to_update(db, monkeypatch):
    user = _user(db)
    service.upsert_prefs(db, user.id, _prefs(metric_hidden=["old"]))

    real_commit = db.commit
    state = {"raised": False}

    def flaky_commit():
        if not state["raised"]:
            state["raised"] = True
            raise IntegrityError("INSERT ...", {}, Exception("Duplicate entry"))
        real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    saved = service.upsert_prefs(db, user.id, _prefs(metric_hidden=["new"]))
    assert saved["metrics"]["hidden"] == ["new"]

    monkeypatch.setattr(db, "commit", real_commit)
    assert service.get_prefs(db, user.id)["metrics"]["hidden"] == ["new"]
