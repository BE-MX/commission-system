"""Current employee reconciliation on owned MySQL; remote reads controlled."""
from decimal import Decimal

import pytest
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, MetaData, String, Table, event, select, text

from app.auth.models import ArkRole
from app.invoice import okki_client
from sqlalchemy.exc import OperationalError
from test_mysql_concurrency import wait_for_lock
from app.invoice.models import Invoice
from app.receipt import remote, reconciliation_service, service
from app.receipt.models import Receipt, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401


@pytest.fixture
def reconcile_app(read_app, monkeypatch):
    c = read_app
    with c.ctx.engine.begin() as connection:
        indexes = connection.execute(text('SHOW INDEX FROM ark_receipts')).mappings().all()
        if not any(row['Column_name'] == 'xiaoman_receipt_id' and not row['Non_unique'] for row in indexes):
            connection.execute(text('ALTER TABLE ark_receipts ADD UNIQUE INDEX uq_owned_recovery_remote (xiaoman_receipt_id)'))
    c.evidence = []
    c.details = {}
    c.remote_rows = []
    with Session(c.ctx.engine) as db:
        for label, identity in c.receipts.items():
            row = db.get(Receipt, identity)
            row.sync_status = 'uncertain'
            row.bank_charge = Decimal('2.00')
            row.xiaoman_order_id = db.get(Invoice, row.invoice_id).xiaoman_order_id
            remote_id = str(identity + 8000000)
            c.details[remote_id] = dict(cash_collection_id=remote_id,
                cash_collection_no='REMOTE-'+remote_id, order_id=row.xiaoman_order_id,
                currency=row.currency, amount='8.00', bank_charge='0', real_amount='8.00',
                collection_date=row.collection_date.isoformat(), collect_status='0')
        db.commit()
    def info(db, identity):
        c.evidence.append(('info', str(identity)))
        return dict(c.details[str(identity)])
    def rows(db, identity):
        c.evidence.append(('rows', str(identity)))
        return [dict(row) for row in c.remote_rows]
    monkeypatch.setattr(remote, 'receipt_info', info)
    monkeypatch.setattr(remote, 'order_receipts', rows)
    return c


def operation(c, kind, label='victim'):
    identity = c.receipts[label]
    remote_id = str(identity + 8000000)
    with Session(c.ctx.engine) as db:
        row = db.get(Receipt, identity)
        row.xiaoman_receipt_id = remote_id if kind == 'reconcile' else None
        db.commit()
    path = '/api/receipts/'+str(identity)
    if kind == 'reconcile':
        return path+'/reconcile', None
    return path+'/resolve', dict(resolution='bind_receipt' if kind == 'bind' else 'confirm_not_created',
        xiaoman_receipt_id=remote_id if kind == 'bind' else None, reason='Verified original receipt')


def grant(client, c, root, kind, extra=()):
    action = c.roles['both'] if kind == 'reconcile' else c.roles['receipt:admin']
    change_user(client, c, root, {'role_ids':[action, *extra]})


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
@pytest.mark.parametrize('revocation', ['disabled', 'roles', 'action'])
def test_reconciliation_rejects_old_jwt_before_evidence(reconcile_app, kind, revocation):
    c = reconcile_app
    path, body = operation(c, kind)
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        grant(client, c, root, kind)
        owner = login(client, c, c.owner_name)
        change_user(client, c, root, {'is_active':False} if revocation == 'disabled' else
            {'role_ids':[]} if revocation == 'roles' else {'role_ids':[c.roles['read']]})
        before = read_snapshot(c)
        result = client.post(path, headers=owner, json=body)
        assert result.status_code == 403, result.text
        assert read_snapshot(c) == before and c.evidence == [] and c.calls == []


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
@pytest.mark.parametrize('global_role', ['all', 'super_admin'])
def test_reconciliation_uses_current_actual_receipt_scope(reconcile_app, kind, global_role):
    c = reconcile_app
    path, body = operation(c, kind, 'foreign')
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        with Session(c.ctx.engine) as db:
            global_id = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin')).id if global_role == 'super_admin' else c.roles['all']
        grant(client, c, root, kind, (global_id,))
        owner = login(client, c, c.owner_name)
        grant(client, c, root, kind, (c.roles['invoice:read_all'],))
        before = read_snapshot(c)
        result = client.post(path, headers=owner, json=body)
        assert result.status_code == 404, result.text
        assert read_snapshot(c) == before and c.evidence == [] and c.calls == []


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
def test_reconciliation_honors_new_current_grant(reconcile_app, kind):
    c = reconcile_app
    path, body = operation(c, kind)
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        change_user(client, c, root, {'role_ids':[c.roles['read']]})
        owner = login(client, c, c.owner_name)
        grant(client, c, root, kind)
        result = client.post(path, headers=owner, json=body)
        assert result.status_code == 200, result.text
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            assert row.sync_status == ('pending' if kind == 'absent' else 'synced')
            assert row.amount == Decimal('10.00') and row.bank_charge == Decimal('2.00')
            actions = [log.action for log in db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id == row.id))]
            assert actions.count('reconciled') == int(kind != 'absent')
            assert actions.count('bind_receipt' if kind == 'bind' else 'confirm_not_created') == int(kind != 'reconcile')
        assert len(c.evidence) == 1 and c.calls == []


