"""Deleted supplier outbound cancellation; isolated financial graph only."""
from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.invoice import settlement_service as shipments, shipment_state_service as states
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, SettlementApplication, Receivable
from app.invoice.settlement_schemas import ShipmentQuote
from tests.test_presale_runtime import order, payment, create, evidence, USER  # noqa: F401


@pytest.fixture
def generated(db, order, monkeypatch):
    cash = payment(db, order)
    row, _ = create(db, order)
    payload = {'serial_id': row.settlement_no, 'record_list': []}
    target = ShipmentOutbound(settlement_id=row.id, invoice_id=order.id,
        outbound_no=row.settlement_no, status='uncertain', payload=payload,
        payload_hash=shipments.digest(payload), remote_id='401',
        remote_line_snapshot={'11': {'outbound_record_id': '9', 'cost_unit_price_rmb': '0'}})
    row.state = 'outbound_uncertain'
    freight = db.query(Receivable).filter_by(settlement_id=row.id, kind='freight').one()
    freight.remote_order_id = '300'; freight.remote_status = 'bound'
    db.add(target); db.commit()
    def authorize(session, identity, user, action):
        invoice = session.get(Invoice, order.id)
        selected, graph = states._capture(session, invoice, identity, action)
        return invoice, selected, graph, USER
    monkeypatch.setattr(states, '_authorize', authorize)
    return order, row, target, cash, freight


def test_generated_deleted_batch_exposes_a_distinct_checked_cancellation(db, generated):
    _, row, _, _, _ = generated
    public = shipments.describe(db, row)
    assert public['actions'].get('cancel_deleted', {}).get('allowed') is True
    assert public['actions']['cancel_deleted']['keep_freight'] is True
    assert public['actions']['cancel']['allowed'] is False


def test_retained_freight_terminal_releases_goods_but_keeps_cash_and_freight(db, generated):
    order, row, target, cash, _ = generated
    original = deepcopy({c.name: getattr(cash, c.name) for c in cash.__table__.columns})
    for app in db.query(SettlementApplication).filter_by(settlement_id=row.id):
        app.status = 'applied' if app.component == 'freight' else 'released'
    row.state = 'cancelled_keep_freight'; target.status = 'cancelled'
    db.commit()
    summary = shipments.funding_balance(db, row)
    assert Decimal(summary['goods_remaining']) == 0
    assert Decimal(summary['outstanding_amount']) == 0
    assert Decimal(summary['total_amount']) == Decimal('38')
    quote = shipments.build_quote(db, order, ShipmentQuote(
        items=[{'invoice_item_id': order.items[0].id, 'quantity': 3}], freight_amount='0'),
        evidence(db, order))
    assert quote['retained_freight_settlement_id'] == row.id
    assert Decimal(quote['retained_freight_amount']) == Decimal('38')
    assert Decimal(quote['advance_applied']) == Decimal('627')
    assert {c.name: getattr(cash, c.name) for c in cash.__table__.columns} == original


def test_replacement_cannot_charge_retained_freight_again(db, generated):
    order, row, target, _, _ = generated
    for app in db.query(SettlementApplication).filter_by(settlement_id=row.id):
        app.status = 'applied' if app.component == 'freight' else 'released'
    row.state = 'cancelled_keep_freight'; target.status = 'cancelled'; db.commit()
    with pytest.raises(ValueError, match='保留.*运费'):
        shipments.build_quote(db, order, ShipmentQuote(
            items=[{'invoice_item_id': order.items[0].id, 'quantity': 3}], freight_amount='38'),
            evidence(db, order))


@pytest.fixture
def cancel_adapter(db, generated, monkeypatch):
    from app.invoice import shipment_deleted_cancellation as cancels
    order, row, target, _, freight = generated
    monkeypatch.setattr(cancels, 'require_delivery', lambda: None)
    monkeypatch.setattr(cancels, '_inspection', lambda *_args, **_kw: ('mirror-401', 'unchanged'))
    proof = {'remote_id': target.remote_id, 'serial_id': target.outbound_no,
        'result': 'verified_deleted', 'observed_at': '2026-10-26T11:00:00',
        'freight': evidence(db, order)['freight'][row.id], 'goods': evidence(db, order)['receipt']}
    db.commit()
    monkeypatch.setattr(cancels, '_observe', lambda *_args: deepcopy(proof))
    return cancels, proof


