"""All writes use isolated SQLite and mocked OKKI; never call production."""
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from app.invoice.models import Invoice, OkkiOutboundTask
from app.shipping_inspection import outbound_delete_service as deletion, outbound_delete_client as remote
from app.shipping_inspection import outbound_service, outbound_queue_service
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection
from tests.test_shipping_inspection import _user, _pc_client, _bind_okki, outbound_scope_seed, product_display_source


@pytest.fixture
def case(db, outbound_scope_seed, monkeypatch):
    user = _user(db, 'deletion-user')
    _bind_okki(db, user)
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN outbound_invoice_id TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='77' WHERE id='OB001'"))
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN outbound_invoice_id TEXT'))
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='77',order_id='123' WHERE outbound_record_id='OB001'"))
    inv = Invoice(invoice_no='DELETE-1', customer_id='C1', customer_name='Customer',
                  invoice_date=date(2026, 9, 20), sales_user_id=user.id, xiaoman_order_id='123')
    db.add(inv)
    db.flush()
    task = OkkiOutboundTask(invoice_id=inv.id, order_id='123', status='done', reason='created: OLD')
    db.add(task)
    db.commit()
    outbound_service._columns_cache.clear()
    monkeypatch.setattr(deletion, 'ensure_access_token', lambda db: 'test')
    state = {'exists': True, 'posts': 0, 'status': 1}

    def read(token, invoice_id):
        assert invoice_id == '77'
        return {'outbound_invoice_id': 77, 'serial_id': 'CK2026001', 'status': state['status'],
                'company_info': {'id': 'C1'}, 'record_list': [{'order_id': 123}]} if state['exists'] else None

    def remove(token, invoice_id):
        state['posts'] += 1
        event = db.query(ShippingOperationEvent).filter_by(scope=deletion.SCOPE).one()
        assert event.action == deletion.PENDING
        assert db.get(OkkiOutboundTask, task.id).reason == 'delete_pending:77'
        state['exists'] = False

    monkeypatch.setattr(remote, 'read', read)
    monkeypatch.setattr(remote, 'remove', remove)
    return user, inv, task, state


BASE = '/api/shipping-inspection/outbound-records'
PERMS = ['shipping_inspection:read', 'shipping_inspection:delete', 'shipping_inspection:read_all']


def test_delete_verifies_remote_hides_stale_mirror_preserves_inspection_and_never_reposts(db, case):
    user, _, task, state = case
    db.add(ShippingInspection(outbound_record_id='OB001', status='submitted', created_by=user.id))
    db.commit()
    with _pc_client(db, user, PERMS) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 200
        assert client.delete(f'{BASE}/OB001').status_code == 200
        assert client.get(f'{BASE}/OB001/print-data').status_code == 404
        result = client.get(BASE).json()['data']
        assert result['total'] == 1
        assert all(r['outbound_record_id'] != 'OB001' for r in result['items'])
    assert state['posts'] == 1
    assert task.status == 'skipped' and task.reason == 'deleted:77'
    assert db.query(ShippingInspection).filter_by(outbound_record_id='OB001').count() == 1
    assert db.execute(text("SELECT COUNT(*) FROM lsordertest.okki_outbound_records WHERE id='OB001'")).scalar() == 1
    # Even when mirror sync removes the header, the old task cannot reappear.
    db.execute(text("DELETE FROM lsordertest.okki_outbound_records WHERE id='OB001'"))
    db.commit()
    rows, _ = outbound_queue_service.list_outbound_records(db)
    assert all(r['outbound_record_id'] != f'task:{task.id}' for r in rows)


def test_delete_requires_permission_and_owner_scope(db, case):
    user, _, _, state = case
    with _pc_client(db, user, ['shipping_inspection:read']) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 403
    other = _user(db, 'other-deleter')
    _bind_okki(db, other, '9002')
    with _pc_client(db, other, ['shipping_inspection:delete']) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 404
    assert state['posts'] == 0


@pytest.mark.parametrize('block', ['shipped', 'running', 'linked', 'local'])
def test_blocked_states_never_send_delete(db, case, block):
    user, inv, task, state = case
    if block == 'shipped': state['status'] = 2
    if block == 'running': task.status = 'running'
    if block == 'linked': inv.linked_sync_id = 'pending-sync'
    db.commit()
    with _pc_client(db, user, PERMS) as client:
        response = client.delete(f'{BASE}/' + ('task:1' if block == 'local' else 'OB001'))
        assert response.status_code in (404, 409)
    assert state['posts'] == 0


def test_timeout_is_not_success_and_second_click_only_checks_then_recovers(db, case, monkeypatch):
    user, _, task, state = case
    def timeout(*args):
        state['posts'] += 1
        raise remote.DeleteRemoteError('timeout', uncertain=True)
    monkeypatch.setattr(remote, 'remove', timeout)
    with _pc_client(db, user, PERMS) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 409
        assert client.delete(f'{BASE}/OB001').status_code == 409
        assert outbound_service.get_outbound_record(db, 'OB001') is not None
        state['exists'] = False
        assert client.delete(f'{BASE}/OB001').status_code == 200
    assert state['posts'] == 1 and task.reason == 'deleted:77'


