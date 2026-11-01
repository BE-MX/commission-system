"""Timeout unlock = restored manual "confirm not created" (isolated SQLite, mocked OKKI).

Runs under the migration seed: phase legacy_only and an EMPTY writer receipt
inventory, the state production is in right after the transition deploy.
"""
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.commerce_transition import service as authority
from app.commerce_transition.models import (
    AuthorityEvent, ClaimEvidence, InvoiceAuthority, PlatformPolicy, SendingClaim, WriterReceipt,
)
from app.core.time import beijing_now, beijing_today
from app.invoice import legacy_sending as gate, okki_client, order_sync_execution
from app.invoice.models import Invoice
from tests.authority_helpers import seed_authority
from tests.test_commerce_legacy_transition_sending import pushable  # noqa: F401  (fixture reuse)

ADMIN = {'id': 1, 'sub': '1', 'roles': ['super_admin'], 'permissions': []}
CLERK = {'id': 2, 'sub': '2', 'roles': [], 'permissions': ['invoice:read', 'invoice:write', 'invoice:sync']}


@pytest.fixture
def ready(db, monkeypatch):
    """Same order as the shared fixture, but WITHOUT installing a transition phase."""
    seed_authority(db, 1, 'invoice:read', 'invoice:write', 'invoice:sync', 'receipt:read', 'receipt:write',
                   roles=('super_admin',))
    policy = db.get(PlatformPolicy, 1)
    assert policy.phase == 'legacy_only' and db.query(WriterReceipt).count() == 0
    row = Invoice(invoice_no='legacy-gated', transaction_mode='legacy', customer_id='101', customer_name='Isolated',
                  sales_user_id=1, created_by=1, invoice_date=beijing_today(), currency='USD',
                  total_amount=Decimal('100'), status='synced', sync_status='synced', xiaoman_order_id='2001')
    db.add(row); db.flush()
    authority.ensure_authority(db, row, route='legacy', source_evidence={'fixture': 'explicit'}, confirmed=True)
    db.commit()
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *a, **k: 'isolated-token')
    monkeypatch.setattr(okki_client, '_base_url', lambda: 'https://test.invalid')
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: pytest.fail('unexpected GET'))
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: pytest.fail('unexpected POST'))
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('unexpected lifecycle HTTP'))
    return row


def manual_events(db, invoice_id):
    return db.query(AuthorityEvent).filter_by(invoice_id=invoice_id, action='manual_not_created').all()


def assert_manual_release(db, claim, *, operator_id, prior='unknown'):
    assert claim.state == 'not_sent' and claim.active_invoice_key is None and claim.terminal_at is not None
    proof = [row for row in db.query(ClaimEvidence).filter_by(claim_id=claim.id)
             if (row.evidence or {}).get('manual_confirm_not_created')]
    assert len(proof) == 1 and proof[0].outcome == 'not_sent' and proof[0].external_id is None
    evidence = proof[0].evidence
    assert evidence['operator_id'] == operator_id and evidence['prior_state'] == prior
    assert evidence['reason'] and evidence['confirmed_at'] and isinstance(evidence['remote_evidence'], dict)
    events = [event for event in manual_events(db, claim.invoice_id) if event.payload.get('claim_id') == claim.id]
    assert len(events) == 1 and events[0].payload['operator_id'] == operator_id
    assert events[0].payload['request_key'] == claim.request_key


# ---------------------------------------------------------------- core gate

def unknown_claim(db, row, key='core-original', operation='order_push'):
    grant = gate.start(db, row, key, operation, {'order_id': '2001'}, {'task_key': key}, 1); db.commit()
    gate.finish(db, key, 'unknown', {'transport_outcome': 'unknown'}); db.commit()
    return gate.find(db, grant.request_key)


def test_manual_release_closes_unknown_claim_with_audit_and_reopens_sending(db, ready):
    claim = unknown_claim(db, ready)
    with pytest.raises(ValueError, match='正在发送或结果未知'):
        gate.start(db, ready, 'blocked-second', 'order_push', {'order_id': '2001'}, {}, 1)
    db.rollback()
    authority.confirm_not_sent(db, claim.id, operator_id=1, reason='Checked OKKI: no order exists',
                               remote_evidence={'remote_readback': 'operator_checked'}, source='test')
    db.commit()
    assert_manual_release(db, gate.find(db, 'core-original'), operator_id=1)
    gate.start(db, ready, 'after-release', 'order_push', {'order_id': '2001'}, {}, 1)
    db.commit()


