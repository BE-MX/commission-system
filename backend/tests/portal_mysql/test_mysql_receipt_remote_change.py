"""Actual JWT/current rights for remote-change; immutable synthetic GET evidence."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import threading
import queue
from sqlalchemy import Column, Integer, MetaData, String, Table, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
import pytest

from app.auth.models import ArkRole
from app.invoice import lifecycle_remote
from app.invoice.models import Invoice
from app.receipt import receipt_index, remote, remote_change_service, service
from app.receipt.models import Receipt, ReceiptLog
from app.portal import authority as portal_authority
from test_mysql_concurrency import wait_for_lock
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401


@pytest.fixture
def change_app(read_app, monkeypatch):
    c = read_app; c.evidence = []; c.details = {}; c.remote_rows = []
    with Session(c.ctx.engine) as db:
        for label, identity in c.receipts.items():
            row = db.get(Receipt, identity)
            row.sync_status = 'synced'; row.bank_charge = Decimal('2.00')
            row.xiaoman_order_id = db.get(Invoice, row.invoice_id).xiaoman_order_id
            row.xiaoman_receipt_id = str(identity + 9000000)
            c.details[row.xiaoman_receipt_id] = dict(cash_collection_id=row.xiaoman_receipt_id,
                order_id=row.xiaoman_order_id, currency=row.currency, amount='6.00',
                bank_charge='0', real_amount='6.00', collection_date=row.collection_date.isoformat(), collect_status='1')
        db.commit()
    def detail(db, kind, identity):
        assert kind == 'receipt'; c.evidence.append(('detail', str(identity)))
        data = c.details[str(identity)]
        return None if data is None else dict(data)
    def rows(db, identity):
        c.evidence.append(('index', str(identity)))
        return [dict(value) for value in c.remote_rows if str(value.get('order_id')) == str(identity)]
    def index(db):
        c.evidence.append(('global-index', None))
        return [dict(value) for value in c.remote_rows]
    monkeypatch.setattr(receipt_index, 'verified_rows', index)
    monkeypatch.setattr(lifecycle_remote, 'read', detail)
    monkeypatch.setattr(remote, 'order_receipts', rows)
    return c


def grant(client, c, root, extra=()):
    change_user(client, c, root, {'role_ids':[c.roles['receipt:admin'], *extra]})


def operation(client, c, root, kind, label='victim'):
    path = '/api/receipts/'+str(c.receipts[label])+'/remote-change'
    if kind == 'delete': c.details[str(c.receipts[label]+9000000)] = None
    if kind == 'preview': return path, None
    response = client.get(path, headers=root)
    assert response.status_code == 200, response.text
    proof = response.json()['data']; c.evidence.clear()
    return path, dict(version=proof['version'], evidence_hash=proof['evidence_hash'],
        confirmed=True, reason='Verified original customer payment and remote change')


def request(client, path, body, headers):
    return client.get(path, headers=headers) if body is None else client.post(path, headers=headers, json=body)


@pytest.mark.parametrize('kind', ['preview', 'modify', 'delete'])
@pytest.mark.parametrize('revocation', ['disabled', 'roles', 'action'])
def test_remote_change_rejects_stale_jwt(change_app, kind, revocation):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, kind)
        change_user(client, c, root, {'is_active':False} if revocation == 'disabled' else
            {'role_ids':[]} if revocation == 'roles' else {'role_ids':[c.roles['both']]})
        before = read_snapshot(c); response = request(client, path, body, owner)
        assert response.status_code == 403, response.text
        assert read_snapshot(c) == before and c.evidence == [] and c.calls == []


@pytest.mark.parametrize('kind', ['preview', 'modify', 'delete'])
@pytest.mark.parametrize('global_role', ['all', 'super_admin'])
def test_remote_change_rebuilds_original_financial_scope(change_app, kind, global_role):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        with Session(c.ctx.engine) as db:
            global_id = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin')).id if global_role == 'super_admin' else c.roles['all']
        grant(client, c, root, (global_id,)); owner = login(client, c, c.owner_name)
        path, body = operation(client, c, root, kind, 'foreign')
        grant(client, c, root, (c.roles['invoice:read_all'],))
        before = read_snapshot(c); response = request(client, path, body, owner)
        assert response.status_code == 404, response.text
        assert read_snapshot(c) == before and c.evidence == [] and c.calls == []


@pytest.mark.parametrize('kind', ['preview', 'modify', 'delete'])
def test_remote_change_honors_current_new_grant(change_app, kind):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        change_user(client, c, root, {'role_ids':[c.roles['both']]}); owner = login(client, c, c.owner_name)
        path, body = operation(client, c, root, kind); grant(client, c, root)
        before = read_snapshot(c); response = request(client, path, body, owner)
        assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            assert row.amount == Decimal('8.00' if kind == 'modify' else '10.00')
            assert row.bank_charge == Decimal('2.00') and row.xiaoman_receipt_id == str(row.id+9000000)
            assert row.status == ('remote_deleted' if kind == 'delete' else 'active')
            assert row.version == (1 if kind == 'preview' else 2)
            assert db.query(ReceiptLog).filter_by(receipt_id=row.id, action='remote_change').count() == int(kind != 'preview')
        if kind == 'preview': assert read_snapshot(c) == before
        assert len(c.evidence) == (2 if kind == 'delete' else 1) and c.calls == []


@pytest.mark.parametrize('kind', ['preview', 'delete'])
def test_receipt_in_another_order_is_never_deleted(change_app, kind):
    c = change_app; identity = c.receipts['victim']; remote_id = str(identity+9000000)
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name)
        path, body = operation(client, c, root, kind)
        c.details[remote_id] = None
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, identity)
            c.remote_rows = [dict(cash_collection_id=remote_id, order_id=str(row.invoice_id+7777000),
                currency='USD', amount='8', collect_status='0', collection_date=row.collection_date.isoformat())]
        before = read_snapshot(c); response = request(client, path, body, owner)
        assert response.status_code == 409, response.text
        assert read_snapshot(c) == before and c.calls == []


def gate_detail(c, monkeypatch, ready, release):
    original = lifecycle_remote.read
    def gate(*args):
        ready.set(); assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(lifecycle_remote, 'read', gate)


@pytest.mark.parametrize('kind', ['modify', 'delete'])
@pytest.mark.parametrize('change', ['disabled', 'action', 'scope'])
@pytest.mark.parametrize('portal_enabled', [False,True])
def test_lock_free_get_and_final_current_authorization(change_app, kind, change, portal_enabled, monkeypatch):
    c = change_app; c.app.settings.PORTAL_ENABLED = portal_enabled; ready = threading.Event(); release = threading.Event()
    monkeypatch.setattr(portal_authority, "get_settings", lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is portal_enabled
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root, (c.roles['all'],) if change == 'scope' else ())
        owner = login(client, c, c.owner_name)
        path, body = operation(client, c, root, kind, 'foreign' if change == 'scope' else 'victim')
        gate_detail(c, monkeypatch, ready, release)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post, path, headers=owner, json=body)
            try:
                assert ready.wait(5)
                update = {'is_active':False} if change == 'disabled' else {'role_ids':[c.roles['both']]} if change == 'action' else {'role_ids':[c.roles['receipt:admin']]}
                revoke = pool.submit(client.put, '/api/auth/users/'+str(c.ctx.actor), headers=root, json=update)
                assert revoke.result(timeout=5).status_code == 200
                assert not action.done(); before = read_snapshot(c)
            finally: release.set()
            response = action.result(timeout=5)
        assert response.status_code == (404 if change == 'scope' else 403), response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('kind', ['modify', 'delete'])
@pytest.mark.parametrize('change', ['amount', 'fee', 'order', 'currency', 'owner', 'batch', 'purpose', 'version', 'remote_id', 'late_result'])
def test_complete_binding_changes_during_get_are_rejected(change_app, kind, change, monkeypatch):
    c = change_app; ready = threading.Event(); release = threading.Event()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, kind)
        gate_detail(c, monkeypatch, ready, release)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post, path, headers=owner, json=body)
            try:
                assert ready.wait(5)
                def mutate():
                    with Session(c.ctx.engine) as db:
                        row = db.get(Receipt, c.receipts['victim']); invoice = db.get(Invoice, c.invoice_id)
                        if change == 'amount': row.amount = Decimal('11')
                        elif change == 'fee': row.bank_charge = Decimal('3')
                        elif change == 'order': row.xiaoman_order_id = '123450000'
                        elif change == 'currency': invoice.currency = 'EUR'
                        elif change == 'owner': invoice.sales_user_id = c.other_id
                        elif change == 'batch': row.batch_id = c.batch_id
                        elif change == 'purpose': row.purpose = 'presale_deposit'
                        elif change == 'version': row.version += 1
                        elif change == 'remote_id': row.xiaoman_receipt_id = str(row.id+9999000)
                        else: service.log(db, row, 'late_result', 'Late result preserved without modifying receipt version')
                        db.commit()
                pool.submit(mutate).result(timeout=5); assert not action.done(); before = read_snapshot(c)
            finally: release.set()
            response = action.result(timeout=5)
        assert response.status_code == (404 if change == 'owner' else 409), response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('state', ['voided', 'pending', 'failed', 'syncing', 'missing_id', 'presale', 'batch'])
def test_original_confirm_guards_precede_io(change_app, state):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, 'modify')
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            if state == 'voided': row.status = state
            elif state == 'missing_id': row.xiaoman_receipt_id = None
            elif state == 'presale': row.purpose = 'presale_deposit'
            elif state == 'batch': row.batch_id = c.batch_id
            else: row.sync_status = state
            db.commit()
        before = read_snapshot(c); response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409 and read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('mixed', [False, True])
def test_full_batch_scope_before_single_change_guard(change_app, mixed):
    c = change_app
    if mixed:
        with Session(c.ctx.engine) as db:
            db.get(Receipt, c.receipts['foreign']).batch_id = c.batch_id; db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name)
        path = '/api/receipts/'+str(c.receipts['positive'])+'/remote-change'
        preview = client.get(path, headers=owner)
        assert preview.status_code == (404 if mixed else 200), preview.text
        if mixed:
            body = dict(version=1, evidence_hash='a'*64, confirmed=True, reason='Verify the complete original payment batch')
        else:
            proof = preview.json()['data']; body = dict(version=proof['version'], evidence_hash=proof['evidence_hash'], confirmed=True, reason='Verify the complete original payment batch')
        c.evidence.clear(); before = read_snapshot(c)
        response = client.post(path, headers=owner, json=body)
        assert response.status_code == (404 if mixed else 409), response.text
        assert read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('sync_status', ['synced', 'uncertain'])
@pytest.mark.parametrize('kind', ['modify', 'delete'])
def test_original_financial_rules_and_review_replay(change_app, sync_status, kind):
    c = change_app
    with Session(c.ctx.engine) as db:
        row = db.get(Receipt, c.receipts['victim']); row.sync_status = sync_status
        invoice = db.get(Invoice, c.invoice_id); invoice.sync_status = 'not_synced'; invoice.total_amount = Decimal('1')
        db.commit()
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, kind)
        response = client.post(path, headers=owner, json=body); assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim'])
            assert row.amount == Decimal('8' if kind == 'modify' else '10') and row.bank_charge == Decimal('2')
            assert row.attachment_ids == [c.proofs['own']] and row.xiaoman_receipt_id == str(row.id+9000000)
            assert row.sync_status == ('synced' if kind == 'modify' else sync_status)
            assert row.status == ('active' if kind == 'modify' else 'remote_deleted') and row.version == 2
            if kind == 'delete': assert '不代表资金退款' in row.last_error
            log = db.query(ReceiptLog).filter_by(receipt_id=row.id, action='remote_change').one()
            assert log.created_by == c.ctx.actor and '10.00' in log.message and body['reason'] in log.message
        before = read_snapshot(c); c.evidence.clear()
        repeat = client.post(path, headers=owner, json=body)
        assert repeat.status_code == 409 and read_snapshot(c) == before and c.evidence == []


@pytest.mark.parametrize('field,value', [('cash_collection_id','other'), ('collection_date','2026-02-30'),
    ('collection_date','20261006'), ('currency',''), ('amount','NaN'), ('amount','-1'), ('bank_charge',{}), ('order_id',{}), ('order_id',True), ('order_id',False), ('order_id',''), ('order_id','  ')])
def test_bad_detail_is_fixed_503_without_mutation(change_app, field, value):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, 'modify')
        c.details[str(c.receipts['victim']+9000000)][field] = value
        before = read_snapshot(c); response = client.post(path, headers=owner, json=body)
        assert response.status_code == 503 and response.headers['cache-control'] == 'private, no-store', response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('field,value', [('order_id','12345000'), ('currency','EUR'), ('bank_charge','1'),
    ('real_amount','5'), ('bank_charge_rmb','1'), ('bank_charge_usd','1'), ('collect_status','2'), ('amount','0')])
def test_inconsistent_or_changed_financial_evidence(change_app, field, value):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, 'modify')
        c.details[str(c.receipts['victim']+9000000)][field] = value
        before = read_snapshot(c); response = client.post(path, headers=owner, json=body)
        assert response.status_code == 409 and read_snapshot(c) == before, response.text


@pytest.mark.parametrize('index', ['bad_id', 'duplicates', 'missing_order', 'not_list', 'bool', 'false', 'empty', 'whitespace'])
def test_invalid_full_index_cannot_release_payment(change_app, index, monkeypatch):
    c = change_app
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, 'delete')
        rows = [{'cash_collection_id':'wrong','order_id':'123'}] if index == 'bad_id' else             [{'cash_collection_id':'123','order_id':'123'}]*2 if index == 'duplicates' else             [{'cash_collection_id':'123'}] if index == 'missing_order' else {}
        if index in ('bool','false','empty','whitespace'):
            rows = [dict(cash_collection_id='123',order_id={'bool':True,'false':False,'empty':'','whitespace':'  '}[index])]
        monkeypatch.setattr(receipt_index, 'verified_rows', lambda *args:rows)
        before = read_snapshot(c); response = client.post(path, headers=owner, json=body)
        assert response.status_code == 503 and response.headers['cache-control'] == 'private, no-store', response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('kind', ['modify', 'delete'])
def test_two_confirmations_only_apply_once(change_app, kind, monkeypatch):
    c = change_app; barrier = threading.Barrier(2); original = lifecycle_remote.read
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, kind)
        def detail(*args):
            barrier.wait(timeout=10); return original(*args)
        monkeypatch.setattr(lifecycle_remote, 'read', detail)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _:client.post(path, headers=owner, json=body), range(2)))
        assert sorted(response.status_code for response in responses) == [200,409]
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt, c.receipts['victim']); assert row.version == 2
            assert db.query(ReceiptLog).filter_by(receipt_id=row.id, action='remote_change').count() == 1


@pytest.mark.parametrize('stage', [1,2,3])
@pytest.mark.parametrize('timing', ['before_commit','after_commit'])
def test_commit_faults_and_original_read_recovery(change_app, stage, timing, monkeypatch):
    c = change_app; sessions = []; hits = []; original_capture = remote_change_service._capture; original_read = lifecycle_remote.read
    metadata = MetaData(); token = Table('owned_remote_change_token', metadata, Column('id',Integer,primary_key=True), Column('value',String(24)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete()); connection.execute(token.insert().values(id=1,value='original'))
    def capture(db, *args):
        if not any(db is value for value in sessions): sessions.append(db)
        return original_capture(db, *args)
    def detail(db, *args):
        db.execute(token.update().where(token.c.id == 1).values(value='refreshed'))
        return original_read(db, *args)
    with c.app.client() as client:
        root = login(client, c, c.root_name); grant(client, c, root)
        owner = login(client, c, c.owner_name); path, body = operation(client, c, root, 'modify'); before = read_snapshot(c)
        monkeypatch.setattr(remote_change_service, '_capture', capture); monkeypatch.setattr(lifecycle_remote, 'read', detail)
        def fail(db):
            if any(db is value for value in sessions):
                count = db.info.get('owned_remote_change_commit',0)+1; db.info['owned_remote_change_commit'] = count
                if count == stage:
                    hits.append((id(db),stage)); raise OperationalError('private-db-details',{},Exception('private-ack'))
        event.listen(Session, timing, fail)
        try: response = client.post(path, headers=owner, json=body)
        finally: event.remove(Session, timing, fail)
        assert hits == [(id(sessions[0]),stage)] and response.status_code == 503, response.text
        assert response.headers['cache-control'] == 'private, no-store' and 'private-db-details' not in response.text
        with c.ctx.engine.connect() as connection:
            assert connection.scalar(select(token.c.value)) == ('refreshed' if stage == 3 or stage == 2 and timing == 'after_commit' else 'original')
        committed = stage == 3 and timing == 'after_commit'
        if committed:
            with Session(c.ctx.engine) as db:
                row = db.get(Receipt,c.receipts['victim']); assert row.version == 2 and row.amount == Decimal('8') and row.bank_charge == Decimal('2')
                assert db.query(ReceiptLog).filter_by(receipt_id=row.id,action='remote_change').count() == 1
        else: assert read_snapshot(c) == before
        after = read_snapshot(c); c.evidence.clear()
        read = client.get('/api/receipts/'+str(c.receipts['victim']),headers=owner)
        assert read.status_code == 200 and read_snapshot(c) == after and c.evidence == []
        if committed:
            replay = client.post(path,headers=owner,json=body)
            assert replay.status_code == 409 and read_snapshot(c) == after and c.evidence == []
        else:
            restored = client.post(path,headers=owner,json=body)
            assert restored.status_code == 200, restored.text


def test_final_current_log_after_real_invoice_wait(change_app, monkeypatch):
    c = change_app; ready = threading.Event(); release = threading.Event(); started = queue.Queue()
    def observe(connection, cursor, statement, parameters, context, executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        root = login(client,c,c.root_name); grant(client,c,root); owner = login(client,c,c.owner_name)
        path,body = operation(client,c,root,'modify'); gate_detail(c,monkeypatch,ready,release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action = pool.submit(client.post,path,headers=owner,json=body)
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5)
                    other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update())
                    service.log(other,other.get(Receipt,c.receipts['victim']),'late_result','Late result after original snapshot'); other.flush()
                    event.listen(c.ctx.engine,'before_cursor_execute',observe); release.set()
                    wait_for_lock(c.ctx.engine,started.get(timeout=5)); assert not action.done()
                    other.commit(); before = read_snapshot(c); response = action.result(timeout=5)
                finally:
                    release.set(); other.rollback()
                    if event.contains(c.ctx.engine,'before_cursor_execute',observe): event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert response.status_code == 409 and read_snapshot(c) == before, response.text


@pytest.mark.parametrize('kind', ['modify','delete'])
@pytest.mark.parametrize('scope', [False,True])
def test_final_authorization_precedes_financial_evidence_disclosure(change_app, kind, scope, monkeypatch):
    c = change_app; ready = threading.Event(); release = threading.Event()
    label = 'foreign' if scope else 'victim'; remote_id = str(c.receipts[label]+9000000)
    with c.app.client() as client:
        root = login(client,c,c.root_name); grant(client,c,root,(c.roles['all'],) if scope else ())
        owner = login(client,c,c.owner_name); path,body = operation(client,c,root,kind,label)
        if kind == 'modify': c.details[remote_id]['currency'] = 'EUR'
        else: c.remote_rows = [dict(cash_collection_id=remote_id,order_id='12345000')]
        gate_detail(c,monkeypatch,ready,release)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action = pool.submit(client.post,path,headers=owner,json=body)
            try:
                assert ready.wait(5)
                update = {'role_ids':[c.roles['receipt:admin']]} if scope else {'is_active':False}
                revoke = pool.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json=update)
                assert revoke.result(timeout=5).status_code == 200
                before = read_snapshot(c)
            finally: release.set()
            response = action.result(timeout=5)
        assert response.status_code == (404 if scope else 403), response.text
        assert read_snapshot(c) == before and c.calls == []


@pytest.mark.parametrize('portal_enabled',[False,True])
def test_remote_change_business_commit_then_revocation_order(change_app, portal_enabled, monkeypatch):
    c = change_app; c.app.settings.PORTAL_ENABLED = portal_enabled
    monkeypatch.setattr(portal_authority, "get_settings", lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is portal_enabled
    with c.app.client() as client:
        root = login(client,c,c.root_name); grant(client,c,root); owner = login(client,c,c.owner_name)
        path,body = operation(client,c,root,'modify')
        response = client.post(path,headers=owner,json=body); assert response.status_code == 200, response.text
        change_user(client,c,root,{'role_ids':[c.roles['both']]}); before = read_snapshot(c)
        repeat = client.post(path,headers=owner,json=body); assert repeat.status_code == 403, repeat.text
        assert read_snapshot(c) == before
        with Session(c.ctx.engine) as db:
            row = db.get(Receipt,c.receipts['victim']); assert row.amount == Decimal('8') and row.version == 2
            assert db.query(ReceiptLog).filter_by(receipt_id=row.id,action='remote_change').count() == 1
