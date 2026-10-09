"""Shipment contract boundaries and deposit lifecycle on owned MySQL."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4
import threading
import queue
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, event
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.portal import authority as portal_authority
from test_mysql_concurrency import wait_for_lock
from app.invoice import shipment_create_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentSettlement, SettlementApplication, ReceiptBatch, SettlementEvent
from app.invoice.settlement_schemas import ShipmentCreate
from app.receipt.models import Receipt, ReceiptIntent
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, body_for, authorize, path, snapshot  # noqa: F401


@pytest.mark.parametrize('value',['0101','１０１','1.0',' 101','0','-1',None])
def test_noncanonical_line_identity_rejected_before_evidence(shipment_app,value):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
        with Session(c.ctx.engine) as db:db.get(InvoiceItem,c.item_id).xiaoman_unique_id=value;db.commit()
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==409 and snapshot(c)==before and c.io==[] and c.calls==[],response.text


def test_foreign_requested_line_rejected_before_evidence(shipment_app):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
        body['items'][0]['invoice_item_id']=999999;before=snapshot(c);c.io.clear()
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==409 and snapshot(c)==before and c.io==[] and c.calls==[],response.text


@pytest.mark.parametrize('status',['draft','armed','ready'])
def test_global_eligible_intent_cannot_share_embedded_proof(shipment_app,status):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
        with Session(c.ctx.engine) as db:
            db.add(ReceiptIntent(invoice_id=c.second_invoice_id,eligible=1,status=status,created_by=c.ctx.actor,
                attachment_ids=body['payment']['attachment_ids']));db.commit()
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==409 and snapshot(c)==before and c.io==[] and c.calls==[],response.text


def final_result(c,body,response):
    assert response.status_code==200,response.text
    identity=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        row=db.get(ShipmentSettlement,identity)
        assert row.invoice_id==c.invoice_id and row.is_final==1 and row.sequence==1
        assert row.quote['goods_amount']=='100.00' and row.quote['handling_amount']=='10.00'
        assert row.quote['deposit_applied']=='40.00' and row.quote['deposit_charge_applied']=='4.00'
        assert row.quote['new_payment_due']=='90.00' and row.quote['goods_payment_charge']=='6.00'
        apps=db.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id==identity)).all()
        assert len(apps)==1 and apps[0].component=='deposit' and apps[0].receipt_id==c.receipts['victim']
        assert apps[0].amount==40 and apps[0].bank_charge==4 and apps[0].status=='reserved'
        deposit=db.get(Receipt,apps[0].receipt_id)
        assert deposit.status=='active' and deposit.amount==40 and deposit.bank_charge==4
        assert db.query(Receipt).filter_by(invoice_id=c.invoice_id,purpose='presale_deposit').count()==1
        assert db.query(ReceiptBatch).filter_by(request_key=body['request_key']).count()==0
        assert db.query(SettlementEvent).filter_by(settlement_id=identity,action='created').count()==1
    assert c.calls==[]
    return identity


def test_final_deposit_without_new_payment_requires_no_receipt_action(shipment_app):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.roles['invoice:write'],c.roles['shipment:write']]})
        owner=login(client,c,c.owner_name);body=body_for(client,c,owner,payment=False,quantity=10)
        identity=final_result(c,body,client.post(path(c),headers=owner,json=body));before=snapshot(c);c.io.clear()
        replay=client.post(path(c),headers=owner,json=body)
        assert replay.status_code==200 and replay.json()['data']['id']==identity and snapshot(c)==before and c.io==[]


@pytest.mark.parametrize('change',['missing_application','wrong_component','wrong_deposit_invoice'])
def test_final_original_deposit_association_replay_rejects_no_repair(shipment_app,change):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner,payment=False,quantity=10);identity=final_result(c,body,client.post(path(c),headers=owner,json=body))
        with Session(c.ctx.engine) as db:
            app=db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id==identity))
            if change=='missing_application':db.delete(app)
            elif change=='wrong_component':app.component='goods'
            else:db.get(Receipt,c.receipts['victim']).invoice_id=c.second_invoice_id
            db.commit()
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==409 and snapshot(c)==before and c.io==[] and c.calls==[],response.text


@pytest.mark.parametrize('same_key',[True,False])
def test_final_competing_creates_reserve_original_deposit_once(shipment_app,same_key,monkeypatch):
    c=shipment_app;barrier=threading.Barrier(2);original=shipment_create_service._evidence;hits=[]
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        first=body_for(client,c,owner,payment=False,quantity=10);second=deepcopy(first)
        if not same_key:second['request_key']=uuid4().hex
        def gate(*args):hits.append(threading.get_ident());barrier.wait(timeout=10);return original(*args)
        monkeypatch.setattr(shipment_create_service,'_evidence',gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(client.post,path(c),headers=owner,json=body) for body in (first,second)]
            responses=[future.result(timeout=20) for future in futures]
        assert len(hits)==2 and sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409]),[r.text for r in responses]
        identity=next(r.json()['data']['id'] for r in responses if r.status_code==200)
        if same_key:assert {r.json()['data']['id'] for r in responses}=={identity}
        with Session(c.ctx.engine) as db:
            assert db.query(ShipmentSettlement).filter_by(invoice_id=c.invoice_id).count()==1
            apps=db.scalars(select(SettlementApplication).where(SettlementApplication.receipt_id==c.receipts['victim'])).all()
            assert len(apps)==1 and apps[0].settlement_id==identity and apps[0].amount==40 and apps[0].bank_charge==4
        assert c.calls==[]


def test_dirty_caller_is_not_flushed_or_rolled_back(shipment_app):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);old=invoice.remark;invoice.remark='Caller-only dirty note'
        with pytest.raises(HTTPException) as caught:
            shipment_create_service.create(db,c.invoice_id,ShipmentCreate.model_validate(body),{'sub':str(c.ctx.actor)})
        assert caught.value.status_code==409 and invoice in db.dirty and db.in_transaction()
        assert invoice.remark=='Caller-only dirty note'
        with Session(c.ctx.engine) as other:assert other.get(Invoice,c.invoice_id).remark==old
        db.rollback()


@pytest.mark.parametrize('change',['receipt','intent','allocation'])
def test_final_current_graph_after_real_invoice_wait(shipment_app,change,monkeypatch):
    c=shipment_app;ready=threading.Event();release=threading.Event();started=queue.Queue()
    locked=threading.Event();resume=threading.Event();target={};original=shipment_create_service._evidence
    def gate(*args):ready.set();assert release.wait(10);return original(*args)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection']=connection;started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection,cursor,statement,parameters,context,executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not locked.is_set():
            locked.set();assert resume.wait(10)
    from app.semifinished.models import InvoiceAllocation
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
        monkeypatch.setattr(shipment_create_service,'_evidence',gate)
        with Session(c.ctx.engine) as other,ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,path(c),headers=owner,json=body)
            try:
                assert ready.wait(5);other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                if change=='receipt':
                    row=other.get(Receipt,c.receipts['positive']);row.status='active';row.amount=80
                elif change=='intent':
                    row=other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                    row.eligible=1;row.status='ready';row.attachment_ids=body['payment']['attachment_ids']
                else:other.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                other.flush();event.listen(c.ctx.engine,'before_cursor_execute',observe);event.listen(c.ctx.engine,'after_cursor_execute',hold)
                release.set();wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                other.commit();assert locked.wait(5) and not action.done()
                # The caller is paused after its current Invoice lock. Its writes
                # cannot enter the externally committed comparison baseline.
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:
                release.set();resume.set();other.rollback()
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
                if event.contains(c.ctx.engine,'after_cursor_execute',hold):event.remove(c.ctx.engine,'after_cursor_execute',hold)
        assert response.status_code==409 and snapshot(c)==before and c.calls==[],response.text


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('commit',[False,True])
def test_final_business_commit_or_rollback_precedes_actual_admin_revocation(shipment_app,enabled,commit,monkeypatch):
    c=shipment_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    ready=threading.Event();resume=threading.Event();started=queue.Queue();sessions=[]
    original=shipment_create_service._authorize
    def authorize_source(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    def gate(db):
        if any(db is item for item in sessions):
            count=db.info.get('owned_shipment_final_fence',0)+1;db.info['owned_shipment_final_fence']=count
            if count==3:
                ready.set();assert resume.wait(10)
                if not commit:raise OperationalError('private-business-commit',{},Exception('rollback'))
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner);before=snapshot(c)
        monkeypatch.setattr(shipment_create_service,'_authorize',authorize_source);event.listen(Session,'before_commit',gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(client.post,path(c),headers=owner,json=body)
            try:
                assert ready.wait(5);event.listen(c.ctx.engine,'before_cursor_execute',observe)
                revoke=pool.submit(change_user,client,c,root,{'is_active':False})
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not revoke.done() and not action.done()
                resume.set();response=action.result(timeout=5);revoke.result(timeout=5)
            finally:
                resume.set();event.remove(Session,'before_commit',gate)
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        if commit:
            from test_mysql_shipment_create import created
            created(c,body,response)
        else:assert response.status_code==503 and snapshot(c)==before,response.text
        after=snapshot(c);c.io.clear();denied=client.post(path(c),headers=owner,json=body)
        assert denied.status_code==403 and snapshot(c)==after and c.io==[] and c.calls==[],denied.text
