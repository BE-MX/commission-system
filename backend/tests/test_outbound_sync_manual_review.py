"""Manual review of uncertain outbound sync tasks. Isolated SQLite, mocked OKKI only.

Runs under the migration seed (legacy_only, empty writer receipts).
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.commerce_transition.models import (
    AuthorityEvent, ClaimEvidence, InvoiceAuthority, PlatformPolicy, SendingClaim, WriterReceipt,
)
from app.invoice import legacy_sending
from app.shipping_inspection import outbound_facts as facts, outbound_service, outbound_sync_service
from app.shipping_inspection import outbound_sync_state as state
from app.shipping_inspection.models import ShippingOperationEvent
from tests.authority_helpers import seed_authority
from tests.test_outbound_delete import case  # noqa: F401  (fixture reuse)
from tests.test_shipping_inspection import outbound_scope_seed, product_display_source  # noqa: F401
from tests.claim_helpers import ended_send_lease  # noqa: F401  (fixture)

@pytest.fixture(autouse=True)
def _ended_send_lease(ended_send_lease):
    """Releases here happen after the original request window (claim_helpers)."""


REVIEW_PERMISSIONS = ('invoice:sync', 'shipping_inspection:write', 'shipping_inspection:admin')
SOURCE_ITEMS = [{'unique_id': '501', 'model': 'B1', 'size': '20', 'color': '1'}]
AFTER = {'outbound_invoice_id': 77, 'update_time': '2026-11-01 10:00:00', 'serial_id': 'CK2026001', 'remark': '',
         'status': 1, 'company_info': {'id': 'C1'}, 'currency': 'USD',
         'record_list': [{'order_record_id': '501', 'outbound_record_id': '9', 'product_id': '11', 'sku_id': '12',
                          'order_id': '123', 'product_name': 'Hair', 'outbound_count': 1, 'product_unit': 'pcs'}]}


@pytest.fixture
def reviewer(db, case):
    user, inv, _, _ = case
    assert db.get(PlatformPolicy, 1).phase == 'legacy_only' and db.query(WriterReceipt).count() == 0
    seed_authority(db, user.id, *REVIEW_PERMISSIONS)
    db.rollback()
    return {'sub': str(user.id), 'id': user.id}


def run(db, user, **options):
    db.rollback()
    return outbound_sync_service.synchronize(db, 'OB001', user, None, force_authority=True, warehouse=True, **options)


def unknown_attempt(db, case):
    """A protocol-1 task whose committed claim timed out (claim unknown, task uncertain)."""
    user, inv, _, _ = case
    record = outbound_service.get_outbound_record(db, 'OB001')
    plan = {'invoice_id': inv.id, 'local_binding_fingerprint': 'f' * 64, 'before': {'outbound_invoice_id': '77'},
            'source_items': SOURCE_ITEMS}
    payload = {'outbound_invoice_id': '77', 'record_list': []}
    attempt = facts.start(db, inv.id, record, user.id, plan, payload, False, 'pc', True)
    event = state.lock(db, 'OB001', user.id)
    event.action, event.payload = 'sync_sending', facts.event_payload(attempt)
    event.result = {'started_at': attempt.data['started_at']}
    facts.mark_sending(db, attempt)
    ticket = legacy_sending.start(db, inv, f'legacy:outbound-sync:{attempt.nonce}', 'outbound_update', payload,
        {'actor_id': user.id, 'nonce': attempt.nonce, 'outbound_record_id': 'OB001'}, attempt.data['authority_epoch'])
    db.commit()
    legacy_sending.finish(db, ticket.request_key, 'unknown', {'transport_outcome': 'unknown'})
    facts.observe(db, attempt, 'unknown')
    event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE, request_id='OB001').one()
    event.action = 'sync_uncertain'
    db.commit()
    return attempt, ticket.request_key


def legacy_event(db, case, action='sync_uncertain'):
    """A pre-deploy office task: no protocol=1, no durable send record, no claim."""
    user, inv, _, _ = case
    event = state.lock(db, 'OB001', user.id)
    event.action = action
    event.payload = {'invoice_id': inv.id, 'plan': {'invoice_id': inv.id, 'before': {'outbound_invoice_id': '77'},
                                                     'source_items': SOURCE_ITEMS}}
    event.result = {'started_at': '2026-10-01T10:00:00', 'message': '同步结果待核对'}
    db.commit()
    return event.id


def later(monkeypatch, minutes=10):
    moment = facts.beijing_now() + timedelta(minutes=minutes)
    monkeypatch.setattr(facts, 'beijing_now', lambda: moment)


def assert_order_unlocked(db, inv):
    db.rollback()
    state.ensure_invoice_idle(db, inv)
    legacy_sending.start(db, inv.id, 'after-review', 'outbound_update', {'outbound_invoice_id': '77'}, {})
    db.commit()


def test_unknown_outbound_sync_confirm_not_created_releases_claim(db, case, reviewer, monkeypatch):
    user, inv, _, _ = case
    attempt, key = unknown_attempt(db, case)
    later(monkeypatch)
    clerk = seed_authority(db, 99, 'invoice:sync', 'shipping_inspection:write', 'shipping_inspection:read_all')
    db.rollback()
    with pytest.raises(HTTPException) as denied:
        run(db, {'sub': '99', 'id': 99}, resolution='confirm_not_created', reason='仓库人员确认小满未改动')
    assert denied.value.status_code in (403, 404)
    result = run(db, reviewer, resolution='confirm_not_created', reason='已在小满核对出库单未被本次同步修改')
    assert result['status'] == 'sync_failed' and result['requires_preview']
    claim = legacy_sending.find(db, key)
    assert claim.state == 'not_sent' and claim.active_invoice_key is None
    proof = [row.evidence for row in db.query(ClaimEvidence).filter_by(claim_id=claim.id) if row.outcome == 'not_sent']
    assert proof[0]['manual_confirm_not_created'] and proof[0]['operator_id'] == user.id
    assert proof[0]['remote_evidence']['facts_fingerprint']
    assert db.query(AuthorityEvent).filter_by(invoice_id=inv.id, action='manual_not_created').count() == 1
    finished = facts.get(db, facts.FINISH, attempt.nonce)
    assert finished.result['not_sent'] and finished.result['manual_review']['operator_id'] == user.id
    assert db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE, request_id='OB001').one().action == 'sync_failed'
    assert_order_unlocked(db, inv)


def test_unknown_outbound_sync_frozen_order_is_refused(db, case, reviewer, monkeypatch):
    _, inv, _, _ = case
    _, key = unknown_attempt(db, case)
    later(monkeypatch)
    db.get(InvoiceAuthority, inv.id).state = 'frozen'; db.commit()
    with pytest.raises(HTTPException) as rejected:
        run(db, reviewer, resolution='confirm_not_created', reason='已在小满核对出库单未被本次同步修改')
    assert rejected.value.status_code == 409 and '冻结' in rejected.value.detail
    db.rollback()
    assert legacy_sending.find(db, key).state == 'unknown'


def test_unknown_outbound_sync_within_lease_is_refused(db, case, reviewer):
    _, key = unknown_attempt(db, case)
    with pytest.raises(HTTPException) as rejected:
        run(db, reviewer, resolution='confirm_not_created', reason='已在小满核对出库单未被本次同步修改')
    assert rejected.value.status_code == 409 and '租约' in rejected.value.detail
    db.rollback()
    assert legacy_sending.find(db, key).state == 'unknown'


def test_legacy_format_task_guides_to_manual_review_then_confirm_not_created(db, case, reviewer):
    _, inv, _, _ = case
    event_id = legacy_event(db, case)
    with pytest.raises(HTTPException) as guided:
        run(db, reviewer)
    assert guided.value.status_code == 409 and '人工核对' in guided.value.detail
    result = run(db, reviewer, resolution='confirm_not_created', reason='旧版同步任务，小满出库单未改动')
    assert result['status'] == 'sync_failed' and result['requires_preview']
    assert db.get(ShippingOperationEvent, event_id).action == 'sync_failed'
    audit = db.query(ShippingOperationEvent).filter_by(scope='outbound-sync-legacy-review').one()
    assert audit.payload['resolution'] == 'confirm_not_created' and audit.payload['previous_action'] == 'sync_uncertain'
    with pytest.raises(ValueError, match='immutable'):
        audit.payload = {'tampered': True}; db.flush()
    db.rollback()
    assert_order_unlocked(db, inv)


def test_legacy_format_task_bind_existing_completes_after_verified_readback(db, case, reviewer, monkeypatch):
    from app.shipping_inspection import outbound_prepare, outbound_sync_plan
    _, inv, _, _ = case
    event_id = legacy_event(db, case, action='sync_sending')
    reads = []
    def read(db_, identity):
        assert not db_.in_transaction()
        reads.append(identity); return dict(AFTER)
    monkeypatch.setattr(outbound_prepare, 'read_outbound', read)
    monkeypatch.setattr(outbound_sync_plan, 'verify', lambda before, after, plan: None)
    result = run(db, reviewer, resolution='bind_existing', reason='小满原单已包含本次同步的全部明细')
    assert result['status'] == 'sync_done' and reads == ['77']
    assert db.get(ShippingOperationEvent, event_id).action == 'sync_done'
    audit = db.query(ShippingOperationEvent).filter_by(scope='outbound-sync-legacy-review').one()
    assert audit.payload['resolution'] == 'bind_existing' and audit.result['readback_sha256']
    assert_order_unlocked(db, inv)


def test_legacy_format_task_bind_existing_mismatch_keeps_task(db, case, reviewer, monkeypatch):
    from app.shipping_inspection import outbound_prepare, outbound_sync_plan
    event_id = legacy_event(db, case)
    monkeypatch.setattr(outbound_prepare, 'read_outbound', lambda db_, identity: dict(AFTER))
    def mismatch(before, after, plan): raise ValueError('lines differ')
    monkeypatch.setattr(outbound_sync_plan, 'verify', mismatch)
    with pytest.raises(HTTPException) as rejected:
        run(db, reviewer, resolution='bind_existing', reason='小满原单已包含本次同步的全部明细')
    assert rejected.value.status_code == 409 and '确认未生成' in rejected.value.detail
    db.rollback()
    assert db.get(ShippingOperationEvent, event_id).action == 'sync_uncertain'


def test_manual_review_is_reachable_through_existing_sync_route(db, case, reviewer):
    from tests.test_shipping_inspection import _pc_client
    user, _, _, _ = case
    event_id = legacy_event(db, case)
    with _pc_client(db, user, list(REVIEW_PERMISSIONS) + ['shipping_inspection:read_all']) as client:
        url = '/api/shipping-inspection/outbound-records/OB001/invoice-sync'
        short = client.post(url, json={'resolution': 'confirm_not_created', 'reason': 'short'})
        assert short.status_code == 422
        done = client.post(url, json={'resolution': 'confirm_not_created', 'reason': '旧版同步任务，小满出库单未改动'})
        assert done.status_code == 200, done.text
        assert done.json()['data']['status'] == 'sync_failed'
    assert db.get(ShippingOperationEvent, event_id).action == 'sync_failed'
