"""Failed-batch cancellation financial algorithm on SQLite; no live provider/DB.

Employee/JWT/lock races are exercised by the separate owned-MySQL suite.
"""
from copy import deepcopy
from decimal import Decimal

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app.invoice import settlement_service as shipments, shipment_state_service as states
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, SettlementApplication, SettlementEvent
from app.invoice.settlement_schemas import ShipmentQuote
from app.receipt.models import Receipt, ReceiptLog
from tests.test_presale_runtime import order, payment, create, evidence, USER  # noqa: F401


@pytest.fixture
def failed_batch(db, order, monkeypatch):
    receipt = payment(db, order, amount='1000')
    row, _ = create(db, order, freight='0')
    payload = {'serial_id': row.settlement_no, 'record_list': []}
    outbound = ShipmentOutbound(settlement_id=row.id, invoice_id=order.id,
        outbound_no=row.settlement_no, status='failed', payload=payload,
        payload_hash=shipments.digest(payload), last_error='Operation Failed: insufficient stock',
        attempt_token='original_failed_attempt', version=4)
    row.state = 'review_required'
    db.add(outbound); db.commit()
    # Explicit isolated financial adapter; does not pretend to validate JWT or
    # SQL row locks. Production uses the current-authority _authorize unchanged.
    def authorize(session, identity, user, action):
        invoice = session.get(Invoice, order.id)
        selected, graph = states._capture(session, invoice, identity, action)
        return invoice, selected, graph, USER
    monkeypatch.setattr(states, '_authorize', authorize)
    return order, row, outbound, receipt


def snap(db, objects):
    return [[deepcopy(getattr(obj, col.name)) for col in obj.__table__.columns] for obj in objects]


def test_cancel_failed_task_reads_unlocked_then_releases_and_allows_new_quote(db, failed_batch, monkeypatch):
    from app.invoice import shipment_cancel_service as cancels
    order, row, target, receipt = failed_batch
    original_receipt = snap(db, [receipt])
    preserved = {key: deepcopy(getattr(target, key)) for key in
        ('payload', 'payload_hash', 'last_error', 'attempt_token')}
    original_version = row.version
    calls = []
    def absent(session, serial):
        assert not session.in_transaction(), 'Business locks must be released before provider I/O'
        calls.append(serial)
        return None
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', absent)
    public = shipments.describe(db, row)
    assert public['actions']['cancel']['allowed'] is True
    assert public['actions']['cancel']['requires_remote_check'] is True
    db.rollback()
    result = states.change(db, row.id, USER, 'cancel', original_version, 'Change unavailable items')
    db.commit()
    assert result['state'] == 'cancelled' and result['version'] == original_version + 1
    assert result['outbound']['status'] == 'cancelled'
    assert calls == [target.outbound_no] and target.version == 5
    assert db.query(SettlementApplication).one().status == 'released'
    assert snap(db, [receipt]) == original_receipt
    assert {key: getattr(target, key) for key in preserved} == preserved
    quote = shipments.build_quote(db, order,
        ShipmentQuote(items=[{'invoice_item_id': order.items[0].id, 'quantity': 2}]), evidence(db, order))
    assert quote['advance_applied'] == '418.00'
    assert db.query(SettlementEvent).filter_by(action='cancel_verified').count() == 1


@pytest.mark.parametrize('outcome', ['exists', 'timeout', 'malformed'])
def test_remote_existence_or_unavailable_never_changes_funds(db, failed_batch, monkeypatch, outcome):
    from app.invoice import shipment_cancel_service as cancels
    order, row, target, receipt = failed_batch
    objects = [row, target, receipt, db.query(SettlementApplication).one()]
    before = snap(db, objects)
    def lookup(*_):
        if outcome == 'timeout':
            raise cancels.okki_client.OkkiApiError('No remote evidence')
        return {'outbound_invoice_id': '401', 'serial_id': target.outbound_no} if outcome == 'exists' else {}
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', lookup)
    with pytest.raises(HTTPException) as caught:
        states.change(db, row.id, USER, 'cancel', row.version, 'Cannot release without evidence')
    assert caught.value.status_code == (409 if outcome == 'exists' else 503)
    db.rollback()
    assert snap(db, objects) == before