def test_cancel_deleted_preserves_freight_and_original_cash(db, generated, cancel_adapter):
    from app.invoice.settlement_models import SettlementEvent
    from app.invoice.settlement_schemas import SettlementAction
    from app.shipping_inspection.models import ShippingOperationEvent
    from app.invoice import shipment_creation_facts as facts
    cancels, _ = cancel_adapter
    order, row, target, cash, freight = generated
    before = deepcopy({c.name: getattr(cash, c.name) for c in cash.__table__.columns})
    frozen = deepcopy({k: getattr(target, k) for k in
        ('payload', 'payload_hash', 'remote_id', 'remote_line_snapshot', 'attempt_token', 'last_error')})
    version, identity = row.version, row.id
    db.rollback()
    result = cancels.cancel(db, identity, SettlementAction(version=version, reason='Retain original paid freight'), USER)
    assert result['state'] == 'cancelled_keep_freight'
    assert result['outbound']['status'] == 'cancelled'
    assert result['version'] == version + 1
    assert Decimal(result['balance']['outstanding_amount']) == 0
    assert {app.component: app.status for app in db.query(SettlementApplication)} == {
        'goods': 'released', 'freight': 'applied'}
    assert {c.name: getattr(cash, c.name) for c in cash.__table__.columns} == before
    assert {key: getattr(target, key) for key in frozen} == frozen
    assert freight.remote_status == 'bound' and freight.remote_order_id == '300'
    assert db.query(SettlementEvent).filter_by(action='cancel_deleted').count() == 1
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').one().action == 'outbound_deleted'
    fact = facts.rows(db, target.id)[0]
    assert fact.safe_diff_json['released_amount'] == '627.00'
    assert 'goods' not in fact.safe_diff_json['observation']
    db.rollback()
    with pytest.raises(HTTPException):
        cancels.cancel(db, identity, SettlementAction(version=version, reason='Do not duplicate'), USER)


@pytest.mark.parametrize('blocked', ['active', 'unavailable', 'changed_graph', 'changed_inspection',
    'late_create', 'late_receipt', 'revoked'])
def test_refused_deletion_keeps_all_allocations(db, generated, cancel_adapter, monkeypatch, blocked):
    from app.invoice.settlement_schemas import SettlementAction
    from app.invoice import shipment_creation_facts as facts
    from app.receipt.models import ReceiptLog
    cancels, proof = cancel_adapter
    _, row, target, cash, _ = generated
    version, identity = row.version, row.id
    authorizer = states._authorize
    revoked = False
    def authorize(*args):
        if revoked:
            raise HTTPException(403, 'Revoked')
        return authorizer(*args)
    monkeypatch.setattr(states, '_authorize', authorize)
    def observe(*args):
        nonlocal revoked
        if blocked == 'active':
            raise ValueError('小满原出库单仍有效')
        if blocked == 'unavailable':
            raise cancels.outbound_presence.PresenceError('Incomplete list')
        if blocked == 'changed_graph':
            cash.remark = 'Changed while unlocked'; db.commit()
        if blocked == 'changed_inspection':
            monkeypatch.setattr(cancels, '_inspection', lambda *_a, **_kw: ('mirror-401', 'changed'))
        if blocked == 'late_create':
            facts.remember_late_result(db, target, 'old-token', '402'); db.commit()
        if blocked == 'late_receipt':
            db.add(ReceiptLog(receipt_id=cash.id, action='late_result', message='late')); db.commit()
        if blocked == 'revoked':
            revoked = True
        return proof
    monkeypatch.setattr(cancels, '_observe', observe)
    db.rollback()
    with pytest.raises((HTTPException, ValueError)):
        cancels.cancel(db, identity, SettlementAction(version=version, reason='Must preserve on conflict'), USER)
    db.rollback()
    assert db.get(type(row), identity).state == 'outbound_uncertain'
    assert {app.status for app in db.query(SettlementApplication)} == {'reserved'}
    assert target.status == 'uncertain'