def gated_remote(c, kind, monkeypatch, ready, release):
    name = 'order_receipts' if kind == 'absent' else 'receipt_info'
    original = getattr(remote, name)
    def gate(*args):
        ready.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(remote, name, gate)


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
@pytest.mark.parametrize('state', ['voided', 'syncing', 'failed'])
def test_recovery_initial_state_guards_before_io(reconcile_app, kind, state):
    c = reconcile_app; path, body = operation(c, kind)
    with Session(c.ctx.engine) as db:
        row = db.get(Receipt, c.receipts['victim'])
        if state == 'voided': row.status = state
        else: row.sync_status = state
        db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and c.evidence == []


def test_reconcile_admin_or_retains_original_scope(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'reconcile')
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        change_user(client, c, root, {'role_ids':[c.roles['receipt:admin']]})
        owner = login(client, c, c.owner_name)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 200, response.text
        other, _ = operation(c, 'reconcile', 'foreign'); before = read_snapshot(c)
        assert client.post(other, headers=owner).status_code == 404
        assert read_snapshot(c) == before and len(c.evidence) == 1


@pytest.mark.parametrize('kind', ['bind', 'absent'])
def test_resolve_does_not_inherit_write_permission(reconcile_app, kind):
    c = reconcile_app; path, body = operation(c, kind)
    with c.app.client() as client:
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 403, response.text
        assert read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
def test_recovery_keeps_receipt_target_without_ready_or_balance_guard(reconcile_app, kind):
    c = reconcile_app; path, body = operation(c, kind)
    with Session(c.ctx.engine) as db:
        invoice = db.get(Invoice, c.invoice_id)
        invoice.status = 'draft'; invoice.sync_status = 'failed'; invoice.xiaoman_order_id = '999900001'
        invoice.total_amount = Decimal('0.01')
        db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 200, response.text
        expected = [('rows', c.details[str(c.receipts['victim']+8000000)]['order_id'])] if kind == 'absent' else [('info', str(c.receipts['victim']+8000000))]
        assert c.evidence == expected


@pytest.mark.parametrize('amount', ['8.00', '10.00'])
@pytest.mark.parametrize('kind', ['reconcile', 'absent'])
def test_candidate_gross_and_net_never_auto_bind_or_allow_absence(reconcile_app, amount, kind):
    c = reconcile_app; path, body = operation(c, kind)
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['victim']).xiaoman_receipt_id = None; db.commit()
    record = dict(c.details[str(c.receipts['victim']+8000000)], amount=amount)
    c.remote_rows = [record]
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == (200 if kind == 'reconcile' else 409), response.text
        if kind == 'reconcile':
            assert response.json()['data']['candidates'] == [dict(xiaoman_receipt_id=record['cash_collection_id'], xiaoman_receipt_no=record['cash_collection_no'], amount=amount)]
        assert read_snapshot(c) == before and len(c.evidence) == 1


