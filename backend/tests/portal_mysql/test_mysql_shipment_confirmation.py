"""Actual current employee authority for explicit shipment confirmation."""
from copy import deepcopy
import pytest
from sqlalchemy.orm import Session
from app.invoice import shipment_delivery
REAL_ENSURE_ACCESS_TOKEN=shipment_delivery.okki_client.ensure_access_token
from app.invoice.settlement_models import ShipmentOutbound,ShipmentSettlement
from test_mysql_outbound_reconciliation import funded_prepare
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app,snapshot,login,change_user  # noqa: F401
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

def path(c):return f'/api/shipments/{c.settlement_id}/confirm-outbound'

def prepared(c,client,monkeypatch):
    from sqlalchemy import select
    from app.auth.models import ArkUserExternalBinding
    from app.invoice.models import Invoice
    from app.invoice.settlement_models import SettlementItem,ReceiptBatch,Receivable
    from app.receipt.models import Receipt
    from app.invoice import xiaoman_service,settlement_service
    from app.invoice.settlement_contract import build_outbound_candidate
    root,owner,body=funded_prepare(c,client,'refresh',monkeypatch)
    from sqlalchemy import Column,MetaData,Table
    metadata=MetaData()
    Table(ArkUserExternalBinding.__tablename__,metadata,*(Column(col.name,col.type,
        primary_key=col.primary_key,nullable=False if col.primary_key else True) for col in ArkUserExternalBinding.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);customer=str(700000+c.invoice_id);invoice.customer_id=customer
        for row in db.scalars(select(Receipt).where(Receipt.invoice_id==invoice.id)):row.customer_id=customer
        batches={row.batch_id for row in db.scalars(select(Receipt).where(Receipt.invoice_id==invoice.id)) if row.batch_id}
        for row in db.scalars(select(ReceiptBatch).where(ReceiptBatch.id.in_(batches))):row.customer_id=customer
        for row in db.scalars(select(Receivable).where(Receivable.invoice_id==invoice.id)):row.customer_id=customer
        mapping=ArkUserExternalBinding(ark_user_id=c.ctx.actor,provider='okki',external_account_id='42',binding_status='active',is_primary=True)
        db.add(mapping);db.flush();c.mapping_id=mapping.id
        target=db.get(ShipmentOutbound,c.target_id);target.status='pending_remote'
        settlement=db.get(ShipmentSettlement,c.settlement_id);settlement.state='outbound_pending'
        items=[{'quantity':item.quantity,'snapshot':item.snapshot} for item in db.scalars(select(SettlementItem).where(SettlementItem.settlement_id==settlement.id))]
        c.main=c.order_details[invoice.xiaoman_order_id]
        c.main.update(company_id=customer,users=[{'user_id':'42'}],exchange_rate=725,exchange_rate_usd=100,
            product_list=[{'unique_id':'101','product_id':'1','sku_id':'2','count':10,'unit_price':'10',
                'unit':'Piece','to_outbound_count':0,'task_outbound_count':0}])
        for detail in c.order_details.values():detail['company_id']=customer
        payload=build_outbound_candidate(settlement.settlement_no,invoice.xiaoman_order_id,customer,
            invoice.currency,items,c.main,17,handler_id=42,reserved_quantities={'101':0})
        target.payload=payload;target.payload_hash=settlement_service.digest(payload);db.commit()
    c.detail.update(status=1,currency='USD',source_type=2,company_info={'id':customer},
        invoice_warehouse_info={'id':'17'},handler_info=[{'user_id':'42'}])
    c.detail['record_list'][0].update(sale_price=10,product_unit='Piece')
    c.posts=[]
    monkeypatch.setattr(xiaoman_service,'get_settings',lambda:c.app.settings)
    monkeypatch.setattr(shipment_delivery.linked_outbound_service,'find_related',lambda *_:[deepcopy(c.detail)])
    def post(path,token,payload,*,context):
        assert path=='/v1/invoices/outbound/push'
        c.posts.append(deepcopy(payload));c.detail['status']=2
        return {'outbound_invoice_id':'401'}
    monkeypatch.setattr(shipment_delivery.okki_client,'_post_json',post)
    c.reads.clear();return root,owner,body

@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_current_confirmation_revocation_before_read(state_app,revoke,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['invoice:write']]})
        before=snapshot(c);response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==403,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.reads==[] and c.posts==[]

