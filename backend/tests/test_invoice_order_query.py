"""Real SQLite state transitions; all supplier I/O is GET-only test evidence."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, update

from app.auth.models import ArkRole, ArkUserRole
from app.core.time import beijing_now
from app.invoice import order_query_recovery as recovery, order_query_plan as plan
from app.invoice import order_push_facts as facts, order_sync_execution as push, service, xiaoman_service
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import ReceiptIntent, Receipt
from app.portal.event_models import AuditEvent
from tests.test_invoice_outbound_tasks import _make_invoice, _seed_settings, _seed_binding, _stock_item


@pytest.fixture
def case(db, monkeypatch, request):
    clock = SimpleNamespace(now=datetime(2026, 10, 26, 12, 0, 0))
    monkeypatch.setattr(recovery, 'beijing_now', lambda: clock.now)
    def seed_event_time(mapper, connection, target):
        target.created_at = clock.now - timedelta(minutes=6)
    event.listen(AuditEvent, 'before_insert', seed_event_time)
    request.addfinalizer(lambda: event.remove(AuditEvent, 'before_insert', seed_event_time))
    _seed_settings(db); _seed_binding(db)
    role = ArkRole(name='super_admin', label='Admin')
    db.add(role); db.flush(); db.add(ArkUserRole(user_id=1, role_id=role.id))
    invoice = _make_invoice(db, order_type='stock', status='sync_uncertain', sync_status='sync_uncertain',
        product_amount=Decimal('37.50'), total_amount=Decimal('44.50'), shipping_fee=Decimal('5'),
        surcharge_amount=Decimal('2'))
    invoice.items.append(_stock_item())
    invoice.sync_attempt = {'token': 'private-original-token', 'attempt_key': str(uuid4()),
        'lease_until': (clock.now - timedelta(minutes=1)).isoformat()}
    db.add(ReceiptIntent(invoice_id=invoice.id, eligible=1, status='armed', amount=Decimal('43.49'),
        bank_charge=0, currency='USD', customer_id=invoice.customer_id, payment_type='Other',
        created_by=1, attachment_ids=[]))
    db.commit(); db.refresh(invoice)
    payload, _, issues = xiaoman_service.build_push_payload(db, invoice)
    assert not issues
    from app.core import config
    with monkeypatch.context() as origin:
        origin.setattr(config, 'get_settings', lambda: SimpleNamespace(
            OKKI_OUTBOUND_AUTO_ENABLED=getattr(request, 'param', True)))
        attempt = facts.start(db, invoice, 1, push.capture(db, invoice, payload), payload, None, None)
    facts.record(db, attempt, facts.observation(attempt, 1, 'unknown'))
    db.commit()
    remote = {'order_id': '424242', 'order_no': '26917', 'name': invoice.invoice_no,
        'company_id': invoice.customer_id, 'currency': 'USD', 'account_date': payload['account_date'] + ' 00:00:00',
        'handler': payload['handler'], 'amount': 42.5, 'create_time': '2026-10-26 11:54:01',
        'status': payload['status'], 'create_user': payload['create_user'],
        'remark': payload.get('remark', ''),
        **{key: value for key, value in payload.items() if key.isdecimal()},
        'users': deepcopy(payload['users']), 'departments': deepcopy(payload['departments']),
        'product_list': [{**r, 'unique_id': str(6001 + n)} for n, r in enumerate(payload['product_list'])],
        'cost_list': deepcopy(payload['cost_list'])}
    identity = invoice.id
    db.rollback()
    calls = []
    def get(path, token, *, context, params, timeout):
        assert not db.in_transaction(), 'GET held a local transaction'
        calls.append((path, deepcopy(params)))
        if path.endswith('/list'):
            return {'count': 1, 'list': [{'order_id': '424242', 'name': remote['name']}]}
        return deepcopy(remote)
    monkeypatch.setattr(recovery.okki_client, '_get_json', get)
    monkeypatch.setattr(push, 'token', lambda *args, **kwargs: 'test-token')
    monkeypatch.setattr(recovery.okki_client, '_post_json', lambda *args, **kwargs: pytest.fail('Unexpected supplier POST'))
    monkeypatch.setattr(recovery, 'get_settings', lambda: SimpleNamespace(
        OKKI_OUTBOUND_AUTO_ENABLED=True, INVOICE_ORDER_QUERY_RECOVERY_ENABLED=True))
    db.info['stock_executor_fence'] = True
    return SimpleNamespace(db=db, id=identity, key=attempt.key, remote=remote, calls=calls, clock=clock)


def test_get_recovery_binds_once_queues_and_preserves_receipt_intent(case):
    c = case
    intent_before = push.state(c.db.scalar(select(ReceiptIntent)))
    c.db.rollback()
    assert recovery.recover(c.db, c.id) == {'status': 'verified'}
    invoice = service.get_invoice(c.db, c.id)
    assert (invoice.xiaoman_order_id, invoice.xiaoman_order_no, invoice.sync_status) == ('424242', '26917', 'synced')
    assert invoice.items[0].xiaoman_unique_id == '6001'
    assert len(c.db.scalars(select(OkkiOutboundTask)).all()) == 1
    assert not facts.unresolved(c.db, invoice)
    assert push.state(c.db.scalar(select(ReceiptIntent))) == intent_before
    assert not c.db.scalar(select(Receipt.id))
    success = c.db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.success == 1))
    assert success and 'automatic_get_only' in success.response_body
    c.db.rollback()
    with pytest.raises(ValueError):
        recovery.recover(c.db, c.id)
    assert len(c.calls) == 4


@pytest.mark.parametrize('fault', ['amount', 'quantity', 'fees', 'uid', 'company', 'old_order', 'sales_split', 'department_split', 'remark', 'flag'])
def test_nonmatching_provider_evidence_never_changes_business(case, fault):
    c = case
    if fault == 'amount': c.remote['amount'] = 99
    if fault == 'quantity': c.remote['product_list'][0]['count'] = 99
    if fault == 'fees': c.remote['cost_list'][0]['cost'] = 99
    if fault == 'uid': c.remote['product_list'][0].pop('unique_id')
    if fault == 'company': c.remote['company_id'] = 'different'
    if fault == 'old_order': c.remote['create_time'] = '2026-10-26 08:00:00'
    if fault == 'sales_split': c.remote['users'][0]['rate'] = 50
    if fault == 'department_split': c.remote['departments'][0]['rate'] = 50
    if fault == 'remark': c.remote['remark'] = 'External edit'
    if fault == 'flag': c.remote[xiaoman_service.FIELD_NEW_DEAL] = 'changed'
    assert recovery.recover(c.db, c.id)['status'] == 'unverified'
    invoice = c.db.get(Invoice, c.id)
    assert invoice.xiaoman_order_id is None and invoice.sync_status == 'sync_uncertain'
    assert not c.db.scalar(select(OkkiOutboundTask.id))
    assert not c.db.scalar(select(Receipt.id))


@pytest.mark.parametrize('fault', ['empty', 'multiple', 'changing', 'incomplete', 'timeout', 'malformed'])
def test_incomplete_or_ambiguous_index_never_posts_or_binds(case, monkeypatch, fault):
    c = case
    def get(*args, **kwargs):
        c.calls.append(1)
        if fault == 'timeout': raise recovery.okki_client.OkkiApiError('GET timed out')
        if fault == 'empty': return {'count': 0, 'list': []}
        if fault == 'incomplete': return {'list': []}
        if fault == 'malformed': return {'count': 1, 'list': [None]}
        if fault == 'changing' and len(c.calls) == 2: return {'count': 0, 'list': []}
        return {'count': 2, 'list': [{'order_id': '424242', 'name': c.remote['name']},
                                    {'order_id': '424243', 'name': c.remote['name']}]}
    monkeypatch.setattr(recovery.okki_client, '_get_json', get)
    assert recovery.recover(c.db, c.id)['status'] == 'unverified'
    assert c.db.get(Invoice, c.id).xiaoman_order_id is None


def test_retry_budget_survives_runs_and_does_not_repeat_posts(case, monkeypatch):
    c = case
    monkeypatch.setattr(recovery.okki_client, '_get_json', lambda *args, **kw: {'count': 0, 'list': []})
    for n in range(3):
        assert recovery.recover(c.db, c.id)['status'] == 'unverified'
        assert recovery.recover(c.db, c.id)['status'] == 'deferred'
        c.clock.now += timedelta(minutes=10)
    assert recovery.recover(c.db, c.id)['status'] == 'deferred'
    assert all(facts.get(c.db, c.id, c.key, recovery.CLAIM + ':' + str(n)) for n in (1, 2, 3))
    assert c.db.get(Invoice, c.id).sync_status == 'sync_uncertain'


@pytest.mark.parametrize('change', ['receipt', 'invoice', 'permission'])
def test_state_or_authority_change_during_get_blocks_recovery(case, monkeypatch, change):
    c = case
    original = recovery.okki_client._get_json
    called = False
    def get(*args, **kwargs):
        nonlocal called
        result = original(*args, **kwargs)
        if not called:
            called = True
            if change == 'receipt':
                c.db.scalar(select(ReceiptIntent)).amount = Decimal('40')
            elif change == 'invoice':
                c.db.get(Invoice, c.id).remark = 'Concurrent edit'
            else:
                monkeypatch.setattr(recovery.edit_authority, 'prepare_recovery',
                    lambda *a, **kw: (_ for _ in ()).throw(HTTPException(403, 'revoked')))
            if change != 'permission': c.db.commit()
        return result
    monkeypatch.setattr(recovery.okki_client, '_get_json', get)
    with pytest.raises((ValueError, HTTPException)):
        recovery.recover(c.db, c.id)
    assert c.db.get(Invoice, c.id).xiaoman_order_id is None
    assert not c.db.scalar(select(OkkiOutboundTask.id))


@pytest.mark.parametrize('kind', ['active_lease', 'production', 'content_changed', 'historical'])
def test_ineligible_original_attempt_is_not_queried(case, kind):
    c = case
    invoice = c.db.get(Invoice, c.id)
    if kind == 'active_lease': invoice.sync_attempt = {**invoice.sync_attempt, 'lease_until': (c.clock.now + timedelta(minutes=1)).isoformat()}
    if kind == 'production': invoice.order_type = 'production'
    if kind == 'content_changed': invoice.remark = 'Changed before recovery'
    if kind == 'historical':
        source = facts.get(c.db, c.id, c.key, facts.START)
        data = dict(source.safe_diff_json); data.pop('auto_query_version')
        # Isolated fixture represents a START persisted by the pre-feature version.
        c.db.execute(update(AuditEvent).where(AuditEvent.id == source.id).values(safe_diff_json=data))
    c.db.commit()
    if kind == 'historical': assert recovery.recover(c.db, c.id)['status'] == 'deferred'
    else:
        with pytest.raises(ValueError): recovery.recover(c.db, c.id)
    assert not c.calls


def test_disabled_outbound_does_not_disable_query_or_release_receipt(case, monkeypatch):
    monkeypatch.setattr(recovery, 'get_settings', lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=False))
    assert recovery.recover(case.db, case.id)['status'] == 'verified'
    assert not case.db.scalar(select(OkkiOutboundTask.id))
    assert case.db.scalar(select(ReceiptIntent)).status == 'armed'


def test_window_crosses_beijing_midnight_without_using_invoice_date():
    lower, upper = plan.window(datetime(2026, 10, 25, 23, 59, 50), '2026-10-26T00:04:50')
    assert lower.date() != upper.date()
    with pytest.raises(ValueError): plan.window(lower, '2026-10-27T00:04:50')


def test_midnight_candidate_is_found_across_both_beijing_dates(case):
    c = case
    c.remote['create_time'] = '2026-10-26 00:00:01'
    request = facts.get(c.db, c.id, c.key, facts.START).safe_diff_json['query_request']
    invoice = c.db.get(Invoice, c.id)
    target = SimpleNamespace(customer_id=invoice.customer_id, currency=invoice.currency,
        total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)
    c.db.rollback()
    params_seen = []
    def read(path, params):
        params_seen.append(params)
        if path.endswith('/list'):
            return {'count': 1, 'list': [{'order_id': '424242', 'name': c.remote['name']}]}
        return deepcopy(c.remote)
    plan.find(read, target, request, datetime(2026, 10, 25, 23, 59, 50), datetime(2026, 10, 26, 0, 4, 50))
    assert params_seen[0]['start_time'] == '2026-10-25 00:00:00'
    assert params_seen[0]['end_time'] == '2026-10-26 23:59:59'


@pytest.mark.parametrize('case', [False], indirect=True)
def test_original_disabled_outbound_remains_disabled_after_switch_on(case):
    assert recovery.recover(case.db, case.id)['status'] == 'verified'
    assert not case.db.scalar(select(OkkiOutboundTask.id))
    assert case.db.scalar(select(ReceiptIntent)).status == 'armed'


def test_crashed_query_consumes_durable_budget_before_network(case, monkeypatch):
    c = case
    monkeypatch.setattr(recovery.okki_client, '_get_json',
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt): recovery.recover(c.db, c.id)
    assert facts.get(c.db, c.id, c.key, recovery.CLAIM + ':1') is not None
    c.db.rollback()
    assert recovery.recover(c.db, c.id)['status'] == 'deferred'
    c.clock.now += timedelta(minutes=10)
    monkeypatch.setattr(recovery.okki_client, '_get_json', lambda *a, **kw: {'count': 0, 'list': []})
    from sqlalchemy.orm import Session
    with Session(c.db.get_bind()) as restarted:
        restarted.info['stock_executor_fence'] = True
        assert recovery.recover(restarted, c.id)['status'] == 'unverified'
        assert facts.get(restarted, c.id, c.key, recovery.CLAIM + ':2') is not None


def test_recovery_does_not_accept_candidate_that_changes_during_get(case, monkeypatch):
    c = case
    original = recovery.okki_client._get_json
    def get(path, *args, **kwargs):
        data = original(path, *args, **kwargs)
        if path.endswith('/info') and sum(p.endswith('/info') for p, _ in c.calls) == 2:
            data['update_time'] = 'changed'
        return data
    monkeypatch.setattr(recovery.okki_client, '_get_json', get)
    assert recovery.recover(c.db, c.id)['status'] == 'unverified'
    assert c.db.get(Invoice, c.id).xiaoman_order_id is None


def test_scheduler_is_single_instance_and_independent_of_outbound_switch(monkeypatch):
    from unittest.mock import Mock
    from app.core.config import Settings
    from app.schedulers import registry
    for enabled in (False, True):
        settings = Settings(_env_file=None).model_copy(update={
            'INVOICE_ORDER_QUERY_RECOVERY_ENABLED': enabled, 'OKKI_OUTBOUND_AUTO_ENABLED': False})
        monkeypatch.setattr(registry, 'get_settings', lambda: settings)
        scheduler = Mock()
        registry._register_jobs(scheduler, outbound_mode='legacy')
        jobs = {call.kwargs['id']: call for call in scheduler.add_job.call_args_list}
        assert ('invoice_order_query_recovery' in jobs) is enabled
        if enabled:
            assert jobs['invoice_order_query_recovery'].kwargs['seconds'] == 60
            assert jobs['invoice_order_query_recovery'].kwargs['max_instances'] == 1


def test_scheduler_uses_owned_session_factory(monkeypatch):
    from app.schedulers import invoice_query
    seen = []
    monkeypatch.setattr(invoice_query, 'run_once', lambda factory: seen.append(factory))
    invoice_query.recover_uncertain_orders()
    assert seen == [invoice_query.SessionLocal]


def test_scheduled_scan_recovers_candidate_with_real_json_selection(case, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.orm import sessionmaker
    c = case
    @contextmanager
    def fence(db):
        assert not db.in_transaction()
        db.info['stock_executor_fence'] = True
        try: yield True
        finally: db.info.pop('stock_executor_fence', None)
    monkeypatch.setattr(recovery.outbound_mode, 'executor_fence', fence)
    c.db.rollback()
    factory = sessionmaker(bind=c.db.get_bind(), autoflush=False)
    result = recovery.run_once(factory)
    assert result == {'status': 'complete', 'processed': 1, 'verified': 1}
    c.db.expire_all()
    assert c.db.get(Invoice, c.id).sync_status == 'synced'


def test_disabled_scheduler_never_opens_a_session(monkeypatch):
    monkeypatch.setattr(recovery, 'get_settings', lambda: SimpleNamespace(INVOICE_ORDER_QUERY_RECOVERY_ENABLED=False))
    result = recovery.run_once(lambda: pytest.fail('Disabled worker opened a session'))
    assert result == {'status': 'disabled', 'processed': 0}


def test_semifinished_allocation_is_not_implicitly_finalized(case):
    from app.semifinished.models import InvoiceAllocation
    c = case
    c.db.add(InvoiceAllocation(invoice_id=c.id, material_id=1, status='pending',
        operation_key='preserved-allocation', pending_delta_grams=100))
    c.db.commit()
    with pytest.raises(ValueError, match='Semifinished'):
        recovery.recover(c.db, c.id)
    assert not c.calls
    assert c.db.scalar(select(InvoiceAllocation)).pending_delta_grams == 100


def test_enterprise_root_department_zero_is_valid(case):
    c = case
    request = deepcopy(facts.get(c.db, c.id, c.key, facts.START).safe_diff_json['query_request'])
    request['departments'][0]['department_id'] = 0
    c.remote['departments'][0]['department_id'] = 0
    invoice = c.db.get(Invoice, c.id)
    assert plan.verify(invoice, request, c.remote, datetime(2026, 10, 26, 11, 54), datetime(2026, 10, 26, 11, 59))


@pytest.mark.parametrize('server_tz', ['UTC', 'Pacific/Honolulu'])
def test_query_backoff_crosses_beijing_midnight(case, monkeypatch, server_tz):
    monkeypatch.setenv('TZ', server_tz)
    c = case
    c.clock.now = datetime(2026, 10, 26, 23, 59, 50)
    monkeypatch.setattr(recovery.okki_client, '_get_json', lambda *a, **kw: {'count': 0, 'list': []})
    assert recovery.recover(c.db, c.id)['status'] == 'unverified'
    claim = facts.get(c.db, c.id, c.key, recovery.CLAIM + ':1')
    assert claim.safe_diff_json['next_query_at'] == '2026-10-27T00:01:50'
