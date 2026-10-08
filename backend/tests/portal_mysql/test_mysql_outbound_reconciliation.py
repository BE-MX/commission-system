"""Actual current-authorized outbound reconciliation on owned main/JWT/MySQL."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.core.time import beijing_now
from app.invoice import shipment_delivery, settlement_service, outbound_reconciliation_service
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, SettlementEvent, Receivable, ReceiptBatch, SettlementApplication
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import Receipt
from decimal import Decimal
from fastapi import HTTPException
from app.receipt import remote
from test_mysql_shipment_retry import prepare as retry_prepare
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user, authorize, body_for, created, path  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

MODES=('bind','refresh')

def route(c):return f'/api/shipments/{c.settlement_id}/reconcile-outbound'

def prepare(c,client,mode,monkeypatch,*,full=False):
    if not full:root,_,body=retry_prepare(c,client,'outbound',monkeypatch)
    else:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        original=body_for(client,c,owner,payment=False)
        original['payment']={'amount':'64.00','bank_charge':'0','collection_date':'2026-10-06',
            'payment_type':'T/T','attachment_ids':[c.proofs['unbound']],'remark':'Complete actual funding'}
        response=client.post(path(c),headers=owner,json=original)
        assert response.status_code==200,response.text
        result=response.json()['data'];c.settlement_id=result['id']
        assert result['request_key']==original['request_key'] and result['quote_hash']==original['quote_hash']
        with Session(c.ctx.engine) as db:
            batch=db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key==original['request_key']))
            assert batch is not None and batch.gross_amount==Decimal('64') and batch.created_by==c.ctx.actor
            children=db.scalars(select(Receipt).where(Receipt.batch_id==batch.id)).all()
            assert {r.purpose:(r.amount,r.bank_charge) for r in children}=={'presale_goods':(Decimal('44'),Decimal('4')),'freight':(Decimal('20'),Decimal('0'))}
        with Session(c.ctx.engine) as db:
            row=db.get(ShipmentSettlement,c.settlement_id);row.state='review_required'
            payload={'serial_id':row.settlement_no,'record_list':[{'order_id':int(db.get(Invoice,c.invoice_id).xiaoman_order_id),
                'order_record_id':101,'product_id':1,'sku_id':2,'outbound_count':4}]}
            target=ShipmentOutbound(settlement_id=row.id,invoice_id=c.invoice_id,outbound_no=row.settlement_no,
                status='failed',payload=payload,payload_hash=settlement_service.digest(payload),version=1)
            db.add(target);db.flush();c.target_id=target.id
            body={'version':row.version,'reason':'Reconcile original outbound with actual complete funding'};db.commit()
    with Session(c.ctx.engine) as db:
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='shipment:admin'))
        if permission is None:
            permission=ArkPermission(code='shipment:admin',module='shipment',action='admin',label='shipment:admin',kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='outbound-admin-'+uuid4().hex,label='Outbound admin');db.add(role);db.flush()
        db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id));c.roles['shipment:admin']=role.id
        target=db.get(ShipmentOutbound,c.target_id);target.status='uncertain'
        target.attempt_token='original-'+str(target.id);target.lease_until=beijing_now()-timedelta(hours=1)
        target.last_error='Original outbound unknown result'
        if mode=='refresh':target.remote_id='401'
        c.detail={'outbound_invoice_id':'401','serial_id':target.outbound_no,'status':1,
            'create_time':'2026-10-06 08:00:00','record_list':deepcopy(target.payload['record_list'])}
        c.detail['record_list'][0].update(outbound_record_id='501',cost_unit_price_rmb='12.50')
        db.commit()
    c.grants=c.shipment_roles+([c.roles['shipment:admin']] if mode=='bind' else [])
    change_user(client,c,root,{'role_ids':c.grants});owner=login(client,c,c.owner_name)
    if mode=='bind':body['remote_id']='401'
    c.reads=[]
    def read(db,path,params=None):c.reads.append((path,deepcopy(params)));return deepcopy(c.detail)
    monkeypatch.setattr(remote,'read',read)
    monkeypatch.setattr(shipment_delivery.okki_client,'ensure_access_token',lambda *_args,**_kwargs:'synthetic-token')
    monkeypatch.setattr(shipment_delivery.outbound_presence,'is_active',lambda *_:True)
    c.io.clear();return root,owner,body

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('revoke',['disabled','roles','shipment:write'])
def test_outbound_reconcile_current_revocation_before_read(state_app,mode,revoke,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch)
        update={'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['shipment:admin']]}
        change_user(client,c,root,update);before=snapshot(c)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==403,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.reads==[] and c.calls==[]

@pytest.mark.parametrize('mode',MODES)
def test_outbound_reconcile_current_grant_to_old_empty_token(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,_,body=prepare(c,client,mode,monkeypatch)
        change_user(client,c,root,{'role_ids':[]});old=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write']]+([c.roles['shipment:admin']] if mode=='bind' else [])})
        response=client.post(route(c),headers=old,json=body)
        assert response.status_code==200,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        with Session(c.ctx.engine) as db:
            target=db.get(ShipmentOutbound,c.target_id)
            assert target.status=='pending_remote' and target.remote_id=='401'
            assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id,action='reconcile_outbound',actor_id=c.ctx.actor,reason=body['reason']).count()==1
        assert c.calls==[]


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('change',['disabled','write','owner','invoice','item','receipt','target','settlement'])
def test_final_current_graph_after_unlocked_outbound_read(state_app,mode,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch);baselines=[]
        def read(db,path,params=None):
            with Session(c.ctx.engine) as other:
                invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                assert invoice.id==c.invoice_id
                if change=='owner':invoice.sales_user_id=c.other_id
                elif change=='invoice':invoice.customer_name='Concurrent outbound change'
                elif change=='item':other.get(InvoiceItem,c.item_id).quantity+=1
                elif change=='receipt':other.get(Receipt,c.receipts['victim']).bank_charge+=1
                elif change=='target':other.get(ShipmentOutbound,c.target_id).version+=1
                elif change=='settlement':other.get(ShipmentSettlement,c.settlement_id).version+=1
                other.commit()
            if change in {'disabled','write'}:
                change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[c.roles['shipment:admin']]})
            baselines.append(snapshot(c));c.reads.append((path,deepcopy(params)));return deepcopy(c.detail)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(403 if change in {'disabled','write'} else 404 if change=='owner' else 409),response.text
        assert len(c.reads)==1 and snapshot(c)==baselines[0] and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('difference',['inactive','serial','identity','count','order','product','sku','baseline_id','baseline_cost'])
def test_manual_mismatch_vs_known_original_quarantine(state_app,mode,difference,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:
            db.get(ShipmentOutbound,c.target_id).remote_line_snapshot={'101':{'outbound_record_id':'501','cost_unit_price_rmb':'12.50'}};db.commit()
        before=snapshot(c)
        if difference=='inactive':monkeypatch.setattr(shipment_delivery.outbound_presence,'is_active',lambda *_:False)
        elif difference in {'serial','identity'}:c.detail['serial_id' if difference=='serial' else 'outbound_invoice_id']='OTHER' if difference=='serial' else '402'
        else:
            key,value={'count':('outbound_count',5),'order':('order_id',123),'product':('product_id',3),'sku':('sku_id',4),
                'baseline_id':('outbound_record_id','502'),'baseline_cost':('cost_unit_price_rmb','12.51')}[difference]
            c.detail['record_list'][0][key]=value
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(409 if mode=='bind' else 200),response.text
        if mode=='bind':assert snapshot(c)==before
        else:
            with Session(c.ctx.engine) as db:
                target=db.get(ShipmentOutbound,c.target_id);row=db.get(ShipmentSettlement,c.settlement_id)
                assert target.status=='uncertain' and target.remote_id=='401' and row.state=='outbound_uncertain'
            outbound_delta(c,before,body,status='uncertain')
        assert c.calls==[]

def outbound_delta(c,before,body,*,status='pending_remote',receipt_data=None):
    expected=[[deepcopy(dict(row._mapping)) for row in table] for table in before]
    actual=[[deepcopy(dict(row._mapping)) for row in table] for table in snapshot(c)]
    assert len(expected)==len(actual)==21
    target=next(row for row in expected[19] if row['id']==c.target_id)
    current=next(row for row in actual[19] if row['id']==c.target_id)
    if body.get('remote_id'):target['remote_id']=body['remote_id']
    target['version']+=2 if body.get('remote_id') else 1;target['status']=status
    target['last_error']={'pending_remote':None,'shipped':None,'uncertain':'小满分批出库身份或数量与冻结任务不一致，请核对原单',
        'shipped_unfunded':'小满已实际出库，但关联回款未通过实时核验，请立即核查'}[status]
    if status!='uncertain':
        assert current['verified_at'] is not None;target['verified_at']=current['verified_at']
    if status=='pending_remote' and target['remote_line_snapshot'] is None:
        target['remote_line_snapshot']={'101':{'outbound_record_id':'501','cost_unit_price_rmb':'12.50'}}
    row=next(row for row in expected[17] if row['id']==c.settlement_id)
    updated=next(row for row in actual[17] if row['id']==c.settlement_id)
    row['version']+=2 if body.get('remote_id') else 1
    row['state']='outbound_pending' if status=='pending_remote' else 'shipped' if status=='shipped' else 'outbound_uncertain'
    assert updated['updated_at'] is not None;row['updated_at']=updated['updated_at']
    old_ids={row['id'] for row in expected[20]};added=[row for row in actual[20] if row['id'] not in old_ids]
    assert len(added)==1
    entry=added[0];assert (entry['settlement_id'],entry['action'],entry['actor_id'],entry['reason'])==(c.settlement_id,'reconcile_outbound',c.ctx.actor,body['reason'])
    expected[20].append(entry);expected[20].sort(key=lambda row:row['id'])
    if receipt_data is not None:
        tables=[i for i,table in enumerate(expected) if table and {'receipt_no','bank_charge','sync_status'}<=table[0].keys()]
        assert len(tables)==1;index=tables[0]
        for identity,data in receipt_data.items():
            receipt=next(row for row in expected[index] if row['id']==identity)
            updated=next(row for row in actual[index] if row['id']==identity)
            receipt.update(xiaoman_receipt_no=data['cash_collection_no'],collect_status=int(data['collect_status']),
                sync_status='synced',last_error=None,version=receipt['version']+1,synced_at=updated['synced_at'],updated_at=updated['updated_at'])
        logs=[i for i,table in enumerate(actual) if table and {'receipt_id','action','message'}<=table[0].keys() and i!=20]
        assert len(logs)==1;index=logs[0];old_ids={row['id'] for row in expected[index]}
        added=[row for row in actual[index] if row['id'] not in old_ids]
        assert {row['receipt_id'] for row in added}==set(receipt_data) and len(added)==len(receipt_data)
        assert all(row['action']=='reconciled' and row['created_by'] is None and row['message']=='已核对并绑定小满回款' for row in added)
        expected[index].extend(added);expected[index].sort(key=lambda row:row['id'])
        if status=='shipped':
            for app in expected[16]:
                if app['settlement_id']==c.settlement_id and app['status']=='reserved':app['status']='applied'
    assert expected==actual

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('fault',['list','missing_id','bool_status','unicode_id','fraction','nan','duplicate','missing_cost','missing_line','time','activity_shape','provider'])
def test_outbound_bad_evidence_does_not_write_business(state_app,mode,fault,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c)
        if fault=='list':monkeypatch.setattr(remote,'read',lambda *_:[])
        elif fault=='activity_shape':monkeypatch.setattr(shipment_delivery.outbound_presence,'is_active',lambda *_:None)
        elif fault=='provider':
            def fail(*args):raise shipment_delivery.okki_client.OkkiApiError('PRIVATE_OUTBOUND_PROVIDER')
            monkeypatch.setattr(remote,'read',fail)
        elif fault=='missing_id':c.detail.pop('outbound_invoice_id')
        elif fault=='bool_status':c.detail['status']=True
        elif fault=='unicode_id':c.detail['record_list'][0]['sku_id']='２'
        elif fault=='fraction':c.detail['record_list'][0]['outbound_count']='4.5'
        elif fault=='nan':c.detail['record_list'][0]['cost_unit_price_rmb']='NaN'
        elif fault=='duplicate':c.detail['record_list'].append(deepcopy(c.detail['record_list'][0]))
        elif fault=='missing_cost':c.detail['record_list'][0].pop('cost_unit_price_rmb')
        elif fault=='missing_line':c.detail['record_list'][0].pop('outbound_record_id')
        elif fault=='time':c.detail['create_time']='invalid'
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert 'PRIVATE_' not in response.text and snapshot(c)==before and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'

def funded_prepare(c,client,mode,monkeypatch):
    root,owner,body=prepare(c,client,mode,monkeypatch,full=True);c.receipt_data={};c.list_rows={};c.order_details={}
    with Session(c.ctx.engine) as db:
        target=db.get(ShipmentOutbound,c.target_id)
        target.remote_line_snapshot={'101':{'outbound_record_id':'501','cost_unit_price_rmb':'12.50'}}
        freight=db.scalar(select(Receivable).where(Receivable.settlement_id==c.settlement_id,Receivable.kind=='freight'))
        freight.remote_status='bound';c.freight_id=str(900000+freight.id);freight.remote_order_id=c.freight_id
        invoice=db.get(Invoice,c.invoice_id)
        goods_id=invoice.xiaoman_order_id
        c.order_details[goods_id]={'order_id':goods_id,'company_id':invoice.customer_id,'currency':invoice.currency,
            'amount':str(invoice.total_amount-invoice.surcharge_amount),'create_time':'2026-10-06 08:00:00'}
        c.order_details[c.freight_id]={'order_id':c.freight_id,'company_id':freight.customer_id,'currency':freight.currency,
            'amount':str(freight.amount),'name':freight.remote_order_name,'product_total_amount':'0.00','product_list':[],
            'create_time':'2026-10-06 08:00:00'}
        children=db.scalars(select(Receipt).join(SettlementApplication,SettlementApplication.receipt_id==Receipt.id)
            .where(SettlementApplication.settlement_id==c.settlement_id)).all()
        assert {r.purpose:r.amount for r in children}=={'presale_goods':Decimal('44'),'freight':Decimal('20')}
        for index,receipt in enumerate(children):
            receipt.xiaoman_receipt_id=str(800000+receipt.id);receipt.xiaoman_order_id=c.freight_id if receipt.purpose=='freight' else goods_id
            receipt.sync_status='uncertain';receipt.collect_status=0;receipt.last_error='Original accepted result needs verification'
            value=str(receipt.amount-receipt.bank_charge)
            data={'cash_collection_id':receipt.xiaoman_receipt_id,'cash_collection_no':'REMOTE-'+receipt.xiaoman_receipt_id,
                'order_id':receipt.xiaoman_order_id,'currency':receipt.currency,'amount':value,'real_amount':value,
                'bank_charge':'0.00','collect_status':1,'collection_date':receipt.collection_date.isoformat()}
            c.receipt_data[receipt.id]=data;c.list_rows.setdefault(receipt.xiaoman_order_id,[]).append(deepcopy(data))
        deposit=db.get(Receipt,c.receipts['victim'])
        c.list_rows[goods_id].append({'cash_collection_id':deposit.xiaoman_receipt_id,'order_id':goods_id,
            'currency':deposit.currency,'amount':str(deposit.amount-deposit.bank_charge),'collect_status':1,
            'collection_date':deposit.collection_date.isoformat()})
        db.commit()
    c.detail['status']=2;c.reads=[]
    def read(db,path,params=None):
        c.reads.append((path,deepcopy(params)))
        if path=='/v1/invoices/outbound/info':return deepcopy(c.detail)
        if path=='/v1/invoices/order/info':return deepcopy(c.order_details[str(params['order_id'])])
        raise AssertionError('Unexpected controlled GET')
    def receipt_info(db,identity):
        c.reads.append(('receipt',identity));return deepcopy(next(data for data in c.receipt_data.values() if data['cash_collection_id']==identity))
    def order_receipts(db,identity):c.reads.append(('list',identity));return deepcopy(c.list_rows[identity])
    monkeypatch.setattr(remote,'read',read);monkeypatch.setattr(remote,'receipt_info',receipt_info)
    monkeypatch.setattr(remote,'order_receipts',order_receipts)
    return root,owner,body

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('funds',['effective','pending','missing','unallocated'])
def test_status_two_uses_actual_funding_and_receipt_algorithms(state_app,mode,funds,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=funded_prepare(c,client,mode,monkeypatch)
        if funds=='pending':
            next(iter(c.list_rows[c.freight_id]))['collect_status']=0
        elif funds=='missing':c.list_rows[c.freight_id]=[]
        elif funds=='unallocated':
            goods=next(key for key in c.list_rows if key!=c.freight_id)
            c.list_rows[goods].append({'cash_collection_id':'99999','order_id':goods,'currency':'USD','amount':'1.00',
                'collect_status':1,'collection_date':'2026-10-06'})
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        outbound_delta(c,before,body,status='shipped' if funds=='effective' else 'shipped_unfunded',receipt_data=c.receipt_data)
        assert c.calls==[] and len(c.reads)==7

@pytest.mark.parametrize('phase',['receipt','main','freight','list'])
@pytest.mark.parametrize('change',['disabled','funding'])
def test_status_two_final_auth_precedes_any_receipt_mutation(state_app,phase,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=funded_prepare(c,client,'refresh',monkeypatch);baselines=[]
        original_read=remote.read;original_receipt=remote.receipt_info;original_list=remote.order_receipts
        def mutate():
            if baselines:return
            with Session(c.ctx.engine) as db:
                assert db.scalar(select(Invoice.id).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))==c.invoice_id
                if change=='funding':db.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                db.commit()
            if change=='disabled':change_user(client,c,root,{'is_active':False})
            baselines.append(snapshot(c))
        def read(db,path,params=None):
            if path=='/v1/invoices/order/info' and ((phase=='main' and str(params['order_id'])!=c.freight_id) or (phase=='freight' and str(params['order_id'])==c.freight_id)):mutate()
            return original_read(db,path,params)
        def receipt(db,identity):
            if phase=='receipt':mutate()
            return original_receipt(db,identity)
        def receipts(db,identity):
            if phase=='list':mutate()
            return original_list(db,identity)
        monkeypatch.setattr(remote,'read',read);monkeypatch.setattr(remote,'receipt_info',receipt);monkeypatch.setattr(remote,'order_receipts',receipts)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(403 if change=='disabled' else 409),response.text
        assert len(baselines)==1 and snapshot(c)==baselines[0] and c.calls==[]