def test_manual_release_refuses_frozen_terminal_or_leased_claims(db, ready):
    claim = unknown_claim(db, ready)
    held = db.get(InvoiceAuthority, ready.id); held.state = 'frozen'; db.commit()
    with pytest.raises(ValueError, match='冻结'):
        authority.confirm_not_sent(db, claim.id, operator_id=1, reason='frozen attempt',
                                   remote_evidence={'x': 1}, source='test')
    db.rollback()
    held = db.get(InvoiceAuthority, ready.id); held.state = 'active'
    stored = gate.find(db, 'core-original'); stored.lease_until = beijing_now() + timedelta(minutes=5); db.commit()
    with pytest.raises(ValueError, match='租约'):
        authority.confirm_not_sent(db, claim.id, operator_id=1, reason='leased attempt',
                                   remote_evidence={'x': 1}, source='test')
    db.rollback()
    stored = gate.find(db, 'core-original'); stored.lease_until = None; db.commit()
    gate.finish(db, 'core-original', 'succeeded', {'original_request_readback': True}, '2001'); db.commit()
    with pytest.raises(ValueError, match='终局'):
        authority.confirm_not_sent(db, claim.id, operator_id=1, reason='terminal attempt',
                                   remote_evidence={'x': 1}, source='test')
    db.rollback()
    assert gate.find(db, 'core-original').state == 'succeeded' and not manual_events(db, ready.id)


def test_late_success_after_manual_release_freezes_order(db, ready):
    claim = unknown_claim(db, ready)
    authority.confirm_not_sent(db, claim.id, operator_id=1, reason='Checked OKKI: no order exists',
                               remote_evidence={'remote_readback': 'operator_checked'}, source='test')
    db.commit()
    gate.finish(db, 'core-original', 'succeeded', {'late_response': True}, '2001'); db.commit()
    assert db.get(InvoiceAuthority, ready.id).state == 'frozen'


# ---------------------------------------------------------------- invoice

def timeout_first_push(db, pushable, monkeypatch):
    invoice = db.get(Invoice, pushable)
    invoice.xiaoman_order_id = None; invoice.status = 'ready'; invoice.sync_status = 'not_synced'
    invoice.items[0].xiaoman_unique_id = None
    db.commit(); db.rollback(); payloads = []
    def timeout(*a, **k): payloads.append(k['json']); raise httpx.ReadTimeout('original response lost')
    monkeypatch.setattr(httpx, 'post', timeout)
    assert not order_sync_execution.run(db, pushable, {'id': 1}, follow_outbound=False)['ok']
    invoice = db.get(Invoice, pushable)
    invoice.sync_attempt = {**invoice.sync_attempt, 'lease_until': (beijing_now() - timedelta(minutes=1)).isoformat()}
    db.commit(); db.rollback()
    return payloads


def succeed_push(db, pushable, monkeypatch, posts):
    def post(*a, **k):
        posts.append(k['json'])
        return httpx.Response(200, json={'code': 200, 'data': {'order_id': '2001', 'product_list': [
            {**line, 'unique_id': line.get('unique_id') or 501} for line in k['json']['product_list']]}})
    monkeypatch.setattr(httpx, 'post', post)
    db.rollback()
    result = order_sync_execution.run(db, pushable, {'id': 1}, follow_outbound=False)
    assert result['ok'] is True
    assert db.get(Invoice, pushable).sync_status == 'synced'


def test_invoice_unknown_claim_confirm_not_created_releases_and_allows_resend(db, pushable, monkeypatch):
    from app.invoice import sync_recovery
    posts = timeout_first_push(db, pushable, monkeypatch)
    seed_authority(db, 2, 'invoice:read', 'invoice:write', 'invoice:sync'); db.rollback()
    with pytest.raises(HTTPException) as denied:
        sync_recovery.resolve(db, pushable, CLERK, resolution='confirm_not_created', reason='clerk cannot unlock')
    assert denied.value.status_code == 403
    db.rollback()
    assert db.scalar(select(SendingClaim)).state == 'unknown'
    db.rollback()
    result = sync_recovery.resolve(db, pushable, ADMIN, resolution='confirm_not_created',
                                   reason='Checked OKKI order list: no order was created')
    assert result['sync_status'] == 'not_synced'
    assert_manual_release(db, db.scalar(select(SendingClaim)), operator_id=1)
    succeed_push(db, pushable, monkeypatch, posts)
    assert len(posts) == 2
    assert [c.state for c in db.query(SendingClaim).order_by(SendingClaim.id)] == ['not_sent', 'succeeded']


