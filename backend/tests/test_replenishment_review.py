"""Administrator "confirm not created" for an uncertain replenishment outbound (SQLite, no HTTP).

The outbound worker's original POST claim (outbound_create) blocks every
legacy send of the order. Production f79af949 only blocked the one task; the
review restores that by releasing the original claim with audit.
"""
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.commerce_transition.models import ClaimEvidence, SendingClaim
from app.core.time import beijing_now
from app.invoice import legacy_sending as gate, outbound_create_facts as creation
from app.invoice.models import OkkiOutboundTask
from app.shipping_inspection import audit_service, outbound_sync_plan as common
from app.shipping_inspection.models import ShippingOperationEvent
from app.shipping_inspection.outbound_prepare import row_state
from tests.test_commerce_manual_unlock import ready  # noqa: F401  (fixture reuse)

ADMIN = {'id': 1, 'sub': '1', 'roles': ['super_admin'], 'permissions': []}
CLERK = {'id': 2, 'sub': '2', 'roles': [], 'permissions': ['invoice:sync', 'shipping_inspection:write']}
REASON = 'Checked OKKI outbound list: nothing was created'


def uncertain_task(db, invoice, *, started_minutes_ago=10, result_class='unknown', claim_state='unknown'):
    """An original worker attempt that sent, timed out and verified as uncertain."""
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id='2001', status='running')
    db.add(task); db.flush(); db.refresh(task)
    nonce = uuid4().hex
    payload = {'serial_id': f'replenish-{nonce[:6]}', 'record_list': []}
    attempt = creation.Attempt(nonce, {'protocol': 1, 'nonce': nonce, 'invoice_id': invoice.id, 'task_id': task.id,
        'actor_id': 1, 'authority_epoch': 1, 'order_id': '2001', 'order': {'order_id': '2001'}, 'payload': payload,
        'payload_fingerprint': common.digest(payload), 'binding_fingerprint': common.digest(['binding']),
        'task_fingerprint': common.digest(row_state(task)), 'lineage': [],
        'started_at': (beijing_now() - timedelta(minutes=started_minutes_ago)).isoformat()})
    creation.append(db, creation.START, nonce, attempt, {})
    creation.append(db, creation.SEND, nonce, attempt, {})
    audit_service.record(db, 'create_sending', 1, 'create:' + str(invoice.id),
        context={'scope': creation.STATE, 'source': 'outbound_worker'}, request_id=str(task.id),
        payload={'protocol': 1, 'nonce': nonce}, result={'started_at': attempt.data['started_at']})
    task.status = 'uncertain'
    db.commit()
    key = f'legacy:outbound-worker:{nonce}'
    gate.start(db, invoice, key, 'outbound_create', payload, {'actor_id': 1, 'nonce': nonce, 'task_id': task.id}, 1)
    db.commit()
    if claim_state != 'sending':
        gate.finish(db, key, claim_state, {'transport_outcome': 'unknown'} if claim_state == 'unknown'
                    else {'original_readback': True}, '3001' if claim_state == 'succeeded' else None)
        db.commit()
    creation.observe(db, attempt, result_class, {'outbound_invoice_id': '3001'} if result_class == 'accepted' else None)
    db.commit()
    task_id = task.id
    db.rollback()
    return task_id, nonce


def confirm(db, task_id, actor, reason=REASON):
    from app.shipping_inspection import replenishment_review
    db.rollback()
    return replenishment_review.confirm_not_created(db, task_id, actor, reason)


def test_admin_confirm_not_created_releases_order_and_requeues_task(db, ready):
    task_id, nonce = uncertain_task(db, ready)
    with pytest.raises(ValueError, match='正在发送或结果未知'):  # The order is blocked for every sender.
        gate.start(db, ready, 'other-object', 'order_push', {'order_id': '2001'}, {}, 1)
    db.rollback()
    result = confirm(db, task_id, ADMIN)
    assert result['status'] == 'waiting_stock' and result['message']
    claim = gate.find(db, f'legacy:outbound-worker:{nonce}')
    assert claim.state == 'not_sent' and claim.active_invoice_key is None
    proof = db.query(ClaimEvidence).filter_by(claim_id=claim.id, outcome='not_sent').one()
    assert proof.evidence['operator_id'] == 1 and proof.evidence['reason'] == REASON
    assert proof.evidence['source'] == 'outbound.replenishment_review'
    assert creation.unresolved(db, ready.id) == []
    task = db.get(OkkiOutboundTask, task_id)
    assert task.status == 'waiting_stock'
    audit = db.query(ShippingOperationEvent).filter_by(scope='outbound-create-review').one()
    assert audit.operator_user_id == 1 and audit.payload['reason'] == REASON
    assert audit.payload['resolution'] == 'confirm_not_created' and audit.payload['task_id'] == task_id
    db.rollback()
    gate.start(db, ready, 'other-object', 'order_push', {'order_id': '2001'}, {}, 1)  # Order is free again.
    db.rollback()


def test_non_admin_and_short_reason_are_refused(db, ready):
    task_id, nonce = uncertain_task(db, ready)
    with pytest.raises(HTTPException) as denied:
        confirm(db, task_id, CLERK)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as short:
        confirm(db, task_id, ADMIN, reason='short')
    assert short.value.status_code == 400
    db.rollback()
    assert gate.find(db, f'legacy:outbound-worker:{nonce}').state == 'unknown'


@pytest.mark.parametrize('case', ['leased', 'accepted', 'succeeded'])
def test_unsafe_states_are_refused_and_keep_the_claim(db, ready, case):
    task_id, nonce = uncertain_task(db, ready, started_minutes_ago=1 if case == 'leased' else 10,
                                    result_class='accepted' if case == 'accepted' else 'unknown',
                                    claim_state='succeeded' if case == 'succeeded' else 'unknown')
    with pytest.raises(HTTPException) as refused:
        confirm(db, task_id, ADMIN)
    assert refused.value.status_code == 409
    db.rollback()
    assert gate.find(db, f'legacy:outbound-worker:{nonce}').state == ('succeeded' if case == 'succeeded' else 'unknown')
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-create-review').count() == 0


def test_task_without_an_uncertain_attempt_needs_no_review(db, ready):
    task = OkkiOutboundTask(invoice_id=ready.id, order_id='2001', status='waiting_stock')
    db.add(task); db.commit(); task_id = task.id
    with pytest.raises(HTTPException) as refused:
        confirm(db, task_id, ADMIN)
    assert refused.value.status_code == 409
    assert db.query(SendingClaim).count() == 0


def test_endpoint_passes_optional_review_body_and_keeps_plain_sync(monkeypatch):
    from fastapi import Response
    from app.shipping_inspection import outbound_inventory_router as router, replenishment_service
    seen = []
    monkeypatch.setattr(replenishment_service, 'synchronize', lambda *a: seen.append(a[1:]) or {'status': 'ok'})
    router.replenishment_sync('task:7', Response(), None, None, {'id': 1})
    body = router.ReplenishmentRequest(resolution='confirm_not_created', reason=REASON)
    router.replenishment_sync('task:7', Response(), body, None, {'id': 1})
    assert seen == [('task:7', {'id': 1}, None, None), ('task:7', {'id': 1}, 'confirm_not_created', REASON)]
    with pytest.raises(ValueError):
        router.ReplenishmentRequest(resolution='bind_existing', reason=REASON)
