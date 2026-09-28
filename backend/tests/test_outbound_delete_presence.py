"""Deleted details stay readable: isolated DB + mock HTTP, no production writes."""
import httpx
import pytest
from sqlalchemy import text

from app.shipping_inspection import outbound_presence as presence
from app.shipping_inspection import outbound_delete_client as remote, outbound_delete_service as deletion
from app.shipping_inspection import outbound_reconcile_service as reconciliation, outbound_service
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection
from tests.test_outbound_delete import case, BASE, PERMS
from tests.test_shipping_inspection import _pc_client, outbound_scope_seed, product_display_source

REAL_READ = remote.read


def mock_pages(monkeypatch, pages):
    calls = []
    def request(method, url, **kw):
        assert method == 'GET' and url.endswith('/outbound/list')
        assert kw['params']['removed'] == 0 and kw['params']['time_type'] == 2
        assert 'status' not in kw['params']
        calls.append(kw['params'])
        body = pages.pop(0)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(200, json={'code': 200, 'data': body})
    monkeypatch.setattr(presence.httpx, 'request', request)
    return calls


def page(ids, count=None):
    return {'count': len(ids) if count is None else count,
            'list': [{'outbound_invoice_id': identity} for identity in ids]}


def rows(*ids):
    return {str(identity): {'outbound_invoice_id': str(identity)} for identity in ids}


def test_complete_stable_pagination_and_all_statuses(monkeypatch):
    monkeypatch.setattr(presence, 'PAGE_SIZE', 2)
    calls = mock_pages(monkeypatch, [page([11, 22], 3), page([33], 3)] * 2)
    assert presence.active_ids('test', '2026-09-01 12:10:11') == {'11', '22', '33'}
    assert [p['start_index'] for p in calls] == [1, 2, 1, 2]
    assert all(p['start_time'] == '2026-09-01 00:00:00' for p in calls)


def test_creation_day_snapshot_has_fixed_bounds_and_creation_time_filter(monkeypatch):
    monkeypatch.setattr(presence, 'PAGE_SIZE', 2)
    calls = mock_pages(monkeypatch, [page([11, 22], 3), page([33], 3)] * 2)

    rows = presence.active_rows_for_day('test', '2026-09-01')

    assert set(rows) == {'11', '22', '33'}
    assert [p['start_index'] for p in calls] == [1, 2, 1, 2]
    assert all(p['start_time'] == '2026-09-01 00:00:00' for p in calls)
    assert all(p['end_time'] == '2026-09-01 23:59:59' for p in calls)
    assert all(p['time_type'] == 2 for p in calls)


def test_reconcile_refreshes_only_bounded_creation_days(db, sync_case, monkeypatch):
    monkeypatch.setattr(reconciliation, 'MAX_SNAPSHOT_DAYS_PER_RUN', 2)
    monkeypatch.setattr(reconciliation, 'beijing_today', lambda: __import__('datetime').date(2026, 9, 21))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET create_time='2026-09-20 14:16:08'"))
    db.commit()
    called = []

    def snapshot(_token, creation_day):
        called.append(str(creation_day))
        return {
            '77': {'outbound_invoice_id': '77', 'create_time': f'{creation_day} 14:16:08'},
            '88': {'outbound_invoice_id': '88', 'create_time': f'{creation_day} 14:17:08'},
        }

    monkeypatch.setattr(presence, 'active_rows_for_day', snapshot)
    stats = reconciliation.reconcile_deleted_outbounds(db)

    assert called == ['2026-09-20', '2026-09-21', '2026-09-21']
    assert stats['snapshot_days'] == 2
    assert stats['checked'] == 2
    saved = db.execute(text(
        "SELECT status, record_count FROM ark_okki_outbound_presence_days "
        "WHERE creation_date='2026-09-20'"
    )).mappings().one()
    assert saved == {'status': 'ready', 'record_count': 2}