def test_invoice_frozen_order_confirm_not_created_is_refused_with_reason(db, pushable, monkeypatch):
    from app.invoice import sync_recovery
    timeout_first_push(db, pushable, monkeypatch)
    db.get(InvoiceAuthority, pushable).state = 'frozen'; db.commit()
    with pytest.raises(HTTPException) as rejected:
        sync_recovery.resolve(db, pushable, ADMIN, resolution='confirm_not_created', reason='frozen order attempt')
    assert rejected.value.status_code == 409 and '冻结' in rejected.value.detail
    db.rollback()
    assert db.scalar(select(SendingClaim)).state == 'unknown'


def test_invoice_legacy_uncertain_without_claim_follows_original_manual_flow(db, pushable, monkeypatch):
    from app.invoice import sync_recovery
    invoice = db.get(Invoice, pushable)
    invoice.xiaoman_order_id = None; invoice.status = 'ready'; invoice.sync_status = 'sync_uncertain'
    invoice.sync_attempt = None; invoice.items[0].xiaoman_unique_id = None
    db.commit(); db.rollback()
    result = sync_recovery.resolve(db, pushable, ADMIN, resolution='confirm_not_created',
                                   reason='Pre-deploy uncertain push; OKKI has no such order')
    assert result['sync_status'] == 'not_synced' and db.query(SendingClaim).count() == 0
    posts = []
    succeed_push(db, pushable, monkeypatch, posts)
    assert len(posts) == 1


# ---------------------------------------------------------------- receipt

@pytest.fixture
def receipts(db, ready, monkeypatch):
    from app.receipt import attachments, remote, sync_service
    monkeypatch.setattr(remote, 'order_snapshot', lambda db, invoice: {
        'rows': [], 'exchange_rate': 1, 'invoice_binding': remote.invoice_binding(invoice)})
    monkeypatch.setattr(remote, 'receipt_types', lambda db: ['T/T'])
    monkeypatch.setattr(remote, 'read', lambda *a, **k: [])
    monkeypatch.setattr(attachments, 'bind', lambda *a, **k: None)
    monkeypatch.setattr(sync_service, 'refresh_accepted', lambda *a: None)
    return ready


def new_receipt(db, invoice_id, key):
    from tests.test_commerce_legacy_transition_sending import receipt
    return receipt(db, invoice_id, key)


def deliver_with(db, monkeypatch, identity, outcome):
    from app.receipt import sync_service
    def post(*a, **k):
        if outcome == 'timeout':
            raise httpx.ReadTimeout('receipt response lost')
        return httpx.Response(200, json={'code': 200, 'data': {'cash_collection_id': outcome,
                                                              'cash_collection_no': f'HK{outcome}'}})
    monkeypatch.setattr(httpx, 'post', post)
    db.rollback()
    sync_service.deliver(db, identity)
    db.rollback()


def receipt_claims(db):
    return db.query(SendingClaim).filter_by(operation='receipt_push').order_by(SendingClaim.id).all()


def resolve_receipt(db, identity, user, resolution, **extra):
    from app.receipt import reconciliation_service
    from app.receipt.schemas import Resolution
    db.rollback()
    body = Resolution(resolution=resolution, reason=extra.pop('reason', 'Checked OKKI receipt list manually'), **extra)
    reconciliation_service.recover(db, identity, user, body)
    db.commit()


def test_receipt_unknown_confirm_not_created_releases_claim_and_resends(db, receipts, monkeypatch):
    from app.receipt import remote
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-unknown')
    deliver_with(db, monkeypatch, first, 'timeout')
    assert db.get(Receipt, first).sync_status == 'uncertain' and receipt_claims(db)[0].state == 'unknown'
    monkeypatch.setattr(remote, 'order_receipts', lambda db, order_id: [])
    seed_authority(db, 3, 'receipt:read', 'receipt:write')
    with pytest.raises(HTTPException) as denied:
        resolve_receipt(db, first, {'id': 3, 'sub': '3'}, 'confirm_not_created')
    assert denied.value.status_code == 403
    db.rollback()
    resolve_receipt(db, first, ADMIN, 'confirm_not_created')
    assert db.get(Receipt, first).sync_status == 'pending'
    assert_manual_release(db, receipt_claims(db)[0], operator_id=1)
    deliver_with(db, monkeypatch, first, '701')
    saved = db.get(Receipt, first)
    assert saved.sync_status == 'synced' and saved.xiaoman_receipt_id == '701'
    assert [c.state for c in receipt_claims(db)] == ['not_sent', 'succeeded']


