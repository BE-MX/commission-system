"""Original outbound state/atomicity controls; real owned JWT/main/MySQL."""
from copy import deepcopy
from datetime import timedelta
import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.core.time import beijing_now
from app.invoice import outbound_reconciliation_service as service, settlement_service
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement
from app.invoice.settlement_schemas import SettlementRemoteReview
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection import outbound_presence
from app.receipt import remote
from test_mysql_outbound_reconciliation import prepare, funded_prepare, route, MODES, outbound_delta
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

ACTUAL_PRESENCE=outbound_presence.is_active

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_exact_third_commit_atomic_funding_and_original_recovery(state_app,mode,timing,monkeypatch):
    c=state_app;sessions=[];hits=[];original=service._capture
    def track(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    with c.app.client() as client:
        _,owner,body=funded_prepare(c,client,mode,monkeypatch);before=snapshot(c)
        monkeypatch.setattr(service,'_capture',track)
        def fail(db):
            if any(db is item for item in sessions):
                count=db.info.get('outbound_commit',0)+1;db.info['outbound_commit']=count
                if count==3:hits.append(id(db));raise OperationalError('PRIVATE_DB',{},Exception('PRIVATE_ACK'))
        event.listen(Session,timing,fail)
        try:response=client.post(route(c),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.status_code==503 and 'PRIVATE_' not in response.text,response.text
        if timing=='before_commit':assert snapshot(c)==before
        else:
            outbound_delta(c,before,body,status='shipped',receipt_data=c.receipt_data)
            retained=snapshot(c);current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
            assert current.status_code==200 and current.json()['data']['outbound']['status']=='shipped'
            assert current.json()['data']['version']==body['version']+(2 if mode=='bind' else 1)
            assert snapshot(c)==retained
            again=client.post(route(c),headers=owner,json=body)
            assert again.status_code==409 and snapshot(c)==retained
        assert c.calls==[]

@pytest.mark.parametrize('mode',MODES)
def test_dirty_caller_is_not_committed_or_rolled_back(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:_,_,body=prepare(c,client,mode,monkeypatch)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);before=invoice.customer_name;invoice.customer_name='Pending caller edit'
        with pytest.raises(HTTPException) as raised:service.reconcile(db,c.settlement_id,SettlementRemoteReview(**body),{'sub':str(c.ctx.actor)})
        assert raised.value.status_code==409 and invoice in db.dirty and invoice.customer_name=='Pending caller edit'
        with Session(c.ctx.engine) as other:assert other.get(Invoice,c.invoice_id).customer_name==before

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('scope',['invoice_all','receipt_all'])
def test_actual_financial_scope_not_invoice_read_all(state_app,mode,scope,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write'],c.roles['invoice:read_all'] if scope=='invoice_all' else c.roles['all']]+([c.roles['shipment:admin']] if mode=='bind' else [])})
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(404 if scope=='invoice_all' else 200),response.text
        if scope=='invoice_all':assert snapshot(c)==before and c.reads==[]
        else:outbound_delta(c,before,body)
        assert c.calls==[]

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('history',['uncertain','unsynced','allocation'])
def test_original_reconciliation_has_no_added_ready_restriction(state_app,mode,history,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id)
            if history=='uncertain':invoice.sync_status='uncertain'
            elif history=='unsynced':invoice.status='draft';invoice.sync_status='pending'
            else:db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
            db.commit()
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        outbound_delta(c,before,body);assert len(c.reads)==1 and c.calls==[]

@pytest.mark.parametrize('mode',MODES)
def test_arbitrary_original_sale_price_precision_is_preserved(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:
            target=db.get(ShipmentOutbound,c.target_id);payload=deepcopy(target.payload)
            payload['record_list'][0].update(sale_price='12.3456',product_unit='Piece');payload['currency']='USD'
            target.payload=payload;target.payload_hash=settlement_service.digest(payload);db.commit()
        c.detail['record_list'][0].update(sale_price='12.3456',product_unit='Piece');c.detail['currency']='USD'
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        outbound_delta(c,before,body);assert c.calls==[]

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('observation',['active','absent','bad_list','bad_count'])
def test_real_outbound_presence_parser_with_controlled_http(state_app,mode,observation,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c);requests=[]
        monkeypatch.setattr(outbound_presence,'is_active',ACTUAL_PRESENCE)
        def request(method,url,**kwargs):
            assert method=='GET' and url.endswith('/v1/invoices/outbound/list')
            requests.append(deepcopy(kwargs['params']))
            class Result:
                status_code=200
                def json(self):
                    return {'code':0,'data':[] if observation=='bad_list' else {'list':[],'count':'bad'} if observation=='bad_count' else {'list':[{'outbound_invoice_id':'401'}],'count':1} if observation=='active' else {'list':[],'count':0}}
            return Result()
        monkeypatch.setattr(outbound_presence.httpx,'request',request)
        response=client.post(route(c),headers=owner,json=body)
        expected=503 if observation.startswith('bad') else 409 if observation=='absent' and mode=='bind' else 200
        assert response.status_code==expected,response.text
        if expected!=200:assert snapshot(c)==before
        else:outbound_delta(c,before,body,status='pending_remote' if observation=='active' else 'uncertain')
        assert len(requests)==(2 if observation=='absent' else 1) and c.calls==[]
        assert all(p['removed']==0 and p['start_time']=='2026-10-06 00:00:00' and p['end_time']=='2026-10-06 23:59:59' for p in requests)

@pytest.mark.parametrize('prior',['shipped','shipped_unfunded','confirming','confirm_uncertain'])
def test_remote_pending_never_reenables_original_confirmation(state_app,prior,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'refresh',monkeypatch)
        with Session(c.ctx.engine) as db:db.get(ShipmentOutbound,c.target_id).status=prior;db.commit()
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        result=response.json()['data'];assert result['state']=='outbound_uncertain'
        assert result['outbound']['status']=='confirm_uncertain'
        assert result['outbound']['confirmation']['blocks_confirmation'] is True
        assert '禁止再次确认' in result['outbound']['last_error'] and c.calls==[]
        if prior.startswith('shipped'):
            assert result['outbound']['confirmation']['state']=='shipped_regression'
            # A second current-version read must not forget the permanent shipped proof.
            again=client.post(route(c),headers=owner,json={**body,'version':result['version']})
            assert again.status_code==200,again.text
            assert again.json()['data']['outbound']['status']=='confirm_uncertain'
            assert again.json()['data']['outbound']['confirmation']['blocks_confirmation'] is True and c.calls==[]

@pytest.mark.parametrize('mode',MODES)
def test_first_already_shipped_missing_baseline_is_preserved_as_uncertain(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);c.detail['status']=2
        for key in ('outbound_record_id','cost_unit_price_rmb'):c.detail['record_list'][0].pop(key)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        result=response.json()['data'];assert result['outbound']['status']=='uncertain' and result['state']=='outbound_uncertain'
        assert '缺少待出库明细 ID 和成本基线' in result['outbound']['last_error'] and len(c.reads)==1 and c.calls==[]

def test_live_confirm_lease_rejects_without_remote_read(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'refresh',monkeypatch)
        with Session(c.ctx.engine) as db:
            target=db.get(ShipmentOutbound,c.target_id);target.status='confirming';target.lease_until=beijing_now()+timedelta(minutes=3);db.commit()
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==409,response.text
        assert snapshot(c)==before and c.reads==[] and c.calls==[]