@pytest.mark.parametrize('field,value', [('order_id','wrong'),('currency','EUR'),('amount','10.00'),
    ('bank_charge','1.00'),('real_amount','7.00'),('collection_date','2000-01-01'),('collect_status','2'),
    ('cash_collection_id','999')])
def test_binding_requires_exact_original_evidence(reconcile_app, field, value):
    c = reconcile_app; path, body = operation(c, 'bind')
    c.details[body['xiaoman_receipt_id']][field] = value
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'bind')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == (503 if field == 'cash_collection_id' else 409), response.text
        assert read_snapshot(c) == before and len(c.evidence) == 1


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
@pytest.mark.parametrize('change', ['disabled', 'action', 'scope'])
def test_remote_get_releases_locks_and_final_authorizes(reconcile_app, kind, change, monkeypatch):
    c = reconcile_app; path, body = operation(c, kind)
    ready = threading.Event(); release = threading.Event()
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        grant(client, c, root, kind, (c.roles['all'],) if change == 'scope' else ())
        if change == 'scope': path, body = operation(c, kind, 'foreign')
        owner = login(client, c, c.owner_name)
        gated_remote(c, kind, monkeypatch, ready, release)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post, path, headers=owner, json=body)
            try:
                assert ready.wait(5)
                if change == 'disabled': update = {'is_active':False}
                elif change == 'action': update = {'role_ids':[c.roles['read']]}
                else: update = {'role_ids':[c.roles['both'] if kind == 'reconcile' else c.roles['receipt:admin']]}
                revoke = pool.submit(client.put, '/api/auth/users/'+str(c.ctx.actor), headers=root, json=update)
                assert revoke.result(timeout=5).status_code == 200
                assert not action.done(); before = read_snapshot(c)
            finally: release.set()
            response = action.result(timeout=5)
        assert response.status_code == (404 if change == 'scope' else 403), response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('change', ['amount', 'order', 'invoice', 'owner', 'batch', 'late_result', 'remote_id'])
def test_recovery_rejects_changes_during_external_io(reconcile_app, change, monkeypatch):
    c = reconcile_app; path, body = operation(c, 'absent')
    ready = threading.Event(); release = threading.Event()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'absent')
        owner = login(client, c, c.owner_name); gated_remote(c, 'absent', monkeypatch, ready, release)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post, path, headers=owner, json=body)
            try:
                assert ready.wait(5)
                def mutate():
                    with Session(c.ctx.engine) as db:
                        row = db.get(Receipt, c.receipts['victim']); invoice = db.get(Invoice, c.invoice_id)
                        if change == 'amount': row.amount = Decimal('11')
                        elif change == 'order': row.xiaoman_order_id = '123450000'
                        elif change == 'invoice': invoice.currency = 'EUR'
                        elif change == 'owner': invoice.sales_user_id = c.other_id
                        elif change == 'batch': row.batch_id = c.batch_id
                        elif change == 'remote_id': row.xiaoman_receipt_id = str(c.receipts['victim']+8000000)
                        else: service.log(db, row, 'late_result', '旧任务返回小满回款 ID 987，请核对，未覆盖当前处理结果')
                        db.commit()
                pool.submit(mutate).result(timeout=5)
                assert not action.done(); before = read_snapshot(c)
            finally: release.set()
            response = action.result(timeout=5)
        assert response.status_code == (404 if change == 'owner' else 409), response.text
        assert read_snapshot(c) == before and c.calls == []


def test_known_late_result_prevents_absence_before_remote_io(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'absent')
    with Session(c.ctx.engine) as db:
        service.log(db, db.get(Receipt, c.receipts['victim']), 'late_result', '旧任务返回小满回款 ID 987，请核对，未覆盖当前处理结果'); db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'absent')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409 and '迟到' in response.text
        assert read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
def test_mixed_batch_scope_denied_without_partial_change(reconcile_app, kind):
    c = reconcile_app; path, body = operation(c, kind, 'positive')
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['foreign']).batch_id = c.batch_id; db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 404, response.text
        assert read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('kind', ['reconcile', 'absent'])
