"""Current-authorized exact failed shipment retries on owned JWT/main/MySQL."""
from copy import deepcopy
import pytest
from sqlalchemy import select, event
from sqlalchemy.orm import Session
from app.invoice import freight_delivery, shipment_delivery, shipment_retry_service, settlement_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import Receivable, ShipmentOutbound, ShipmentSettlement, SettlementEvent
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, body_for, path, snapshot, created, login, authorize, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

from app.receipt.models import Receipt
from app.invoice.settlement_schemas import SettlementAction
from sqlalchemy.exc import OperationalError
from app.portal.errors import TransactionBusy
from fastapi import HTTPException
ACTUAL_FREIGHT_SCAN=freight_delivery._matching_active_orders
KINDS=('freight','outbound')
def command_path(c,kind):return f'/api/shipments/{c.settlement_id}/retry-{kind}'
def prepare(c,client,kind,monkeypatch):
    root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
    original=body_for(client,c,owner,payment=False)
    c.settlement_id=created(c,original,client.post(path(c),headers=owner,json=original))
    with Session(c.ctx.engine) as db:
        row=db.get(ShipmentSettlement,c.settlement_id)
        if kind=='freight':
            target=db.scalar(select(Receivable).where(Receivable.settlement_id==row.id,Receivable.kind=='freight'))
            target.remote_status='failed';c.target_id=target.id
        else:
            payload={'serial_id':row.settlement_no,'record_list':[{'order_id':int(db.get(Invoice,c.invoice_id).xiaoman_order_id),'order_record_id':101,'product_id':1,'sku_id':2,'outbound_count':4}]}
            target=ShipmentOutbound(settlement_id=row.id,invoice_id=c.invoice_id,outbound_no=row.settlement_no,
                status='failed',payload=payload,payload_hash=settlement_service.digest(payload),version=1)
            row.state='review_required';db.add(target);db.flush();c.target_id=target.id
        body={'version':row.version,'reason':'Retry original definite failed operation'};db.commit()
    c.lookups=[]
    def freight_lookup(db,target):c.lookups.append(('freight',target.remote_order_name));return set()
    def outbound_lookup(db,serial):c.lookups.append(('outbound',serial));return None
    monkeypatch.setattr(freight_delivery,'_matching_active_orders',freight_lookup)
    monkeypatch.setattr(shipment_delivery.okki_client,'find_outbound_by_serial',outbound_lookup)
    c.io.clear();return root,owner,body

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('revoke',['disabled','roles','shipment:write'])
def test_original_retry_current_revocation_precedes_external_lookup(state_app,kind,revoke,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,kind,monkeypatch)
        update={'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['invoice:write'],c.roles['write']]}
        change_user(client,c,root,update);before=snapshot(c)
        response=client.post(command_path(c,kind),headers=owner,json=body)
        assert response.status_code==403,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.io==[] and c.lookups==[] and c.calls==[]

@pytest.mark.parametrize('kind',KINDS)
def test_original_retry_new_current_shipment_action_to_old_token(state_app,kind,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,_,body=prepare(c,client,kind,monkeypatch)
        change_user(client,c,root,{'role_ids':[]});old=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write']]})
        before=snapshot(c)
        response=client.post(command_path(c,kind),headers=old,json=body)
        assert response.status_code==200,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        with Session(c.ctx.engine) as db:
            if kind=='freight':assert db.get(Receivable,c.target_id).remote_status=='unverified'
            else:assert db.get(ShipmentOutbound,c.target_id).status=='pending' and db.get(ShipmentSettlement,c.settlement_id).state=='outbound_pending'
        assert len(c.lookups)==1 and c.calls==[]
        retry_delta(c,before,kind,body)


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('change',['disabled','roles','owner','invoice','item','receipt','target','settlement'])
def test_retry_rechecks_current_authority_and_original_graph_after_unlocked_lookup(state_app,kind,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,kind,monkeypatch);outside=[];snapshots=[]
        def lookup(db,target):
            # The reader may refresh token metadata, but holds no business locks.
            with Session(c.ctx.engine) as independent:
                invoice=independent.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                assert invoice.id==c.invoice_id
                if change=='owner':invoice.sales_user_id=c.other_id
                elif change=='invoice':invoice.customer_name='Changed during lookup'
                elif change=='item':independent.get(InvoiceItem,c.item_id).quantity+=1
                elif change=='receipt':independent.get(Receipt,c.receipts['victim']).bank_charge+=1
                elif change=='target':
                    actual=independent.get(Receivable,c.target_id) if kind=='freight' else independent.get(ShipmentOutbound,c.target_id)
                    actual.version+=1
                elif change=='settlement':independent.get(ShipmentSettlement,c.settlement_id).version+=1
                independent.commit()
            if change in {'disabled','roles'}:change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[]})
            outside.append(target);snapshots.append(snapshot(c));return set() if kind=='freight' else None
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',lookup)
        monkeypatch.setattr(shipment_delivery.okki_client,'find_outbound_by_serial',lookup)
        response=client.post(command_path(c,kind),headers=owner,json=body)
        assert response.status_code==(403 if change in {'disabled','roles'} else 404 if change=='owner' else 409),response.text
        assert len(outside)==1 and snapshot(c)==snapshots[0] and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('fault',['found','malformed','exception'])