def test_current_confirmation_grant_to_old_empty_token(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,_,body=prepared(c,client,monkeypatch)
        change_user(client,c,root,{'role_ids':[]});owner=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write']]})
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert response.json()['data']['outbound']['status']=='shipped' and len(c.posts)==1


def journal(c):
    from app.portal.event_models import AuditEvent
    from app.invoice import shipment_confirmation_facts as facts
    from sqlalchemy import select
    with Session(c.ctx.engine) as db:
        return [dict(row._mapping) for row in db.execute(select(*AuditEvent.__table__.columns)
            .where(AuditEvent.object_type=='shipment_outbound',AuditEvent.object_public_id==facts.object_id(c.target_id)).order_by(AuditEvent.id))]

def test_actual_complete_confirmation_one_post_exact_payload_and_no_duplicate(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        result=response.json()['data'];assert result['outbound']['status']=='shipped' and result['version']==body['version']+1
        assert len(c.posts)==1 and c.posts[0]['status']==2 and c.posts[0]['outbound_invoice_id']==401
        assert c.posts[0]['record_list'][0]['outbound_record_id']==501 and c.posts[0]['record_list'][0]['cost_unit_price_rmb']==12.5
        records=journal(c);assert len(records)==4 and [r['action'] for r in records]==['shipment_confirm_start','shipment_confirm_send','shipment_confirm_fact','shipment_confirm_finish']
        assert records[2]['safe_diff_json']['result_class']=='accepted' and records[3]['safe_diff_json']['resolved'] is True
        retained=snapshot(c);again=client.post(path(c),headers=owner,json=body)
        assert again.status_code==409 and snapshot(c)==retained and journal(c)==records and len(c.posts)==1

@pytest.mark.parametrize('change',['disabled','write','owner','funds','invoice','target','mapping','settlement'])
def test_final_current_preflight_after_unlocked_supplier_reads(state_app,change,monkeypatch):
    from sqlalchemy import select
    from app.invoice.models import Invoice
    from app.receipt.models import Receipt
    from app.auth.models import ArkUserExternalBinding
    from app.receipt import remote
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch);original=remote.read;baselines=[]
        def read(db,path,params=None):
            if not baselines:
                with Session(c.ctx.engine) as other:
                    invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                    if change=='owner':invoice.sales_user_id=c.other_id
                    elif change=='invoice':invoice.customer_name='Concurrent commercial change'
                    elif change=='funds':other.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                    elif change=='target':other.get(ShipmentOutbound,c.target_id).version+=1
                    elif change=='mapping':other.get(ArkUserExternalBinding,c.mapping_id).external_account_id='43'
                    elif change=='settlement':other.get(ShipmentSettlement,c.settlement_id).version+=1
                    other.commit()
                if change in ('disabled','write'):change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[]})
                baselines.append(snapshot(c))
            return original(db,path,params)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(403 if change in ('disabled','write') else 404 if change=='owner' else 409),response.text
        assert snapshot(c)==baselines[0] and journal(c)==[] and c.posts==[]

@pytest.mark.parametrize('change',['disabled','owner','funds'])
def test_token_io_is_unlocked_and_presend_reauthorizes_claim(state_app,change,monkeypatch):
    from sqlalchemy import select
    from app.invoice.models import Invoice
    from app.receipt.models import Receipt
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch);baselines=[];original=shipment_delivery.okki_client.ensure_access_token
        def token(db,**kwargs):
            # Initial detail GET also needs a token, but has no durable claim yet.
            if journal(c) and not baselines:
                with Session(c.ctx.engine) as other:
                    invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                    if change=='owner':invoice.sales_user_id=c.other_id
                    elif change=='funds':other.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                    other.commit()
                if change=='disabled':change_user(client,c,root,{'is_active':False})
                baselines.append(snapshot(c))
            return original(db,**kwargs)
        monkeypatch.setattr(shipment_delivery.okki_client,'ensure_access_token',token)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(403 if change=='disabled' else 404 if change=='owner' else 409),response.text
        assert snapshot(c)==baselines[0] and len(journal(c))==1 and c.posts==[]

