"""Real JWT/current authority and owned InnoDB; provider responses are synthetic."""
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest

from app.invoice import okki_client, settlement_service, shipment_confirmation_facts, shipment_delivery
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication
from app.receipt.models import Receipt, ReceiptLog
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import (shipment_app, snapshot, login, change_user, authorize,
    body_for, created, path)  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


def prepare(c, client):
    root = login(client, c, c.root_name); authorize(client, c, root)
    owner = login(client, c, c.owner_name)
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['victim']).purpose = 'presale_advance'; db.commit()
    original = body_for(client, c, owner, payment=False, freight='0.00')
    c.settlement_id = created(c, original, client.post(path(c), headers=owner, json=original))
    with Session(c.ctx.engine) as db:
        row = db.get(ShipmentSettlement, c.settlement_id)
        payload = {'serial_id': row.settlement_no, 'record_list': []}
        target = ShipmentOutbound(settlement_id=row.id, invoice_id=c.invoice_id, outbound_no=row.settlement_no,
            status='failed', payload=payload, payload_hash=settlement_service.digest(payload),
            last_error='Operation Failed: insufficient stock', attempt_token='original_failed_token', version=4)
        row.state = 'review_required'; db.add(target); db.flush(); c.target_id = target.id
        body = {'version': row.version, 'reason': 'Select available products and create a new batch'}
        db.commit()
    c.io.clear()
    return root, owner, body


def address(c):
    return f'/api/shipments/{c.settlement_id}/cancel'


def test_failed_cancel_delta_and_real_new_quote_with_retained_task(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client)
        before = snapshot(c); observed = []
        def absent(db, serial):
            with Session(c.ctx.engine) as other:
                other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update(nowait=True))
            observed.append(serial)
            return None
        monkeypatch.setattr(okki_client, 'find_outbound_by_serial', absent)
        detail = client.get(f'/api/shipments/{c.settlement_id}', headers=owner)
        assert detail.json()['data']['actions']['cancel']['requires_remote_check'] is True
        body['reason'] = 'x' * 500
        result = client.post(address(c), headers=owner, json=body)
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'private, no-store'
        data = result.json()['data']
        assert data['state'] == 'cancelled' and data['version'] == body['version'] + 1
        assert data['outbound']['status'] == 'cancelled' and len(observed) == 1
        expected = [[deepcopy(dict(row._mapping)) for row in table] for table in before]
        actual = [[dict(row._mapping) for row in table] for table in snapshot(c)]
        for entry in expected[16]:
            if entry['settlement_id'] == c.settlement_id: entry['status'] = 'released'
        row = next(entry for entry in expected[17] if entry['id'] == c.settlement_id)
        row.update(state='cancelled', version=body['version'] + 1,
            updated_at=next(entry for entry in actual[17] if entry['id'] == c.settlement_id)['updated_at'])
        target = next(entry for entry in expected[19] if entry['id'] == c.target_id)
        target.update(status='cancelled', version=5)
        old_ids = {entry['id'] for entry in expected[20]}
        additions = [entry for entry in actual[20] if entry['id'] not in old_ids]
        assert {entry['action'] for entry in additions} == {'cancel', 'cancel_verified'}
        assert next(entry for entry in additions if entry['action'] == 'cancel')['reason'] == body['reason']
        assert all(entry['actor_id'] == c.ctx.actor for entry in additions)
        expected[20].extend(additions); expected[20].sort(key=lambda entry: entry['id'])
        assert actual == expected and c.calls == []
        quoted = body_for(client, c, owner, payment=False, quantity=2, freight='0.00')
        new = client.post(path(c), headers=owner, json=quoted)
        assert new.status_code == 200, new.text
        with Session(c.ctx.engine) as db:
            replacement = db.get(ShipmentSettlement, new.json()['data']['id'])
            assert replacement.sequence == 2
            assert db.get(ShipmentOutbound, c.target_id).status == 'cancelled'
        # Stale user commands and direct delivery cannot revive the retired task.
        assert client.post(address(c), headers=owner, json=body).status_code == 409
        assert client.post(f'/api/shipments/{c.settlement_id}/retry-outbound', headers=owner, json={
            'version': data['version'], 'reason': 'Old failed task cannot retry'}).status_code == 409
        with Session(c.ctx.engine) as db:
            shipment_delivery.deliver(db, c.target_id)
            assert db.get(ShipmentOutbound, c.target_id).status == 'cancelled'


