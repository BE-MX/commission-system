"""Current quote/read boundaries; immutable evidence, actual waits and finite snapshots."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import threading,queue
import pytest
from fastapi import HTTPException
from sqlalchemy import select,text,event,MetaData,Table,Column,Integer,String
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.auth.models import ArkRole,ArkPermission,ArkRolePermission
from app.invoice.models import Invoice,InvoiceItem
from app.invoice.settlement_models import ReceiptBatch
from app.invoice.settlement_schemas import ShipmentQuote
from app.invoice import shipment_create_service as facts, shipment_quote_service
from app.receipt.models import Receipt,ReceiptIntent,ReceiptLog
from app.semifinished.models import InvoiceAllocation
from app.portal import authority as portal_authority
from test_mysql_concurrency import wait_for_lock
from test_mysql_shipment_reads import request,setup,ROUTES
from test_mysql_shipment_create import shipment_app,snapshot,authorize,login,change_user  # noqa: F401
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


def guarded(response,code):
    assert response.status_code==code,response.text
    assert response.headers.get('cache-control')=='private, no-store' and response.headers.get('pragma')=='no-cache'


@pytest.mark.parametrize('route',ROUTES)
@pytest.mark.parametrize('credential',['anonymous','invalid'])
def test_dependency_rejection_private_no_store(shipment_app,route,credential):
    c=shipment_app
    with c.app.client() as client:
        setup(client,c,route);before=snapshot(c);c.io.clear()
        response=request(client,c,route,{} if credential=='anonymous' else {'Authorization':'Bearer invalid'})
        guarded(response,403 if credential=='anonymous' else 401)
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('route',['quote','order','detail'])
def test_validation_error_sanitized_private_no_store(shipment_app,route):
    c=shipment_app
    with c.app.client() as client:
        _,owner=setup(client,c,route);before=snapshot(c);c.io.clear()
        if route=='quote':response=client.post(f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=owner,json={
            'items':[{'invoice_item_id':c.item_id,'quantity':4}],'private_value':'PRIVATE_SHIPMENT_MARKER'})
        else:response=client.get('/api/shipments/order/PRIVATE_SHIPMENT_MARKER' if route=='order' else '/api/shipments/PRIVATE_SHIPMENT_MARKER',headers=owner)
        guarded(response,422);assert 'PRIVATE_SHIPMENT_MARKER' not in response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


def role_for(c,code):
    with Session(c.ctx.engine) as db:
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
        if permission is None:
            module,action=code.split(':');permission=ArkPermission(code=code,module=module,action=action,label=code,kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='owned-read-'+uuid4().hex,label=code);db.add(role);db.flush()
        db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id));identity=role.id;db.commit()
    return identity


@pytest.mark.parametrize('route,code',[('capabilities',value) for value in ('invoice:read','invoice:write','receipt:write','shipment:read')]+
    [('quote',value) for value in ('invoice:read','invoice:write')]+[(route,value) for route in ('order','detail') for value in ('shipment:read','shipment:write')])
def test_each_original_or_action_remains_sufficient(shipment_app,route,code):
    c=shipment_app
    with c.app.client() as client:
        root,_=setup(client,c,route);change_user(client,c,root,{'role_ids':[role_for(c,code)]});owner=login(client,c,c.owner_name)
        before=snapshot(c);c.io.clear();response=request(client,c,route,owner);guarded(response,200)
        assert snapshot(c)==before and c.calls==[]
        if route!='quote':assert c.io==[]


@pytest.mark.parametrize('route',['order','detail'])
def test_history_read_does_not_require_new_order_ready(shipment_app,route):
    c=shipment_app
    with c.app.client() as client:
        _,owner=setup(client,c,route)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id);invoice.sync_status='pending';invoice.status='draft';db.commit()
        before=snapshot(c);c.io.clear();response=request(client,c,route,owner);guarded(response,200)
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('route',['quote','order','detail'])
@pytest.mark.parametrize('scope',['all','super_admin'])
def test_current_actual_financial_scope_not_invoice_read_all(shipment_app,route,scope):
    c=shipment_app
    with c.app.client() as client:
        root,_=setup(client,c,route)
        with Session(c.ctx.engine) as db:identity=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id if scope=='super_admin' else c.roles['all']
        change_user(client,c,root,{'role_ids':c.shipment_roles+[identity]});owner=login(client,c,c.owner_name)
        with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
        guarded(request(client,c,route,owner),200)
        change_user(client,c,root,{'role_ids':c.shipment_roles+[c.roles['invoice:read_all']]})
        before=snapshot(c);c.io.clear();guarded(request(client,c,route,owner),404)
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('change',['disabled','actions','owner'])
def test_quote_unlocked_evidence_admin_can_commit_then_rejected(shipment_app,enabled,change,monkeypatch):
    c=shipment_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    ready=threading.Event();resume=threading.Event();original=facts._evidence
    def gate(*args):ready.set();assert resume.wait(10);return original(*args)
    with c.app.client() as client:
        root,owner=setup(client,c,'quote');monkeypatch.setattr(facts,'_evidence',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(request,client,c,'quote',owner)
            try:
                assert ready.wait(5) and not action.done()
                if change=='owner':
                    with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
                else:change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[c.roles['shipment:write']]})
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        guarded(response,404 if change=='owner' else 403);assert snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['invoice','item','receipt','intent','allocation','log'])
def test_quote_complete_graph_change_during_evidence_rejects_no_write(shipment_app,change,monkeypatch):
    c=shipment_app;ready=threading.Event();resume=threading.Event();original=facts._evidence
    def gate(*args):ready.set();assert resume.wait(10);return original(*args)
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');monkeypatch.setattr(facts,'_evidence',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(request,client,c,'quote',owner)
            try:
                assert ready.wait(5)
                with Session(c.ctx.engine) as db:
                    if change=='invoice':db.get(Invoice,c.invoice_id).remark='Changed commercial note'
                    elif change=='item':db.get(InvoiceItem,c.item_id).quantity=11
                    elif change=='receipt':db.get(Receipt,c.receipts['positive']).remark='Changed funds'
                    elif change=='intent':db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).status='armed'
                    elif change=='allocation':db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                    else:db.add(ReceiptLog(receipt_id=c.receipts['victim'],action='late_result',message='Persisted original sender fact'))
                    db.commit()
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        guarded(response,409);assert snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('stage',[1,2])
@pytest.mark.parametrize('timing',['before','after'])
def test_quote_exact_two_commit_faults_only_metadata_can_persist(shipment_app,stage,timing,monkeypatch):
    c=shipment_app;sessions=[];hits=[];original=shipment_quote_service._authorize;evidence=facts._evidence
    metadata=MetaData();table=Table('owned_quote_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(12)))
    metadata.create_all(c.ctx.engine)
    identity=int(uuid4().hex[:7],16)
    with c.ctx.engine.begin() as connection:connection.execute(table.insert().values(id=identity,value='old'))
    def authorize_source(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    def refresh(db,*args):
        db.execute(table.update().where(table.c.id==identity).values(value='new'));return evidence(db,*args)
    def inject(db):
        if any(db is item for item in sessions):
            count=db.info.get('owned_quote_commit',0)+1;db.info['owned_quote_commit']=count
            if count==stage:hits.append((db,stage,timing));raise OperationalError('private-quote-commit',{},Exception('private-token'))
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');before=snapshot(c)
        monkeypatch.setattr(shipment_quote_service,'_authorize',authorize_source);monkeypatch.setattr(facts,'_evidence',refresh)
        event.listen(Session,'before_commit' if timing=='before' else 'after_commit',inject)
        try:response=request(client,c,'quote',owner)
        finally:event.remove(Session,'before_commit' if timing=='before' else 'after_commit',inject)
        guarded(response,503);assert 'private-token' not in response.text and len(hits)==1
        assert hits[0][0] is sessions[0] and snapshot(c)==before and c.calls==[]
        with Session(c.ctx.engine) as db:assert db.scalar(select(table.c.value).where(table.c.id==identity))==('new' if stage==2 and timing=='after' else 'old')


def test_quote_dirty_caller_retains_transaction(shipment_app):
    c=shipment_app
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);before=invoice.remark;invoice.remark='Caller-only note'
        with pytest.raises(HTTPException) as caught:
            shipment_quote_service.quote(db,c.invoice_id,ShipmentQuote(items=[{'invoice_item_id':c.item_id,'quantity':4}]),{'sub':str(c.ctx.actor)})
        assert caught.value.status_code==409 and invoice in db.dirty and db.in_transaction() and invoice.remark=='Caller-only note'
        with Session(c.ctx.engine) as other:assert other.get(Invoice,c.invoice_id).remark==before
        db.rollback()


@pytest.mark.parametrize('change',['receipt','intent'])
def test_quote_current_graph_after_real_invoice_wait(shipment_app,change,monkeypatch):
    c=shipment_app;ready=threading.Event();release=threading.Event();started=queue.Queue();locked=threading.Event();resume=threading.Event();target={};original=facts._evidence
    def gate(*args):ready.set();assert release.wait(10);return original(*args)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():target['connection']=connection;started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection,cursor,statement,parameters,context,executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not locked.is_set():locked.set();assert resume.wait(10)
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');monkeypatch.setattr(facts,'_evidence',gate)
        with Session(c.ctx.engine) as other,ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(request,client,c,'quote',owner)
            try:
                assert ready.wait(5);other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                if change=='receipt':other.get(Receipt,c.receipts['positive']).remark='Concurrent current funds'
                else:other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).status='armed'
                other.flush();event.listen(c.ctx.engine,'before_cursor_execute',observe);event.listen(c.ctx.engine,'after_cursor_execute',hold)
                release.set();wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                other.commit();assert locked.wait(5) and not action.done();before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:
                release.set();resume.set();other.rollback()
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
                if event.contains(c.ctx.engine,'after_cursor_execute',hold):event.remove(c.ctx.engine,'after_cursor_execute',hold)
        guarded(response,409);assert snapshot(c)==before and c.calls==[]


def test_unrelated_null_key_batch_not_in_quote_graph(shipment_app,monkeypatch):
    c=shipment_app;ready=threading.Event();resume=threading.Event();original=facts._evidence
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);row=ReceiptBatch(request_key=None,gross_amount=1,bank_charge_total=0,currency=invoice.currency,customer_id=invoice.customer_id,created_by=c.ctx.actor,remark='Unrelated')
        db.add(row);db.flush();identity=row.id;db.commit()
    def gate(*args):ready.set();assert resume.wait(10);return original(*args)
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');monkeypatch.setattr(facts,'_evidence',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(request,client,c,'quote',owner)
            try:
                assert ready.wait(5)
                with Session(c.ctx.engine) as db:db.get(ReceiptBatch,identity).remark='Other operation changed';db.commit()
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        guarded(response,200);assert snapshot(c)==before and response.json()['data']['new_payment_due']=='64.00' and c.calls==[]