def test_final_current_log_after_real_invoice_lock_wait(reconcile_app, kind, monkeypatch):
    c = reconcile_app; path, body = operation(c, kind)
    ready = threading.Event(); release = threading.Event(); started = queue.Queue()
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name); gated_remote(c, kind, monkeypatch, ready, release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action = pool.submit(client.post, path, headers=owner, json=body)
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5)
                    other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update())
                    service.log(other, other.get(Receipt, c.receipts['victim']), 'late_result', '旧任务返回小满回款 ID 987，请核对，未覆盖当前处理结果'); other.flush()
                    event.listen(c.ctx.engine, 'before_cursor_execute', observe); release.set()
                    wait_for_lock(c.ctx.engine, started.get(timeout=5)); assert not action.done()
                    other.commit(); before = read_snapshot(c)
                    response = action.result(timeout=5)
                finally:
                    release.set(); other.rollback()
                    if event.contains(c.ctx.engine, 'before_cursor_execute', observe): event.remove(c.ctx.engine, 'before_cursor_execute', observe)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('stage', [1, 2, 3])
@pytest.mark.parametrize('timing', ['before_commit', 'after_commit'])
def test_exact_session_commit_failures_and_read_only_recovery(reconcile_app, stage, timing, monkeypatch):
    c = reconcile_app; path, body = operation(c, 'bind')
    sessions = []; hits = []; original_capture = reconciliation_service._capture; original_info = remote.receipt_info
    metadata = MetaData(); token = Table('owned_recovery_metadata', metadata, Column('id', Integer, primary_key=True), Column('value', String(24)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete()); connection.execute(token.insert().values(id=1, value='original'))
    def capture(db, *args):
        if not any(db is value for value in sessions): sessions.append(db)
        return original_capture(db, *args)
    def info(db, identity):
        db.execute(token.update().where(token.c.id == 1).values(value='refreshed'))
        return original_info(db, identity)
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'bind')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        monkeypatch.setattr(reconciliation_service, '_capture', capture); monkeypatch.setattr(remote, 'receipt_info', info)
        def fail(db):
            if any(db is value for value in sessions):
                count = db.info.get('owned_recovery_commit', 0)+1; db.info['owned_recovery_commit'] = count
                if count == stage:
                    hits.append((id(db), stage)); raise OperationalError('private-db-details', {}, Exception('private-driver-ack'))
        event.listen(Session, timing, fail)
        try: response = client.post(path, headers=owner, json=body)
        finally: event.remove(Session, timing, fail)
        assert hits == [(id(sessions[0]), stage)] and response.status_code == 503, response.text
        assert response.headers['cache-control'] == 'private, no-store' and 'private-' not in response.text
        with c.ctx.engine.connect() as connection:
            value = connection.scalar(select(token.c.value))
            assert value == ('refreshed' if stage == 3 or stage == 2 and timing == 'after_commit' else 'original')
        committed = stage == 3 and timing == 'after_commit'
        if not committed: assert read_snapshot(c) == before
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            assert row.sync_status == ('synced' if committed else 'uncertain')
            assert row.xiaoman_receipt_id == (body['xiaoman_receipt_id'] if committed else None)
            assert row.version == (2 if committed else 1)
            logs = db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id == row.id)).all()
            assert [log.action for log in logs].count('reconciled') == int(committed)
            assert [log.action for log in logs].count('bind_receipt') == int(committed)
        prior = read_snapshot(c); reads = list(c.evidence)
        recovered = client.get('/api/receipts/'+str(c.receipts['victim']), headers=owner)
        assert recovered.status_code == 200, recovered.text
        assert read_snapshot(c) == prior and c.evidence == reads
        if committed:
            repeated = client.post(path, headers=owner, json=body)
            assert repeated.status_code == 409 and read_snapshot(c) == prior and c.evidence == reads
        else:
            assert client.post(path, headers=owner, json=body).status_code == 200
        assert c.calls == []