def test_receipt_frozen_order_confirm_not_created_is_refused(db, receipts, monkeypatch):
    from app.receipt import remote
    first = new_receipt(db, receipts.id, 'receipt-frozen')
    deliver_with(db, monkeypatch, first, 'timeout')
    monkeypatch.setattr(remote, 'order_receipts', lambda db, order_id: [])
    db.get(InvoiceAuthority, receipts.id).state = 'frozen'; db.commit()
    with pytest.raises(ValueError, match='冻结'):  # The receipt router turns ValueError into 409 + message.
        resolve_receipt(db, first, ADMIN, 'confirm_not_created')
    db.rollback()
    assert receipt_claims(db)[0].state == 'unknown'


def test_receipt_bind_original_closes_unknown_claim_and_order_can_send_again(db, receipts, monkeypatch):
    from app.receipt import remote
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-bind')
    deliver_with(db, monkeypatch, first, 'timeout')
    original = {'cash_collection_id': '701', 'cash_collection_no': 'HK701', 'order_id': '2001', 'currency': 'USD',
                'amount': '10.00', 'bank_charge': '0', 'real_amount': '10.00',
                'collection_date': beijing_today().isoformat(), 'collect_status': 1}
    monkeypatch.setattr(remote, 'receipt_info', lambda db, identity: dict(original))
    resolve_receipt(db, first, ADMIN, 'bind_receipt', xiaoman_receipt_id='701')
    assert db.get(Receipt, first).xiaoman_receipt_id == '701'
    claim = receipt_claims(db)[0]
    assert claim.state == 'succeeded' and claim.external_id == '701' and claim.active_invoice_key is None
    monkeypatch.setattr(remote, 'order_snapshot', lambda db, invoice: {  # The bound original is now remote.
        'rows': [dict(original)], 'exchange_rate': 1, 'invoice_binding': remote.invoice_binding(invoice)})
    second = new_receipt(db, receipts.id, 'receipt-after-bind')
    deliver_with(db, monkeypatch, second, '702')
    assert db.get(Receipt, second).xiaoman_receipt_id == '702', db.get(Receipt, second).last_error
    assert [c.state for c in receipt_claims(db)] == ['succeeded', 'succeeded']


# ------------------------------------------- receipt stuck behind own claim

def stale_pending(db, identity, status='pending'):
    """Pre-batch-A state: the row went back to pending/failed, its claim stayed unknown."""
    from app.receipt.models import Receipt
    db.query(Receipt).filter_by(id=identity).update({'sync_status': status, 'send_phase': None,
                                                    'recovery_kind': None, 'last_error': None})
    db.commit()


@pytest.mark.parametrize('stale', ['pending', 'failed'])
def test_receipt_behind_its_own_unknown_claim_becomes_uncertain_and_resolvable(db, receipts, monkeypatch, stale):
    from app.receipt import remote, retry_service
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, f'receipt-stuck-{stale}')
    deliver_with(db, monkeypatch, first, 'timeout')
    assert receipt_claims(db)[0].state == 'unknown'
    stale_pending(db, first, stale)
    if stale == 'failed':
        db.rollback(); retry_service.retry(db, first, ADMIN); db.commit()
    deliver_with(db, monkeypatch, first, 'must-not-send')
    row = db.get(Receipt, first)
    assert row.sync_status == 'uncertain' and row.recovery_kind == 'unknown', row.last_error
    assert '确认未生成' in row.last_error and '绑定' in row.last_error
    assert len(receipt_claims(db)) == 1 and receipt_claims(db)[0].state == 'unknown'
    monkeypatch.setattr(remote, 'order_receipts', lambda db, order_id: [])
    resolve_receipt(db, first, ADMIN, 'confirm_not_created')
    assert_manual_release(db, receipt_claims(db)[0], operator_id=1)
    deliver_with(db, monkeypatch, first, '711')
    assert db.get(Receipt, first).xiaoman_receipt_id == '711'


