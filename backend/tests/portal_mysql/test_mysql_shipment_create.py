"""Actual shipment-create JWT/main/owned MySQL; provider facts are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import threading
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.invoice import linked_outbound_service, settlement_policy, settlement_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, ShipmentOutbound,
    SettlementEvent, Receivable, SettlementApplication, ReceiptBatch, BatchAttachment)
from app.receipt import attachments, remote
from app.invoice import shipment_create_service
from app.semifinished.models import InvoiceAllocation
from app.portal import authority as portal_authority
from test_mysql_receipt_batch_presale import separate_proof
from test_mysql_receipt_batch_presale import presale_payload
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app, financial_snapshot  # noqa: F401


ACTUAL_FIND_RELATED = linked_outbound_service.find_related


@pytest.fixture
def shipment_app(batch_create_app,monkeypatch):
    c=batch_create_app
    c.app.settings.PRESALE_SETTLEMENT_ENABLED=True;c.app.settings.PRESALE_DELIVERY_ENABLED=True
    c.app.settings.OKKI_PRESALE_WAREHOUSE_ID=17
    monkeypatch.setattr(settlement_policy,'get_settings',lambda:c.app.settings)
    metadata=MetaData()
    for model in (SettlementItem,ShipmentOutbound,SettlementEvent):
        Table(model.__tablename__,metadata,*(Column(col.name,col.type,primary_key=col.primary_key,
            nullable=False if col.primary_key else True) for col in model.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        for columns,name in [('request_key','uq_owned_shipment_key'),('invoice_id,sequence','uq_owned_shipment_sequence')]:
            if not connection.execute(text('SHOW INDEX FROM ark_shipment_settlements WHERE Key_name= :name'),{'name':name}).first():
                connection.execute(text('ALTER TABLE ark_shipment_settlements ADD UNIQUE KEY '+name+'('+columns+')'))
    with Session(c.ctx.engine) as db:
        for code in ('shipment:write','shipment:read'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':');permission=ArkPermission(code=code,module=module,action=action,
                    label=code,kind='action',is_legacy=False,sort=1);db.add(permission);db.flush()
            role=ArkRole(name='shipment-owned-'+uuid4().hex,label=code);db.add(role);db.flush()
            db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id));c.roles[code]=role.id
        invoice=db.get(Invoice,c.invoice_id);invoice.order_type='presale';invoice.shipping_fee=0
        invoice.internal_accessory=0;invoice.product_amount=100;invoice.total_amount=110;invoice.surcharge_amount=10
        items=db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id)).all()
        assert len(items)==1
        item=items[0];item.product_id=1;item.sku_id=2;item.xiaoman_unique_id='101';item.quantity=10
        item.total_price=100;item.price_per_piece=10;c.item_id=item.id
        for receipt in db.scalars(select(Receipt).where(Receipt.invoice_id==invoice.id)):receipt.status='voided'
        deposit=db.get(Receipt,c.receipts['victim']);deposit.status='active';deposit.purpose='presale_deposit'
        c.deposit_remote_id=str(500000000+deposit.id)
        deposit.amount=40;deposit.bank_charge=4;deposit.xiaoman_receipt_id=c.deposit_remote_id;deposit.collect_status=1
        deposit.sync_status='synced';deposit.xiaoman_order_id=invoice.xiaoman_order_id
        foreign=db.get(Invoice,c.foreign_invoice_id);foreign.order_type='presale';foreign.shipping_fee=0
        db.commit()
    c.shipment_roles=[c.roles['invoice:write'],c.roles['shipment:write'],c.roles['write']]
    def snapshot(db,target):
        c.io.append(('shipment-balance',target.id))
        return {'invoice_binding':remote.invoice_binding(target),'exchange_rate':725,
            'rows':[{'cash_collection_id':c.deposit_remote_id,'amount':'36.00','currency':'USD','collect_status':1}]}
    def read(db,path,params=None):
        c.io.append(('shipment-order',path));return {'order_id':str(params['order_id']),'amount':'100.00','status':1}
    monkeypatch.setattr(remote,'order_snapshot',snapshot);monkeypatch.setattr(remote,'read',read)
    monkeypatch.setattr(remote,'order_active',lambda *_:True)
    monkeypatch.setattr(linked_outbound_service,'find_related',lambda *_:[])
    return c


def body_for(client,c,headers,*,payment=True,quantity=4,freight='20.00'):
    draft={'items':[{'invoice_item_id':c.item_id,'quantity':quantity}],'freight_amount':freight}
    response=client.post(f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=headers,json=draft)
    assert response.status_code==200,response.text
    result={**draft,'quote_hash':response.json()['data']['quote_hash'],'request_key':uuid4().hex}
    if payment:result['payment']={'amount':'32.00','bank_charge':'0','collection_date':'2026-10-06',
        'payment_type':'T/T','attachment_ids':[c.proofs['unbound']],'remark':'Embedded shipment payment'}
    return result


def path(c):return f'/api/invoices/{c.invoice_id}/shipment-settlements'


def snapshot(c):
    with Session(c.ctx.engine) as db:
        additional=tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all())
            for model in (SettlementItem,ShipmentOutbound,SettlementEvent))
    return financial_snapshot(c)+additional


def authorize(client,c,root):change_user(client,c,root,{'role_ids':c.shipment_roles})


def created(c,body,response):
    assert response.status_code==200,response.text
    result=response.json()['data']
    assert result['request_key']==body['request_key'] and result['quote_hash']==body['quote_hash']
    identity=result['id']
    with Session(c.ctx.engine) as db:
        settlement=db.get(ShipmentSettlement,identity)
        assert settlement.request_key==body['request_key'] and settlement.created_by==c.ctx.actor
        assert settlement.invoice_id==c.invoice_id and settlement.sequence==1
        assert db.query(ShipmentSettlement).filter_by(request_key=body['request_key']).count()==1
        assert db.query(SettlementEvent).filter_by(settlement_id=identity,action='created').count()==1
        items=db.scalars(select(SettlementItem).where(SettlementItem.settlement_id==identity)).all()
        assert len(items)==1 and items[0].quantity==body['items'][0]['quantity'] and items[0].invoice_item_id==c.item_id
        batch=db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key==body['request_key']))
        if 'payment' in body:
            assert batch is not None and batch.created_by==c.ctx.actor and batch.gross_amount==Decimal(body['payment']['amount'])
            children=db.scalars(select(Receipt).where(Receipt.batch_id==batch.id)).all()
            assert {r.purpose:(r.amount,r.bank_charge) for r in children}=={'presale_goods':(Decimal('22'),Decimal('2')),'freight':(Decimal('10'),Decimal('0'))}
            assert all(r.sync_status=='waiting_target' and r.invoice_id==c.invoice_id for r in children)
            apps=db.scalars(select(SettlementApplication).where(SettlementApplication.receipt_id.in_([r.id for r in children]))).all()
            assert len(apps)==2 and all(a.settlement_id==identity for a in apps)
            assert db.query(BatchAttachment).filter_by(batch_id=batch.id).count()==1
            assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([r.id for r in children]),ReceiptLog.action=='created').count()==2
            assert settlement.state=='awaiting_payment' and settlement.version==2 and batch.bank_charge_total==2
        else:assert batch is None and settlement.version==1
    assert c.calls==[]
    return identity


@pytest.mark.parametrize('revoke',['disabled','roles','invoice:write','shipment:write','receipt:write'])
def test_current_revocation_before_create_is_zero_write(shipment_app,revoke):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles'
            else {'role_ids':[identity for identity in c.shipment_roles if identity!=c.roles['write' if revoke=='receipt:write' else revoke]]})
        before=snapshot(c);c.io.clear()
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==403,response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':c.shipment_roles})
        created(c,body,client.post(path(c),headers=owner,json=body))


def test_new_current_grants_work_with_old_identity_token(shipment_app):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name)
        authorize(client,c,root);fresh=login(client,c,c.owner_name);body=body_for(client,c,fresh)
        created(c,body,client.post(path(c),headers=owner,json=body))


@pytest.mark.parametrize('embedded',[False,True])
def test_original_create_replay_after_later_legitimate_payment(shipment_app,embedded,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner,payment=embedded)
        c.settlement_id=created(c,body,client.post(path(c),headers=owner,json=body))
        extra=presale_payload(client,c,owner,'16');extra['attachment_ids']=[separate_proof(c)]
        later=client.post('/api/receipts/batches',headers=owner,json=extra)
        assert later.status_code==200,later.text
        before=snapshot(c);c.io.clear()
        def forbidden(*args):raise AssertionError('Original replay must not perform storage evidence IO')
        monkeypatch.setattr(attachments,'verify_storage',forbidden)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200 and response.json()['data']['id']==c.settlement_id,response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('state',['feature_off','not_ready','missing_file','paused'])
def test_original_replay_before_new_creation_guards(shipment_app,state,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner);identity=created(c,body,client.post(path(c),headers=owner,json=body))
        if state=='feature_off':c.app.settings.PRESALE_SETTLEMENT_ENABLED=False
        elif state=='missing_file':
            with Session(c.ctx.engine) as db:attachments.path_for(db.get(ReceiptAttachment,c.proofs['unbound'])).unlink()
        else:
            with Session(c.ctx.engine) as db:
                if state=='not_ready':db.get(Invoice,c.invoice_id).sync_status='failed'
                else:db.get(ShipmentSettlement,identity).state='paused'
                db.commit()
        def forbidden(*args):raise AssertionError('Original replay must not perform new evidence IO')
        monkeypatch.setattr(attachments,'verify_storage',forbidden)
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200 and response.json()['data']['id']==identity,response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('change',['body','actor','missing_target','wrong_target','wrong_component','missing_application','wrong_batch','wrong_item'])
def test_replay_actual_original_graph_rejects_without_repair(shipment_app,change):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner);identity=created(c,body,client.post(path(c),headers=owner,json=body))
        if change=='body':body['payment']['remark']='Different payment'
        else:
            with Session(c.ctx.engine) as db:
                settlement=db.get(ShipmentSettlement,identity)
                batch=db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key==body['request_key']))
                row=db.scalar(select(Receipt).where(Receipt.batch_id==batch.id,Receipt.purpose=='presale_goods'))
                app=db.scalar(select(SettlementApplication).where(SettlementApplication.receipt_id==row.id))
                if change=='actor':settlement.created_by=c.other_id
                elif change=='missing_target':db.delete(db.get(Receivable,row.receivable_id))
                elif change=='wrong_target':db.get(Receivable,row.receivable_id).invoice_id=c.second_invoice_id
                elif change=='wrong_component':app.component='freight'
                elif change=='missing_application':db.delete(app)
                elif change=='wrong_batch':batch.created_by=c.other_id
                else:db.scalar(select(SettlementItem).where(SettlementItem.settlement_id==identity)).invoice_item_id=999999
                db.commit()
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==409,response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('role',['all','super_admin'])
def test_actual_scope_revocation_before_any_evidence(shipment_app,role):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:role_id=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id if role=='super_admin' else c.roles['all']
        change_user(client,c,root,{'role_ids':c.shipment_roles+[role_id]});owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner)
        with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
        change_user(client,c,root,{'role_ids':c.shipment_roles+[c.roles['invoice:read_all']]})
        before=snapshot(c);c.io.clear();response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==404,response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('change',['disabled','write','owner'])
def test_unlocked_evidence_allows_admin_then_current_rejects(shipment_app,enabled,change,monkeypatch):
    c=shipment_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    ready=threading.Event();resume=threading.Event();original=attachments.verify_storage
    def gate(*args):ready.set();assert resume.wait(10);return original(*args)
    monkeypatch.setattr(attachments,'verify_storage',gate)
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,path(c),headers=owner,json=body)
            try:
                assert ready.wait(5) and not action.done()
                if change=='owner':
                    with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
                else:change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[c.roles['read']]})
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        assert response.status_code==(404 if change=='owner' else 403),response.text
        assert snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['invoice','item','receipt','intent','proof','allocation','late_log','settlement','target'])
def test_complete_graph_changed_during_evidence_cannot_create(shipment_app,change,monkeypatch):
    c=shipment_app;ready=threading.Event();resume=threading.Event();original=remote.order_snapshot
    def gate(*args):ready.set();assert resume.wait(10);return original(*args)
    monkeypatch.setattr(remote,'order_snapshot',gate)
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        # Quote first without the create gate.
        monkeypatch.setattr(remote,'order_snapshot',original);body=body_for(client,c,owner);monkeypatch.setattr(remote,'order_snapshot',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,path(c),headers=owner,json=body)
            try:
                assert ready.wait(5) and not action.done()
                with Session(c.ctx.engine) as db:
                    if change=='invoice':db.get(Invoice,c.invoice_id).remark='Changed commercial note'
                    elif change=='item':db.get(InvoiceItem,c.item_id).total_price=101
                    elif change=='receipt':db.get(Receipt,c.receipts['victim']).amount=41
                    elif change=='intent':
                        row=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                        row.eligible=1;row.status='armed';row.attachment_ids=body['payment']['attachment_ids']
                    elif change=='proof':db.get(ReceiptAttachment,c.proofs['unbound']).sha256='a'*64
                    elif change=='allocation':db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                    elif change=='late_log':db.add(ReceiptLog(receipt_id=c.receipts['victim'],action='late_result',message='Existing sender fact'))
                    elif change=='settlement':db.add(ShipmentSettlement(invoice_id=c.invoice_id,sequence=1,settlement_no=uuid4().hex,
                        quote={},is_final=0,state='paused',version=1,request_key=uuid4().hex,request_hash='a'*64,quote_hash='b'*64,created_by=c.ctx.actor))
                    else:
                        invoice=db.get(Invoice,c.invoice_id)
                        db.add(Receivable(invoice_id=invoice.id,business_key=f'invoice:{invoice.id}:goods',kind='goods',currency=invoice.currency,
                            customer_id=invoice.customer_id,amount=invoice.total_amount,handling_amount=invoice.surcharge_amount,
                            remote_order_id=invoice.xiaoman_order_id,remote_status='bound'))
                    db.commit()
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        assert response.status_code==409,response.text
        assert snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('stage',[1,2,3])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_exact_three_commit_faults_and_original_key_recovery(shipment_app,stage,timing,monkeypatch):
    c=shipment_app;sessions=[];hits=[];authorize_original=shipment_create_service._authorize;original_snapshot=remote.order_snapshot
    metadata=MetaData();token=Table('owned_shipment_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(24)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:connection.execute(token.delete());connection.execute(token.insert().values(id=1,value='original'))
    def authorization(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return authorize_original(db,*args)
    def refresh(db,target):
        db.execute(token.update().where(token.c.id==1).values(value='refreshed'));return original_snapshot(db,target)
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);body=body_for(client,c,owner);before=snapshot(c)
        monkeypatch.setattr(shipment_create_service,'_authorize',authorization);monkeypatch.setattr(remote,'order_snapshot',refresh)
        def fail(db):
            if any(db is item for item in sessions):
                count=db.info.get('owned_shipment_commit',0)+1;db.info['owned_shipment_commit']=count
                if count==stage:hits.append((id(db),stage));raise OperationalError('private-database',{},Exception('private-ack'))
        event.listen(Session,timing,fail)
        try:response=client.post(path(c),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[(id(sessions[0]),stage)]
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store' and 'private-' not in response.text,response.text
        committed=stage==3 and timing=='after_commit'
        with c.ctx.engine.connect() as connection:
            assert connection.scalar(select(token.c.value))==('refreshed' if stage==3 or stage==2 and timing=='after_commit' else 'original')
        with Session(c.ctx.engine) as db:assert db.query(ShipmentSettlement).filter_by(request_key=body['request_key']).count()==int(committed)
        if not committed:assert snapshot(c)==before
        else:created(c,body,client.post(path(c),headers=owner,json=body))
        monkeypatch.setattr(remote,'order_snapshot',original_snapshot)
        identity=created(c,body,client.post(path(c),headers=owner,json=body));current=snapshot(c);c.io.clear()
        replay=client.post(path(c),headers=owner,json=body)
        assert replay.status_code==200 and replay.json()['data']['id']==identity and snapshot(c)==current and c.io==[]


@pytest.mark.parametrize('same_key',[True,False])
def test_two_captures_make_only_one_active_settlement_and_payment(shipment_app,same_key,monkeypatch):
    c=shipment_app;barrier=threading.Barrier(2);original=shipment_create_service._evidence;hits=[];guard=threading.Lock()
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name);first=body_for(client,c,owner);second=deepcopy(first)
        if not same_key:second['request_key']=uuid4().hex;second['payment']['attachment_ids']=[separate_proof(c)]
        def together(*args):
            with guard:hits.append(threading.get_ident())
            barrier.wait(timeout=10);return original(*args)
        monkeypatch.setattr(shipment_create_service,'_evidence',together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(client.post,path(c),headers=owner,json=body) for body in (first,second)]
            responses=[future.result(timeout=20) for future in futures]
        assert len(hits)==2
        assert sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409]),[r.text for r in responses]
        identity=next(r.json()['data']['id'] for r in responses if r.status_code==200)
        if same_key:assert {r.json()['data']['id'] for r in responses}=={identity}
        with Session(c.ctx.engine) as db:
            assert db.query(ShipmentSettlement).filter_by(invoice_id=c.invoice_id).count()==1
            batch=db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key.in_([first['request_key'],second['request_key']])))
            assert db.query(ReceiptBatch).filter(ReceiptBatch.request_key.in_([first['request_key'],second['request_key']])).count()==1
            assert db.query(Receipt).filter_by(batch_id=batch.id).count()==2
            assert db.query(SettlementApplication).filter_by(settlement_id=identity).count()==2
            assert db.query(SettlementEvent).filter_by(settlement_id=identity,action='created').count()==1
        assert c.calls==[]


def historical_shipment(client,c,owner,monkeypatch):
    # Build the original partial settlement through the actual creation endpoint.
    original=body_for(client,c,owner);original['payment']['amount']='64.00'
    response=client.post(path(c),headers=owner,json=original)
    assert response.status_code==200,response.text
    identity=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        row=db.get(ShipmentSettlement,identity);row.state='shipped'
        batch=db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key==original['request_key']))
        children=db.scalars(select(Receipt).where(Receipt.batch_id==batch.id)).all()
        assert {r.purpose:r.amount for r in children}=={'presale_goods':Decimal('44'),'freight':Decimal('20')}
        goods=next(r for r in children if r.purpose=='presale_goods')
        freight_receipt=next(r for r in children if r.purpose=='freight')
        c.history_goods_remote_id=str(500000000+goods.id);c.history_freight_remote_id=str(500000000+freight_receipt.id)
        goods.xiaoman_receipt_id=c.history_goods_remote_id;freight_receipt.xiaoman_receipt_id=c.history_freight_remote_id
        for child in children:child.sync_status='synced';child.collect_status=1;child.last_error=None
        for app in db.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id==identity)):app.status='applied'
        target=db.scalar(select(Receivable).where(Receivable.settlement_id==identity,Receivable.kind=='freight'))
        target.remote_order_id='90001';target.remote_order_name='HISTORY-F';target.remote_status='bound'
        freight_receipt.xiaoman_order_id=target.remote_order_id
        record={'order_id':str(db.get(Invoice,c.invoice_id).xiaoman_order_id),'order_record_id':'101','outbound_count':4}
        db.add(ShipmentOutbound(settlement_id=identity,invoice_id=c.invoice_id,outbound_no='OUT-'+uuid4().hex,
            status='shipped',remote_id='91001',payload={'record_list':[record]},payload_hash='a'*64))
        db.commit()
    provider={'fault':None}
    def receipt_snapshot(db,target):
        c.io.append(('history-balance',target.id))
        return {'invoice_binding':remote.invoice_binding(target),'exchange_rate':725,'rows':[
            {'cash_collection_id':c.deposit_remote_id,'amount':'36.00','currency':'USD','collect_status':1},
            {'cash_collection_id':c.history_goods_remote_id,'amount':'40.00','currency':'USD','collect_status':1}]}
    def detail():
        line=deepcopy(record);fault=provider['fault']
        if fault=='count_null':line['outbound_count']=None
        elif fault=='count_bool':line['outbound_count']=True
        elif fault=='count_text':line['outbound_count']='not-a-quantity'
        elif fault=='count_nonfinite':line['outbound_count']='NaN'
        elif fault=='count_fraction':line['outbound_count']='4.5'
        elif fault=='uid_missing':line.pop('order_record_id')
        elif fault=='uid_unicode':line['order_record_id']='１０１'
        elif fault=='different_quantity':line['outbound_count']=5
        return {'outbound_invoice_id':'91001','status':2,'record_list':[line,line] if fault=='duplicate_line' else [line]}
    def provider_read(db,route,params=None):
        c.io.append(('history-provider',route))
        if route=='/v1/invoices/outbound/list':return {'list':[{'outbound_invoice_id':'91001'}],'count':1}
        if route=='/v1/invoices/order/info':
            if str(params['order_id'])=='90001':
                if provider['fault']=='freight_none':return None
                if provider['fault']=='freight_list':return []
                return {'order_id':'90001','name':'HISTORY-F','company_id':c.customer_id,'currency':'USD',
                    'amount':'20.00','product_total_amount':0,'product_list':[],'exchange_rate':725}
            return {'order_id':record['order_id'],'amount':'100.00','create_time':'2026-10-01 08:00:00'}
        raise AssertionError('Unexpected synthetic provider endpoint')
    with Session(c.ctx.engine) as db:c.customer_id=db.get(Invoice,c.invoice_id).customer_id
    monkeypatch.setattr(remote,'order_snapshot',receipt_snapshot)
    monkeypatch.setattr(remote,'read',provider_read)
    monkeypatch.setattr(remote,'order_receipts',lambda *_:[{'cash_collection_id':c.history_freight_remote_id,'amount':'20.00','currency':'USD','collect_status':1}])
    monkeypatch.setattr(linked_outbound_service,'find_related',ACTUAL_FIND_RELATED)
    from app.invoice import okki_client
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *_args,**_kwargs:'synthetic-token')
    monkeypatch.setattr(okki_client,'_get_json',lambda *_args,**_kwargs:detail())
    next_body=body_for(client,c,owner,payment=False,quantity=2,freight='0')
    return provider,next_body


@pytest.mark.parametrize('fault',['count_null','count_bool','count_text','count_nonfinite','count_fraction',
    'uid_missing','uid_unicode','duplicate_line','freight_none','freight_list'])
def test_actual_history_readers_bad_technical_shapes_are_503(shipment_app,fault,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        provider,body=historical_shipment(client,c,owner,monkeypatch);provider['fault']=fault
        before=snapshot(c);response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('fault',[None,'different_quantity'])
def test_history_reader_valid_exact_and_real_quantity_difference(shipment_app,fault,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        provider,body=historical_shipment(client,c,owner,monkeypatch);provider['fault']=fault;before=snapshot(c)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(409 if fault else 200),response.text
        if fault:assert snapshot(c)==before
        else:
            with Session(c.ctx.engine) as db:
                row=db.get(ShipmentSettlement,response.json()['data']['id'])
                assert row.sequence==2 and row.quote['goods_amount']=='20.00' and row.quote['handling_amount']=='2.00'
        assert c.calls==[]