def test_locked_remote_restores_task_without_hiding_record(db, case, monkeypatch):
    user, _, task, _ = case
    def locked(*args): raise remote.DeleteRemoteError('小满单据被锁定，无法删除')
    monkeypatch.setattr(remote, 'remove', locked)
    with _pc_client(db, user, PERMS) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 409
    assert task.status == 'done' and task.reason == 'created: OLD'
    assert outbound_service.get_outbound_record(db, 'OB001') is not None


def test_remote_success_with_failed_local_commit_recovers_without_second_post(db, case, monkeypatch):
    user, _, _, state = case
    original = deletion._commit
    count = 0
    def fail_once(session):
        nonlocal count
        count += 1
        if count == 2:
            session.rollback()
            raise RuntimeError('simulated database outage')
        original(session)
    monkeypatch.setattr(deletion, '_commit', fail_once)
    record = outbound_service.get_outbound_record(db, 'OB001')
    with pytest.raises(RuntimeError): deletion.delete_outbound(db, record, user.id)
    assert deletion.delete_outbound(db, record, user.id)['deleted'] is True
    assert state['posts'] == 1


def test_missing_task_is_reserved_so_reconciliation_cannot_recreate_deleted_outbound(db, case, monkeypatch):
    from app.invoice.outbound_task_service import enqueue_outbound_task
    user, inv, task, state = case
    db.delete(task)
    db.commit()
    def remove(*args):
        state['posts'] += 1
        state['exists'] = False
    monkeypatch.setattr(remote, 'remove', remove)
    record = outbound_service.get_outbound_record(db, 'OB001')
    assert deletion.delete_outbound(db, record, user.id)['deleted']
    queued = enqueue_outbound_task(db, inv)
    assert queued.status == 'skipped' and queued.reason == 'deleted:77'
    assert state['posts'] == 1


def test_other_outbound_delete_hold_cannot_be_overwritten_by_second_delete(db, case):
    user, _, task, state = case
    task.status, task.reason = 'skipped', 'delete_pending:88'
    db.commit()
    with pytest.raises(deletion.OutboundDeleteError, match='另一张'):
        deletion.delete_outbound(db, outbound_service.get_outbound_record(db, 'OB001'), user.id)
    assert task.reason == 'delete_pending:88' and state['posts'] == 0
    assert db.query(ShippingOperationEvent).filter_by(scope=deletion.SCOPE).count() == 0


def test_already_missing_remote_still_holds_mirror_linked_task(db, case):
    user, _, task, state = case
    state['exists'] = False
    result = deletion.delete_outbound(db, outbound_service.get_outbound_record(db, 'OB001'), user.id)
    assert result['deleted'] and task.reason == 'deleted:77' and state['posts'] == 0


def test_uncertain_intent_can_recover_after_mirror_header_disappears(db, case, monkeypatch):
    user, _, _, state = case
    def timeout(*args):
        state['posts'] += 1
        raise remote.DeleteRemoteError('timeout', uncertain=True)
    monkeypatch.setattr(remote, 'remove', timeout)
    with _pc_client(db, user, ['shipping_inspection:read', 'shipping_inspection:delete']) as client:
        assert client.delete(f'{BASE}/OB001').status_code == 409
        db.execute(text("DELETE FROM lsordertest.okki_outbound_records WHERE id='OB001'"))
        db.commit()
        state['exists'] = False
        assert client.delete(f'{BASE}/OB001').status_code == 200
    assert state['posts'] == 1


def test_finished_receipt_cannot_be_downgraded_by_late_failed_response(db, case):
    user, _, task, _ = case
    record = outbound_service.get_outbound_record(db, 'OB001')
    deletion.delete_outbound(db, record, user.id)
    event = db.query(ShippingOperationEvent).filter_by(scope=deletion.SCOPE).one()
    assert deletion._finish(db, event, deletion.FAILED, 'late error')['deleted']
    assert event.action == deletion.DELETED and task.reason == 'deleted:77'


def test_remote_client_uses_query_id_and_does_not_retry_timeout(monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(remote.httpx, 'request', request)
    with pytest.raises(remote.DeleteRemoteError) as error: remote.remove('test', '77')
    assert error.value.uncertain
    assert len(calls) == 1 and calls[0][0] == 'POST'
    assert calls[0][1].endswith('/outbound/remove')
    assert calls[0][2]['params'] == {'outbound_invoice_id': '77'}


@pytest.mark.parametrize('code,message,missing', [(404, 'Not Found Resource', True), (404, '单据被锁定，无法操作', False), (404, 'Invalid query', False)])
def test_only_exact_not_found_proves_absence(monkeypatch, code, message, missing):
    monkeypatch.setattr(remote.httpx, 'request', lambda *a, **k: httpx.Response(200, json={'code': code, 'message': message}))
    if missing: assert remote.read('test', '77') is None
    else:
        with pytest.raises(remote.DeleteRemoteError): remote.read('test', '77')