def test_original_absence_is_required_and_lookup_failure_never_requeues(state_app,kind,fault,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,kind,monkeypatch);before=snapshot(c)
        def lookup(*args):
            if fault=='exception':raise shipment_delivery.okki_client.OkkiApiError('PRIVATE_PROVIDER_DETAIL')
            if kind=='freight':return {'301'} if fault=='found' else None
            return {'outbound_invoice_id':'401'} if fault=='found' else {}
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',lookup);monkeypatch.setattr(shipment_delivery.okki_client,'find_outbound_by_serial',lookup)
        response=client.post(command_path(c,kind),headers=owner,json=body)
        assert response.status_code==(409 if fault=='found' else 503),response.text
        assert 'PRIVATE_PROVIDER_DETAIL' not in response.text and snapshot(c)==before and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_retry_exact_third_business_commit_and_original_version_recovery(state_app,kind,timing,monkeypatch):
    c=state_app;sessions=[];hits=[];original=shipment_retry_service._capture
    def track(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    with c.app.client() as client:
        _,owner,body=prepare(c,client,kind,monkeypatch);before=snapshot(c)
        monkeypatch.setattr(shipment_retry_service,'_capture',track)
        def fail(db):
            if any(db is item for item in sessions):
                count=db.info.get('retry_commit',0)+1;db.info['retry_commit']=count
                if count==3:hits.append(id(db));raise OperationalError('PRIVATE_DB',{},Exception('PRIVATE_ACK'))
        event.listen(Session,timing,fail)
        try:response=client.post(command_path(c,kind),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.status_code==503 and 'PRIVATE_' not in response.text,response.text
        if timing=='before_commit':assert snapshot(c)==before
        else:
            current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
            assert current.status_code==200
            data=current.json()['data']
            assert data['version']==body['version']+int(kind=='outbound')
            assert data['freight_target' if kind=='freight' else 'outbound']['status']==('unverified' if kind=='freight' else 'pending')
            with Session(c.ctx.engine) as db:
                assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id,action='retry_'+kind,actor_id=c.ctx.actor,reason=body['reason']).count()==1
            retained=retry_delta(c,before,kind,body);again=client.post(command_path(c,kind),headers=owner,json=body)
            assert again.status_code==409 and snapshot(c)==retained
        assert c.calls==[]

@pytest.mark.parametrize('kind',KINDS)
def test_retry_dirty_caller_is_not_flushed_or_rolled_back(state_app,kind,monkeypatch):
    c=state_app
    with c.app.client() as client:_,_,body=prepare(c,client,kind,monkeypatch)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);original=invoice.customer_name;invoice.customer_name='Uncommitted caller data'
        with pytest.raises(HTTPException) as raised:shipment_retry_service.retry(db,c.settlement_id,SettlementAction(**body),{'sub':str(c.ctx.actor)},kind=kind)
        assert raised.value.status_code==409 and invoice in db.dirty and invoice.customer_name=='Uncommitted caller data'
        with Session(c.ctx.engine) as independent:assert independent.get(Invoice,c.invoice_id).customer_name==original


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('change',['disabled','owner'])
def test_final_current_authority_precedes_original_found_business_conflict(state_app,kind,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,kind,monkeypatch);baselines=[]
        def lookup(*args):
            if change=='disabled':change_user(client,c,root,{'is_active':False})
            else:
                with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
            baselines.append(snapshot(c));return {'301'} if kind=='freight' else {'outbound_invoice_id':'401'}
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',lookup);monkeypatch.setattr(shipment_delivery.okki_client,'find_outbound_by_serial',lookup)
        response=client.post(command_path(c,kind),headers=owner,json=body)
        assert response.status_code==(403 if change=='disabled' else 404),response.text
        assert len(baselines)==1 and snapshot(c)==baselines[0] and c.calls==[]

