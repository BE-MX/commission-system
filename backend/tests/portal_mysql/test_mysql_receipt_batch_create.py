"""Actual batch creation authority; owned main/JWT/MySQL, synthetic provider facts."""
from concurrent.futures import ThreadPoolExecutor
import threading
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import Column, MetaData, Table, select, text
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable, SettlementApplication, ShipmentSettlement, ReceiptBatch, BatchAttachment
from app.receipt import attachments, batch_create_service, fees, remote
from app.receipt.models import Receipt, ReceiptLog, ReceiptIntent, ReceiptAttachment
from app.semifinished.models import InvoiceAllocation
from app.portal import authority as portal_authority
from app.core.time import beijing_today
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401


@pytest.fixture
def batch_create_app(read_app,monkeypatch):
    c=read_app
    metadata=MetaData()
    for model in (Receivable,SettlementApplication,ShipmentSettlement):
        Table(model.__tablename__,metadata,*(Column(col.name,col.type,primary_key=col.primary_key,
            nullable=False if col.primary_key else True) for col in model.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        for table,column,name in [('ark_receipt_batches','request_key','uq_owned_batch_create_key'),
            ('ark_receipts','request_key','uq_owned_batch_receipt_key'),('ark_receivables','business_key','uq_owned_batch_target')]:
            if not connection.execute(text('SHOW INDEX FROM '+table+' WHERE Key_name= :name'),{'name':name}).first():
                connection.execute(text('ALTER TABLE '+table+' ADD UNIQUE KEY '+name+'('+column+')'))
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);invoice.surcharge_amount=Decimal('12.80')
        second=Invoice(invoice_no='PI-BATCH-'+uuid4().hex,order_type='stock',invoice_date=beijing_today(),
            customer_name=invoice.customer_name,customer_id=invoice.customer_id,sales_user_id=c.ctx.actor,
            currency='USD',total_amount=100,surcharge_amount=10,product_amount=90,shipping_fee=0,
            internal_accessory=0,status='synced',sync_status='synced',source_type='manual')
        db.add(second);db.flush();second.xiaoman_order_id=str(second.id+1000000);c.second_invoice_id=second.id
        foreign=db.get(Invoice,c.foreign_invoice_id);foreign.customer_id=invoice.customer_id;foreign.surcharge_amount=Decimal('12.80')
        db.get(Receipt,c.receipts['foreign']).customer_id=invoice.customer_id
        db.commit()
    def evidence(db,binding):
        c.io.append(('fees',binding[0]));return fees.FeeEvidence(tuple(binding),())
    monkeypatch.setattr(fees,'read_evidence',evidence)
    return c


def payload(client,c,headers,foreign=False):
    ids=[c.foreign_invoice_id if foreign else c.invoice_id,c.second_invoice_id]
    allocations=[]
    for identity in ids:
        response=client.get('/api/receipts/order-balance/'+str(identity),headers=headers)
        assert response.status_code==200,response.text
        allocations.append({'invoice_id':identity,'amount':'10','balance_version':response.json()['data']['version']})
    return {'request_key':uuid4().hex,'amount':'20','bank_charge':'0','collection_date':'2026-10-06',
        'payment_type':'T/T','remark':'Shared customer payment','attachment_ids':[c.proofs['unbound']],
        'allocations':allocations}


def financial_snapshot(c):
    with Session(c.ctx.engine) as db:
        extra=tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all())
            for model in (Receivable,SettlementApplication,ShipmentSettlement))
    return read_snapshot(c)+extra


def created(c,body,response):
    assert response.status_code==200,response.text
    identity=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        batch=db.get(ReceiptBatch,identity);assert batch.request_key==body['request_key'] and batch.created_by==c.ctx.actor
        assert batch.gross_amount==20 and batch.bank_charge_total==2 and batch.status=='active' and batch.version==1
        rows=db.scalars(select(Receipt).where(Receipt.batch_id==identity)).all()
        assert len(rows)==2 and {r.invoice_id for r in rows}=={x['invoice_id'] for x in body['allocations']}
        assert all(r.amount==10 and r.bank_charge==1 and r.status=='active' and r.sync_status=='pending' for r in rows)
        assert all(r.attachment_ids==body['attachment_ids'] and r.created_by==c.ctx.actor for r in rows)
        assert db.query(BatchAttachment).filter_by(batch_id=identity).count()==1
        assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([r.id for r in rows]),ReceiptLog.action=='created').count()==2
    assert c.calls==[]
    return identity


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_batch_create_rejects_actual_admin_revocation(batch_create_app,revoke):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);body=payload(client,c,owner)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=financial_snapshot(c);c.io.clear();response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==403,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['write']]})
        created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))