def test_snapshot_detail_lookup_is_capped_without_deletion(db, sync_case, monkeypatch):
    monkeypatch.setattr(reconciliation, 'MAX_SNAPSHOT_DAYS_PER_RUN', 2)
    monkeypatch.setattr(reconciliation, 'MAX_SNAPSHOT_DETAIL_LOOKUPS', 1)
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: {
        '88': {'outbound_invoice_id': '88', 'create_time': '2026-09-21 14:16:08'},
        '99': {'outbound_invoice_id': '99', 'create_time': '2026-09-21 14:17:08'},
    })
    db.execute(text('DELETE FROM lsordertest.okki_outbound_record_items'))
    db.commit()

    calls = []
    monkeypatch.setattr(reconciliation.okki_client, '_get_json', lambda *a, **k: (
        calls.append(k['params']['outbound_invoice_id']) or
        {'outbound_invoice_id': k['params']['outbound_invoice_id'], 'record_list': []}
    ))
    stats = reconciliation.reconcile_deleted_outbounds(db)

    assert stats['snapshot_errors'] == 0
    assert len(calls) == 1
    assert db.query(ShippingOperationEvent).count() == 0
    saved = db.execute(text(
        "SELECT status, pending_detail_ids FROM ark_okki_outbound_presence_days "
        "WHERE creation_date='2026-09-22'"
    )).mappings().one()
    assert saved['status'] == 'pending'
    assert len(__import__('json').loads(saved['pending_detail_ids'])) == 2


def test_snapshot_detail_lookup_uses_short_timeout(db, sync_case, monkeypatch):
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: rows(99))
    calls = []

    def detail(*args, **kwargs):
        calls.append(kwargs)
        return {'outbound_invoice_id': '99', 'record_list': []}

    monkeypatch.setattr(reconciliation.okki_client, '_get_json', detail)
    row = reconciliation._scan_snapshot_day(
        db, 'test', __import__('datetime').date(2026, 9, 21), {},
    )
    complete = reconciliation._hydrate_snapshot_day(db, 'test', row, {'remaining': 1})

    assert complete
    assert calls[0]['timeout'] == reconciliation.SNAPSHOT_DETAIL_TIMEOUT_SECONDS == 15


def test_snapshot_detail_progress_resumes_across_bounded_runs(db, sync_case, monkeypatch):
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: rows(101, 102, 103))
    calls = []

    def detail(*args, **kwargs):
        identity = kwargs['params']['outbound_invoice_id']
        calls.append(identity)
        return {'outbound_invoice_id': identity, 'record_list': [{'order_id': int(identity) + 1000}]}

    monkeypatch.setattr(reconciliation.okki_client, '_get_json', detail)
    day = __import__('datetime').date(2026, 9, 21)
    for remaining in (2, 1, 0):
        row = reconciliation._scan_snapshot_day(db, 'test', day, {})
        reconciliation._hydrate_snapshot_day(db, 'test', row, {'remaining': 1})
        db.refresh(row)
        assert len(row.pending_detail_ids) == remaining
    assert calls == ['101', '102', '103']
    assert row.status == 'ready'
    assert set(row.retained_order_ids) == {'1101', '1102', '1103'}


def test_changed_active_row_requeues_only_its_detail_association(db, sync_case, monkeypatch):
    day = __import__('datetime').date(2026, 9, 21)
    version = {'value': 'A'}
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: {
        '101': {'outbound_invoice_id': '101', 'update_time': version['value']}
    })
    monkeypatch.setattr(reconciliation.okki_client, '_get_json', lambda *a, **k: {
        'outbound_invoice_id': '101', 'record_list': [{'order_id': 1101}]
    })
    row = reconciliation._scan_snapshot_day(db, 'test', day, {'101': {'999'}})
    assert row.status == 'ready' and row.retained_order_ids == ['999']
    version['value'] = 'B'
    row = reconciliation._scan_snapshot_day(db, 'test', day, {'101': {'999'}})
    assert row.status == 'pending' and row.pending_detail_ids == ['101']
    assert row.detail_order_ids == {} and row.retained_order_ids == []
    row = reconciliation._scan_snapshot_day(db, 'test', day, {'101': {'999'}})
    assert row.status == 'pending' and row.pending_detail_ids == ['101']

    assert reconciliation._hydrate_snapshot_day(db, 'test', row, {'remaining': 1})
    assert row.detail_order_ids == {'101': ['1101']}
    assert row.retained_order_ids == ['1101']