@pytest.mark.parametrize('revoke', ['disabled', 'roles', 'shipment:write'])
def test_denied_before_lookup(state_app, monkeypatch, revoke):
    c = state_app
    with c.app.client() as client:
        root, owner, body = prepare(c, client)
        patch = {'is_active': False} if revoke == 'disabled' else {'role_ids': []} if revoke == 'roles' else {
            'role_ids': [c.roles['invoice:write'], c.roles['write']]}
        change_user(client, c, root, patch); before = snapshot(c)
        monkeypatch.setattr(okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('Denied lookup'))
        response = client.post(address(c), headers=owner, json=body)
        assert response.status_code == 403 and snapshot(c) == before


@pytest.mark.parametrize('change', ['owner', 'receipt', 'task', 'settlement', 'confirmation_history', 'late_result', 'disabled'])
def test_changed_during_unlocked_lookup_rejected(state_app, monkeypatch, change):
    c = state_app
    with c.app.client() as client:
        root, owner, body = prepare(c, client); after_external = []
        def absent(db, serial):
            with Session(c.ctx.engine) as other:
                invoice = other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update(nowait=True))
                if change == 'owner': invoice.sales_user_id = c.other_id
                elif change == 'receipt': other.get(Receipt, c.receipts['victim']).remark = 'Changed during GET'
                elif change == 'task': other.get(ShipmentOutbound, c.target_id).version += 1
                elif change == 'settlement': other.get(ShipmentSettlement, c.settlement_id).version += 1
                elif change == 'confirmation_history':
                    # An incomplete legacy confirmation on a failed task is an
                    # inconsistency to preserve, never evidence of no shipment.
                    key = 'a' * 32
                    shipment_confirmation_facts.append(other, c.target_id, key,
                        shipment_confirmation_facts.START, {'attempt_key': key}, c.ctx.actor)
                elif change == 'late_result':
                    other.add(ReceiptLog(receipt_id=c.receipts['victim'], action='late_result', message='Late fact'))
                other.commit()
            if change == 'disabled': change_user(client, c, root, {'is_active': False})
            after_external.append(snapshot(c))
            return None
        monkeypatch.setattr(okki_client, 'find_outbound_by_serial', absent)
        response = client.post(address(c), headers=owner, json=body)
        assert response.status_code == (403 if change == 'disabled' else 404 if change == 'owner' else 409), response.text
        assert snapshot(c) == after_external[0] and c.calls == []


@pytest.mark.parametrize('outcome', ['exists', 'malformed', 'timeout'])
def test_no_absence_proof_no_business_change(state_app, monkeypatch, outcome):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client); before = snapshot(c)
        def lookup(db, serial):
            if outcome == 'timeout': raise okki_client.OkkiApiError('Remote unavailable')
            return {'outbound_invoice_id': '401', 'serial_id': serial} if outcome == 'exists' else {}
        monkeypatch.setattr(okki_client, 'find_outbound_by_serial', lookup)
        response = client.post(address(c), headers=owner, json=body)
        assert response.status_code == (409 if outcome == 'exists' else 503), response.text
        assert snapshot(c) == before and c.calls == []


def test_internal_absence_parameter_cannot_be_supplied_over_http(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client); before = snapshot(c)
        monkeypatch.setattr(okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('Invalid command lookup'))
        response = client.post(address(c), headers=owner, json={**body, 'failed_outbound_absent': True})
        assert response.status_code == 422 and snapshot(c) == before
