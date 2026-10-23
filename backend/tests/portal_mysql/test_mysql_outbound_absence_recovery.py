"""Admin terminal declarations on real JWT/main/owned MySQL; no supplier writes."""
from copy import deepcopy

import pytest
from sqlalchemy import Column, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.invoice import shipment_absence_recovery as recovery, shipment_creation_facts as facts
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication, Receivable, ReceiptBatch, SettlementItem, SettlementEvent
from app.receipt.models import Receipt
from test_mysql_outbound_reconciliation import prepare as original_prepare
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


@pytest.fixture(scope='session')
def service_schema(service_schema):
    # The historical owned-MySQL portal harness predates nullable catalog and
    # quote fields now present in main. Scaffold current columns needed by its
    # trade fixture only; this is not a full production migration replay.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.portal.models import CatalogItem, Quote, OrderRequest
    assert service_schema.engine.url.host == '127.0.0.1'
    with service_schema.engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for model in (CatalogItem, Quote, OrderRequest):
            present = {column['name'] for column in inspect(connection).get_columns(model.__tablename__)}
            for column in model.__table__.columns:
                if column.name not in present:
                    operations.add_column(model.__tablename__, Column(column.name, column.type, nullable=True))
    return service_schema


def route(c): return f'/api/shipments/{c.settlement_id}/recover-outbound'


def prepare(c, client, monkeypatch):
    root, owner, _ = original_prepare(c, client, 'bind', monkeypatch)
    with Session(c.ctx.engine) as db:
        row = db.get(ShipmentSettlement, c.settlement_id)
        row.state = 'outbound_uncertain'; row.version += 1
        db.get(ShipmentOutbound, c.target_id).lease_until = None
        db.commit()
    response = client.get(f'/api/shipments/{c.settlement_id}', headers=owner)
    assert response.status_code == 200, response.text
    view = response.json()['data']
    assert view['actions']['recover_outbound']['allowed'] is True
    body = {'version': view['version'], 'recovery_version': view['actions']['recover_outbound']['version'],
        'original_request_closed': True, 'resolution_reference': 'OKKI synthetic closed-request ticket 2026-001',
        'reason': 'Employee verified the original request terminated without creation'}
    c.lookups = []
    def absent(db, serial):
        assert db.info.get('stock_executor_fence') is True
        with Session(c.ctx.engine) as independent:
            invoice = independent.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update(nowait=True))
            assert invoice.id == c.invoice_id
        c.lookups.append(serial)
        return None
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', absent)
    c.io.clear(); c.calls.clear()
    return root, owner, body


def financial_rows(c):
    with Session(c.ctx.engine) as db:
        return {model.__tablename__: [dict(row) for row in db.execute(select(*model.__table__.columns)
            .order_by(*model.__table__.primary_key.columns)).mappings()]
            for model in (Invoice, InvoiceItem, Receipt, ReceiptBatch, Receivable, SettlementApplication, SettlementItem)}


def test_employee_terminal_resolution_recovers_only_original_task(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client, monkeypatch)
        before = financial_rows(c)
        with Session(c.ctx.engine) as db:
            target = db.get(ShipmentOutbound, c.target_id)
            fixed = {key: deepcopy(getattr(target, key)) for key in ('id', 'outbound_no', 'payload', 'payload_hash')}
            quote = deepcopy(db.get(ShipmentSettlement, c.settlement_id).quote)
        response = client.post(route(c), headers=owner, json=body)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        result = response.json()['data']
        assert result['version'] == body['version'] + 1 and result['state'] == 'outbound_pending'
        assert result['outbound']['id'] == c.target_id and result['quote'] == quote
        assert financial_rows(c) == before and c.calls == [] and len(c.lookups) == 1
        with Session(c.ctx.engine) as db:
            target = db.get(ShipmentOutbound, c.target_id)
            assert {key: getattr(target, key) for key in fixed} == fixed
            audit = facts.rows(db, target.id)[0]
            assert audit.actor_id == c.ctx.actor and audit.action == facts.RECOVERED
            assert audit.safe_diff_json['resolution_reference'] == body['resolution_reference']
            assert audit.safe_diff_json['attempt_token'] == 'original-' + str(c.target_id)
            assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id, action='recover_outbound').count() == 1
        again = client.post(route(c), headers=owner, json=body)
        assert again.status_code == 409 and financial_rows(c) == before and len(c.lookups) == 1


@pytest.mark.parametrize('revoke', ['disabled', 'write', 'admin', 'owner'])
def test_current_permissions_and_invoice_scope_precede_provider_lookup(state_app, monkeypatch, revoke):
    c = state_app
    with c.app.client() as client:
        root, owner, body = prepare(c, client, monkeypatch)
        if revoke == 'disabled': change_user(client, c, root, {'is_active': False})
        elif revoke == 'owner':
            with Session(c.ctx.engine) as db: db.get(Invoice, c.invoice_id).sales_user_id = c.other_id; db.commit()
        else:
            denied = c.roles['shipment:' + revoke]
            change_user(client, c, root, {'role_ids': [role for role in c.grants if role != denied]})
        before = snapshot(c)
        response = client.post(route(c), headers=owner, json=body)
        assert response.status_code == (404 if revoke == 'owner' else 403), response.text
        assert snapshot(c) == before and c.lookups == [] and c.calls == []


