"""Inspection is physical completion; supplier status remains draft. SQLite only."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.test_presale_runtime import order, payment, create, evidence
from app.invoice import shipment_delivery, settlement_service as shipments
from app.invoice import outbound_reconciliation_service as reconciliation
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.settlement_models import ShipmentOutbound, SettlementApplication, SettlementEvent
from app.invoice.settlement_schemas import ShipmentQuote
from app.shipping_inspection import service, outbound_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto


@pytest.fixture
def batch(db, order):
    outbound_service._columns_cache.clear()
    for column in ('outbound_invoice_id TEXT', 'company_id TEXT'):
        db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN ' + column))
    for column in ('outbound_invoice_id TEXT', 'order_id TEXT', 'order_record_id TEXT', 'product_id TEXT', 'sku_id TEXT'):
        db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN ' + column))
    payment(db, order)
    row, _ = create(db, order, quantity=1, freight='0')
    payload = {'serial_id': row.settlement_no, 'status': 1, 'record_list': [{
        'order_id': 100, 'order_record_id': 11, 'product_id': 1, 'sku_id': 2, 'outbound_count': 1}]}
    outbound = ShipmentOutbound(invoice_id=order.id, settlement_id=row.id, outbound_no=row.settlement_no,
        status='pending_remote', remote_id='900', payload=payload, payload_hash=shipments.digest(payload),
        remote_line_snapshot={'11': {'outbound_record_id': '901', 'cost_unit_price_rmb': '0'}})
    db.add(outbound)
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='900', company_id='C1', outbound_no=:no WHERE id='OB001'"), {'no': row.settlement_no})
    db.execute(text("DELETE FROM lsordertest.okki_outbound_record_items WHERE id='IT002'"))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='900', outbound_record_id='901', order_id='100', order_record_id='11', product_id='1', sku_id='2', quantity=1 WHERE id='IT001'"))
    inspection = ShippingInspection(outbound_record_id='OB001', outbound_no=row.settlement_no, status='draft', created_by=1)
    db.add(inspection); db.flush()
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, file_path='fixture.jpg', created_by=1))
    row.state = 'outbound_pending'
    db.commit()
    yield row, outbound, inspection
    outbound_service._columns_cache.clear()


def submit(db):
    return service.submit(db, outbound_record_id='OB001', user_id=1)


def detail(outbound, status=1):
    result = deepcopy(outbound.payload)
    result.update(outbound_invoice_id=900, status=status, create_time='2026-10-10 10:00:00')
    result['record_list'][0].update(outbound_record_id=901, cost_unit_price_rmb=0)
    return result


def remote_reads(monkeypatch, outbound, status=1):
    monkeypatch.setattr(shipment_delivery.remote, 'read', lambda *_args, **_kwargs: detail(outbound, status))
    monkeypatch.setattr(shipment_delivery.okki_client, 'ensure_access_token', lambda *_: 'test')
    monkeypatch.setattr(shipment_delivery.outbound_presence, 'is_active', lambda *_: True)
    monkeypatch.setattr(shipment_delivery, '_refresh_funding', lambda *_: True)
    monkeypatch.setattr(shipment_delivery, '_live_funding', lambda *_: {})


def test_submit_completes_batch_unlocks_editor_and_allows_next_quote_with_remote_draft(db, order, batch):
    row, outbound, inspection = batch
    submit(db)
    assert (row.state, outbound.status) == ('shipped', 'shipped')
    assert db.query(SettlementApplication).one().status == 'applied'
    ensure_mutable(db, order)
    data = evidence(db, order); data['outbounds'] = [detail(outbound)]
    quoted = shipments.build_quote(db, order, ShipmentQuote(items=[{'invoice_item_id': order.items[0].id, 'quantity': 2}], freight_amount='0'), data, current=True)
    assert quoted['items'][0]['quantity'] == 2
    assert db.query(SettlementEvent).filter_by(action='inspection_submitted').count() == 1
    submit(db)
    assert db.query(SettlementEvent).filter_by(action='inspection_submitted').count() == 1


def test_recall_relocks_without_releasing_consumed_money_and_resubmit_restores(db, order, batch):
    row, outbound, inspection = batch
    submit(db)
    service.recall(db, inspection.id, 1, 0)
    assert (row.state, outbound.status) == ('outbound_pending', 'pending_remote')
    assert db.query(SettlementApplication).one().status == 'applied'
    with pytest.raises(ValueError, match='未完成'):
        ensure_mutable(db, order)
    service.submit(db, outbound_record_id='OB001', user_id=1, edit_version=1)
    assert (row.state, outbound.status) == ('shipped', 'shipped')


@pytest.mark.parametrize('remote_status,submitted,expected', [(1,True,'shipped'), (2,False,'pending_remote'), (1,False,'pending_remote')])
def test_refresh_uses_inspection_instead_of_supplier_status(db, batch, monkeypatch, remote_status, submitted, expected):
    row, outbound, inspection = batch
    if submitted: submit(db)
    remote_reads(monkeypatch, outbound, remote_status)
    assert shipment_delivery.refresh(db, outbound.id) == expected
    assert row.state == ('shipped' if submitted else 'outbound_pending')


def test_mirror_identity_and_quantity_must_match_frozen_batch(db, batch):
    row, outbound, inspection = batch
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET quantity=2 WHERE id='IT001'")); db.commit()
    submit(db)
    assert row.state != 'shipped'
    assert db.query(SettlementApplication).one().status == 'reserved'


def test_reconciliation_draft_readback_retains_inspection_completion_without_remote_shipped_proof(db, order, batch, monkeypatch):
    row, outbound, inspection = batch
    submit(db)
    graph = SimpleNamespace(outbound=outbound, applications=db.query(SettlementApplication).all())
    observed = SimpleNamespace(active=True, matches=True, status='1', lines_json='{}', funds=object())
    monkeypatch.setattr(reconciliation.funding, 'apply', lambda *_: True)
    reconciliation._apply(db, order, row, graph, SimpleNamespace(remote_id=None), observed)
    assert (row.state, outbound.status) == ('shipped', 'shipped')


def test_submission_and_recall_work_when_production_autoflush_is_disabled(db, batch):
    db.autoflush = False
    row, outbound, inspection = batch
    submit(db)
    assert (row.state, outbound.status) == ('shipped', 'shipped')
    service.recall(db, inspection.id, 1, 0)
    db.expire_all()
    assert (row.state, outbound.status, inspection.status) == ('outbound_pending', 'pending_remote', 'draft')
    assert db.query(SettlementApplication).one().status == 'applied'


def test_existing_submitted_inspection_is_backfilled_by_background_readback(db, batch, monkeypatch):
    row, outbound, inspection = batch
    inspection.status = 'submitted'; db.commit()  # Pre-upgrade warehouse record.
    remote_reads(monkeypatch, outbound)
    assert shipment_delivery.refresh(db, outbound.id) == 'shipped'
    assert row.state == 'shipped'
    assert db.query(SettlementApplication).one().status == 'applied'


def test_submitted_inspection_cannot_bypass_invalid_funding(db, batch):
    from app.receipt.models import Receipt
    row, outbound, inspection = batch
    db.query(Receipt).one().collect_status = 0; db.commit()
    submit(db)
    assert inspection.status == 'submitted'
    assert (row.state, outbound.status) == ('outbound_uncertain', 'shipped_unfunded')
    assert db.query(SettlementApplication).one().status == 'reserved'


def test_refresh_cannot_overwrite_recall_during_unlocked_funding_read(db, batch, monkeypatch):
    row, outbound, inspection = batch
    submit(db); remote_reads(monkeypatch, outbound)
    def race(*_):
        service.recall(db, inspection.id, 1, 0)
        return True
    monkeypatch.setattr(shipment_delivery, '_refresh_funding', race)
    with pytest.raises(ValueError, match='检验状态.*变化'):
        shipment_delivery.refresh(db, outbound.id)
    assert (row.state, outbound.status, inspection.status) == ('outbound_pending', 'pending_remote', 'draft')


def test_removed_confirmation_route_and_writer_cannot_send_supplier_status_two():
    from app.invoice.settlement_router import shipment_state_router
    from app.invoice import shipment_confirmation_service
    assert not any(route.path.endswith('/confirm-outbound') for route in shipment_state_router.routes)
    assert not hasattr(shipment_delivery, 'confirm')
    assert not hasattr(shipment_confirmation_service, 'confirm')


def test_admin_binding_reads_submitted_inspection_and_funds_from_proposed_remote_id(db, order, batch, monkeypatch):
    from app.auth.models import ArkUser, ArkRole
    from app.invoice.settlement_schemas import SettlementRemoteReview
    row, outbound, inspection = batch
    actor = ArkUser(id=1, username='inspection-admin', password_hash='x', real_name='Admin', is_active=True)
    actor.roles = [ArkRole(name='super_admin', label='Admin')]
    db.add(actor)
    inspection.status = 'submitted'
    outbound.remote_id = None; outbound.status = 'uncertain'; row.state = 'outbound_uncertain'
    db.commit()
    body = SettlementRemoteReview(version=row.version, reason='Bind original inspected note', remote_id='900')
    identity = row.id
    db.commit()
    remote_reads(monkeypatch, outbound)
    reads = []
    monkeypatch.setattr(reconciliation.funding, 'read', lambda _db, target: reads.append(target) or object())
    monkeypatch.setattr(reconciliation.funding, 'apply', lambda *_: True)
    result = reconciliation.reconcile(db, identity, body, {'sub':'1'})
    assert len(reads) == 1
    assert result['state'] == 'shipped' and result['outbound']['remote_id'] == '900'
    assert result['outbound']['status'] == 'shipped'


def test_resolving_unsent_historical_confirmation_keeps_inspection_completion(db, batch, monkeypatch):
    from app.invoice import shipment_confirmation_recovery as recovery
    row, outbound, inspection = batch
    submit(db)
    history = SimpleNamespace(unsent=True, rejected=False, was_shipped=False, attempt=object())
    journal = SimpleNamespace(pending=(history,), histories=(history,), proven_shipped=False)
    observed = SimpleNamespace(active=True, matches=True, status='1')
    finishes = []
    monkeypatch.setattr(recovery.facts, 'finish', lambda *_args, **kwargs: finishes.append(kwargs['resolution']))
    recovery.apply(db,outbound,row,journal,observed,previous_status='shipped',inspection_basis=True)
    assert finishes == ['not_sent']
    assert (row.state,outbound.status) == ('shipped','shipped')