@pytest.mark.parametrize('change',['disabled','owner','funds','lease','token'])
def test_post_effect_survives_revocation_and_ownership_changes_as_original_fact(state_app,change,monkeypatch):
    from sqlalchemy import select
    from datetime import timedelta
    from app.core.time import beijing_now
    from app.invoice.models import Invoice
    from app.receipt.models import Receipt
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch);original=shipment_delivery.okki_client._post_json;baselines=[]
        def post(*args,**kwargs):
            with Session(c.ctx.engine) as other:
                invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                if change=='owner':invoice.sales_user_id=c.other_id
                elif change=='funds':other.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                elif change=='lease':other.get(ShipmentOutbound,c.target_id).lease_until=beijing_now()-timedelta(minutes=1)
                elif change=='token':other.get(ShipmentOutbound,c.target_id).attempt_token='new-owner'
                other.commit()
            if change=='disabled':change_user(client,c,root,{'is_active':False})
            baselines.append(snapshot(c));return original(*args,**kwargs)
        monkeypatch.setattr(shipment_delivery.okki_client,'_post_json',post)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(403 if change=='disabled' else 404 if change=='owner' else 409),response.text
        assert snapshot(c)==baselines[0] and len(c.posts)==1
        records=journal(c);assert len(records)==3 and records[-1]['safe_diff_json']['result_class']=='accepted'

@pytest.mark.parametrize('result',['timeout','bad_id','bool_id','missing_id','bad_list','rejected','auth_then_ok','auth_twice'])
def test_supplier_result_classifications_and_bounded_auth_retry(state_app,result,monkeypatch):
    from app.invoice import okki_client
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch);original=okki_client._post_json
        def post(*args,**kwargs):
            if result=='auth_then_ok' and c.posts:return original(*args,**kwargs)
            c.posts.append(deepcopy(args[2]))
            if result=='timeout':raise okki_client.OkkiOutcomeUncertainError('PRIVATE_TIMEOUT')
            if result=='rejected':raise okki_client.OkkiApiError('PRIVATE_REJECTION')
            return {'outbound_invoice_id':'402'} if result=='bad_id' else {'outbound_invoice_id':True} if result=='bool_id' else {} if result=='missing_id' else [] if result=='bad_list' else None
        monkeypatch.setattr(okki_client,'_post_json',post)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200 and 'PRIVATE_' not in response.text,response.text
        expected='shipped' if result=='auth_then_ok' else 'pending_remote' if result in ('rejected','auth_twice') else 'confirm_uncertain'
        assert response.json()['data']['outbound']['status']==expected
        assert len(c.posts)==(2 if result.startswith('auth_') else 1)
        records=journal(c);assert len(records)==(6 if result.startswith('auth_') else 4)
        if expected=='confirm_uncertain':
            retained=snapshot(c);again=client.post(path(c),headers=owner,json={**body,'version':response.json()['data']['version']})
            assert again.status_code==409 and snapshot(c)==retained and len(c.posts)==1