def test_current_grant_can_authorize_an_old_token_without_permission_claims(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        root, _, body = prepare(c, client, monkeypatch)
        change_user(client, c, root, {'role_ids': []}); old_token = login(client, c, c.owner_name)
        change_user(client, c, root, {'role_ids': c.grants})
        response = client.post(route(c), headers=old_token, json=body)
        assert response.status_code == 200, response.text
        assert response.json()['data']['state'] == 'outbound_pending' and c.calls == []


@pytest.mark.parametrize('patch', [{'original_request_closed': False}, {'resolution_reference': '    '}, {'original_request_closed': 'true'}])
def test_route_rejects_invalid_terminal_declarations_without_echoing_private_input(state_app, monkeypatch, patch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client, monkeypatch); before = snapshot(c)
        body.update(reason='PRIVATE_OPERATOR_NOTE', **patch)
        response = client.post(route(c), headers=owner, json=body)
        assert response.status_code == 422 and 'PRIVATE_' not in response.text, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert snapshot(c) == before and c.lookups == [] and c.calls == []


@pytest.mark.parametrize('change', ['authority', 'receipt', 'item', 'token', 'late_result'])
def test_current_graph_and_employee_grants_are_rechecked_after_lookup(state_app, monkeypatch, change):
    c = state_app
    with c.app.client() as client:
        root, owner, body = prepare(c, client, monkeypatch)
        observed = []
        def lookup(db, serial):
            if change == 'authority': change_user(client, c, root, {'is_active': False})
            else:
                with Session(c.ctx.engine) as independent:
                    if change == 'receipt': independent.get(Receipt, c.receipts['victim']).remark = 'Concurrent receipt edit'
                    elif change == 'item': independent.get(InvoiceItem, c.item_id).product_name = 'Concurrent item edit'
                    elif change == 'token': independent.get(ShipmentOutbound, c.target_id).attempt_token = 'new_attempt'
                    else: facts.remember_late_result(independent, independent.get(ShipmentOutbound, c.target_id), 'old_attempt', '401')
                    independent.commit()
            observed.append(snapshot(c)); return None
        monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lookup)
        response = client.post(route(c), headers=owner, json=body)
        assert response.status_code == (403 if change == 'authority' else 409), response.text
        assert len(observed) == 1 and snapshot(c) == observed[0] and c.calls == []


@pytest.mark.parametrize('fault', ['found', 'timeout', 'malformed'])
def test_remote_missing_is_strict_and_private(state_app, monkeypatch, fault):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client, monkeypatch); before = snapshot(c)
        def lookup(*args):
            if fault == 'timeout': raise recovery.okki_client.OkkiApiError('PRIVATE_PROVIDER_DETAIL')
            return {'serial_id': c.detail['serial_id'], 'outbound_invoice_id': '401'} if fault == 'found' else {}
        monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lookup)
        response = client.post(route(c), headers=owner, json=body)
        assert response.status_code == (409 if fault == 'found' else 503), response.text
        assert 'PRIVATE_' not in response.text and response.headers['cache-control'] == 'private, no-store'
        assert snapshot(c) == before and c.calls == []


def test_running_original_sender_holds_the_same_real_mysql_fence(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = prepare(c, client, monkeypatch); before = snapshot(c)
        with c.ctx.engine.connect() as sender:
            assert sender.scalar(text("SELECT GET_LOCK('ark-okki-outbound-poller',0)")) == 1
            try:
                response = client.post(route(c), headers=owner, json=body)
                assert response.status_code == 409, response.text
                assert snapshot(c) == before and c.lookups == []
            finally: assert sender.scalar(text("SELECT RELEASE_LOCK('ark-okki-outbound-poller')")) == 1


@pytest.mark.parametrize('timing', ['before_commit', 'after_commit'])
def test_uncertain_final_commit_is_read_back_without_replaying(state_app, monkeypatch, timing):
    c = state_app; sessions = []; hits = []; capture = recovery._capture
    def track(db, *args):
        if not any(db is item for item in sessions): sessions.append(db)
        return capture(db, *args)
    with c.app.client() as client:
        _, owner, body = prepare(c, client, monkeypatch); before = financial_rows(c)
        monkeypatch.setattr(recovery, '_capture', track)
        def fail(db):
            if any(db is item for item in sessions):
                count = db.info.get('absence_recovery_commit', 0) + 1; db.info['absence_recovery_commit'] = count
                if count == 3: hits.append(id(db)); raise OperationalError('PRIVATE_DB', {}, Exception('PRIVATE_ACK'))
        event.listen(Session, timing, fail)
        try: response = client.post(route(c), headers=owner, json=body)
        finally: event.remove(Session, timing, fail)
        assert response.status_code == 503 and hits == [id(sessions[0])] and 'PRIVATE_' not in response.text
        result = client.get(f'/api/shipments/{c.settlement_id}', headers=owner)
        assert result.status_code == 200, result.text
        assert result.json()['data']['state'] == ('outbound_uncertain' if timing == 'before_commit' else 'outbound_pending')
        assert financial_rows(c) == before and c.calls == []