def test_receipt_behind_another_objects_unknown_claim_stays_failed_and_names_it(db, receipts, monkeypatch):
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-holder')
    deliver_with(db, monkeypatch, first, 'timeout')
    second = new_receipt(db, receipts.id, 'receipt-waiting')
    deliver_with(db, monkeypatch, second, 'must-not-send')
    row = db.get(Receipt, second)
    assert row.sync_status == 'failed', row.last_error
    assert 'receipt-holder' in row.last_error and '回款' in row.last_error
    assert len(receipt_claims(db)) == 1


def test_receipt_claim_refusal_after_precheck_is_classified_not_plain_failed(db, receipts, monkeypatch):
    from app.receipt import sync_service
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-race')
    deliver_with(db, monkeypatch, first, 'timeout')
    stale_pending(db, first)
    real, calls = sync_service._claim_block, []
    def late(db, row):  # The claim is invisible to the pre-check, then refuses begin_send.
        calls.append(row.id)
        return (None, None) if len(calls) == 1 else real(db, row)
    monkeypatch.setattr(sync_service, '_claim_block', late)
    deliver_with(db, monkeypatch, first, 'must-not-send')
    row = db.get(Receipt, first)
    assert len(calls) == 2 and row.sync_status == 'uncertain' and row.recovery_kind == 'unknown', row.last_error
    assert len(receipt_claims(db)) == 1


# ------------------------------- bind closes every open claim of the receipt

ORIGINAL_701 = {'cash_collection_id': '701', 'cash_collection_no': 'HK701', 'order_id': '2001', 'currency': 'USD',
                'amount': '10.00', 'bank_charge': '0', 'real_amount': '10.00', 'collect_status': 1}


def bind_701_then_second_sends(db, monkeypatch, first, receipts):
    from app.receipt import remote
    from app.receipt.models import Receipt
    original = {**ORIGINAL_701, 'collection_date': beijing_today().isoformat()}
    monkeypatch.setattr(remote, 'receipt_info', lambda db, identity: dict(original))
    resolve_receipt(db, first, ADMIN, 'bind_receipt', xiaoman_receipt_id='701')
    assert db.get(Receipt, first).xiaoman_receipt_id == '701'
    assert all(claim.state in ('succeeded', 'not_sent', 'failed') for claim in receipt_claims(db)), \
        [claim.state for claim in receipt_claims(db)]
    monkeypatch.setattr(remote, 'order_snapshot', lambda db, invoice: {
        'rows': [dict(original)], 'exchange_rate': 1, 'invoice_binding': remote.invoice_binding(invoice)})
    second = new_receipt(db, receipts.id, f'after-bind-{first}')
    deliver_with(db, monkeypatch, second, '702')
    assert db.get(Receipt, second).xiaoman_receipt_id == '702', db.get(Receipt, second).last_error


def test_crash_recovered_receipt_bind_closes_its_original_claim(db, receipts, monkeypatch):
    from app.receipt import recovery
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-crash-bind')
    deliver_with(db, monkeypatch, first, 'timeout')
    # Simulate a worker crash mid-send: the row stayed syncing past its lease.
    db.query(Receipt).filter_by(id=first).update({'sync_status': 'syncing', 'send_phase': 'sending',
                                                  'lease_until': beijing_now() - timedelta(minutes=1)})
    db.commit()
    recovery.recover_expired(db)
    row = db.get(Receipt, first)
    assert row.sync_status == 'uncertain' and row.attempt_token is None
    db.rollback()
    bind_701_then_second_sends(db, monkeypatch, first, receipts)


def test_own_claim_hold_receipt_bind_closes_its_original_claim(db, receipts, monkeypatch):
    from app.receipt import sync_service
    from app.receipt.models import Receipt
    first = new_receipt(db, receipts.id, 'receipt-hold-bind')
    deliver_with(db, monkeypatch, first, 'timeout')
    stale_pending(db, first)
    real, calls = sync_service._claim_block, []
    def late(db, row):  # Refusal arrives after a new attempt token was issued.
        calls.append(row.id)
        return (None, None) if len(calls) == 1 else real(db, row)
    monkeypatch.setattr(sync_service, '_claim_block', late)
    deliver_with(db, monkeypatch, first, 'must-not-send')
    monkeypatch.setattr(sync_service, '_claim_block', real)
    assert db.get(Receipt, first).sync_status == 'uncertain'
    db.rollback()
    bind_701_then_second_sends(db, monkeypatch, first, receipts)
