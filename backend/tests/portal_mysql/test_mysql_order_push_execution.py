"""Actual employee JWT/MySQL order push phases; provider HTTP and follow-up boundaries only."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import Column, MetaData, Table, select, update, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.time import beijing_now, beijing_today, utc_now_naive
from app.invoice import edit_authority, okki_client, order_push_facts as facts, order_sync_execution as execution
from app.invoice import outbound_followup_service, xiaoman_service
from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog, XiaomanSettings, CustomProduct, OkkiOutboundTask
from app.invoice.settlement_models import BatchAttachment
from app.portal.authority import lock_authority, get_settings
from app.portal.models import AuditEvent
from app.receipt import attachments
from app.receipt.models import ReceiptIntent, ReceiptAttachment
from app.semifinished.models import SemifinishedMaterial, ProductMapping, ProductComponent, InventoryBalance, InventoryLedger, InvoiceAllocation
from test_mysql_invoice_cancellation_refresh import demote_admin


def setup_push(e, monkeypatch, tmp_path, *, editing=False, production=False):
    metadata = MetaData()
    for model in (XiaomanSettings, CustomProduct, ArkUserExternalBinding, BatchAttachment,
                  SemifinishedMaterial, ProductMapping, ProductComponent, InventoryBalance, InventoryLedger):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(e.ctx.engine)
    proof_id = uuid4().hex
    proof = tmp_path / 'owned-proof.png'; proof.write_bytes(b'synthetic storage boundary')
    monkeypatch.setattr(attachments, 'path_for', lambda row: proof)
    monkeypatch.setattr(attachments, 'origin', lambda: None)
    monkeypatch.setattr(xiaoman_service.get_settings(), 'OKKI_OUTBOUND_AUTO_ENABLED', False)
    with Session(e.ctx.engine) as db:
        lock_authority(db); invoice = edit_authority.lock_document(db, e.invoice_id)
        invoice.xiaoman_order_id = str(970000 + e.invoice_id) if editing else None
        invoice.status, invoice.sync_status = 'ready', 'not_synced'
        for index, item in enumerate(invoice.items):
            item.xiaoman_unique_id = str(501 + index) if editing else None
        db.get(ArkUser, e.ctx.actor).okki_department_id = 0
        db.add(ArkUserExternalBinding(ark_user_id=e.ctx.actor, provider='okki', external_account_id=str(e.ctx.actor),
                                     binding_status='active', is_primary=True))
        settings = db.get(XiaomanSettings, 1)
        if settings is None:
            settings = XiaomanSettings(id=1, default_currency='USD'); db.add(settings)
        settings.default_order_status = '1'; settings.access_token = None; settings.token_expires_at = None
        # Portal approval no longer creates this intent; seed it the way the
        # existing Ark invoice-edit entry would, ready for the push to arm.
        intent = ReceiptIntent(invoice_id=invoice.id, eligible=1, created_by=e.ctx.actor,
                               attachment_ids=[], status='draft')
        db.add(intent)
        intent.amount, intent.collection_date, intent.payment_type = Decimal('50'), beijing_today(), 'bank_transfer'
        intent.currency, intent.customer_id, intent.attachment_ids = invoice.currency, invoice.customer_id, [proof_id]
        db.add(ReceiptAttachment(id=proof_id, filename='owned.png', storage_key=proof_id+'.png',
            content_type='image/png', size=30, sha256='a'*64, created_by=e.ctx.admin))
        material_id = None
        if production:
            invoice.order_type = 'production'
            material = SemifinishedMaterial(material_code='OWN-'+uuid4().hex[:12], size='20', color_code='1', color_key='1')
            db.add(material); db.flush(); material_id = material.id
            item = invoice.items[0]
            mapping = ProductMapping(source_type='okki', product_id=int(item.product_id), product_name='Owned product',
                size='20', color_expression='1', unit_grams=20, parse_status='confirmed', parser_version='test')
            db.add(mapping); db.flush()
            db.add(ProductComponent(mapping_id=mapping.id, material_id=material.id, ratio=1, grams_per_piece=20))
            db.add(InventoryBalance(material_id=material.id, on_hand_grams=100, reserved_grams=0, version=0))
            item.semifinished_enabled = 1
            item.semifinished_plan = [{'material_id':material.id, 'quantity_grams':'60.000'}]
        db.commit()
    ctx = SimpleNamespace(e=e, route=f'/api/invoice/invoices/{e.invoice_id}/sync', posts=[], tokens=[],
                          followups=[], target=str(970000+e.invoice_id), material_id=material_id)
    def fetch():
        value = 'synthetic-provider-token-'+str(len(ctx.tokens)+1); ctx.tokens.append(value)
        return value, utc_now_naive()+timedelta(hours=8)
    def accepted(payload):
        return {'order_id':ctx.target,'product_list':[
            {**row,'unique_id':row.get('unique_id') or str(501+i)} for i,row in enumerate(payload['product_list']) if not row.get('remove')],
            'provider_private':'private-provider-body-must-not-be-logged'}
    def post(url, *, headers, json, timeout):
        assert url.endswith('/v1/invoices/order/push')
        ctx.posts.append(deepcopy(json))
        return httpx.Response(200, json={'code':200,'data':accepted(json)})
    def followup(*args, **kwargs):
        ctx.followups.append(args[1].id)
        return {'status':'manual','message':'Explicitly substituted downstream executor boundary'}
    ctx.accepted = accepted; ctx.post = post
    monkeypatch.setattr(okki_client, 'fetch_token', fetch)
    monkeypatch.setattr(okki_client.httpx, 'post', post)  # Keep actual _post_json classification and actual token helper.
    monkeypatch.setattr(outbound_followup_service, 'safely_run', followup)
    return ctx


def business(e):
    with Session(e.ctx.engine) as db:
        return e.snapshot(), tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (ReceiptAttachment, InvoiceAllocation, OkkiOutboundTask, InventoryBalance, InventoryLedger))


def events(e, action):
    with Session(e.ctx.engine) as db:
        return [deepcopy(row.safe_diff_json) for row in db.scalars(select(AuditEvent).where(
            AuditEvent.action==action, AuditEvent.safe_diff_json['invoice_id'].as_integer()==e.invoice_id)).all()]


def audit(e):
    with Session(e.ctx.engine) as db:
        object_id, _ = facts.object_binding(db, e.invoice_id)
        return [(row.action,deepcopy(row.safe_diff_json)) for row in db.scalars(select(AuditEvent).where(
            AuditEvent.object_public_id==object_id, AuditEvent.action.in_([facts.START,facts.FACT,facts.FINISH,facts.REVIEW]))).all()]


def execute(ctx):
    return asyncio.run(ctx.e.write(ctx.route,{},'POST',ctx.e.admin_token))


@pytest.mark.parametrize('editing',[False,True])
def test_create_success_and_update_preserve_receipt_and_single_post(editor,monkeypatch,tmp_path,editing):
    e=editor; c=setup_push(e,monkeypatch,tmp_path,editing=editing)
    response=execute(c); assert response.status_code==200,response.text
    assert response.json()['data']['ok'] is True,response.text
    assert len(c.posts)==1 and len(c.tokens)==1 and c.followups==[e.invoice_id]
    assert ('order_id' in c.posts[0])==editing and 'no-store' in response.headers['cache-control']
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        assert invoice.sync_status=='synced' and invoice.xiaoman_order_id==c.target and invoice.sync_attempt is None
        assert invoice.items[0].xiaoman_unique_id=='501'
        assert intent.status=='ready' and intent.attempt_token is None
        assert db.scalar(select(ReceiptAttachment).where(ReceiptAttachment.id.in_(intent.attachment_ids))).invoice_id==invoice.id
        assert facts.unresolved(db,invoice)==[]
    rows=audit(e); assert [x[0] for x in rows].count(facts.START)==1
    assert [x[0] for x in rows].count(facts.FACT)==1 and [x[0] for x in rows].count(facts.FINISH)==1
    assert c.tokens[0] not in str(rows)+response.text and 'private-provider-body' not in str(rows)+response.text


@pytest.mark.parametrize('change',['inactive','role','scope'])
def test_initial_current_authority_denies_before_token_or_claim(editor,monkeypatch,tmp_path,change):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    if change=='inactive':
        with Session(e.ctx.engine) as db:lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    else:demote_admin(e,[] if change=='role' else ['invoice:sync'])
    before=business(e);response=execute(c)
    assert response.status_code==(404 if change=='scope' else 403),response.text
    assert c.posts==c.tokens==c.followups==[] and business(e)==before


@pytest.mark.parametrize('change',['inactive','scope','amount','currency','uid','intent','proof','task','cancelled'])
def test_actual_token_helper_window_is_unlocked_and_claim_rechecks(editor,monkeypatch,tmp_path,change):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);ready=Event();release=Event();original=okki_client.fetch_token
    def gate():ready.set();assert release.wait(8);return original()
    monkeypatch.setattr(okki_client,'fetch_token',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(execute,c)
        try:
            assert ready.wait(6)
            if change=='scope':demote_admin(e,['invoice:sync'])
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'));lock_authority(db)
                invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='amount':db.execute(update(Invoice).where(Invoice.id==invoice.id).values(total_amount=invoice.total_amount+1))
                elif change=='currency':invoice.currency='EUR'
                elif change=='uid':db.execute(update(InvoiceItem).where(InvoiceItem.id==invoice.items[0].id).values(xiaoman_unique_id='9001'))
                elif change=='intent':db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).amount+=1
                elif change=='proof':db.scalar(select(ReceiptAttachment).where(ReceiptAttachment.invoice_id.is_(None),ReceiptAttachment.created_by==e.ctx.admin).order_by(ReceiptAttachment.created_at.desc())).sha256='b'*64
                elif change=='task':db.add(OkkiOutboundTask(invoice_id=invoice.id,order_id='401',status='running'))
                elif change=='cancelled':invoice.status='cancelled'
                db.commit()
            before=business(e);release.set();response=pending.result(timeout=10)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 404 if change=='scope' else 409),response.text
    assert business(e)==before and c.posts==c.followups==[] and audit(e)==[]


@pytest.mark.parametrize('fault',['timeout','disconnect','server_error','bad_json','primitive','no_order','wrong_uid','leading_zero_uid','duplicate_uid','wrong_product'])
def test_actual_post_classification_preserves_unknown_and_prevents_resend(editor,monkeypatch,tmp_path,fault):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    def post(url,**kwargs):
        c.posts.append(deepcopy(kwargs['json']))
        if fault=='timeout':raise httpx.ReadTimeout('synthetic transport timeout')
        if fault=='disconnect':raise httpx.ConnectError('synthetic transport interruption')
        if fault=='server_error':return httpx.Response(503,json={'message':'synthetic provider failure'})
        if fault=='bad_json':return httpx.Response(200,text='<invalid>')
        if fault=='primitive':return httpx.Response(200,json=[])
        result=c.accepted(kwargs['json'])
        if fault=='no_order':result.pop('order_id')
        elif fault=='wrong_uid':result['product_list'][0]['unique_id']='unverified'
        elif fault=='leading_zero_uid':result['product_list'][0]['unique_id']='0501'
        elif fault=='duplicate_uid':result['product_list'].append(deepcopy(result['product_list'][0]))
        elif fault=='wrong_product':result['product_list'][0]['product_id']=999999
        return httpx.Response(200,json={'code':200,'data':result})
    monkeypatch.setattr(okki_client.httpx,'post',post)
    response=execute(c);assert response.status_code==200,response.text
    assert response.json()['data']['ok'] is False and len(c.posts)==1 and c.followups==[]
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        assert invoice.status==invoice.sync_status=='sync_uncertain' and invoice.sync_attempt
        assert invoice.items[0].xiaoman_unique_id is None
        assert facts.unresolved(db,invoice)
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        assert intent.status=='armed' and intent.attempt_token is None
    before=business(e);repeat=execute(c)
    assert repeat.status_code==409 and len(c.posts)==1 and business(e)==before


@pytest.mark.parametrize('outcome',['accepted','rejected','unknown'])
def test_production_real_inventory_reserve_finalize_release(editor,monkeypatch,tmp_path,outcome):
    e=editor;c=setup_push(e,monkeypatch,tmp_path,production=True)
    def post(url,**kwargs):
        with Session(e.ctx.engine) as db:
            balance=db.scalar(select(InventoryBalance).where(InventoryBalance.material_id==c.material_id))
            allocation=db.scalar(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id==e.invoice_id))
            assert balance.on_hand_grams==100 and balance.reserved_grams==60
            assert allocation.status=='pending' and len(events(e,facts.START))==1
        c.posts.append(deepcopy(kwargs['json']))
        if outcome=='unknown':raise httpx.ReadTimeout('synthetic timeout')
        return httpx.Response(422,json={'message':'known rejected'}) if outcome=='rejected' else httpx.Response(200,json={'data':c.accepted(kwargs['json'])})
    monkeypatch.setattr(okki_client.httpx,'post',post)
    response=execute(c);assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        balance=db.scalar(select(InventoryBalance).where(InventoryBalance.material_id==c.material_id))
        allocation=db.scalar(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id==e.invoice_id))
        invoice=edit_authority.lock_document(db,e.invoice_id)
        assert balance.on_hand_grams==(40 if outcome=='accepted' else 100)
        assert balance.reserved_grams==(60 if outcome=='unknown' else 0)
        assert allocation.status==('pending' if outcome=='unknown' else 'allocated')
        assert allocation.allocated_qty_grams==(60 if outcome=='accepted' else 0)
        movements=db.scalars(select(InventoryLedger.movement_type).where(InventoryLedger.business_id==invoice.id).order_by(InventoryLedger.id)).all()
        assert movements==['reserve']+(['outbound'] if outcome=='accepted' else ['release'] if outcome=='rejected' else [])
        assert invoice.sync_status=={'accepted':'synced','rejected':'sync_failed','unknown':'sync_uncertain'}[outcome]


@pytest.mark.parametrize('change',['inactive','scope','amount','takeover','expired','cancelled'])
def test_post_window_preserves_original_acceptance_without_overwriting_new_state(editor,monkeypatch,tmp_path,change):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);ready=Event();release=Event()
    def post(url,**kwargs):ready.set();assert release.wait(8);return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',post)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(execute,c)
        try:
            assert ready.wait(6)
            if change=='scope':demote_admin(e,['invoice:sync'])
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'));lock_authority(db)
                invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='amount':db.execute(update(Invoice).where(Invoice.id==invoice.id).values(total_amount=invoice.total_amount+1))
                elif change=='takeover':invoice.sync_attempt={**invoice.sync_attempt,'token':uuid4().hex}
                elif change=='expired':invoice.sync_attempt={**invoice.sync_attempt,'lease_until':(beijing_now()-timedelta(minutes=1)).isoformat()}
                elif change=='cancelled':invoice.status='cancelled'
                db.commit()
                if change not in {'inactive','scope'}:
                    db.expire_all();invoice=edit_authority.lock_document(db,e.invoice_id)
                    frozen=(invoice.status,invoice.sync_status,invoice.xiaoman_order_id,deepcopy(invoice.sync_attempt),invoice.total_amount)
            release.set();response=pending.result(timeout=10)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 404 if change=='scope' else 200),response.text
    rows=audit(e);assert len([row for row in rows if row[0]==facts.FACT])==1
    observation=[row[1] for row in rows if row[0]==facts.FACT][0]
    assert observation['result_class']=='accepted' and observation['provider_reference']==c.target
    if change in {'inactive','scope'}:
        assert c.followups==[]
        with Session(e.ctx.engine) as db:
            invoice=db.get(Invoice,e.invoice_id)
            assert invoice.sync_status=='sync_uncertain' and invoice.sync_attempt is not None
            assert facts.unresolved(db,invoice)
        assert [row[0] for row in rows].count(facts.FINISH)==0
    else:
        assert response.json()['data']['execution_changed'] is True and c.followups==[]
        with Session(e.ctx.engine) as db:
            invoice=edit_authority.lock_document(db,e.invoice_id)
            assert (invoice.status,invoice.sync_status,invoice.xiaoman_order_id,invoice.sync_attempt,invoice.total_amount)==frozen
            assert facts.unresolved(db,invoice)


@pytest.mark.parametrize('revoke',[False,True])
def test_auth_rejected_refresh_current_authority_controls_second_post(editor,monkeypatch,tmp_path,revoke):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);original_fetch=okki_client.fetch_token
    def fetch():
        if c.tokens and revoke:
            with Session(e.ctx.engine) as db:lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
        return original_fetch()
    def post(url,**kwargs):
        if not c.posts:
            c.posts.append(deepcopy(kwargs['json']));return httpx.Response(401,json={'error':'access_denied'})
        return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client,'fetch_token',fetch);monkeypatch.setattr(okki_client.httpx,'post',post)
    response=execute(c)
    assert response.status_code==(403 if revoke else 200),response.text
    assert len(c.posts)==(1 if revoke else 2) and len(c.tokens)==2
    observed=[row[1] for row in audit(e) if row[0]==facts.FACT]
    assert [row['result_class'] for row in observed]==(['auth_rejected'] if revoke else ['auth_rejected','accepted'])
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id)
        assert invoice.sync_status==('sync_uncertain' if revoke else 'synced')
        if revoke:
            assert invoice.sync_attempt is not None and facts.unresolved(db,invoice)
    if revoke:assert [row[0] for row in audit(e)].count(facts.FINISH)==0


@pytest.mark.parametrize('stage',['claim_before','claim_after','fact_before','fact_after','finish_after'])
def test_actual_commit_faults_never_duplicate_post_or_original_facts(editor,monkeypatch,tmp_path,stage):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);original=Session.commit;hit=[]
    def commit(db):
        if db.get_bind() is e.ctx.engine and not hit:
            object_id, _ = facts.object_binding(db, e.invoice_id)
            # Inspect actual flushed SQL facts: SQLAlchemy's identity map holds weak references.
            actions=set(db.scalars(select(AuditEvent.action).where(AuditEvent.object_public_id==object_id)).all())
            target=facts.START if stage.startswith('claim') else facts.FINISH if stage=='finish_after' else facts.FACT
            if target in actions and (target!=facts.START or not c.posts):
                hit.append(stage)
                if stage.endswith('after'):original(db)
                raise OperationalError('synthetic lost commit acknowledgement',{},RuntimeError('owned fault'))
        return original(db)
    monkeypatch.setattr(Session,'commit',commit)
    response=execute(c)
    assert hit==[stage],(stage,response.text)
    if stage.startswith('claim'):
        assert response.status_code==503 and c.posts==[]
        assert bool(audit(e))==(stage=='claim_after')
    else:
        assert response.status_code==200 and response.json()['data']['ok'] is True,response.text
        assert len(c.posts)==1
        assert len([row for row in audit(e) if row[0]==facts.FACT])==1
        assert len([row for row in audit(e) if row[0]==facts.FINISH])==1


@pytest.mark.parametrize('uid',['0501','-1','0','unverified','５０１'])
def test_invalid_existing_uid_stops_before_token_or_post(editor,monkeypatch,tmp_path,uid):
    e=editor;c=setup_push(e,monkeypatch,tmp_path,editing=True)
    with Session(e.ctx.engine) as db:
        db.execute(update(InvoiceItem).where(InvoiceItem.invoice_id==e.invoice_id).values(xiaoman_unique_id=uid));db.commit()
    before=business(e);response=execute(c)
    assert response.status_code==409 and c.posts==c.tokens==[] and business(e)==before,response.text
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('invalid',['missing_amount','missing_payment','missing_proof','wrong_currency'])
def test_receipt_preflight_failure_rolls_back_proof_binding_and_claim(editor,monkeypatch,tmp_path,invalid):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    with Session(e.ctx.engine) as db:
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==e.invoice_id))
        if invalid=='missing_amount':intent.amount=None
        elif invalid=='missing_payment':intent.payment_type=''
        elif invalid=='missing_proof':intent.attachment_ids=[]
        else:intent.currency='EUR'
        db.commit()
    before=business(e);response=execute(c)
    assert response.status_code==409 and c.posts==[] and business(e)==before and audit(e)==[],response.text


def test_two_real_overlapping_token_windows_only_claim_and_send_once(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);both=Event();release=Event();post_ready=Event();post_release=Event();mutex=Lock();count=[]
    original=okki_client.fetch_token
    def fetch():
        with mutex:
            count.append(1)
            if len(count)==2:both.set()
        assert release.wait(8);return original()
    def post(url,**kwargs):post_ready.set();assert post_release.wait(8);return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client,'fetch_token',fetch);monkeypatch.setattr(okki_client.httpx,'post',post)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls=[pool.submit(execute,c) for _ in range(2)]
        try:
            assert both.wait(6);release.set();assert post_ready.wait(6)
            done,_=wait(calls,timeout=6,return_when=FIRST_COMPLETED)
            assert len(done)==1 and next(iter(done)).result().status_code==409
            post_release.set();results=[call.result(timeout=10) for call in calls]
        finally:release.set();post_release.set()
    assert sorted(r.status_code for r in results)==[200,409] and len(c.posts)==1
    assert len([row for row in audit(e) if row[0]==facts.START])==1
    assert len([row for row in audit(e) if row[0]==facts.FACT])==1


@pytest.mark.parametrize('revoke',[False,True])
def test_inflight_off_retains_original_fact_and_current_response_authority(editor,monkeypatch,tmp_path,revoke):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);settings=get_settings();statements=[]
    from sqlalchemy import event
    def observe(conn,cursor,statement,params,context,many):
        if not settings.PORTAL_ENABLED and 'FOR UPDATE' in statement.upper():statements.append(statement)
    def post(url,**kwargs):
        with Session(e.ctx.engine) as db:
            lock_authority(db)
            if revoke:db.get(ArkUser,e.ctx.admin).is_active=False
            db.commit()
        monkeypatch.setattr(settings,'PORTAL_ENABLED',False)
        return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',post);event.listen(e.ctx.engine,'before_cursor_execute',observe)
    try:response=execute(c)
    finally:event.remove(e.ctx.engine,'before_cursor_execute',observe)
    assert response.status_code==(403 if revoke else 200),response.text
    assert len([r for r in audit(e) if r[0]==facts.FACT])==1
    if revoke:assert c.followups==[]
    positions=[]
    for name in ('ark_order_portal_auth_barriers','ark_order_portal_requests','ark_order_portal_conversions','ark_invoices'):
        positions.append(next(i for i,statement in enumerate(statements) if name in statement))
    assert positions==sorted(positions),statements


def test_provider_token_cache_is_committed_outside_authority(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    assert execute(c).status_code==200
    with Session(e.ctx.engine) as db:
        row=db.get(XiaomanSettings,1)
        assert row.access_token==c.tokens[0] and row.token_expires_at>utc_now_naive()
        assert okki_client.ensure_access_token(db)==c.tokens[0]
    assert len(c.tokens)==1


def test_known_accepted_stock_finalize_failure_preserves_original_reservation(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path,production=True)
    def post(url,**kwargs):
        # Corruption fault at the financial boundary; do not substitute inventory methods.
        with Session(e.ctx.engine) as db:
            db.execute(update(InventoryBalance).where(InventoryBalance.material_id==c.material_id).values(on_hand_grams=0));db.commit()
        return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',post)
    response=execute(c);assert response.status_code==200,response.text
    assert response.json()['data']['okki_accepted'] is True and response.json()['data']['inventory_pending'] is True
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        allocation=db.scalar(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id==invoice.id))
        balance=db.scalar(select(InventoryBalance).where(InventoryBalance.material_id==c.material_id))
        assert invoice.xiaoman_order_id==c.target and invoice.sync_status=='sync_uncertain'
        assert invoice.items[0].xiaoman_unique_id=='501' and allocation.status=='pending' and balance.reserved_grams==60
        assert facts.unresolved(db,invoice)
    assert execute(c).status_code==409 and len(c.posts)==1


@pytest.mark.parametrize('snapshot',[
    [{"unique_id":"0501"}], [{"unique_id":"５０１"}], [{"unique_id":0}],
    [{"unique_id":"invalid"}], [{"unique_id":True}], [{"unique_id":"700"},{"unique_id":700}],
    {"unique_id":"700"}, ["700"], [{"product_id":"100"}],
])
def test_removed_snapshot_identity_rejects_before_token_claim_or_post(editor,monkeypatch,tmp_path,snapshot):
    e=editor;c=setup_push(e,monkeypatch,tmp_path,editing=True)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_removed_lines=json.dumps(snapshot);db.commit()
    before=business(e)
    response=execute(c)
    assert response.status_code==409,response.text
    assert c.tokens==[] and c.posts==[] and audit(e)==[]
    assert business(e)==before


def test_canonical_removed_snapshot_is_sent_once(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path,editing=True)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_removed_lines=json.dumps([{"unique_id":"700","product_id":"100","sku_id":"200"}]);db.commit()
    response=execute(c)
    assert response.status_code==200,response.text
    assert len(c.posts)==1
    assert [row["unique_id"] for row in c.posts[0]["product_list"] if row.get("remove")]==[700]
    with Session(e.ctx.engine) as db:
        assert db.get(Invoice,e.invoice_id).xiaoman_removed_lines is None