@pytest.mark.parametrize('change', ['version', 'receipt', 'task', 'late_result', 'authority'])
def test_final_capture_rejects_changed_graph_or_authority(db, failed_batch, monkeypatch, change):
    from app.invoice import shipment_cancel_service as cancels
    _, row, target, receipt = failed_batch
    current_authorize = states._authorize
    revoked = False
    def authorize(*args):
        if revoked:
            raise HTTPException(403, 'Current authority revoked')
        return current_authorize(*args)
    monkeypatch.setattr(states, '_authorize', authorize)
    def lookup(*_):
        nonlocal revoked
        if change == 'version': row.version += 1
        elif change == 'receipt': receipt.remark = 'Changed while reading remote'
        elif change == 'task': target.version += 1
        elif change == 'late_result': db.add(ReceiptLog(receipt_id=receipt.id, action='late_result', message='Late fact'))
        else: revoked = True
        db.commit()
        return None
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', lookup)
    version = row.version
    with pytest.raises((ValueError, HTTPException)):
        states.change(db, row.id, USER, 'cancel', version, 'Concurrent change must reject')
    db.rollback()
    assert row.state == 'review_required' and target.status == 'failed'
    assert db.query(SettlementApplication).one().status == 'reserved'


def test_direct_financial_apply_without_provider_proof_is_rejected(db, failed_batch):
    order, row, _, _ = failed_batch
    _, graph = states._capture(db, order, row.id, 'cancel')
    with pytest.raises(ValueError, match='核实'):
        shipments._change_state_verified(db, row, USER, 'cancel', row.version, 'No proof', graph)
    assert row.state == 'review_required'


@pytest.mark.parametrize('field,value', [('status', 'uncertain'), ('remote_id', '401'),
    ('lease_until', 'active'), ('remote_line_snapshot', {'old': 'shipped'})])
def test_unknown_or_prior_remote_effect_is_never_eligible(db, failed_batch, field, value):
    from app.core.time import beijing_now
    _, row, target, _ = failed_batch
    setattr(target, field, beijing_now() if field == 'lease_until' else value)
    db.commit()
    assert shipments.describe(db, row)['actions']['cancel']['allowed'] is False


@pytest.mark.parametrize('blocker', ['payload_hash', 'confirmation_history'])
def test_invalid_original_evidence_denied_before_remote_lookup(db, failed_batch, monkeypatch, blocker):
    from app.invoice import shipment_cancel_service as cancels, shipment_confirmation_facts as facts
    _, row, target, _ = failed_batch
    if blocker == 'payload_hash':
        target.payload_hash = '0' * 64
    else:
        key = 'a' * 32
        facts.append(db, target.id, key, facts.START, {'attempt_key': key}, 1)
    db.commit()
    assert shipments.describe(db, row)['actions']['cancel']['allowed'] is False
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('No remote lookup'))
    with pytest.raises((ValueError, HTTPException)):
        states.change(db, row.id, USER, 'cancel', row.version, 'Original evidence invalid')
    db.rollback()
    assert row.state == 'review_required' and target.status == 'failed'
    assert db.query(SettlementApplication).one().status == 'reserved'


def test_final_business_transaction_rolls_back_all_four_kinds_of_effect(db, failed_batch, monkeypatch):
    from app.invoice import shipment_cancel_service as cancels
    from sqlalchemy.exc import OperationalError
    _, row, target, receipt = failed_batch
    objects = [row, target, receipt, db.query(SettlementApplication).one()]
    before = snap(db, objects)
    event_count = db.query(SettlementEvent).count()
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', lambda *_: None)
    result = states.change(db, row.id, USER, 'cancel', row.version, 'Rollback whole final commit')
    assert result['state'] == 'cancelled'
    # The service has flushed the complete business transaction, but has not
    # committed it. A failed outer commit must roll back every business effect.
    def failed_commit():
        raise OperationalError('COMMIT', {}, Exception('Injected local commit failure'))
    monkeypatch.setattr(db, 'commit', failed_commit)
    with pytest.raises(OperationalError): db.commit()
    db.rollback()
    assert snap(db, objects) == before
    assert db.query(SettlementEvent).count() == event_count