@pytest.mark.parametrize('role',['all','super_admin'])
def test_batch_create_rechecks_scope_for_every_invoice(batch_create_app,role):
    c=batch_create_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:role_id=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id if role=='super_admin' else c.roles['all']
        change_user(client,c,root,{'role_ids':[role_id]});owner=login(client,c,c.owner_name)
        body=payload(client,c,owner,True)
        change_user(client,c,root,{'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
        before=financial_snapshot(c);c.io.clear();response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==404,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


def test_batch_create_current_new_write_grant_works_with_old_token(batch_create_app):
    c=batch_create_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        change_user(client,c,root,{'role_ids':[c.roles['write']]});c.io.clear()
        created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))


@pytest.mark.parametrize('state',['ordinary','not_ready','voided','missing_file'])
def test_original_key_replay_precedes_new_evidence_guards(batch_create_app,state,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);body=payload(client,c,owner)
        identity=created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        if state=='voided':
            response=client.post('/api/receipts/batches/'+str(identity)+'/void-entry',headers=root,
                json={'version':1,'reason':'Correct original batch entry'})
            assert response.status_code==200,response.text
        elif state=='missing_file':
            with Session(c.ctx.engine) as db:attachments.path_for(db.get(ReceiptAttachment,body['attachment_ids'][0])).unlink()
        elif state=='not_ready':
            with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sync_status='failed';db.commit()
        def forbidden(*args,**kwargs):raise AssertionError('Original key must not perform evidence IO')
        monkeypatch.setattr(fees,'read_evidence',forbidden);monkeypatch.setattr(remote,'order_snapshot',forbidden)
        monkeypatch.setattr(attachments,'verify_storage',forbidden)
        before=financial_snapshot(c);c.io.clear();response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==200 and response.json()['data']['id']==identity,response.text
        assert response.json()['data']['status']==('voided' if state=='voided' else 'active')
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('change',['body','wrong_target','creator'])
def test_original_key_replay_validates_actual_target_and_body(batch_create_app,change):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        identity=created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        if change=='body':body['remark']='Different payment'
        else:
            with Session(c.ctx.engine) as db:
                if change=='creator':db.get(ReceiptBatch,identity).created_by=c.other_id
                else:db.scalar(select(Receipt).where(Receipt.batch_id==identity,Receipt.invoice_id==c.invoice_id)).invoice_id=c.second_invoice_id
                db.commit()
        before=financial_snapshot(c);c.io.clear();response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


def slow_fee(c,monkeypatch,ready,resume):
    original=fees.read_evidence;hits=[]
    def gate(*args,**kwargs):
        if not hits:
            hits.append(True);ready.set();assert resume.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(fees,'read_evidence',gate)


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('change',['disabled','write','scope'])
def test_unlocked_evidence_and_final_current_authorization(batch_create_app,enabled,change,monkeypatch):
    c=batch_create_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready=threading.Event();resume=threading.Event()
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        if change=='scope':change_user(client,c,root,{'role_ids':[c.roles['all']]})
        owner=login(client,c,c.owner_name);body=payload(client,c,owner,change=='scope')
        slow_fee(c,monkeypatch,ready,resume)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,'/api/receipts/batches',headers=owner,json=body)
            try:
                assert ready.wait(5)
                change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[c.roles['read']]} if change=='write' else {'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
                before=financial_snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        assert response.status_code==(404 if change=='scope' else 403),response.text
        assert financial_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('mutation',['owner','invoice','receipt','intent','allocation','proof_owner','proof_hash',
    'proof_batch','new_target','new_settlement','late_log'])
def test_complete_graph_changed_during_unlocked_evidence_is_rejected(batch_create_app,mutation,monkeypatch):
    c=batch_create_app;ready=threading.Event();resume=threading.Event()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner);slow_fee(c,monkeypatch,ready,resume)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,'/api/receipts/batches',headers=owner,json=body)
            try:
                assert ready.wait(5)
                with Session(c.ctx.engine) as db:
                    if mutation=='owner':db.get(Invoice,c.invoice_id).sales_user_id=c.other_id
                    elif mutation=='invoice':db.get(Invoice,c.invoice_id).total_amount=129
                    elif mutation=='receipt':db.get(Receipt,c.receipts['victim']).amount=11
                    elif mutation=='intent':
                        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                        intent.eligible=1;intent.status='armed';intent.amount=5;intent.attachment_ids=body['attachment_ids']
                    elif mutation=='allocation':db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                    elif mutation=='proof_owner':db.get(ReceiptAttachment,body['attachment_ids'][0]).created_by=c.other_id
                    elif mutation=='proof_hash':db.get(ReceiptAttachment,body['attachment_ids'][0]).sha256='a'*64
                    elif mutation=='proof_batch':db.add(BatchAttachment(batch_id=c.batch_id,attachment_id=body['attachment_ids'][0]))
                    elif mutation=='new_target':
                        inv=db.get(Invoice,c.invoice_id)
                        db.add(Receivable(invoice_id=inv.id,business_key=f'invoice:{inv.id}:goods',kind='goods',currency=inv.currency,
                            customer_id=inv.customer_id,amount=inv.total_amount,handling_amount=inv.surcharge_amount,remote_order_id=inv.xiaoman_order_id,remote_status='bound'))
                    elif mutation=='new_settlement':db.add(ShipmentSettlement(invoice_id=c.invoice_id,sequence=1,settlement_no=uuid4().hex,
                        state='awaiting_payment',is_final=0,quote={},quote_hash='a'*64,request_key=uuid4().hex,request_hash='a'*64,created_by=c.ctx.actor))
                    else:db.add(ReceiptLog(receipt_id=c.receipts['victim'],action='late_result',message='Original sender result'))
                    db.commit()
                before=financial_snapshot(c);resume.set();response=action.result(timeout=5)
            finally:resume.set()
        assert response.status_code==(404 if mutation=='owner' else 409),response.text
        assert financial_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('guard',['proof_foreign','proof_invoice','proof_receipt','proof_batch','intent'])
