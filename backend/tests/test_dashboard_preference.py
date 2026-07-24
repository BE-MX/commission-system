"""工作台配置：roundtrip / upsert 幂等 / 用户隔离 / 重置 / 形状校验 / 并发兜底"""

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
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
