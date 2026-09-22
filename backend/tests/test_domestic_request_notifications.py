from unittest.mock import AsyncMock, Mock
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.models import ArkUser, ArkRole, ArkPermission
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import constants as C
from app.domestic.models import DomesticCustomer, DomesticOrder
from app.domestic.schemas import CustomerAdjust
from app.domestic import request_service as requests
from app.domestic import request_notification_service as notices


def user(db, name, roles=(), active=True, ding=True, real_name=None):
    row = ArkUser(username=name, real_name=real_name or name, password_hash='x', dingtalk_id=name if ding else None, is_active=active, roles=list(roles))
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
    applicant = user(db, 'applicant', real_name='张三')
    result = submit(db, applicant, 'notice-request')
    notifier = AsyncMock()
    notifier.send_oa_notice.return_value = True
    monkeypatch.setattr(notices, 'get_work_notifier', lambda: notifier)
    await notices.notify_submitted(db, result)
    notifier.send_oa_notice.assert_awaited_once()
    args = notifier.send_oa_notice.call_args.args
    assert args[0] == ['review']
    assert '提交人：张三' in args[2]
    assert '客户名称：notice-request' in args[2]
    assert '申请类型：调整' in args[2]
    assert '1 笔' in args[2]
    assert args[3].endswith('/domestic/customer-requests')
    await notices.notify_submitted(db, dict(result, replayed=True))
    assert notifier.send_oa_notice.await_count == 1
    notifier.send_oa_notice.side_effect = RuntimeError('transport unavailable')
    await notices.notify_submitted(db, result)
    assert requests.pending_request_count(db, viewer_user_id=applicant.id, can_review_all=False) == 1


@pytest.mark.asyncio
async def test_order_notice_names_submitter_order_and_customer(db, monkeypatch):
    review = role(db, 'order-reviewer', ['domestic:review'])
    user(db, 'review', [review])
    applicant = user(db, 'sales-login', real_name='李销售')
    customer = DomesticCustomer(
        shop_name='北京星光假发店', custom_code='notice-order-customer',
        created_by=applicant.id, owner_user_id=applicant.id,
    )
    db.add(customer)
    db.flush()
    order = DomesticOrder(
        domestic_no='DO20260922-008', order_no='KH-2026-8899',
        order_date=date(2026, 9, 22), required_ship_date=date(2026, 9, 30),
        customer_id=customer.id, order_category='normal', order_type='first_order',
        order_channel='wechat', status=C.ORDER_PENDING_REVIEW,
        total_amount=Decimal('12880.50'), charged_amount=0, created_by=applicant.id,
    )
    db.add(order)
    db.commit()
    notifier = AsyncMock()
    notifier.send_oa_notice.return_value = True
    monkeypatch.setattr(notices, 'get_work_notifier', lambda: notifier)

    result = {'id': order.id, 'status': C.ORDER_PENDING_REVIEW, 'replayed': False}
    await notices.notify_order_submitted(db, result)

    notifier.send_oa_notice.assert_awaited_once()
    args = notifier.send_oa_notice.call_args.args
    assert args[0] == ['review']
    assert args[1] == '内贸订单金额待审核'
    assert '提交人：李销售' in args[2]
    assert '系统单号：DO20260922-008' in args[2]
    assert '客户单号：KH-2026-8899' in args[2]
    assert '客户名称：北京星光假发店' in args[2]
    assert '订单金额：¥12880.50' in args[2]
    assert args[3].endswith('/domestic/orders?status=5')

    await notices.notify_order_submitted(db, dict(result, replayed=True))
    await notices.notify_order_submitted(db, dict(result, status=C.ORDER_PRODUCING))
    assert notifier.send_oa_notice.await_count == 1


def test_order_sync_notice_bridge_runs_coroutine(db, monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(notices, 'notify_order_submitted', notify)
    result = {'id': 900, 'status': C.ORDER_PENDING_REVIEW, 'replayed': False}

    notices.notify_order_submitted_sync(db, result)

    notify.assert_awaited_once_with(db, result)


def test_order_endpoints_dispatch_post_commit_notice(db, monkeypatch):
    from app.domestic import order_service
    from app.domestic.router import router

    applicant = user(db, 'order-api-applicant')
    app = FastAPI()
    app.include_router(router, prefix='/api/domestic')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        'sub': str(applicant.id), 'roles': [], 'permissions': ['domestic:write'],
    }
    notice = Mock()
    created = {
        'id': 901, 'status': C.ORDER_PENDING_REVIEW, 'replayed': False,
        'is_draft': False, 'warnings': [],
    }
    submitted = {'id': 902, 'status': C.ORDER_PENDING_REVIEW, 'replayed': False}
    monkeypatch.setattr(order_service, 'create_order', lambda *_args, **_kwargs: created)
    monkeypatch.setattr(order_service, 'submit_draft', lambda *_args, **_kwargs: submitted)
    monkeypatch.setattr(notices, 'notify_order_submitted_sync', notice)
    client = TestClient(app)

    response = client.post('/api/domestic/orders', json={
        'request_id': 'notice-order-create',
        'order_no': 'CUSTOMER-001',
        'order_date': '2026-09-22',
        'required_ship_date': '2026-09-30',
        'customer_id': 1,
        'order_category': 'special',
        'order_type': 'first_order',
        'order_channel': 'wechat',
        'items': [{
            'client_key': 'line-1',
            'attrs': {
                'product_type': 'cap', 'craft': '递旋', 'net_color': '自然色',
                'size': '12*14', 'length': '20厘米', 'hair_style_series': '标准款',
            },
            'order_qty': 1,
            'special_price': '880.00',
        }],
    })
    assert response.status_code == 200
    response = client.post('/api/domestic/orders/902/submit', json={
        'request_id': 'notice-draft-submit', 'expected_quotes': [],
    })
    assert response.status_code == 200
    assert notice.call_args_list[0].args == (db, created)
    assert notice.call_args_list[1].args == (db, submitted)


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