def test_initial_proof_and_intent_guards_precede_external_evidence(batch_create_app,guard):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        with Session(c.ctx.engine) as db:
            proof=db.get(ReceiptAttachment,body['attachment_ids'][0])
            if guard=='proof_foreign':proof.created_by=c.other_id
            elif guard=='proof_invoice':proof.invoice_id=c.invoice_id
            elif guard=='proof_receipt':proof.receipt_id=c.receipts['victim']
            elif guard=='proof_batch':db.add(BatchAttachment(batch_id=c.batch_id,attachment_id=proof.id))
            else:
                intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.foreign_invoice_id))
                intent.eligible=1;intent.status='ready';intent.attachment_ids=[proof.id]
            db.commit()
        before=financial_snapshot(c);c.io.clear();response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('fault',['index_shape','index_currency','index_negative','types','fee_ids','fee_amount','file','storage_os','provider_os'])
def test_unverifiable_evidence_keeps_entire_financial_graph(batch_create_app,fault,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        if fault.startswith('index_'):
            def bad(db,target):
                if fault=='index_shape':return {'invoice_binding':remote.invoice_binding(target),'rows':'bad'}
                row={'cash_collection_id':'123','currency':'EUR' if fault=='index_currency' else 'USD','amount':'-1' if fault=='index_negative' else '10','collect_status':1}
                return {'invoice_binding':remote.invoice_binding(target),'rows':[row]}
            monkeypatch.setattr(remote,'order_snapshot',bad)
        elif fault=='types':monkeypatch.setattr(remote,'receipt_types',lambda db:[])
        elif fault.startswith('fee_'):
            def history(db,target):
                return {'invoice_binding':remote.invoice_binding(target),'rows':[
                    {'cash_collection_id':'123','currency':'USD','amount':'1','collect_status':1}]}
            monkeypatch.setattr(remote,'order_snapshot',history)
            monkeypatch.setattr(fees,'read_evidence',lambda db,binding:fees.FeeEvidence(tuple(binding),
                (('different-id' if fault=='fee_ids' else '123',Decimal('1' if fault=='fee_ids' else '2'),Decimal('0')),)))
            for allocation in body['allocations']:
                balance=client.get('/api/receipts/order-balance/'+str(allocation['invoice_id']),headers=owner)
                assert balance.status_code==200,balance.text
                allocation['balance_version']=balance.json()['data']['version']
        elif fault=='file':
            with Session(c.ctx.engine) as db:attachments.path_for(db.get(ReceiptAttachment,body['attachment_ids'][0])).unlink()
        else:
            def fail(*args,**kwargs):raise OSError('private-provider-storage-details')
            monkeypatch.setattr(attachments if fault=='storage_os' else remote,'verify_storage' if fault=='storage_os' else 'order_snapshot',fail)
        before=financial_snapshot(c);response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert 'private-provider-storage-details' not in response.text
        assert financial_snapshot(c)==before and c.calls==[]
