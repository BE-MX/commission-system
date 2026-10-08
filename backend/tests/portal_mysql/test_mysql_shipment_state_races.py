"""Actual InnoDB waits and single-transaction local state acknowledgment recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import queue
import threading
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.auth import admin_router
from app.invoice import shipment_state_service
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement, SettlementApplication, SettlementEvent, ReceiptBatch
from app.portal import authority as portal_authority
from app.receipt import batch_create_service
from app.receipt.models import Receipt, ReceiptLog
from app.semifinished.models import InvoiceAllocation
from test_mysql_shipment_state import setup, state_path, ACTIONS, state_app  # noqa: F401
from test_mysql_shipment_state_boundaries import guarded, rejected
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401
from test_mysql_receipt_batch_presale import presale_payload, separate_proof
from test_mysql_concurrency import wait_for_lock



def state_delta(c, before, action, body):
    """Whitelist the actual change across the explicit 21-model snapshot."""
    after = snapshot(c)
    assert len(before) == len(after) == 21
    expected = [[deepcopy(dict(row._mapping)) for row in table] for table in before]
    actual = [[deepcopy(dict(row._mapping)) for row in table] for table in after]
    # The snapshot contract appends Application, Settlement, Item, Outbound,
    # Event after the original finite Receipt/PI/portal/batch/target graph.
    assert all({'receipt_id', 'component', 'bank_charge', 'status'} <= row.keys() for row in expected[16])
    assert all({'invoice_id', 'state', 'version', 'updated_at'} <= row.keys() for row in expected[17])
    target = [row for row in expected[17] if row['id'] == c.settlement_id]
    assert len(target) == 1 and target[0]['version'] == body['version']
    current = next(row for row in actual[17] if row['id'] == c.settlement_id)
    target[0].update(state={'cancel': 'cancelled', 'pause': 'paused', 'resume': 'awaiting_payment'}[action],
        version=body['version'] + 1, updated_at=current['updated_at'])
    if action == 'cancel':
        for row in expected[16]:
            if row['settlement_id'] == c.settlement_id: row['status'] = 'released'
    old_ids = {row['id'] for row in expected[20]}
    new_events = [row for row in actual[20] if row['id'] not in old_ids]
    assert len(new_events) == 1
    new = new_events[0]
    assert (new['settlement_id'], new['action'], new['reason'], new['actor_id']) == (
        c.settlement_id, action, body['reason'], c.ctx.actor)
    assert new['created_at'] is not None
    expected[20].append(new)
    expected[20].sort(key=lambda row: row['id'])
    # Receipt amount/fee/status, other Applications, historical events and all
    # remaining association rows must be exactly unchanged, not just counts.
    assert actual == expected
    return after


@pytest.mark.parametrize('change', ['receipt', 'application', 'late_log', 'allocation', 'invoice_binding'])
def test_current_graph_after_real_invoice_wait_rejects_without_writes(state_app, change):
    c = state_app; started = queue.Queue(); locked = threading.Event(); resume = threading.Event(); target = {}
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection'] = connection; started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection, cursor, statement, parameters, context, executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not locked.is_set():
            locked.set(); assert resume.wait(10)
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'resume', quantity=10, freight='0.00')
        with Session(c.ctx.engine) as other, ThreadPoolExecutor(max_workers=1) as pool:
            other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update())
            app = other.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id))
            if change == 'receipt': other.get(Receipt, app.receipt_id).sync_status = 'uncertain'
            elif change == 'application': app.component = 'goods'
            elif change == 'late_log': other.add(ReceiptLog(receipt_id=app.receipt_id, action='late_result', message='Concurrent persisted fact only'))
            elif change == 'allocation': other.add(InvoiceAllocation(invoice_id=c.invoice_id, status='pending'))
            else: other.get(ShipmentSettlement, c.settlement_id).invoice_id = c.second_invoice_id
            other.flush(); c.io.clear()
            event.listen(c.ctx.engine, 'before_cursor_execute', observe); event.listen(c.ctx.engine, 'after_cursor_execute', hold)
            action = pool.submit(client.post, state_path(c, 'resume'), headers=owner, json=body)
            try:
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not action.done()
                other.commit(); assert locked.wait(5) and not action.done()
                # Pause after actual current lock acquisition so target writes
                # cannot accidentally enter the externally committed baseline.
                before = snapshot(c); resume.set(); response = action.result(timeout=5)
            finally:
                resume.set(); other.rollback()
                event.remove(c.ctx.engine, 'before_cursor_execute', observe); event.remove(c.ctx.engine, 'after_cursor_execute', hold)
        guarded(response, 409); assert snapshot(c) == before and c.io == [] and c.calls == []


def test_resume_sees_new_funds_and_response_after_real_invoice_wait(state_app):
    c = state_app; started = queue.Queue(); locked = threading.Event(); resume = threading.Event(); target = {}
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection'] = connection; started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection, cursor, statement, parameters, context, executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not locked.is_set():
            locked.set(); assert resume.wait(10)
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'resume', payment=True)
        with Session(c.ctx.engine) as other, ThreadPoolExecutor(max_workers=1) as pool:
            other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update())
            apps = other.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id == c.settlement_id)).all()
            for app in apps:
                app.amount *= 2; app.bank_charge *= 2
                receipt = other.get(Receipt, app.receipt_id); receipt.amount = app.amount; receipt.bank_charge = app.bank_charge
            for batch_id in {other.get(Receipt, app.receipt_id).batch_id for app in apps}:
                batch = other.get(ReceiptBatch, batch_id); batch.gross_amount *= 2; batch.bank_charge_total *= 2
            other.flush(); c.io.clear()
            event.listen(c.ctx.engine, 'before_cursor_execute', observe); event.listen(c.ctx.engine, 'after_cursor_execute', hold)
            action = pool.submit(client.post, state_path(c, 'resume'), headers=owner, json=body)
            try:
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not action.done()
                other.commit(); assert locked.wait(5) and not action.done(); resume.set(); response = action.result(timeout=5)
            finally:
                resume.set(); other.rollback()
                event.remove(c.ctx.engine, 'before_cursor_execute', observe); event.remove(c.ctx.engine, 'after_cursor_execute', hold)
        guarded(response, 200); data = response.json()['data']
        assert data['state'] == 'awaiting_verification' and data['balance']['remaining_amount'] == '0.00'
        assert data['balance']['registered_amount'] == '64.00' and data['balance']['charge_remaining'] == '0.00'
        with Session(c.ctx.engine) as db:
            assert db.get(ShipmentSettlement, c.settlement_id).version == body['version'] + 1
            assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id, action='resume').count() == 1
        assert c.io == [] and c.calls == []


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('commit', [False, True])
def test_state_commit_or_rollback_precedes_actual_admin_revocation(state_app, enabled, commit, monkeypatch):
    c = state_app; c.app.settings.PORTAL_ENABLED = enabled
    monkeypatch.setattr(portal_authority, 'get_settings', lambda: c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready = threading.Event(); resume = threading.Event(); started = queue.Queue(); sessions = []; hits = []
    original = shipment_state_service.change
    def changed(db, *args):
        sessions.append(db); return original(db, *args)
    def gate(db):
        if any(db is value for value in sessions):
            hits.append(db); ready.set(); assert resume.wait(10)
            if not commit: raise OperationalError('private-state-final', {}, Exception('private-rollback'))
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        root, owner, body = setup(client, c, 'cancel', quantity=10, freight='0.00'); before = snapshot(c); c.io.clear()
        monkeypatch.setattr(shipment_state_service, 'change', changed); event.listen(Session, 'before_commit', gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post, state_path(c, 'cancel'), headers=owner, json=body)
            try:
                assert ready.wait(5); event.listen(c.ctx.engine, 'before_cursor_execute', observe)
                revoked = pool.submit(change_user, client, c, root, {'is_active': False})
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not action.done() and not revoked.done()
                resume.set(); response = action.result(timeout=5); revoked.result(timeout=5)
            finally:
                resume.set(); event.remove(Session, 'before_commit', gate)
                if event.contains(c.ctx.engine, 'before_cursor_execute', observe): event.remove(c.ctx.engine, 'before_cursor_execute', observe)
        assert len(sessions) == 1 and hits == sessions
        guarded(response, 200 if commit else 503)
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, c.settlement_id)
            assert row.state == ('cancelled' if commit else 'awaiting_payment') and row.version == body['version'] + int(commit)
            assert db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id)).status == ('released' if commit else 'reserved')
            assert db.query(SettlementEvent).filter_by(settlement_id=row.id, action='cancel').count() == int(commit)
        if commit: state_delta(c, before, 'cancel', body)
        else: assert snapshot(c) == before
        rejected(client, c, 'cancel', owner, body, 403)
        assert c.io == [] and c.calls == []


@pytest.mark.parametrize('enabled', [False, True])
def test_actual_admin_revocation_commits_before_waiting_state(state_app, enabled, monkeypatch):
    c = state_app; c.app.settings.PORTAL_ENABLED = enabled
    monkeypatch.setattr(portal_authority, 'get_settings', lambda: c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready = threading.Event(); resume = threading.Event(); started = queue.Queue(); sessions = []
    original = admin_router.begin_employee_authority_write
    def authority_write(db, *args, **kwargs):
        sessions.append(db); return original(db, *args, **kwargs)
    def gate(db):
        if any(db is value for value in sessions): ready.set(); assert resume.wait(10)
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        root, owner, body = setup(client, c, 'pause'); before = snapshot(c); c.io.clear()
        monkeypatch.setattr(admin_router, 'begin_employee_authority_write', authority_write); event.listen(Session, 'before_commit', gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoked = pool.submit(change_user, client, c, root, {'role_ids': []})
            try:
                assert ready.wait(5); event.listen(c.ctx.engine, 'before_cursor_execute', observe)
                action = pool.submit(client.post, state_path(c, 'pause'), headers=owner, json=body)
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not action.done() and not revoked.done()
                resume.set(); revoked.result(timeout=5); response = action.result(timeout=5)
            finally:
                resume.set(); event.remove(Session, 'before_commit', gate)
                if event.contains(c.ctx.engine, 'before_cursor_execute', observe): event.remove(c.ctx.engine, 'before_cursor_execute', observe)
        guarded(response, 403); assert len(sessions) == 1 and snapshot(c) == before and c.io == [] and c.calls == []


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('timing', ['before_commit', 'after_commit'])
def test_exact_single_commit_fault_then_read_original_version_event(state_app, action, timing, monkeypatch):
    c = state_app; sessions = []; hits = []; original = shipment_state_service.change
    def changed(db, *args):
        sessions.append(db); return original(db, *args)
    def fail(db):
        if any(db is value for value in sessions):
            hits.append(db); raise OperationalError('private-state-commit', {}, Exception('private-ack'))
    with c.app.client() as client:
        _, owner, body = setup(client, c, action, quantity=10, freight='0.00'); before = snapshot(c); c.io.clear()
        monkeypatch.setattr(shipment_state_service, 'change', changed); event.listen(Session, timing, fail)
        try: response = client.post(state_path(c, action), headers=owner, json=body)
        finally: event.remove(Session, timing, fail)
        guarded(response, 503); assert 'private-' not in response.text and len(sessions) == 1 and hits == sessions
        committed = timing == 'after_commit'
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, c.settlement_id)
            assert row.version == body['version'] + int(committed)
            assert row.state == ({'cancel': 'cancelled', 'pause': 'paused', 'resume': 'awaiting_payment'}[action] if committed else ('paused' if action == 'resume' else 'awaiting_payment'))
            assert db.query(SettlementEvent).filter_by(settlement_id=row.id, action=action).count() == int(committed)
            assert db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id)).status == ('released' if action == 'cancel' and committed else 'reserved')
        if committed: state_delta(c, before, action, body)
        else: assert snapshot(c) == before
        after = snapshot(c); c.io.clear()
        read = client.get(f'/api/shipments/{c.settlement_id}', headers=owner); guarded(read, 200)
        assert read.json()['data']['version'] == body['version'] + int(committed) and snapshot(c) == after
        if committed: rejected(client, c, action, owner, body)
        else:
            result = client.post(state_path(c, action), headers=owner, json=body); guarded(result, 200)
            with Session(c.ctx.engine) as db: assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id, action=action).count() == 1
        assert c.io == [] and c.calls == []


@pytest.mark.parametrize('action', ACTIONS)
def test_success_has_exactly_one_caller_commit(state_app, action, monkeypatch):
    c = state_app; sessions = []; before = []; after = []; original = shipment_state_service.change
    def changed(db, *args): sessions.append(db); return original(db, *args)
    def started(db):
        if any(db is value for value in sessions): before.append(db)
    def completed(db):
        if any(db is value for value in sessions): after.append(db)
    with c.app.client() as client:
        _, owner, body = setup(client, c, action, quantity=10, freight='0.00'); financial_before = snapshot(c); c.io.clear()
        monkeypatch.setattr(shipment_state_service, 'change', changed)
        event.listen(Session, 'before_commit', started); event.listen(Session, 'after_commit', completed)
        try: response = client.post(state_path(c, action), headers=owner, json=body)
        finally: event.remove(Session, 'before_commit', started); event.remove(Session, 'after_commit', completed)
        guarded(response, 200); assert len(sessions) == 1 and before == sessions and after == sessions
        state_delta(c, financial_before, action, body)
        assert c.io == [] and c.calls == []


@pytest.mark.parametrize('table', ['ark_users', 'ark_settlement_applications', 'ark_receivables'])
def test_actual_sql_failure_no_private_data_or_partial_state(state_app, table):
    c = state_app; hits = []
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and table in statement:
            hits.append(table); raise OperationalError('private-state-query', {}, Exception('private-secret'))
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'cancel', quantity=10, freight='0.00'); before = snapshot(c); c.io.clear()
        event.listen(c.ctx.engine, 'before_cursor_execute', fail)
        try: response = client.post(state_path(c, 'cancel'), headers=owner, json=body)
        finally: event.remove(c.ctx.engine, 'before_cursor_execute', fail)
        guarded(response, 503); assert hits == [table] and 'private-' not in response.text
        assert snapshot(c) == before and c.io == [] and c.calls == []


@pytest.mark.parametrize('second_action', ['cancel', 'resume'])
def test_competing_same_version_only_one_success_and_event(state_app, second_action, monkeypatch):
    c = state_app; ready = threading.Event(); release = threading.Event(); sessions = []; started = queue.Queue()
    original = shipment_state_service.change
    def changed(db, *args): sessions.append(db); return original(db, *args)
    def gate(db):
        if sessions and db is sessions[0]: ready.set(); assert release.wait(10)
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'resume', quantity=10, freight='0.00'); financial_before = snapshot(c); c.io.clear()
        monkeypatch.setattr(shipment_state_service, 'change', changed); event.listen(Session, 'before_commit', gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, state_path(c, 'cancel'), headers=owner, json=body)
            try:
                assert ready.wait(5); event.listen(c.ctx.engine, 'before_cursor_execute', observe)
                second = pool.submit(client.post, state_path(c, second_action), headers=owner, json=deepcopy(body))
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not first.done() and not second.done()
                release.set(); responses = [first.result(timeout=5), second.result(timeout=5)]
            finally:
                release.set(); event.remove(Session, 'before_commit', gate)
                if event.contains(c.ctx.engine, 'before_cursor_execute', observe): event.remove(c.ctx.engine, 'before_cursor_execute', observe)
        assert [response.status_code for response in responses] == [200, 409], [response.text for response in responses]
        for response in responses: guarded(response, response.status_code)
        assert responses[0].json()['data']['state'] == 'cancelled'
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, c.settlement_id); assert row.version == body['version'] + 1 and row.state == 'cancelled'
            assert db.query(SettlementEvent).filter_by(settlement_id=row.id, action='cancel').count() == 1
            assert db.query(SettlementEvent).filter_by(settlement_id=row.id, action='resume').count() == 0
            assert db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id)).status == 'released'
        state_delta(c, financial_before, 'cancel', body)
        assert len(sessions) == 2 and c.io == [] and c.calls == []


@pytest.mark.parametrize('first', ['state', 'funding'])
def test_actual_batch_funding_and_state_final_transactions_serialize(state_app, first, monkeypatch):
    c = state_app; ready = threading.Event(); release = threading.Event(); started = queue.Queue(); states = []; funds = []; state_locked = threading.Event(); state_release = threading.Event(); state_thread = []
    original_state = shipment_state_service.change; original_fund = batch_create_service._authorize
    def changed(db, *args):
        states.append(db); state_thread.append(threading.get_ident()); return original_state(db, *args)
    def funded(db, *args):
        if not any(db is value for value in funds): funds.append(db)
        return original_fund(db, *args)
    def gate(db):
        selected = states if first == 'state' else funds
        if any(db is value for value in selected):
            count = db.info.get('owned_state_fund_commit', 0) + 1; db.info['owned_state_fund_commit'] = count
            if count == (1 if first == 'state' else 3): ready.set(); assert release.wait(10)
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold_state(connection, cursor, statement, parameters, context, executemany):
        if first == 'funding' and state_thread and threading.get_ident() == state_thread[0] and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not state_locked.is_set():
            state_locked.set(); assert state_release.wait(10)
    with c.app.client() as client:
        _, owner, body = setup(client, c, 'pause'); payment = presale_payload(client, c, owner, '32.00')
        payment['attachment_ids'] = [separate_proof(c)]; financial_before = snapshot(c); c.io.clear()
        monkeypatch.setattr(shipment_state_service, 'change', changed); monkeypatch.setattr(batch_create_service, '_authorize', funded)
        event.listen(Session, 'before_commit', gate); event.listen(c.ctx.engine, 'after_cursor_execute', hold_state)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(client.post, state_path(c, 'pause'), headers=owner, json=body) if first == 'state' else pool.submit(client.post, '/api/receipts/batches', headers=owner, json=payment)
            try:
                assert ready.wait(5); event.listen(c.ctx.engine, 'before_cursor_execute', observe)
                second_future = pool.submit(client.post, '/api/receipts/batches', headers=owner, json=payment) if first == 'state' else pool.submit(client.post, state_path(c, 'cancel'), headers=owner, json=body)
                wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not first_future.done() and not second_future.done()
                release.set(); first_response = first_future.result(timeout=5)
                if first == 'funding':
                    assert state_locked.wait(5) and not second_future.done()
                    funded_before = snapshot(c); state_release.set()
                responses = [first_response, second_future.result(timeout=5)]
            finally:
                release.set(); state_release.set(); event.remove(Session, 'before_commit', gate)
                event.remove(c.ctx.engine, 'after_cursor_execute', hold_state)
                if event.contains(c.ctx.engine, 'before_cursor_execute', observe): event.remove(c.ctx.engine, 'before_cursor_execute', observe)
        assert [r.status_code for r in responses] == [200, 409], [r.text for r in responses]
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, c.settlement_id)
            assert row.state == ('paused' if first == 'state' else 'awaiting_payment') and row.version == body['version'] + 1
            assert db.query(ReceiptBatch).filter_by(request_key=payment['request_key']).count() == int(first == 'funding')
            apps = db.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id)).all()
            assert len(apps) == (0 if first == 'state' else 2)
            if first == 'funding':
                batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key == payment['request_key']))
                assert (batch.gross_amount, batch.bank_charge_total, batch.customer_id, batch.currency) == (Decimal('32'), Decimal('2'), row.quote['customer_id'], row.quote['currency'])
                for app in apps:
                    receipt = db.get(Receipt, app.receipt_id)
                    assert (receipt.batch_id, receipt.invoice_id, receipt.customer_id, receipt.currency, receipt.amount, receipt.bank_charge) == (batch.id, row.invoice_id, batch.customer_id, batch.currency, app.amount, app.bank_charge)
                assert {app.component: (app.amount, app.bank_charge) for app in apps} == {'goods': (Decimal('22'), Decimal('2')), 'freight': (Decimal('10'), Decimal('0'))}
        if first == 'funding':
            assert snapshot(c) == funded_before
            body['version'] += 1; rejected(client, c, 'cancel', owner, body)
        else: state_delta(c, financial_before, 'pause', body)
        assert c.calls == []
