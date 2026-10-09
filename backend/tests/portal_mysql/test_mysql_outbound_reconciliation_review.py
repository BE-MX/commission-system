"""Independent review counterexamples, kept distinct from initial authorization green."""
from copy import deepcopy
from sqlalchemy.orm import Session
import pytest
from app.invoice import settlement_service
from app.invoice.settlement_models import ShipmentOutbound
from app.receipt.models import Receipt
from test_mysql_outbound_reconciliation import prepare, funded_prepare, route, MODES, outbound_delta
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('currency',['','   '])
def test_blank_outbound_currency_is_technical_not_mismatch(state_app,mode,currency,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:
            target=db.get(ShipmentOutbound,c.target_id);target.payload={**target.payload,'currency':'USD'}
            target.payload_hash=settlement_service.digest(target.payload);db.commit()
        c.detail['currency']=currency;before=snapshot(c)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert response.headers.get('cache-control')=='private, no-store' and snapshot(c)==before and c.calls==[]

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('field',['bank_charge','real_amount'])
@pytest.mark.parametrize('value',['missing','null'])
def test_receipt_detail_must_be_complete_before_financial_readback(state_app,mode,field,value,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=funded_prepare(c,client,mode,monkeypatch)
        data=next(iter(c.receipt_data.values()))
        if value=='missing':data.pop(field)
        else:data[field]=None
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert response.headers.get('cache-control')=='private, no-store' and snapshot(c)==before and c.calls==[]

def test_inactive_funding_preserves_proven_shipment_without_fictitious_balance(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=funded_prepare(c,client,'refresh',monkeypatch)
        inactive=next(iter(c.receipt_data))
        with Session(c.ctx.engine) as db:db.get(Receipt,inactive).status='voided';db.commit()
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        result=response.json()['data']
        assert result['outbound']['status']=='shipped_unfunded' and result['state']=='outbound_uncertain'
        assert result['balance'] is None and result['balance_error']=='本批关联回款已失效，余额暂不可计算，请核对原单'
        with Session(c.ctx.engine) as db:assert db.get(Receipt,inactive).status=='voided'
        assert c.calls==[]
        outbound_delta(c,before,body,status='shipped_unfunded',receipt_data={identity:data for identity,data in c.receipt_data.items() if identity!=inactive})
        retained=snapshot(c)
        read=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
        assert read.status_code==200 and read.json()['data']['balance'] is None,read.text
        assert snapshot(c)==retained


@pytest.mark.parametrize('diagnostic',['normal','logger','stdout'])
def test_reliable_unfunded_result_survives_diagnostic_failure(state_app,diagnostic,monkeypatch):
    from app.invoice import outbound_reconciliation_funding as funding
    import builtins
    c=state_app
    with c.app.client() as client:
        _,owner,body=funded_prepare(c,client,'refresh',monkeypatch);hits=[];sessions=[]
        from app.invoice import outbound_reconciliation_service as reconcile
        original_capture=reconcile._capture
        def track(db,*args):
            if not any(db is item for item in sessions):sessions.append(db)
            return original_capture(db,*args)
        monkeypatch.setattr(reconcile,'_capture',track)
        goods=next(key for key in c.list_rows if key!=c.freight_id)
        c.list_rows[goods].append({'cash_collection_id':'99999','order_id':goods,'currency':'USD','amount':'1.00',
            'collect_status':1,'collection_date':'2026-10-06'})
        if diagnostic=='logger':
            def fail(*args,**kwargs):hits.append('logger');raise RuntimeError('PRIVATE_DIAGNOSTIC')
            monkeypatch.setattr(funding.logger,'warning',fail)
        elif diagnostic=='stdout':
            original=builtins.print
            def fail(*args,**kwargs):
                if args and args[0]=='[shipment] complete funding evidence did not verify':
                    hits.append('stdout');raise BrokenPipeError('PRIVATE_STDOUT')
                return original(*args,**kwargs)
            monkeypatch.setattr(builtins,'print',fail)
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        assert hits==([] if diagnostic=='normal' else [diagnostic])
        assert len(sessions)==1
        assert sessions[0].info.get('outbound_diagnostic_failures',[])==([] if diagnostic=='normal' else [{'sink':diagnostic,'error':'RuntimeError' if diagnostic=='logger' else 'BrokenPipeError'}])
        outbound_delta(c,before,body,status='shipped_unfunded',receipt_data=c.receipt_data)
        assert c.calls==[] and 'PRIVATE_' not in response.text