def test_failed_final_commit_rolls_back_release_and_tombstone(db, generated, cancel_adapter, monkeypatch):
    from app.invoice.settlement_schemas import SettlementAction
    from app.shipping_inspection.models import ShippingOperationEvent
    from sqlalchemy.exc import OperationalError
    cancels, _ = cancel_adapter
    _, row, target, _, _ = generated
    version, identity = row.version, row.id
    original_commit = db.commit
    # Avoid ORM reads inside the commit hook before the first clean capture.
    count = 0
    def staged_commit():
        nonlocal count
        count += 1
        if count == 3:
            raise OperationalError('COMMIT', {}, Exception('No durable release'))
        return original_commit()
    monkeypatch.setattr(db, 'commit', staged_commit)
    db.rollback()
    with pytest.raises(HTTPException):
        cancels.cancel(db, identity, SettlementAction(version=version, reason='Rollback all effects'), USER)
    db.rollback()
    assert row.state == 'outbound_uncertain' and target.status == 'uncertain'
    assert {app.status for app in db.query(SettlementApplication)} == {'reserved'}
    assert not db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count()


def test_cancelled_target_cannot_be_revived_by_readback(db, generated, monkeypatch):
    from app.invoice import shipment_delivery
    _, row, target, _, _ = generated
    target.status = 'cancelled'; row.state = 'cancelled_keep_freight'; db.commit()
    monkeypatch.setattr(shipment_delivery.remote, 'read', lambda *_: pytest.fail('No provider read for cancelled target'))
    assert shipment_delivery.refresh(db, target.id) == 'cancelled'
    assert target.status == 'cancelled'


def test_retained_freight_is_only_carried_by_the_immediate_replacement(db, generated):
    order, row, target, _, _ = generated
    for app in db.query(SettlementApplication).filter_by(settlement_id=row.id):
        app.status = 'applied' if app.component == 'freight' else 'released'
    row.state = 'cancelled_keep_freight'; target.status = 'cancelled'; db.commit()
    replacement, _ = create(db, order, freight='0', key='replacement_000001')
    assert replacement.sequence == 2
    assert replacement.quote['retained_freight_settlement_id'] == row.id
    assert db.query(Receivable).filter_by(kind='freight').count() == 1
    from app.invoice.shipment_cancellation_policy import replacement_freight
    assert replacement_freight(db, order) is None
    for app in db.query(SettlementApplication).filter_by(settlement_id=replacement.id):
        app.status = 'released'
    replacement.state = 'cancelled'; db.commit()
    assert replacement_freight(db, order).id == row.id


@pytest.mark.parametrize('tamper', ['goods_reserved', 'freight_released', 'freight_amount', 'source_purpose',
    'target_status', 'source_ineffective'])
def test_retained_freight_corruption_never_becomes_available_pool_money(db, generated, tamper):
    from app.invoice import presale_runtime
    order, row, target, cash, freight = generated
    apps = {app.component: app for app in db.query(SettlementApplication).filter_by(settlement_id=row.id)}
    apps['goods'].status = 'released'; apps['freight'].status = 'applied'
    row.state = 'cancelled_keep_freight'; target.status = 'cancelled'
    if tamper == 'goods_reserved': apps['goods'].status = 'reserved'
    if tamper == 'freight_released': apps['freight'].status = 'released'
    if tamper == 'freight_amount': apps['freight'].amount += 1
    if tamper == 'source_purpose': cash.purpose = 'presale_deposit'
    if tamper == 'target_status': freight.remote_status = 'uncertain'
    if tamper == 'source_ineffective': cash.collect_status = 0
    db.commit()
    with pytest.raises(ValueError):
        shipments.build_quote(db, order, ShipmentQuote(
            items=[{'invoice_item_id': order.items[0].id, 'quantity': 3}], freight_amount='0'),
            evidence(db, order))
