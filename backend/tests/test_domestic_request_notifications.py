from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.models import ArkUser, ArkRole, ArkPermission
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic.models import DomesticCustomer
from app.domestic.schemas import CustomerAdjust
from app.domestic import request_service as requests
from app.domestic import request_notification_service as notices


def user(db, name, roles=(), active=True, ding=True):
    row = ArkUser(username=name, real_name=name, password_hash='x', dingtalk_id=name if ding else None, is_active=active, roles=list(roles))
    db.add(row)
    db.flush()
    return row


def role(db, name, codes):
    row = ArkRole(name=name, label=name, permissions=[ArkPermission(code=c, module='domestic', action=c.split(':')[-1], label=c) for c in codes])
    db.add(row)
    db.flush()
    return row


def submit(db, applicant, key):
    customer = DomesticCustomer(shop_name=key, custom_code=key, created_by=applicant.id, owner_user_id=applicant.id)
    db.add(customer)
    db.flush()
    return requests.create_adjust_request(db, customer.id, CustomerAdjust(amount=1, request_id=key, remark='test adjustment'), applicant.id)


def test_recipients_follow_role_permissions_and_self_review(db):
    review = role(db, 'reviewer', ['domestic:review'])
    admin = role(db, 'admin', ['domestic:admin'])
    root = role(db, 'super_admin', [])
    applicant = user(db, 'applicant', [review])
    user(db, 'review', [review])
    user(db, 'admin', [review, admin])
    user(db, 'root', [root])
    user(db, 'inactive', [review], active=False)
    user(db, 'unbound', [review], ding=False)
    user(db, 'unrelated')
    assert notices.reviewer_ids(db, applicant.id) == ['admin', 'review', 'root']
    applicant.roles.append(admin)
    db.flush()
    assert 'applicant' in notices.reviewer_ids(db, applicant.id)


def test_pending_count_scope_and_review_changes(db):
    a, b = user(db, 'a'), user(db, 'b')
    first = submit(db, a, 'pending-first')
    submit(db, b, 'pending-second')
    assert requests.pending_request_count(db, viewer_user_id=a.id, can_review_all=False) == 1
    assert requests.pending_request_count(db, viewer_user_id=a.id, can_review_all=True) == 2
    requests.reject_request(db, first['id'], reviewer_id=b.id, can_admin=False, remark='test rejection')
    assert requests.pending_request_count(db, viewer_user_id=a.id, can_review_all=False) == 0
    assert requests.pending_request_count(db, viewer_user_id=b.id, can_review_all=True) == 1


@pytest.mark.asyncio
async def test_replay_and_transport_failure_do_not_duplicate_or_rollback(db, monkeypatch):
    review = role(db, 'reviewer', ['domestic:review'])
    user(db, 'review', [review])
    applicant = user(db, 'applicant')
    result = submit(db, applicant, 'notice-request')
    notifier = AsyncMock()
    notifier.send_oa_notice.return_value = True
    monkeypatch.setattr(notices, 'get_work_notifier', lambda: notifier)
    await notices.notify_submitted(db, result)
    notifier.send_oa_notice.assert_awaited_once()
    args = notifier.send_oa_notice.call_args.args
    assert args[0] == ['review']
    assert '1 笔' in args[2]
    assert args[3].endswith('/domestic/customer-requests')
    await notices.notify_submitted(db, dict(result, replayed=True))
    assert notifier.send_oa_notice.await_count == 1
    notifier.send_oa_notice.side_effect = RuntimeError('transport unavailable')
    await notices.notify_submitted(db, result)
    assert requests.pending_request_count(db, viewer_user_id=applicant.id, can_review_all=False) == 1


def test_endpoint_permission_and_scope(db):
    from app.domestic.router import router
    a, b = user(db, 'a'), user(db, 'b')
    submit(db, a, 'endpoint-first')
    submit(db, b, 'endpoint-second')
    app = FastAPI()
    app.include_router(router, prefix='/api/domestic')
    app.dependency_overrides[get_db] = lambda: db
    identity = {'sub': str(a.id), 'roles': [], 'permissions': []}
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app)
    url = '/api/domestic/customer-requests/pending-count'
    assert client.get(url).status_code == 403
    identity['permissions'] = ['domestic:recharge']
    assert client.get(url).json()['data']['count'] == 1
    identity['permissions'] = ['domestic:review']
    assert client.get(url).json()['data']['count'] == 2


def test_adjust_endpoint_commit_before_notice_and_replays_do_not_notify(db, monkeypatch):
    from app.domestic.router import router
    review = role(db, 'reviewer', ['domestic:review'])
    user(db, 'review', [review])
    applicant = user(db, 'applicant')
    customer = DomesticCustomer(shop_name='notice customer', custom_code='notice-customer', created_by=applicant.id, owner_user_id=applicant.id)
    db.add(customer)
    db.commit()
    notifier = AsyncMock()
    notifier.send_oa_notice.return_value = True
    monkeypatch.setattr(notices, 'get_work_notifier', lambda: notifier)
    app = FastAPI()
    app.include_router(router, prefix='/api/domestic')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(applicant.id), 'roles': [], 'permissions': ['domestic:recharge']}
    client = TestClient(app)
    url = f'/api/domestic/customers/{customer.id}/adjust'
    payload = {'amount': 10, 'remark': 'test adjustment', 'request_id': 'api-notice-once'}
    response = client.post(url, json=payload)
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'pending'
    assert notifier.send_oa_notice.await_count == 1
    response = client.post(url, json=payload)
    assert response.status_code == 200
    assert response.json()['data']['replayed'] is True
    assert notifier.send_oa_notice.await_count == 1
    assert client.post(url, json=dict(payload, amount=11)).status_code == 400
    assert notifier.send_oa_notice.await_count == 1