@pytest.mark.parametrize('diagnostic',['logger','stdout'])
def test_fact_retry_survives_diagnostic_failure_after_actual_post(state_app,diagnostic,monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from app.invoice import shipment_confirmation_service as service
    import builtins
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch);sessions=[];faults=[];hits=[];original=service.capture
        def track(db,*args,**kwargs):
            if not any(db is item for item in sessions):sessions.append(db)
            return original(db,*args,**kwargs)
        monkeypatch.setattr(service,'capture',track)
        def fail(db):
            if any(db is item for item in sessions) and c.posts and not faults:
                faults.append(id(db));raise OperationalError('PRIVATE_FACT',{},Exception('PRIVATE_SQL'))
        if diagnostic=='logger':
            def broken(*args,**kwargs):hits.append('logger');raise RuntimeError('PRIVATE_LOGGER')
            monkeypatch.setattr(service.logger,'warning',broken)
        else:
            actual=builtins.print
            def broken(*args,**kwargs):
                if args and str(args[0]).startswith('[shipment-confirm] original fact retry'):
                    hits.append('stdout');raise BrokenPipeError('PRIVATE_STDOUT')
                return actual(*args,**kwargs)
            monkeypatch.setattr(builtins,'print',broken)
        event.listen(Session,'before_commit',fail)
        try:response=client.post(path(c),headers=owner,json=body)
        finally:event.remove(Session,'before_commit',fail)
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='shipped',response.text
        assert len(c.posts)==1 and len(faults)==1 and hits==[diagnostic]
        assert len([r for r in journal(c) if r['action']=='shipment_confirm_fact'])==1

@pytest.mark.parametrize('change',['action','object','delete','renamed_delete'])
def test_original_journal_cannot_be_rewritten_after_expiration(state_app,change,monkeypatch):
    from sqlalchemy import select
    from app.portal.event_models import AuditEvent
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch)
        response=client.post(path(c),headers=owner,json=body);assert response.status_code==200,response.text
        before=journal(c)
        with Session(c.ctx.engine) as db:
            row=db.get(AuditEvent,before[0]['id']);db.expire(row,['action'])
            row.action='ordinary_safe_action'
            if change=='object':row.object_type='other';row.object_public_id='00000000-0000-0000-0000-000000000000'
            if change in ('delete','renamed_delete'):db.delete(row)
            message='must be retained' if change in ('delete','renamed_delete') else 'immutable'
            with pytest.raises(ValueError,match=message):db.flush()
            db.rollback()
        assert journal(c)==before

@pytest.mark.parametrize('phase',['preflight','token','readback'])
def test_actual_token_helper_bad_expiry_is_private_unavailable(state_app,phase,monkeypatch):
    from types import SimpleNamespace
    import httpx
    from app.invoice import okki_client,xiaoman_service
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch);before=snapshot(c);hits=[]
        settings=SimpleNamespace(OKKI_CLIENT_ID='synthetic-id',OKKI_CLIENT_SECRET='synthetic-secret',
            OKKI_API_BASE='https://synthetic.invalid')
        cache=SimpleNamespace(access_token=None,token_expires_at=None)
        monkeypatch.setattr(okki_client,'get_settings',lambda:settings)
        monkeypatch.setattr(xiaoman_service,'get_or_create_settings',lambda db:cache)
        def transport(url,**kwargs):
            hits.append(url)
            return httpx.Response(200,json={'access_token':'PRIVATE_TOKEN','expires_in':10**100})
        monkeypatch.setattr(okki_client.httpx,'post',transport)
        def token(db,**kwargs):
            records=journal(c)
            should_fail=(phase=='preflight' and not records) or (phase=='token' and len(records)==1) or (phase=='readback' and len(records)==3)
            return REAL_ENSURE_ACCESS_TOKEN(db,**kwargs) if should_fail else 'synthetic-token'
        monkeypatch.setattr(okki_client,'ensure_access_token',token)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==503 and 'PRIVATE_' not in response.text,response.text
        assert response.headers.get('cache-control')=='private, no-store' and len(hits)==1
        records=journal(c)
        assert len(c.posts)==(1 if phase=='readback' else 0)
        assert len(records)==({'preflight':0,'token':1,'readback':3}[phase])
        assert not any(r['action']=='shipment_confirm_finish' for r in records)
        if phase=='preflight':assert snapshot(c)==before