@pytest.mark.parametrize('kind', ['reconcile', 'bind', 'absent'])
def test_two_captured_commands_only_one_local_application(reconcile_app, kind, monkeypatch):
    c = reconcile_app; path, body = operation(c, kind); barrier = threading.Barrier(2)
    name = 'order_receipts' if kind == 'absent' else 'receipt_info'; original = getattr(remote, name)
    def gate(*args): barrier.wait(timeout=10); return original(*args)
    monkeypatch.setattr(remote, name, gate)
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, path, headers=owner, json=body) for _ in range(2)]
            responses = [future.result(timeout=15) for future in futures]
        assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim']); assert row.version == 2
            actions = [log.action for log in db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id == row.id))]
            assert actions.count('reconciled') == int(kind != 'absent')
            if kind != 'reconcile': assert actions.count('bind_receipt' if kind == 'bind' else 'confirm_not_created') == 1
        assert len(c.evidence) == 2 and c.calls == []


@pytest.mark.parametrize('shape', ['info', 'money', 'id', 'rows', 'row', 'duplicate', 'provider'])
def test_malformed_remote_evidence_safe_and_no_local_write(reconcile_app, shape, monkeypatch):
    c = reconcile_app; kind = 'absent' if shape in ('rows', 'row', 'duplicate') else 'bind'
    path, body = operation(c, kind); hits = []
    def info(*args):
        hits.append(shape)
        if shape == 'provider': raise okki_client.OkkiApiError('private-provider-details')
        if shape == 'info': return None
        value = dict(c.details[body['xiaoman_receipt_id']])
        value['amount' if shape == 'money' else 'cash_collection_id'] = 'private-invalid'
        return value
    def rows(*args):
        hits.append(shape)
        if shape == 'rows': return None
        if shape == 'row': return [None]
        value = c.details[str(c.receipts['victim']+8000000)]
        return [value, value]
    monkeypatch.setattr(remote, 'receipt_info', info); monkeypatch.setattr(remote, 'order_receipts', rows)
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 503 and response.headers['cache-control'] == 'private, no-store', response.text
        assert 'private-' not in response.text and hits == [shape]
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('field,value', [('collection_date',''),('collection_date','garbage'),
    ('collection_date','2026-02-31'),('collection_date','20261006'),('currency',''),('currency',' USD ')])
def test_invalid_candidate_identity_cannot_be_treated_as_absence(reconcile_app, field, value):
    c = reconcile_app; path, body = operation(c, 'absent')
    record = dict(c.details[str(c.receipts['victim']+8000000)]); record[field] = value
    c.remote_rows = [record]
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'absent')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 503 and response.headers['cache-control'] == 'private, no-store', response.text
        assert read_snapshot(c) == before and len(c.evidence) == 1 and c.calls == []


def test_valid_other_date_is_not_a_matching_candidate(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'absent')
    c.remote_rows = [dict(c.details[str(c.receipts['victim']+8000000)], collection_date='2000-01-01 12:34:56')]
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'absent')
        owner = login(client, c, c.owner_name)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as db:
            assert db.get(Receipt, c.receipts['victim']).sync_status == 'pending'


@pytest.mark.parametrize('kind', ['reconcile', 'bind'])
def test_valid_datetime_and_effective_status_keeps_binding(reconcile_app, kind):
    c = reconcile_app; path, body = operation(c, kind)
    identity = str(c.receipts['victim']+8000000)
    c.details[identity]['collection_date'] += 'T12:34:56+08:00'
    c.details[identity]['collect_status'] = 1
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, kind)
        owner = login(client, c, c.owner_name)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            assert row.sync_status == 'synced' and row.collect_status == 1


def test_binding_cannot_replace_known_id(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'bind')
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['victim']).xiaoman_receipt_id = '123456789'; db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'bind')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and len(c.evidence) == 1


def test_current_remote_id_bound_to_other_row_cannot_be_reused(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'bind')
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['foreign']).xiaoman_receipt_id = body['xiaoman_receipt_id']; db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'bind')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and len(c.evidence) == 1


def test_known_id_absence_denied_before_io(reconcile_app):
    c = reconcile_app; path, body = operation(c, 'absent')
    with Session(c.ctx.engine) as db:
        db.get(Receipt, c.receipts['victim']).xiaoman_receipt_id = str(c.receipts['victim']+8000000); db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, 'absent')
        owner = login(client, c, c.owner_name); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and c.evidence == []