def test_failed_detail_consumes_global_budget_and_keeps_cursor(db, sync_case, monkeypatch):
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: rows(101, 102))
    day = __import__('datetime').date(2026, 9, 21)
    row = reconciliation._scan_snapshot_day(db, 'test', day, {})
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs['params']['outbound_invoice_id'])
        raise reconciliation.okki_client.OkkiApiError('timeout')

    monkeypatch.setattr(reconciliation.okki_client, '_get_json', fail)
    budget = {'remaining': 1}
    with pytest.raises(reconciliation.okki_client.OkkiApiError):
        reconciliation._hydrate_snapshot_day(db, 'test', row, budget)
    db.rollback()
    db.refresh(row)
    assert budget['remaining'] == 0 and calls == ['101']
    assert row.pending_detail_ids == ['101', '102']


def test_shared_budget_stays_hard_capped_after_one_day_fails(db, sync_case, monkeypatch):
    day_type = __import__('datetime').date
    current = {'ids': ('101',)}
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *_: rows(*current['ids']))
    first = reconciliation._scan_snapshot_day(db, 'test', day_type(2026, 9, 20), {})
    current['ids'] = tuple(str(value) for value in range(201, 221))
    second = reconciliation._scan_snapshot_day(db, 'test', day_type(2026, 9, 21), {})
    calls = []

    def detail(*args, **kwargs):
        identity = kwargs['params']['outbound_invoice_id']
        calls.append(identity)
        if identity == '101':
            raise reconciliation.okki_client.OkkiApiError('timeout')
        return {'outbound_invoice_id': identity, 'record_list': []}

    monkeypatch.setattr(reconciliation.okki_client, '_get_json', detail)
    budget = {'remaining': 16}
    with pytest.raises(reconciliation.okki_client.OkkiApiError):
        reconciliation._hydrate_snapshot_day(db, 'test', first, budget)
    db.rollback()
    reconciliation._hydrate_snapshot_day(db, 'test', second, budget)

    assert len(calls) == 16 and budget['remaining'] == 0
    assert len(second.pending_detail_ids) == 5


@pytest.mark.parametrize('pages', [
    [page([11], 2)],                       # incomplete page
    [page([11, 11])],                     # duplicated IDs
    [page([None])],                       # invalid ID
    [{'list': [], 'count': True}],        # malformed count
    [page([11]), page([22])],             # same count, changed membership
    [page([]), httpx.ReadTimeout('no')],   # failed second confirmation
    [page([11, 22], 3), page([], 2)],      # count changes mid-pagination
])
def test_bad_or_changing_snapshot_never_proves_absence(monkeypatch, pages):
    monkeypatch.setattr(presence, 'PAGE_SIZE', 2)
    mock_pages(monkeypatch, pages)
    with pytest.raises(presence.PresenceError):
        presence.active_ids('test', '2026-09-01 00:00:00')


def test_scan_limit_never_returns_partial_index(monkeypatch):
    monkeypatch.setattr(presence, 'MAX_PAGES', 1)
    monkeypatch.setattr(presence, 'PAGE_SIZE', 1)
    mock_pages(monkeypatch, [page([11], 2)])
    with pytest.raises(presence.PresenceError):
        presence.active_ids('test', '2026-09-01 00:00:00')


