"""Actual employee JWT/MySQL outbound preparation; provider/mirror boundaries synthetic."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from sqlalchemy import Column, MetaData, Table, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice import edit_authority, xiaoman_service
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.receipt.models import ReceiptAttachment, ReceiptIntent
from app.shipping_inspection import outbound_sync_state as state
from app.portal.authority import lock_authority
from app.shipping_inspection import outbound_service, outbound_sync_router, outbound_sync_service as sync
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from test_mysql_order_push_execution import setup_push, business
from test_mysql_invoice_cancellation_refresh import demote_admin


def setup(e, monkeypatch, tmp_path):
    push = setup_push(e, monkeypatch, tmp_path, editing=True)
    metadata = MetaData()
    for model in (ShippingInspection, ShippingInspectionPhoto):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
              nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(e.ctx.engine)
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        invoice = edit_authority.lock_document(db, e.invoice_id)
        invoice.status = invoice.sync_status = 'synced'
        rows, bindings, issues, _ = xiaoman_service._build_product_rows(
            db, invoice, xiaoman_service.get_settings_row(db), editing=True)
        assert not issues and all(len(items) == 1 for items, _ in bindings)
        products = [{**row, 'product_name': items[0].product_name, 'unit': 'Piece',
                     'product_model': items[0].model or '', 'product_cn_name': '',
                     'cost_amount': str(items[0].total_price)} for items, row in bindings]
        company, currency, amount = invoice.customer_id, invoice.currency, str(invoice.total_amount)
        db.commit()
    record = {'outbound_record_id': 'OWN-'+str(e.invoice_id), 'outbound_invoice_id': '701',
              'company_id': company, 'order_id': push.target, 'mirror_updated_at': '2026-10-05 09:00:00'}
    order = {'order_id': push.target, 'company_id': company, 'currency': currency, 'amount': amount,
             'product_list': deepcopy(products), 'update_time': '2026-10-05 09:00:00', 'create_time': '2026-10-05 09:00:00'}
    outbound = {'outbound_invoice_id': 701, 'serial_id': 'CK-OWN', 'status': 1,
                'company_info': {'id': company}, 'currency': currency,
                'handler_info': [{'user_id': str(e.ctx.actor)}], 'remark': 'Before owned sync',
                'update_time': '2026-10-05 09:00:00', 'record_list': []}
    for i, row in enumerate(products):
        outbound['record_list'].append({'outbound_record_id': 801+i, 'order_id': push.target,
            'order_record_id': row['unique_id'], 'product_id': row['product_id'], 'sku_id': row['sku_id'],
            'outbound_count': row['count'], 'sale_price': row['unit_price'], 'product_name': row['product_name'],
            'product_model': row['product_model'], 'product_cn_name': '', 'product_unit': 'Piece',
            'cost_unit_price_rmb': 0})
    c = SimpleNamespace(e=e, record=record, order=order, outbound=outbound, reads=[], gate=None, posts=push.posts)
    def mirror(db, record_id, okki_user_id=None, **kwargs):
        if str(record_id) != record['outbound_record_id'] or okki_user_id not in (None, str(e.ctx.actor)):
            return None
        return deepcopy(record)
    counts = {}
    def read(db, path, params):
        c.reads.append(path)
        counts[path] = counts.get(path, 0)+1
        name = 'outbound' if path.endswith('/outbound/info') else 'order'
        if c.gate: c.gate(name+(':'+'first' if counts[path] == 1 else ':readback'))
        return deepcopy(c.outbound if path.endswith('/outbound/info') else c.order)
    monkeypatch.setattr(outbound_service, 'get_outbound_record', mirror)
    monkeypatch.setattr(sync.remote, 'read', read)
    def related(*args):
        if c.gate: c.gate('related')
        return [deepcopy(c.outbound)]
    monkeypatch.setattr(sync.linked_outbound_service, 'find_related', related)
    e.app.include_router(outbound_sync_router.router, prefix='/api/shipping-inspection')
    c.route = '/api/shipping-inspection/outbound-records/'+record['outbound_record_id']+'/invoice-sync/preview'
    return c


def snapshot(c):
    with Session(c.e.ctx.engine) as db:
        return business(c.e), tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                 for model in (ShippingOperationEvent, ShippingInspection, ShippingInspectionPhoto))


def preview(c):
    return asyncio.run(c.e.write(c.route, {}, 'POST', c.e.admin_token))


@pytest.mark.parametrize('change', ['inactive', 'permission', 'invoice_scope'])
def test_preview_uses_current_employee_before_supplier_read(editor, monkeypatch, tmp_path, change):
    c = setup(editor, monkeypatch, tmp_path)
    if change == 'inactive':
        with Session(editor.ctx.engine) as db:
            lock_authority(db); db.get(ArkUser, editor.ctx.admin).is_active = False; db.commit()
    else:
        demote_admin(editor, [] if change == 'permission' else
                     ['invoice:sync', 'shipping_inspection:write', 'shipping_inspection:read_all'])
    before = snapshot(c)
    response = preview(c)
    assert response.status_code == (404 if change == 'invoice_scope' else 403), response.text
    assert c.reads == [] and c.posts == [] and snapshot(c) == before


def test_preview_success_keeps_version_stable_for_actual_sync_prepare(editor, monkeypatch, tmp_path):
    c = setup(editor, monkeypatch, tmp_path)
    first = preview(c)
    second = preview(c)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()['data']['version'] == second.json()['data']['version']
    assert 'no-store' in first.headers['cache-control'] and c.posts == []
    with Session(editor.ctx.engine) as db:
        invoice, event, plan = sync._prepare(db, c.record, {'sub': str(editor.ctx.admin)}, force_authority=True)
        assert plan['version'] == first.json()['data']['version']
        assert invoice.id == editor.invoice_id and event.action == 'sync_idle'
        db.rollback()


@pytest.mark.parametrize('window', ['outbound:first', 'order:first', 'related', 'outbound:readback', 'order:readback'])
@pytest.mark.parametrize('change', ['inactive', 'permission', 'invoice_scope'])
def test_preview_rechecks_current_authority_after_unlocked_supplier(editor, monkeypatch, tmp_path, window, change):
    c = setup(editor, monkeypatch, tmp_path)
    ready, release = Event(), Event()
    def gate(stage):
        if stage == window:
            ready.set(); assert release.wait(8)
    c.gate = gate
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(preview, c)
        try:
            assert ready.wait(6)
            if change != 'inactive':
                demote_admin(editor, [] if change == 'permission' else
                    ['invoice:sync', 'shipping_inspection:write', 'shipping_inspection:read_all'])
            with Session(editor.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db); edit_authority.lock_document(db, editor.invoice_id)
                if change == 'inactive': db.get(ArkUser, editor.ctx.admin).is_active = False
                db.commit()
            before = snapshot(c)
            release.set(); response = pending.result(timeout=10)
        finally: release.set()
    assert response.status_code == (404 if change == 'invoice_scope' else 403), response.text
    assert snapshot(c) == before and c.posts == []
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('change', ['currency', 'amount', 'uid', 'proof', 'intent', 'task', 'inspection', 'photo', 'event'])
def test_preview_full_local_binding_rejects_supplier_window_changes(editor, monkeypatch, tmp_path, change):
    c = setup(editor, monkeypatch, tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection = ShippingInspection(outbound_record_id=c.record['outbound_record_id'], outbound_no='CK-OWN')
        db.add(inspection); db.flush()
        db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id='801', file_path='owned-before.png'))
        db.commit()
    ready, release = Event(), Event()
    def gate(stage):
        if stage == 'related': ready.set(); assert release.wait(8)
    c.gate = gate
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(preview, c)
        try:
            assert ready.wait(6)
            with Session(editor.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db); invoice = edit_authority.lock_document(db, editor.invoice_id)
                if change == 'currency': db.execute(update(Invoice).where(Invoice.id == invoice.id).values(currency='EUR'))
                elif change == 'amount': db.execute(update(Invoice).where(Invoice.id == invoice.id).values(total_amount=invoice.total_amount+1))
                elif change == 'uid': db.execute(update(InvoiceItem).where(InvoiceItem.id == invoice.items[0].id).values(xiaoman_unique_id='9001'))
                elif change == 'proof': db.scalar(select(ReceiptAttachment).order_by(ReceiptAttachment.created_at.desc())).sha256='b'*64
                elif change == 'intent': db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)).amount+=1
                elif change == 'task': db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id, status='running'))
                elif change == 'inspection': db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id == c.record['outbound_record_id'])).remark='Changed independently'
                elif change == 'photo': db.scalar(select(ShippingInspectionPhoto).order_by(ShippingInspectionPhoto.id.desc())).file_path='owned-changed.png'
                else:
                    event = state.lock(db, c.record['outbound_record_id'], editor.ctx.admin)
                    event.action = 'sync_uncertain'; event.payload = {'invoice_id': invoice.id}; event.result = {'message': 'Another task owns this target'}
                db.commit()
            before = snapshot(c)
            release.set(); response = pending.result(timeout=10)
        finally: release.set()
    assert response.status_code == 409, response.text
    assert snapshot(c) == before and c.posts == []


def test_preview_initial_enabled_then_off_keeps_current_authority(editor, monkeypatch, tmp_path):
    c = setup(editor, monkeypatch, tmp_path)
    ready, release = Event(), Event()
    def gate(stage):
        if stage == 'order:first': ready.set(); assert release.wait(8)
    c.gate = gate
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(preview, c)
        try:
            assert ready.wait(6)
            from app.portal.authority import get_settings
            monkeypatch.setattr(get_settings(), 'PORTAL_ENABLED', False)
            with Session(editor.ctx.engine) as db:
                lock_authority(db, force=True); db.get(ArkUser, editor.ctx.admin).is_active=False; db.commit()
            before = snapshot(c)
            release.set(); response = pending.result(timeout=10)
        finally: release.set()
    assert response.status_code == 403 and snapshot(c) == before and c.posts == []


@pytest.mark.parametrize('mode', ['unflushed', 'flushed', 'core'])
@pytest.mark.parametrize('inactive', [False, True])
def test_follow_existing_rejects_caller_transaction_before_any_flush_or_commit(editor, monkeypatch, tmp_path, mode, inactive):
    from fastapi import HTTPException
    from app.invoice import outbound_followup_service as followup
    c = setup(editor, monkeypatch, tmp_path)
    monkeypatch.setattr(outbound_service, 'get_record_by_outbound_invoice_id',
                        lambda *args, **kwargs: deepcopy(c.record))
    if inactive:
        with Session(editor.ctx.engine) as db:
            lock_authority(db); db.get(ArkUser, editor.ctx.admin).is_active=False; db.commit()
    before = snapshot(c)
    with Session(editor.ctx.engine, expire_on_commit=False) as db:
        if mode == 'core':
            db.execute(update(Invoice).where(Invoice.id == editor.invoice_id).values(surcharge_amount=99))
        else:
            invoice = db.get(Invoice, editor.invoice_id)
            invoice.surcharge_amount = 99
            if mode == 'flushed': db.flush()
        with pytest.raises(HTTPException) as error:
            followup._follow_existing(db, SimpleNamespace(id=editor.invoice_id, invoice_no='Owned PI'),
                    {'sub': str(editor.ctx.admin)}, [c.outbound], force_authority=True)
        assert error.value.status_code == 409
        # Independent committed view must stay identical even before this caller rolls back.
        assert snapshot(c) == before and c.reads == [] and c.posts == []
        db.rollback()


def test_actual_enabled_sync_preserves_successful_single_existing_outbound(editor, monkeypatch, tmp_path):
    c = setup(editor, monkeypatch, tmp_path)
    def post(url, *, headers, json, timeout):
        assert url.endswith('/v1/invoices/outbound/push')
        c.posts.append(deepcopy(json))
        c.outbound['record_list'] = deepcopy(json['record_list'])
        c.outbound.update(remark=json['remark'], update_time='2026-10-05 11:00:00')
        return httpx.Response(200, json={'code': 200, 'data': {'outbound_invoice_id': 701}})
    monkeypatch.setattr(sync.okki_client.httpx, 'post', post)
    first = preview(c)
    assert first.status_code == 200, first.text
    response = asyncio.run(editor.write(c.route.removesuffix('/preview'),
                 {'expected_version': first.json()['data']['version']}, 'POST', editor.admin_token))
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'sync_done'
    assert len(c.posts) == 1 and c.posts[0]['outbound_invoice_id'] == 701
    with Session(editor.ctx.engine) as db:
        event = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == state.SCOPE,
                    ShippingOperationEvent.request_id == c.record['outbound_record_id']))
        assert event.action == 'sync_done' and event.result['verified']['remark'] == ''


def test_prepare_recheck_versions_and_inspection_guard_remain_stable(editor, monkeypatch, tmp_path):
    c = setup(editor, monkeypatch, tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection=ShippingInspection(outbound_record_id=c.record['outbound_record_id'],outbound_no='CK-OWN')
        db.add(inspection);db.flush()
        db.add(ShippingInspectionPhoto(inspection_id=inspection.id,file_path='owned-whole.png'))
        db.commit()
    first, second = preview(c), preview(c)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()['data']['requires_recheck'] is True
    assert first.json()['data']['version'] == second.json()['data']['version']
    response = asyncio.run(editor.write(c.route.removesuffix('/preview'),
                 {'expected_version': first.json()['data']['version']}, 'POST', editor.admin_token))
    assert response.status_code == 200 and response.json()['data']['status'] == state.RECHECK
    assert c.posts == []
    with Session(editor.ctx.engine) as db:
        assert db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id == c.record['outbound_record_id'])).edit_version == 0


def test_preview_uses_current_warehouse_binding_before_private_read(editor, monkeypatch, tmp_path):
    c = setup(editor, monkeypatch, tmp_path)
    demote_admin(editor, ['invoice:sync', 'invoice:read_all', 'shipping_inspection:write'])
    with Session(editor.ctx.engine) as db:
        lock_authority(db)
        db.add(ArkUserExternalBinding(ark_user_id=editor.ctx.admin,provider='okki',external_account_id='wrong-owner',binding_status='active',is_primary=True))
        db.commit()
    before = snapshot(c);response = preview(c)
    assert response.status_code == 404 and snapshot(c) == before and c.reads == c.posts == []


@pytest.mark.parametrize('change', ['inactive','permission'])
def test_preview_commit_then_response_revocation_preserves_authorized_event(editor, monkeypatch, tmp_path, change):
    c = setup(editor, monkeypatch, tmp_path)
    commit = Session.commit; hit = []; observed = []
    def gate(db):
        target = any(isinstance(row, ShippingOperationEvent) and row.scope == state.SCOPE
                     and row.action == 'sync_idle' and row.request_id == c.record['outbound_record_id'] for row in list(db.new)+list(db.identity_map.values()))
        commit(db)
        if target and not hit:
            hit.append(True)
            if change == 'inactive':
                with Session(editor.ctx.engine) as revoke:
                    lock_authority(revoke);revoke.get(ArkUser, editor.ctx.admin).is_active=False;commit(revoke)
            else: demote_admin(editor, ['invoice:sync','invoice:read_all','shipping_inspection:read_all'])
            observed.append(snapshot(c))
    monkeypatch.setattr(Session,'commit',gate)
    response = preview(c)
    assert response.status_code == 403 and hit == [True]
    assert snapshot(c) == observed[0] and c.posts == [] and 'version' not in response.text


def test_follow_existing_fresh_current_actor_can_read_owned_target(editor, monkeypatch, tmp_path):
    from app.invoice import outbound_followup_service as followup
    c = setup(editor, monkeypatch, tmp_path)
    c.outbound['remark']=''
    monkeypatch.setattr(outbound_service,'get_record_by_outbound_invoice_id',lambda *a,**kw:deepcopy(c.record))
    with Session(editor.ctx.engine,expire_on_commit=False) as db:
        result=followup._follow_existing(db,SimpleNamespace(id=editor.invoice_id,invoice_no='Owned PI'),
                  {'sub':str(editor.ctx.admin)},[c.outbound],force_authority=True)
        assert result['status']=='done',result
    assert c.posts==[]


@pytest.mark.parametrize('fault', ['first_outbound', 'readback_outbound', 'readback_order', 'incomplete_scan'])
def test_prepare_incomplete_supplier_evidence_is_503_and_never_creates_event(editor, monkeypatch, tmp_path, fault):
    from app.invoice import linked_outbound_service
    scanner = linked_outbound_service.find_related
    c = setup(editor, monkeypatch, tmp_path)
    before = snapshot(c)
    read = sync.remote.read
    counts = {}
    def evidence(db, path, params):
        counts[path] = counts.get(path, 0)+1
        if fault == 'first_outbound' and path.endswith('/outbound/info'): return None
        if fault == 'readback_outbound' and path.endswith('/outbound/info') and counts[path] > 1: return None
        if fault == 'readback_order' and path.endswith('/order/info') and counts[path] > 1: return None
        if path.endswith('/outbound/list'): return {'count': 2, 'list': []}
        return read(db, path, params)
    monkeypatch.setattr(sync.remote, 'read', evidence)
    if fault == 'incomplete_scan': monkeypatch.setattr(linked_outbound_service, 'find_related', scanner)
    response = preview(c)
    assert response.status_code == 503, response.text
    assert snapshot(c) == before and c.posts == [] and 'no-store' in response.headers['cache-control']


def test_actual_token_reader_releases_capture_before_refresh_and_final_authority(editor, monkeypatch, tmp_path):
    actual_read = sync.remote.read
    c = setup(editor, monkeypatch, tmp_path)
    monkeypatch.setattr(sync.remote, 'read', actual_read)
    def get(url, **kwargs):
        return httpx.Response(200, json={'code': 200, 'data': deepcopy(c.outbound if url.endswith('/outbound/info') else c.order)})
    monkeypatch.setattr(sync.okki_client.httpx, 'get', get)
    fetch = sync.okki_client.fetch_token
    ready, release = Event(), Event()
    def token(): ready.set(); assert release.wait(8); return fetch()
    monkeypatch.setattr(sync.okki_client,'fetch_token',token)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(preview,c)
        try:
            assert ready.wait(6)
            with Session(editor.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db); edit_authority.lock_document(db,editor.invoice_id)
                db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
            before=snapshot(c)
            release.set();response=pending.result(timeout=10)
        finally: release.set()
    assert response.status_code==403 and snapshot(c)==before and c.posts==[]


@pytest.mark.parametrize('supplier', ['outbound','order'])
@pytest.mark.parametrize('window', ['first','readback'])
@pytest.mark.parametrize('field', ['currency','customer'])
@pytest.mark.parametrize('shape', ['dict','list','bool'])
def test_prepare_supplier_head_types_are_unknown_evidence(editor, monkeypatch, tmp_path, supplier, window, field, shape):
    c = setup(editor,monkeypatch,tmp_path)
    read=sync.remote.read;counts={};before=snapshot(c)
    bad={'dict':{'code':'USD'},'list':['USD'],'bool':True}[shape]
    def evidence(db,path,params):
        result=read(db,path,params)
        counts[path]=counts.get(path,0)+1
        if path.endswith('/'+supplier+'/info') and counts[path] == (1 if window == 'first' else 2):
            if field == 'currency':result['currency']=deepcopy(bad)
            elif supplier == 'outbound':result['company_info']['id']=deepcopy(bad)
            else:result['company_id']=deepcopy(bad)
        return result
    monkeypatch.setattr(sync.remote,'read',evidence)
    response=preview(c)
    assert response.status_code==503,response.text
    assert snapshot(c)==before and c.posts==[]


@pytest.mark.parametrize('change', ['outbound_currency','outbound_status','order_currency'])
def test_prepare_trustworthy_commercial_difference_remains_409(editor,monkeypatch,tmp_path,change):
    c=setup(editor,monkeypatch,tmp_path)
    if change=='outbound_currency':c.outbound['currency']='EUR'
    elif change=='outbound_status':c.outbound['status']=2
    else:c.order['currency']='EUR'
    before=snapshot(c);response=preview(c)
    assert response.status_code==409,response.text
    assert snapshot(c)==before and c.posts==[]


@pytest.mark.parametrize('change', ['invoice','target','owned'])
def test_active_original_plan_remains_bound_to_current_invoice_and_target(editor,monkeypatch,tmp_path,change):
    c=setup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine,expire_on_commit=False) as db:
        invoice,event,plan=sync._prepare(db,c.record,{'sub':str(editor.ctx.admin)},force_authority=True)
        if change=='invoice':plan['invoice_id']=editor.invoice_id+100000
        elif change=='target':plan['before']['outbound_invoice_id']=900001
        event.action='sync_uncertain'
        event.payload={'invoice_id':invoice.id,'plan':plan}
        event.result={'message':'Existing original attempt awaiting verification'}
        db.commit()
    before=snapshot(c);c.reads.clear();response=preview(c)
    assert response.status_code==(200 if change=='owned' else 409),response.text
    if change=='owned':assert response.json()['data']['recover'] is True
    assert snapshot(c)==before and c.reads==c.posts==[]


@pytest.mark.parametrize('commit_first', [False,True])
def test_preview_event_commit_failure_preserves_atomic_original_result(editor,monkeypatch,tmp_path,commit_first):
    c=setup(editor,monkeypatch,tmp_path);before=snapshot(c)
    commit=Session.commit;hit=[]
    def fault(db):
        target=any(isinstance(row,ShippingOperationEvent) and row.scope==state.SCOPE
            and row.request_id==c.record['outbound_record_id'] for row in list(db.new)+list(db.identity_map.values()))
        if target and not hit:
            hit.append(True)
            if commit_first:commit(db)
            raise OperationalError('owned synthetic commit failure',{},RuntimeError('unknown acknowledgment'))
        return commit(db)
    monkeypatch.setattr(Session,'commit',fault)
    response=preview(c);after=snapshot(c)
    assert response.status_code==503 and hit==[True] and c.posts==[]
    if not commit_first:assert after==before
    else:
        assert after[0]==before[0] and after[1][1:]==before[1][1:]
        assert tuple(after[1][0][:-1])==before[1][0]
        fields=[column.name for column in ShippingOperationEvent.__table__.columns]
        event=dict(zip(fields,after[1][0][-1]))
        assert event['scope']==state.SCOPE and event['request_id']==c.record['outbound_record_id']
        assert event['action']=='sync_idle' and event['operator_user_id']==editor.ctx.admin
    retry=preview(c)
    assert retry.status_code==200 and c.posts==[]
    with Session(editor.ctx.engine) as db:
        assert len(db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==state.SCOPE,
                    ShippingOperationEvent.request_id==c.record['outbound_record_id'])).all())==1


@pytest.mark.parametrize('commit_first', [False,True])
def test_capture_commit_failure_stops_before_supplier_and_mutation(editor,monkeypatch,tmp_path,commit_first):
    c=setup(editor,monkeypatch,tmp_path);before=snapshot(c)
    commit=Session.commit;hit=[]
    def fault(db):
        if not hit:
            hit.append(True)
            if commit_first:commit(db)
            raise OperationalError('owned capture commit failure',{},RuntimeError('unknown acknowledgment'))
        return commit(db)
    monkeypatch.setattr(Session,'commit',fault)
    response=preview(c)
    assert response.status_code==503 and hit==[True]
    assert snapshot(c)==before and c.reads==c.posts==[]
