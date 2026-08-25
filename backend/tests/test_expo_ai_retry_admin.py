"""Expo AI retry state, support phone, and DingTalk administrator alert tests."""

from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.dingtalk import work_notify
from app.expo import ai_pipeline, service
from app.expo.models import ExpoCustomer, ExpoSession, ExpoStore, ExpoStoreUser
from app.expo.router import router as expo_router


def _session(db, *, store=None, error_message=None):
    customer = ExpoCustomer(
        name="陈女士",
        phone="13800000000",
        consent_at=datetime.utcnow(),
        expo_code="test",
    )
    db.add(customer)
    db.flush()
    row = ExpoSession(
        customer_id=customer.id,
        store_id=store.id if store else None,
        photo_path="uploads/expo/photos/test.jpg",
        mode="tryon",
        status="pending",
        error_message=error_message,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _admin(db, *, username="expo-admin", active=True, dingtalk_id="dt-admin", phone="13900000000"):
    permission = db.query(ArkPermission).filter(ArkPermission.code == "expo:admin").first()
    if permission is None:
        permission = ArkPermission(
            code="expo:admin",
            module="expo",
            action="admin",
            label="展会管理员",
        )
        db.add(permission)
        db.flush()
    role = ArkRole(
        name=f"{username}-role",
        label=f"{username} role",
        permissions=[permission],
    )
    user = ArkUser(
        username=username,
        password_hash="x",
        real_name="展会管理员",
        phone=phone,
        dingtalk_id=dingtalk_id,
        is_active=active,
        roles=[role],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_timeout_retries_exactly_three_times_and_clears_marker(db, monkeypatch):
    row = _session(db)
    monkeypatch.setattr(ai_pipeline.time, "sleep", lambda _seconds: None)
    seen_retry_counts = []
    attempts = {"count": 0}

    def call():
        attempts["count"] += 1
        issue = ai_pipeline.parse_ai_issue(row.error_message)
        if issue:
            seen_retry_counts.append(issue["retry_count"])
        if attempts["count"] <= 3:
            raise TimeoutError("provider timed out")
        return "ok"

    result = ai_pipeline._call_with_ai_retry(
        call,
        db,
        row.id,
        stage="analysis",
    )

    assert result == "ok"
    assert attempts["count"] == 4  # initial call + exactly three retries
    assert seen_retry_counts == [1, 2, 3]
    assert row.error_message is None


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("direct provider error"),
        httpx.HTTPStatusError(
            "bad request",
            request=httpx.Request("POST", "https://provider.test"),
            response=httpx.Response(
                400,
                request=httpx.Request("POST", "https://provider.test"),
            ),
        ),
    ],
)
def test_non_timeout_error_is_not_retried(db, monkeypatch, exc):
    row = _session(db)
    monkeypatch.setattr(ai_pipeline.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}

    def call():
        attempts["count"] += 1
        raise exc

    with pytest.raises(type(exc)):
        ai_pipeline._call_with_ai_retry(call, db, row.id, stage="analysis")
    assert attempts["count"] == 1


def test_terminal_issue_is_monotonic_across_parallel_composites(db):
    row = _session(
        db,
        error_message=ai_pipeline.format_ai_issue(
            stage="composite",
            state="contact_admin",
            reason="error",
            result_id=7,
            notified_at="2026-08-25T12:00:00",
        ),
    )

    ai_pipeline._set_ai_issue(
        db,
        row.id,
        stage="composite",
        state="retrying",
        reason="timeout",
        exc=TimeoutError("another result timed out"),
        retry_count=1,
        result_id=8,
    )
    ai_pipeline._clear_own_ai_issue(
        db, row.id, stage="composite", result_id=8,
    )

    issue = ai_pipeline.parse_ai_issue(row.error_message)
    assert issue["state"] == "contact_admin"
    assert issue["result_id"] == 7
    assert issue["notified_at"] == "2026-08-25T12:00:00"