@pytest.mark.parametrize('page',[[],{}, {'list':[],'count':'bad'}, {'list':[{'order_id':'5'}],'count':1},
    {'list':[{'order_id':'0','name':'Other'}],'count':1}, {'list':[{'order_id':'05','name':'Other'}],'count':1},
    {'list':[{'order_id':'５','name':'Other'}],'count':1}, {'list':[{'order_id':'5','name':None}],'count':1}])
def test_real_freight_scanner_incomplete_page_never_proves_absence(state_app,page,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'freight',monkeypatch);before=snapshot(c);observed=[]
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',ACTUAL_FREIGHT_SCAN)
        def read(*args):observed.append(deepcopy(page));return deepcopy(page)
        monkeypatch.setattr(freight_delivery.remote,'read',read)
        response=client.post(command_path(c,'freight'),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert observed and snapshot(c)==before and c.calls==[]

def test_real_freight_scanner_changing_complete_observations_not_absence(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'freight',monkeypatch);before=snapshot(c);calls=[]
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',ACTUAL_FREIGHT_SCAN)
        def read(*args):calls.append(True);return {'list':[{'order_id':str(4+len(calls)),'name':'Other'}],'count':1}
        monkeypatch.setattr(freight_delivery.remote,'read',read)
        response=client.post(command_path(c,'freight'),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert len(calls)==2 and snapshot(c)==before and c.calls==[]


def retry_delta(c, before, kind, body):
    """Compare every column across the finite 21-model test graph."""
    after=snapshot(c)
    expected=[[deepcopy(dict(row._mapping)) for row in table] for table in before]
    actual=[[deepcopy(dict(row._mapping)) for row in table] for table in after]
    assert len(expected)==len(actual)==21
    if kind=='freight':
        tables=[table for table in expected if table and {'remote_status','remote_order_name','amount'} <= table[0].keys()]
        assert len(tables)==1
        target=next(row for row in tables[0] if row['id']==c.target_id)
        target.update(remote_status='unverified',attempt_token=None,lease_until=None,last_error=None,version=target['version']+1)
    else:
        target=next(row for row in expected[19] if row['id']==c.target_id)
        current=next(row for row in actual[19] if row['id']==c.target_id)
        target.update(status='pending',attempt_token=None,lease_until=None,last_error=None,version=target['version']+1)
        if 'updated_at' in target:target['updated_at']=current['updated_at']
        target=next(row for row in expected[17] if row['id']==c.settlement_id)
        current=next(row for row in actual[17] if row['id']==c.settlement_id)
        target.update(state='outbound_pending',version=body['version']+1,updated_at=current['updated_at'])
    old_ids={row['id'] for row in expected[20]}
    additions=[row for row in actual[20] if row['id'] not in old_ids]
    assert len(additions)==1
    added=additions[0]
    assert (added['settlement_id'],added['action'],added['actor_id'],added['reason'])==(c.settlement_id,'retry_'+kind,c.ctx.actor,body['reason'])
    assert added['created_at'] is not None
    expected[20].append(added);expected[20].sort(key=lambda row:row['id'])
    assert actual==expected
    return after


@pytest.mark.parametrize('mode',['empty','other','match','reordered','changed_name'])
def test_real_freight_scanner_complete_positive_and_conflict_controls(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'freight',monkeypatch);before=snapshot(c);observed=[]
        monkeypatch.setattr(freight_delivery,'_matching_active_orders',ACTUAL_FREIGHT_SCAN)
        with Session(c.ctx.engine) as db:name=db.get(Receivable,c.target_id).remote_order_name
        def read(*args):
            observed.append(True)
            if mode=='empty':return {'list':[],'count':0}
            if mode in {'reordered','changed_name'}:
                rows=[{'order_id':'5','name':'Other'},{'order_id':'6','name':'Another'}]
                if len(observed)==2:
                    rows.reverse()
                    if mode=='changed_name':rows[0]['name']='Changed'
                return {'list':rows,'count':2}
            return {'list':[{'order_id':'5','name':name if mode=='match' else 'Other'}],'count':1}
        monkeypatch.setattr(freight_delivery.remote,'read',read)
        response=client.post(command_path(c,'freight'),headers=owner,json=body)
        assert response.status_code==(409 if mode=='match' else 503 if mode=='changed_name' else 200),response.text
        assert len(observed)==2 and c.calls==[]
        if mode in {'match','changed_name'}:assert snapshot(c)==before
        else:retry_delta(c,before,'freight',body)