@pytest.mark.parametrize('status', [1, 2])
def test_detail_status_does_not_override_verified_list_absence(monkeypatch, status):
    detail = {'outbound_invoice_id': 77, 'status': status, 'create_time': '2026-09-21 14:16:08'}
    monkeypatch.setattr(remote, '_request', lambda *a, **k: detail)
    mock_pages(monkeypatch, [page([88]), page([88])])
    assert REAL_READ('test', '77') is None


def test_active_detail_is_preserved_and_list_failure_is_not_missing(monkeypatch):
    detail = {'outbound_invoice_id': 77, 'status': 2, 'create_time': '2026-09-21 14:16:08'}
    monkeypatch.setattr(remote, '_request', lambda *a, **k: detail)
    mock_pages(monkeypatch, [page([77]), page([77])])
    assert REAL_READ('test', '77') == detail
    mock_pages(monkeypatch, [page([], 1)])
    with pytest.raises(remote.DeleteRemoteError):
        REAL_READ('test', '77')


def test_missing_creation_time_never_guesses_absence(monkeypatch):
    monkeypatch.setattr(remote, '_request', lambda *a, **k: {'outbound_invoice_id': 77, 'status': 1})
    with pytest.raises(remote.DeleteRemoteError):
        REAL_READ('test', '77')


def test_delete_succeeds_when_detail_stays_pending_after_actual_delete(db, case, monkeypatch):
    user, _, task, state = case
    monkeypatch.setattr(remote, 'read', REAL_READ)
    def request(method, url, **kw):
        if url.endswith('/info'):
            data = {'outbound_invoice_id': 77, 'status': 1, 'create_time': '2026-09-21 14:16:08',
                    'company_info': {'id': 'C1'}, 'record_list': [{'order_id': 123}]}
        else:
            assert method == 'GET' and url.endswith('/list')
            data = page([77] if state['exists'] else [])
        return httpx.Response(200, json={'code': 200, 'data': data})
    monkeypatch.setattr(remote.httpx, 'request', request)
    with _pc_client(db, user, PERMS) as client:
        assert client.delete(f'{BASE}/OB001').json()['data']['deleted']
        assert client.get(f'{BASE}/OB001/print-data').status_code == 404
        assert client.delete(f'{BASE}/OB001').status_code == 200
    assert state['posts'] == 1 and task.reason == 'deleted:77'


@pytest.fixture
def sync_case(db, case, monkeypatch):
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN create_time TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET create_time='2026-09-21 14:16:08'"))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='88' WHERE id != 'OB001'"))
    db.commit()
    outbound_service._columns_cache.clear()
    monkeypatch.setattr(reconciliation, 'beijing_today', lambda: __import__('datetime').date(2026, 9, 22))
    monkeypatch.setattr(reconciliation, 'ensure_access_token', lambda db: 'test')
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *args: rows(88))
    monkeypatch.setattr(reconciliation.okki_client, '_get_json', lambda *a, **k:
                        {'outbound_invoice_id': k['params']['outbound_invoice_id'], 'record_list': []})
    return case


def test_direct_xiaoman_deletion_auto_hides_mirror_without_post_or_media_loss(db, sync_case):
    user, _, task, state = sync_case
    db.add(ShippingInspection(outbound_record_id='OB001', status='submitted', created_by=user.id))
    db.commit()
    stats = reconciliation.reconcile_deleted_outbounds(db)
    assert stats['deleted'] == 1 and state['posts'] == 0
    assert task.status == 'skipped' and task.reason == 'deleted:77'
    assert outbound_service.get_outbound_record(db, 'OB001') is None
    assert db.query(ShippingInspection).count() == 1
    assert db.execute(text("SELECT COUNT(*) FROM lsordertest.okki_outbound_records WHERE id='OB001'")).scalar() == 1
    event = db.query(ShippingOperationEvent).filter_by(request_id='77').one()
    assert event.source == 'scheduler' and event.operator_name == '系统同步'
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 0