@pytest.mark.parametrize('stage',['start','send','finish'])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_exact_commits_do_not_send_after_unknown_ack(state_app,stage,timing,monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from app.invoice import shipment_confirmation_service as service
    c=state_app;sessions=[];hits=[];original=service.capture
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch);before=snapshot(c)
        def track(db,*args,**kwargs):
            if not any(db is item for item in sessions):sessions.append(db)
            return original(db,*args,**kwargs)
        monkeypatch.setattr(service,'capture',track)
        checkpoint={'start':3,'send':5,'finish':8}[stage]
        def fail(db):
            if any(db is item for item in sessions):
                count=db.info.get('confirmation_commits',0)+1;db.info['confirmation_commits']=count
                if count==checkpoint:
                    hits.append(id(db));raise OperationalError('PRIVATE_COMMIT',{},Exception('PRIVATE_ACK'))
        event.listen(Session,timing,fail)
        try:response=client.post(path(c),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert response.status_code==503 and 'PRIVATE_' not in response.text,response.text
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.headers.get('cache-control')=='private, no-store'
        assert len(c.posts)==(1 if stage=='finish' else 0)
        expected_records=({'start':0,'send':1,'finish':3} if timing=='before_commit' else {'start':1,'send':2,'finish':4})[stage]
        assert len(journal(c))==expected_records
        if stage=='start' and timing=='before_commit':assert snapshot(c)==before
        else:
            retained=snapshot(c);records=journal(c)
            again=client.post(path(c),headers=owner,json=body)
            assert again.status_code==409 and snapshot(c)==retained and journal(c)==records
            assert len(c.posts)==(1 if stage=='finish' else 0)
        if stage=='finish' and timing=='after_commit':
            current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
            assert current.status_code==200 and current.json()['data']['outbound']['status']=='shipped'
            assert snapshot(c)==retained

@pytest.mark.parametrize('change',['disabled','funds'])
def test_authentication_retry_rechecks_current_authority_before_second_send(state_app,change,monkeypatch):
    from sqlalchemy import select
    from app.invoice.models import Invoice
    from app.receipt.models import Receipt
    from app.invoice import okki_client
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch);baselines=[]
        def post(path,token,payload,**kwargs):c.posts.append(deepcopy(payload));return None
        def token(db,**kwargs):
            if kwargs.get('force'):
                with Session(c.ctx.engine) as other:
                    other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                    if change=='funds':other.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                    other.commit()
                if change=='disabled':change_user(client,c,root,{'is_active':False})
                baselines.append(snapshot(c))
            return 'synthetic-token'
        monkeypatch.setattr(okki_client,'_post_json',post);monkeypatch.setattr(okki_client,'ensure_access_token',token)
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(403 if change=='disabled' else 409),response.text
        assert len(c.posts)==1 and len(baselines)==1 and snapshot(c)==baselines[0]
        records=journal(c);assert len(records)==3 and records[-1]['safe_diff_json']['result_class']=='auth_rejected'

@pytest.mark.parametrize('scope',['invoice_all','receipt_all'])
def test_confirmation_requires_actual_financial_scope(state_app,scope,monkeypatch):
    from app.invoice.models import Invoice
    from app.auth.models import ArkUserExternalBinding
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepared(c,client,monkeypatch)
        with Session(c.ctx.engine) as db:
            db.get(Invoice,c.invoice_id).sales_user_id=c.other_id
            db.get(ArkUserExternalBinding,c.mapping_id).ark_user_id=c.other_id;db.commit()
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write'],c.roles['invoice:read_all'] if scope=='invoice_all' else c.roles['all']]})
        before=snapshot(c);response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==(404 if scope=='invoice_all' else 200),response.text
        if scope=='invoice_all':assert snapshot(c)==before and c.reads==[] and c.posts==[] and journal(c)==[]
        else:assert response.json()['data']['outbound']['status']=='shipped' and len(c.posts)==1

@pytest.mark.parametrize('history',['uncertain','unsynced','allocation'])
def test_confirmation_preserves_original_no_ready_restriction(state_app,history,monkeypatch):
    from app.invoice.models import Invoice
    from app.semifinished.models import InvoiceAllocation
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepared(c,client,monkeypatch)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id)
            if history=='uncertain':invoice.sync_status='uncertain'
            elif history=='unsynced':invoice.status='draft';invoice.sync_status='pending'
            else:db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
            db.commit()
        response=client.post(path(c),headers=owner,json=body)
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='shipped',response.text
        assert len(c.posts)==1 and len(journal(c))==4
