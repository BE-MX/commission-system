"""Actual shipment state policies, original finance and binding rejection."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.invoice import shipment_state_service
from app.invoice.models import Invoice
from app.invoice.settlement_models import (ShipmentSettlement, SettlementApplication, SettlementEvent,
    Receivable, ShipmentOutbound, ReceiptBatch)
from app.receipt.models import Receipt, ReceiptLog
from app.semifinished.models import InvoiceAllocation
from test_mysql_shipment_state import setup, state_path, ACTIONS, state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401
from test_mysql_receipt_batch_presale import presale_payload, separate_proof


def guarded(response, code):
    assert response.status_code == code, response.text
    assert response.headers.get('cache-control') == 'private, no-store'
    assert response.headers.get('pragma') == 'no-cache'


def rejected(client, c, action, owner, body, code=409):
    before = snapshot(c); c.io.clear()
    response = client.post(state_path(c, action), headers=owner, json=body)
    guarded(response, code)
    assert snapshot(c) == before and c.io == [] and c.calls == []
    return response


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('scope', ['all', 'super_admin'])
def test_current_original_financial_scope_not_invoice_all(state_app, action, scope):
    c = state_app
    with c.app.client() as client:
        root, _, body = setup(client, c, action)
        with Session(c.ctx.engine) as db:
            identity = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin')).id if scope == 'super_admin' else c.roles['all']
            db.get(Invoice, c.invoice_id).sales_user_id = c.other_id; db.commit()
        change_user(client, c, root, {'role_ids': [c.roles['shipment:write'], identity]})
        owner = login(client, c, c.owner_name)
        assert client.get(f'/api/shipments/{c.settlement_id}', headers=owner).status_code == 200
        change_user(client, c, root, {'role_ids': [c.roles['shipment:write'], c.roles['invoice:read_all']]})
        rejected(client, c, action, owner, body, 404)
        change_user(client, c, root, {'role_ids': [c.roles['shipment:write'], identity]})
        guarded(client.post(state_path(c, action), headers=owner, json=body), 200)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('credential', ['anonymous', 'invalid'])
def test_dependency_rejection_private_no_store(state_app, action, credential):
    c = state_app
    with c.app.client() as client:
        _, _, body = setup(client, c, action)
        rejected(client, c, action, {} if credential == 'anonymous' else {'Authorization': 'Bearer invalid'},
            body, 403 if credential == 'anonymous' else 401)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('invalid', ['path', 'body'])
def test_422_does_not_echo_private_command(state_app, action, invalid):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, action); before = snapshot(c); c.io.clear()
        if invalid == 'path':
            address = f'/api/shipments/PRIVATE_STATE_MARKER/{action}'
        else:
            address = state_path(c, action); body['private_note'] = 'PRIVATE_STATE_MARKER'
        response = client.post(address, headers=owner, json=body)
        guarded(response, 422); assert 'PRIVATE_STATE_MARKER' not in response.text
        assert snapshot(c) == before and c.io == [] and c.calls == []


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('state', ['shipped', 'cancelled', 'outbound_uncertain', 'review_required'])
def test_original_terminal_and_unknown_states_guard(state_app, action, state):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, action)
        with Session(c.ctx.engine) as db: db.get(ShipmentSettlement, c.settlement_id).state = state; db.commit()
        rejected(client, c, action, owner, body)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('status', ['sending', 'verifying', 'uncertain'])
def test_original_freight_unknown_guard(state_app, action, status):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, action)
        with Session(c.ctx.engine) as db:
            db.scalar(select(Receivable).where(Receivable.settlement_id == c.settlement_id)).remote_status = status; db.commit()
        rejected(client, c, action, owner, body)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('status', ['pending', 'failed'])
def test_any_existing_outbound_blocks_original_actions(state_app, action, status):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, action)
        with Session(c.ctx.engine) as db:
            db.add(ShipmentOutbound(settlement_id=c.settlement_id, invoice_id=c.invoice_id,
                outbound_no='OB-' + uuid4().hex, status=status, payload={}, payload_hash='a'*64)); db.commit()
        rejected(client, c, action, owner, body)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('status', ['syncing', 'uncertain'])
def test_original_funding_sync_guard(state_app, action, status):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, action, payment=True)
        with Session(c.ctx.engine) as db:
            app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id,
                SettlementApplication.component == 'goods'))
            db.get(Receipt, app.receipt_id).sync_status = status; db.commit()
        rejected(client, c, action, owner, body)


@pytest.mark.parametrize('change', ['ordinary', 'not_ready', 'pending_stock', 'main_freight'])
def test_original_order_prerequisites_preserved(state_app, change):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'pause')
        with Session(c.ctx.engine) as db:
            invoice = db.get(Invoice, c.invoice_id)
            if change == 'ordinary': invoice.order_type = 'stock'
            elif change == 'not_ready': invoice.sync_status = 'pending'
            elif change == 'main_freight': invoice.shipping_fee = Decimal('1')
            else: db.add(InvoiceAllocation(invoice_id=invoice.id, status='pending'))
            db.commit()
        rejected(client, c, 'pause', owner, body)


@pytest.mark.parametrize('change', ['invoice', 'customer', 'currency', 'purpose', 'missing_receipt',
    'component', 'target_invoice', 'target_key', 'target_kind', 'target_settlement', 'missing_target',
    'batch', 'amount', 'fee'])
def test_current_funding_association_rejected_before_any_apply(state_app, change):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'pause', payment=True)
        with Session(c.ctx.engine) as db:
            app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id,
                SettlementApplication.component == 'goods'))
            receipt = db.get(Receipt, app.receipt_id); target = db.get(Receivable, receipt.receivable_id)
            if change == 'invoice': receipt.invoice_id = c.second_invoice_id
            elif change == 'customer': receipt.customer_id = 'wrong-company'
            elif change == 'currency': receipt.currency = 'EUR'
            elif change == 'purpose': receipt.purpose = 'ordinary'
            elif change == 'missing_receipt': db.delete(receipt)
            elif change == 'component': app.component = 'freight'
            elif change == 'target_invoice': target.invoice_id = c.second_invoice_id
            elif change == 'target_key': target.business_key = 'invoice:wrong-' + uuid4().hex + ':goods'
            elif change == 'target_kind': target.kind = 'freight'
            elif change == 'target_settlement': target.settlement_id = c.settlement_id
            elif change == 'missing_target': db.delete(target)
            elif change == 'batch': receipt.batch_id = None
            elif change == 'amount': app.amount += 1
            else: app.bank_charge += 1
            db.commit()
        rejected(client, c, 'pause', owner, body)


@pytest.mark.parametrize('other_status', ['reserved', 'released'])
def test_cancel_releases_only_original_deposit_application(state_app, other_status):
    c = state_app
    with c.app.client() as client:
        root, owner, body = setup(client, c, 'cancel', quantity=10, freight='0.00')
        # No invoice or receipt write required for this original state action.
        change_user(client, c, root, {'role_ids': [c.roles['shipment:write']]})
        with Session(c.ctx.engine) as db:
            selected = db.get(ShipmentSettlement, c.settlement_id)
            own = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == selected.id))
            assert own.amount == 40 and own.bank_charge == 4 and own.status == 'reserved'
            historical = ShipmentSettlement(invoice_id=c.invoice_id, sequence=2, settlement_no='H-' + uuid4().hex,
                state='shipped', is_final=0, quote=deepcopy(selected.quote), quote_hash='h'*64,
                request_key=uuid4().hex, request_hash='b'*64, version=1, created_by=c.ctx.actor)
            db.add(historical); db.flush()
            other = SettlementApplication(settlement_id=historical.id, receipt_id=own.receipt_id,
                component='deposit', amount=10, bank_charge=1, status=other_status)
            db.add(other); db.flush(); other_id = other.id
            db.commit()
            receipt_before = tuple(getattr(db.get(Receipt, own.receipt_id), col.name) for col in Receipt.__table__.columns)
            other_before = tuple(getattr(other, col.name) for col in SettlementApplication.__table__.columns)
        c.io.clear(); response = client.post(state_path(c, 'cancel'), headers=owner, json=body); guarded(response, 200)
        assert response.json()['data']['state'] == 'cancelled' and response.json()['data']['version'] == body['version'] + 1
        with Session(c.ctx.engine) as db:
            assert db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id)).status == 'released'
            assert tuple(getattr(db.get(Receipt, c.receipts['victim']), col.name) for col in Receipt.__table__.columns) == receipt_before
            assert tuple(getattr(db.get(SettlementApplication, other_id), col.name) for col in SettlementApplication.__table__.columns) == other_before
            assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id, action='cancel').count() == 1
        rejected(client, c, 'cancel', owner, body)
        assert c.io == [] and c.calls == []


def test_original_real_payment_cancel_denied_pause_and_full_funding_resume_allowed(state_app):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'pause', payment=True)
        rejected(client, c, 'cancel', owner, body)
        payment = presale_payload(client, c, owner, '32.00'); payment['attachment_ids'] = [separate_proof(c)]
        response = client.post('/api/receipts/batches', headers=owner, json=payment)
        assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as db: body['version'] = db.get(ShipmentSettlement, c.settlement_id).version
        c.io.clear(); paused = client.post(state_path(c, 'pause'), headers=owner, json=body); guarded(paused, 200)
        assert paused.json()['data']['balance']['remaining_amount'] == '0.00'
        body['version'] = paused.json()['data']['version']
        resumed = client.post(state_path(c, 'resume'), headers=owner, json=body); guarded(resumed, 200)
        data = resumed.json()['data']; assert data['state'] == 'awaiting_verification'
        assert data['balance']['registered_amount'] == '64.00' and data['balance']['charge_remaining'] == '0.00'
        assert data['version'] == body['version'] + 1 and c.io == [] and c.calls == []


@pytest.mark.parametrize('history', ['late', 'legacy_reconciled', 'new_late_after_reconciled'])
def test_synced_and_free_text_reconciled_do_not_prove_late_facts_resolved(state_app, history):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'resume', payment=True)
        with Session(c.ctx.engine) as db:
            app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id,
                SettlementApplication.component == 'goods'))
            receipt = db.get(Receipt, app.receipt_id)
            receipt.sync_status = 'synced'; receipt.collect_status = 1; receipt.xiaoman_receipt_id = uuid4().hex
            db.add(ReceiptLog(receipt_id=receipt.id, action='late_result', message='Original persisted late effect'))
            if history != 'late': db.add(ReceiptLog(receipt_id=receipt.id, action='reconciled', message='Legacy unstructured manual bind marker'))
            if history == 'new_late_after_reconciled': db.add(ReceiptLog(receipt_id=receipt.id, action='late_result', message='Another late effect'))
            db.commit()
        rejected(client, c, 'resume', owner, body)


def test_pause_remains_allowed_with_late_fact_but_cancel_resume_not_allowed(state_app):
    c = state_app
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'cancel', quantity=10, freight='0.00')
        with Session(c.ctx.engine) as db:
            db.add(ReceiptLog(receipt_id=c.receipts['victim'], action='late_result', message='Persisted late deposit effect')); db.commit()
        rejected(client, c, 'cancel', owner, body)
        c.io.clear(); paused = client.post(state_path(c, 'pause'), headers=owner, json=body); guarded(paused, 200)
        assert paused.json()['data']['state'] == 'paused'
        body['version'] = paused.json()['data']['version']
        rejected(client, c, 'resume', owner, body)


def test_dirty_caller_preserves_its_unflushed_changes(state_app):
    c = state_app
    with Session(c.ctx.engine) as db:
        invoice = db.get(Invoice, c.invoice_id); before = invoice.remark; invoice.remark = 'Private caller-only note'
        with pytest.raises(HTTPException) as caught:
            shipment_state_service.change(db, 1, {'sub': str(c.ctx.actor)}, 'pause', 1, 'Caller dirty guard')
        assert caught.value.status_code == 409 and invoice in db.dirty and db.in_transaction()
        assert invoice.remark == 'Private caller-only note'
        with Session(c.ctx.engine) as other: assert other.get(Invoice, c.invoice_id).remark == before
        db.rollback()


@pytest.mark.parametrize('autoflush', [False, True])
def test_cancel_release_survives_production_autoflush_setting(state_app, autoflush, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core import database
    c = state_app; sessions = []; original = shipment_state_service.change
    def changed(db, *args):
        sessions.append(db); assert db.autoflush is autoflush; return original(db, *args)
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'cancel', quantity=10, freight='0.00')
        monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=c.ctx.engine, autoflush=autoflush))
        monkeypatch.setattr(shipment_state_service, 'change', changed); c.io.clear()
        response = client.post(state_path(c, 'cancel'), headers=owner, json=body); guarded(response, 200)
        assert len(sessions) == 1 and response.json()['data']['state'] == 'cancelled'
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, c.settlement_id)
            assert row.state == 'cancelled' and row.version == body['version'] + 1
            app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id))
            assert app.status == 'released' and app.amount == 40 and app.bank_charge == 4
            assert db.get(Receipt, app.receipt_id).status == 'active'
            assert db.query(SettlementEvent).filter_by(settlement_id=row.id, action='cancel').count() == 1
        assert c.io == [] and c.calls == []