def test_stale_parallel_worker_cannot_overwrite_or_clear_terminal_issue(db):
    row = _session(
        db,
        error_message=ai_pipeline.format_ai_issue(
            stage="composite",
            state="retrying",
            reason="timeout",
            retry_count=1,
            result_id=8,
        ),
    )
    stale_db = sessionmaker(bind=db.get_bind(), expire_on_commit=False)()
    try:
        stale_db.get(ExpoSession, row.id)  # cache the pre-terminal retry marker
        ai_pipeline._set_ai_issue(
            db,
            row.id,
            stage="composite",
            state="contact_admin",
            reason="error",
            exc=ValueError("result 7 failed"),
            result_id=7,
        )
        ai_pipeline._set_ai_issue(
            stale_db,
            row.id,
            stage="composite",
            state="retrying",
            reason="timeout",
            exc=TimeoutError("stale result 8 retry"),
            retry_count=2,
            result_id=8,
        )
        ai_pipeline._clear_own_ai_issue(
            stale_db, row.id, stage="composite", result_id=8,
        )
    finally:
        stale_db.close()

    db.expire(row)
    issue = ai_pipeline.parse_ai_issue(row.error_message)
    assert issue["state"] == "contact_admin"
    assert issue["result_id"] == 7


def test_retrying_and_terminal_payloads_hide_internal_detail_and_use_store_phone(db):
    store = ExpoStore(
        name="杭州展位",
        code="HZ-RETRY",
        contact_name="李经理",
        contact_phone=" 0571-12345678 ",
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    retrying = _session(
        db,
        store=store,
        error_message=ai_pipeline.format_ai_issue(
            stage="analysis",
            state="retrying",
            reason="timeout",
            retry_count=2,
            detail="secret provider diagnostic",
        ),
    )
    payload = service.serialize_session(db, retrying)
    assert payload["ai_issue"] == {
        "stage": "analysis",
        "state": "retrying",
        "reason": "timeout",
        "retry_count": 2,
        "message": "当前接口服务负载较高，已自动重试，请耐心等待",
        "notified": False,
    }
    assert "secret provider diagnostic" not in str(payload)

    retrying.error_message = ai_pipeline.format_ai_issue(
        stage="composite",
        state="contact_admin",
        reason="error",
        detail="HTTP 400 details",
        result_id=7,
    )
    db.commit()
    payload = service.serialize_session(db, retrying)
    assert payload["ai_issue"]["message"] == "请联系管理员"
    assert payload["ai_issue"]["admin_phone"] == "0571-12345678"
    assert payload["ai_issue"]["notifying"] is False


@pytest.mark.asyncio
async def test_contact_admin_notifies_permission_bound_users_once(db, monkeypatch):
    store = ExpoStore(
        name="杭州展位",
        code="HZ-ALERT",
        contact_phone="0571-87654321",
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    session = _session(
        db,
        store=store,
        error_message=ai_pipeline.format_ai_issue(
            stage="analysis",
            state="contact_admin",
            reason="error",
            detail="provider rejected request",
        ),
    )
    admin = _admin(db)
    _admin(
        db,
        username="disabled-admin",
        active=False,
        dingtalk_id="dt-disabled",
    )

    calls = []

    class FakeNotifier:
        async def send_to_users(self, user_ids, title, markdown_text):
            calls.append((user_ids, title, markdown_text))
            return True

    monkeypatch.setattr(work_notify, "get_work_notifier", lambda: FakeNotifier())

    first = await service.notify_ai_issue_admins(db, session)
    second = await service.notify_ai_issue_admins(db, session)

    assert first == {
        "sent": True,
        "already_notified": False,
        "admin_phone": "0571-87654321",
    }
    assert second["already_notified"] is True
    assert calls == [(
        [admin.dingtalk_id],
        "展会 AI 试戴异常提醒",
        "陈女士用户在展会AI试戴功能的人脸识别环节发生问题，请及时解决。",
    )]
    assert ai_pipeline.parse_ai_issue(session.error_message)["notified_at"]


@pytest.mark.asyncio
async def test_contact_admin_claim_prevents_reentrant_duplicate(db, monkeypatch):
    session = _session(
        db,
        error_message=ai_pipeline.format_ai_issue(
            stage="composite",
            state="contact_admin",
            reason="error",
        ),
    )
    _admin(db)
    nested_results = []

    class ReentrantNotifier:
        async def send_to_users(self, user_ids, title, markdown_text):
            nested_results.append(await service.notify_ai_issue_admins(db, session))
            return True

    monkeypatch.setattr(work_notify, "get_work_notifier", lambda: ReentrantNotifier())
    result = await service.notify_ai_issue_admins(db, session)

    assert result["already_notified"] is False
    assert nested_results[0] == {
        "sent": False,
        "already_notified": False,
        "in_progress": True,
        "admin_phone": "13900000000",
    }
    assert not ai_pipeline.parse_ai_issue(session.error_message)["notified_at"].startswith("pending:")


@pytest.mark.asyncio
async def test_failed_sender_rolls_back_claim_after_reentrant_request(db, monkeypatch):
    session = _session(
        db,
        error_message=ai_pipeline.format_ai_issue(
            stage="analysis",
            state="contact_admin",
            reason="error",
        ),
    )
    _admin(db)
    nested_results = []

    class FailingNotifier:
        async def send_to_users(self, user_ids, title, markdown_text):
            nested_results.append(await service.notify_ai_issue_admins(db, session))
            return False

    monkeypatch.setattr(work_notify, "get_work_notifier", lambda: FailingNotifier())
    with pytest.raises(RuntimeError, match="发送失败"):
        await service.notify_ai_issue_admins(db, session)

    assert nested_results[0]["sent"] is False
    issue = ai_pipeline.parse_ai_issue(session.error_message)
    assert not issue.get("notified_at")
    assert service.serialize_session(db, session)["ai_issue"]["notified"] is False


def test_legacy_error_message_does_not_leak_to_public_ai_issue(db):
    session = _session(db, error_message="analysis: raw upstream failure")
    assert service.serialize_session(db, session)["ai_issue"] is None


def test_contact_admin_endpoint_requires_write_permission_and_returns_notification_result(db, monkeypatch):
    store = ExpoStore(name="杭州展位", code="HZ-ENDPOINT", contact_phone="0571-1")
    other_store = ExpoStore(name="上海展位", code="SH-ENDPOINT", contact_phone="021-1")
    db.add_all([store, other_store])
    db.commit()
    operator = _admin(db, username="kiosk-operator", dingtalk_id="dt-kiosk")
    other_operator = _admin(db, username="other-operator", dingtalk_id="dt-other")
    db.add_all([
        ExpoStoreUser(store_id=store.id, user_id=operator.id, is_primary=True),
        ExpoStoreUser(store_id=other_store.id, user_id=other_operator.id, is_primary=True),
    ])
    db.commit()
    session = _session(
        db,
        store=store,
        error_message=ai_pipeline.format_ai_issue(
            stage="composite",
            state="contact_admin",
            reason="error",
        ),
    )
    app = FastAPI()
    app.include_router(expo_router, prefix="/api/expo")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    async def fake_notify(_db, target):
        assert target.id == session.id
        return {"sent": True, "already_notified": False, "admin_phone": "0571-1"}

    monkeypatch.setattr(service, "notify_ai_issue_admins", fake_notify)
    allowed = create_access_token({
        "sub": str(operator.id), "username": "kiosk", "roles": [], "permissions": ["expo:write"],
    })
    wrong_store = create_access_token({
        "sub": str(other_operator.id), "username": "other", "roles": [], "permissions": ["expo:write"],
    })
    denied = create_access_token({
        "sub": "2", "username": "viewer", "roles": [], "permissions": ["expo:read"],
    })

    with TestClient(app) as client:
        response = client.post(
            f"/api/expo/sessions/{session.id}/contact-admin",
            headers={"Authorization": f"Bearer {allowed}"},
        )
        forbidden = client.post(
            f"/api/expo/sessions/{session.id}/contact-admin",
            headers={"Authorization": f"Bearer {denied}"},
        )
        cross_store = client.post(
            f"/api/expo/sessions/{session.id}/contact-admin",
            headers={"Authorization": f"Bearer {wrong_store}"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["sent"] is True
    assert forbidden.status_code == 403
    assert cross_store.status_code == 400
