"""PCW 路由层契约测试：权限、信封、幂等头、错误码映射。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer.pcw_errors import register_pcw_error_handler
from app.customer.pcw_router import router
from app.customer.router import router as customer_hub_router
from tests.test_customer_workflow import _account, _grant_permission, _user

NOW = beijing_now().replace(microsecond=0)


@pytest.fixture()
def client(db):
    app = FastAPI()
    # customer_hub_router 已 include pcw_router；仅注册一次避免重复路由
    app.include_router(customer_hub_router, prefix="/api/customer-hub")
    register_pcw_error_handler(app)
    identity = {
        "sub": "9401",
        "roles": [],
        "permissions": [
            "customer_pcw:read",
            "customer_pcw:write",
            "customer_profile:write",
            "customer:admin",
            "customer:read",
        ],
    }
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    with TestClient(app) as test_client:
        yield test_client


def _setup_customer(db, code="C-PCW-API", user_id=9401):
    account, _version = _account(db, code=code)
    user = _user(db, user_id)
    for code_value in ("customer:read", "customer_pcw:write", "customer:admin"):
        _grant_permission(db, user_id, code_value)
    from app.customer.models import CustomerAssignment

    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=user.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    return account, user


def test_workbench_overview_envelope(client, db):
    _setup_customer(db)
    response = client.get("/api/customer-hub/workbench/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["customers_total"] == 1
    assert "pending_actions" in data
    assert "scans" in data
    assert "watermarks" in data


def test_profile_revision_endpoints(client, db):
    account, _user = _setup_customer(db)
    # 固定快照版本：重放必须与首次请求内容一致（同键不同内容按契约 409）
    snapshot_version_id = account.current_profile_version_id
    snapshot_seq = account.profile_input_seq
    payload = {
        "expected_profile_version_id": snapshot_version_id,
        "expected_profile_input_seq": snapshot_seq,
        "field_key": "preference.expressed.color",
        "value_type": "string",
        "value": "#1B",
        "reason": "客户确认",
    }
    response = client.post(
        "/api/customer-hub/customers/{}/profile-revisions".format(account.id),
        json=payload,
        headers={"Idempotency-Key": "profile-rev-test-0001"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["revision_annotation_id"] > 0

    # 同键同内容重放返回相同 annotation
    replay = client.post(
        "/api/customer-hub/customers/{}/profile-revisions".format(account.id),
        json=payload,
        headers={"Idempotency-Key": "profile-rev-test-0001"},
    )
    assert replay.json()["data"]["revision_annotation_id"] == data["revision_annotation_id"]

    # 旧版本 → 409 PROFILE_VERSION_CONFLICT
    conflict = client.post(
        "/api/customer-hub/customers/{}/profile-revisions".format(account.id),
        json={
            "expected_profile_version_id": snapshot_version_id,
            "expected_profile_input_seq": 0,
            "field_key": "preference.expressed.color",
            "value_type": "string",
            "value": "#2A",
            "reason": "过期快照",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["data"]["error_code"] == "PROFILE_VERSION_CONFLICT"

    history = client.get(
        "/api/customer-hub/customers/{}/profile-revisions".format(account.id)
    )
    assert history.status_code == 200
    assert history.json()["data"]["total"] >= 1


def test_governed_field_rejected(client, db):
    account, _user = _setup_customer(db)
    response = client.post(
        "/api/customer-hub/customers/{}/profile-revisions".format(account.id),
        json={
            "expected_profile_version_id": account.current_profile_version_id,
            "expected_profile_input_seq": account.profile_input_seq,
            "field_key": "identity.legal_name",
            "value_type": "string",
            "value": "X",
            "reason": "越权治理字段",
        },
    )
    assert response.status_code == 400
    assert response.json()["data"]["error_code"] == "GOVERNED_FIELD_REQUIRED"


def test_monitor_subscription_lifecycle(client, db, monkeypatch):
    import socket

    _real_getaddrinfo = socket.getaddrinfo

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        if host in {"customer.example"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]
        return _real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    account, _user = _setup_customer(db)
    created = client.post(
        "/api/customer-hub/customers/{}/monitor-subscriptions".format(account.id),
        json={"channel": "website", "url": "https://customer.example/news", "interval_days": 7},
        headers={"Idempotency-Key": "monitor-sub-0001-aaaa"},
    )
    assert created.status_code == 200
    sub = created.json()["data"]
    assert sub["enabled"] is True
    assert sub["collection_status"] == "baseline"

    # 重复订阅 409
    duplicate = client.post(
        "/api/customer-hub/customers/{}/monitor-subscriptions".format(account.id),
        json={"channel": "website", "url": "https://customer.example/news", "interval_days": 7},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["data"]["error_code"] == "SUBSCRIPTION_EXISTS"

    # 非法 URL 400
    bad_url = client.post(
        "/api/customer-hub/customers/{}/monitor-subscriptions".format(account.id),
        json={"channel": "website", "url": "http://customer.example/news", "interval_days": 7},
    )
    assert bad_url.status_code == 400
    assert bad_url.json()["data"]["error_code"] == "URL_NOT_ALLOWED"

    # 暂停只动 enabled
    patched = client.patch(
        "/api/customer-hub/monitor-subscriptions/{}".format(sub["id"]),
        json={"expected_subscription_version": sub["row_version"], "enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["enabled"] is False

    run = client.post(
        "/api/customer-hub/monitor-subscriptions/{}/runs".format(sub["id"])
    )
    assert run.status_code == 200
    assert run.json()["data"]["status"] in {"disabled", "paused"}


def test_evaluation_run_and_get(client, db):
    account, _user = _setup_customer(db)
    response = client.post(
        "/api/customer-hub/evaluation-runs",
        json={"dry_run": False, "rule_version": "pcw_rules_v1", "run_kind": "manual"},
    )
    assert response.status_code == 202
    run = response.json()["data"]
    assert run["expected_count"] == 1

    detail = client.get("/api/customer-hub/evaluation-runs/{}".format(run["run_uid"]))
    assert detail.status_code == 200
    assert detail.json()["data"]["run_uid"] == run["run_uid"]


def test_action_v2_complete_via_put(client, db):
    account, user = _setup_customer(db)
    created = client.post(
        "/api/customer-hub/customers/{}/actions".format(account.id),
        json={
            "work_item_business_key": "manual:api-test",
            "work_item_business_cycle": "round-1",
            "work_type": "manual",
            "title": "API 测试行动",
            "action_type": "message",
            "thread_group": "key_account",
            "priority": "normal",
            "reason": "测试",
            "next_action": "联系客户",
            "channel": "whatsapp",
            "business_due_at": (NOW + timedelta(days=1)).isoformat(),
        },
        headers={"Idempotency-Key": "create-action-0001-aaa"},
    )
    assert created.status_code == 200
    action_id = created.json()["data"]["action_id"]
    work_item_version = created.json()["data"]["work_item_version"]

    completed = client.put(
        "/api/customer-hub/actions/{}".format(action_id),
        json={
            "operation": "complete",
            "expected_action_version": 1,
            "expected_work_item_version": work_item_version,
            "work_item_transition": "await_reply",
            "outcome_code": "contacted",
            "channel": "whatsapp",
            "occurred_at": NOW.isoformat(),
            "summary": "已联系客户",
            "next_step": "等待回复",
            "next_step_due_at": (NOW + timedelta(days=2)).isoformat(),
            "followup_action_type": "message",
            "followup_channel": "whatsapp",
        },
        headers={"Idempotency-Key": "complete-action-0001-aaa"},
    )
    assert completed.status_code == 200
    data = completed.json()["data"]
    assert data["action"]["status"] == "done"
    assert data["followup_action"]["id"] > 0
    assert data["event_state"] == "awaiting_reply"