def test_current_day_snapshot_never_proves_candidate_absence(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    today = reconciliation.beijing_today().isoformat()
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET create_time=:stamp"),
               {'stamp': f'{today} 09:00:00'})
    db.commit()
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *args: rows(88))

    stats = reconciliation.reconcile_deleted_outbounds(db)

    assert stats['coverage_ready'] and stats['checked'] == 0 and stats['deleted'] == 0
    assert stats['deferred'] == 2
    assert task.status == 'done'
    assert db.query(ShippingOperationEvent).count() == 0


def test_current_day_change_after_hydration_blocks_historical_deletion(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    calls = []

    def snapshot(_token, creation_day):
        calls.append(str(creation_day))
        if str(creation_day) == '2026-09-22' and calls.count('2026-09-22') == 2:
            return rows(88, 99)
        return rows(88)

    monkeypatch.setattr(presence, 'active_rows_for_day', snapshot)
    stats = reconciliation.reconcile_deleted_outbounds(db)

    assert stats['snapshot_errors'] == 1 and stats['deleted'] == 0
    assert not stats['coverage_ready'] and stats['deferred'] == 2
    assert task.status == 'done' and db.query(ShippingOperationEvent).count() == 0


def test_failed_snapshot_does_not_write_tombstone_or_task(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    def fail(*args):
        raise presence.PresenceError('incomplete')
    monkeypatch.setattr(presence, 'active_rows_for_day', fail)
    assert reconciliation.reconcile_deleted_outbounds(db)['snapshot_errors'] > 0
    assert db.query(ShippingOperationEvent).count() == 0
    assert task.status == 'done'


@pytest.mark.parametrize('state', ['running', 'uncertain', 'linked', 'changed'])
def test_scheduler_defers_concurrent_business_changes(db, sync_case, monkeypatch, state):
    _, inv, task, _ = sync_case
    if state == 'linked':
        inv.linked_sync_id = 'busy'
    elif state == 'changed':
        def change_during_scan(*args):
            task.reason = 'created: replacement'
            task.attempts += 1
            db.commit()
            return rows(88)
        monkeypatch.setattr(presence, 'active_rows_for_day', change_during_scan)
    else:
        task.status = state
    db.commit()
    assert reconciliation.reconcile_deleted_outbounds(db)['deferred'] == 1
    assert outbound_service.get_outbound_record(db, 'OB001') is not None


def test_scheduler_finishes_uncertain_receipt_without_sending_again(db, sync_case, monkeypatch):
    user, _, task, state = sync_case
    def timeout(*args):
        state['posts'] += 1
        raise remote.DeleteRemoteError('timeout', uncertain=True)
    monkeypatch.setattr(remote, 'remove', timeout)
    with pytest.raises(deletion.OutboundDeleteError):
        deletion.delete_outbound(db, outbound_service.get_outbound_record(db, 'OB001'), user.id)
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 1
    assert task.reason == 'deleted:77' and state['posts'] == 1


def test_replacement_outbound_keeps_its_task_when_old_mirror_is_hidden(db, sync_case):
    _, _, task, _ = sync_case
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='88',order_id='123' WHERE outbound_record_id != 'OB001'"))
    task.reason = 'created: replacement'
    db.commit()
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 1
    assert task.status == 'done' and task.reason == 'created: replacement'


def test_missing_task_is_held_after_external_delete(db, sync_case):
    from app.invoice.models import OkkiOutboundTask
    _, inv, task, _ = sync_case
    db.delete(task)
    db.commit()
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 1
    assert db.query(OkkiOutboundTask).filter_by(invoice_id=inv.id).one().reason == 'deleted:77'


def test_pending_receipt_recovers_even_after_header_sync_removed_it(db, sync_case, monkeypatch):
    user, _, task, state = sync_case
    original_read = remote.read
    def read(*args):
        return {**original_read(*args), 'create_time': '2026-09-21 14:16:08'}
    monkeypatch.setattr(remote, 'read', read)
    def timeout(*args):
        state['posts'] += 1
        raise remote.DeleteRemoteError('timeout', uncertain=True)
    monkeypatch.setattr(remote, 'remove', timeout)
    with pytest.raises(deletion.OutboundDeleteError):
        deletion.delete_outbound(db, outbound_service.get_outbound_record(db, 'OB001'), user.id)
    db.execute(text("DELETE FROM lsordertest.okki_outbound_records WHERE id='OB001'"))
    db.commit()
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 1
    assert task.reason == 'deleted:77' and state['posts'] == 1


def test_scheduler_job_is_independent_of_automatic_creation(db, sync_case, monkeypatch):
    from unittest.mock import MagicMock
    from contextlib import nullcontext
    from app.schedulers import registry
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'OKKI_OUTBOUND_AUTO_ENABLED', False)
    monkeypatch.setattr(settings, 'OKKI_CLIENT_ID', 'test')
    monkeypatch.setattr(settings, 'OKKI_CLIENT_SECRET', 'test')
    monkeypatch.setattr(registry, 'SessionLocal', lambda: nullcontext(db))
    scheduler = MagicMock()
    registry._register_jobs(scheduler)
    calls = {call.kwargs.get('id'): call for call in scheduler.add_job.call_args_list}
    assert registry.JOB_OKKI_OUTBOUND_RECONCILE not in calls
    job = calls[registry.JOB_OKKI_OUTBOUND_DELETE_RECONCILE]
    assert job.kwargs['minutes'] == 15 and job.kwargs['max_instances'] == 1
    job.args[0]()
    assert outbound_service.get_outbound_record(db, 'OB001') is None


def test_live_replacement_without_any_mirror_rows_keeps_task(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    task.reason = 'created: replacement'
    db.commit()
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *a: rows(88, 99))
    monkeypatch.setattr(reconciliation.okki_client, '_get_json', lambda *a, **k:
                        {'outbound_invoice_id': k['params']['outbound_invoice_id'],
                         'record_list': [{'order_id': 123}] if k['params']['outbound_invoice_id'] == '99' else []})
    assert reconciliation.reconcile_deleted_outbounds(db)['deleted'] == 1
    assert task.status == 'done' and task.reason == 'created: replacement'


def test_same_second_poller_completion_during_snapshot_is_deferred(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    stamp = deletion.beijing_now().replace(microsecond=0)
    task.updated_at = stamp
    db.commit()
    def complete(*args):
        task.attempts += 1
        task.updated_at = stamp  # Production poller and MySQL DATETIME use seconds.
        db.commit()
        return rows(88)
    monkeypatch.setattr(presence, 'active_rows_for_day', complete)
    assert reconciliation.reconcile_deleted_outbounds(db)['deferred'] == 1
    assert task.status == 'done' and task.reason == 'created: OLD'


def test_live_replacement_lookup_failure_never_changes_local_state(db, sync_case, monkeypatch):
    _, _, task, _ = sync_case
    monkeypatch.setattr(presence, 'active_rows_for_day', lambda *a: rows(88, 99))
    monkeypatch.setattr(reconciliation.okki_client, '_get_json', lambda *a, **k: None)
    assert reconciliation.reconcile_deleted_outbounds(db)['snapshot_errors'] > 0
    assert task.status == 'done' and db.query(ShippingOperationEvent).count() == 0


@pytest.mark.parametrize('http_status,body', [
    (401, {'code': 200, 'data': page([])}),
    (500, {'code': 200, 'data': page([])}),
    (200, {'code': 404, 'message': 'Not Found Resource'}),
    (200, {'code': 200, 'data': {}}),
])
def test_list_errors_cannot_be_treated_as_an_empty_list(monkeypatch, http_status, body):
    monkeypatch.setattr(presence.httpx, 'request', lambda *a, **k: httpx.Response(http_status, json=body))
    with pytest.raises(presence.PresenceError):
        presence.active_ids('test', '2026-09-21 00:00:00')
