"""Real isolated claim/HTTP adapters. No external credentials or production traffic."""
from datetime import timedelta
from decimal import Decimal
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.commerce_transition import service as authority
from app.commerce_transition.models import ClaimEvidence, InvoiceAuthority, SendingClaim
from app.core.time import beijing_now, beijing_today
from app.invoice import legacy_sending as gate, okki_client, order_sync_execution, outbound_followup_execution
from app.invoice.models import Invoice
from app.receipt import remote, sync_service, attachments
from app.receipt.models import Receipt
from tests.authority_helpers import seed_authority
from tests.test_commerce_transition_authority import install

@pytest.fixture
def ready(db,monkeypatch):
    seed_authority(db,1,'invoice:read','invoice:write','invoice:sync','receipt:read','receipt:write',roles=('super_admin',))
    install(db)
    row=Invoice(invoice_no='legacy-gated',transaction_mode='legacy',customer_id='101',customer_name='Isolated',sales_user_id=1,created_by=1,invoice_date=beijing_today(),currency='USD',total_amount=Decimal('100'),status='synced',sync_status='synced',xiaoman_order_id='2001')
    db.add(row);db.flush();authority.ensure_authority(db,row,route='legacy',source_evidence={'fixture':'explicit'},confirmed=True);db.commit()
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *a,**k:'isolated-token')
    monkeypatch.setattr(okki_client,'_base_url',lambda:'https://test.invalid')
    monkeypatch.setattr(httpx,'get',lambda *a,**k:pytest.fail('unexpected GET'))
    monkeypatch.setattr(httpx,'post',lambda *a,**k:pytest.fail('unexpected POST'))
    monkeypatch.setattr(httpx,'request',lambda *a,**k:pytest.fail('unexpected lifecycle HTTP'))
    return row

def ticket(db,row,key,payload):
    grant=gate.start(db,row,key,'order_push',payload,{'original_task':key},1);db.commit();return grant

@pytest.mark.parametrize('path,payload,response',[
 ('/v1/invoices/order/push',{'order_id':'2001'},{'order_id':'2001'}),
 ('/v1/invoices/outbound/push',{'outbound_invoice_id':'3001'},{'outbound_invoice_id':'3001'}),
 ('/v1/invoices/receipt/push',{'order_id':2001},{'cash_collection_id':'4001','cash_collection_no':'HK4001'})])
def test_real_http_observes_committed_claim_and_no_local_transaction(db,ready,monkeypatch,path,payload,response):
    grant=ticket(db,ready,'committed-original',payload)
    def post(*a,**k):
        assert not db.in_transaction()
        with Session(db.get_bind()) as observer:
            stored=observer.scalar(select(SendingClaim).where(SendingClaim.request_key==grant.request_key))
            assert stored and stored.state=='sending' and stored.route=='legacy' and stored.epoch==1
        assert k['json']==payload
        return httpx.Response(200,json={'code':200,'data':response})
    monkeypatch.setattr(httpx,'post',post)
    assert gate.invoke(db,grant,path,'token',payload,context='isolated')==response
    assert gate.find(db,grant.request_key).state=='succeeded'


def test_unknown_and_expired_claim_cannot_be_reposted_or_replaced(db,ready,monkeypatch):
    payload={'order_id':'2001'};grant=ticket(db,ready,'unknown-original',payload);posts=[]
    def timeout(*a,**k):posts.append(1);raise httpx.ReadTimeout('lost response')
    monkeypatch.setattr(httpx,'post',timeout)
    with pytest.raises(okki_client.OkkiOutcomeUncertainError):gate.invoke(db,grant,'/v1/invoices/order/push','token',payload,context='isolated')
    stored=gate.find(db,grant.request_key);stored.lease_until=beijing_now()-timedelta(days=1);db.commit()
    with pytest.raises(ValueError):ticket(db,ready,grant.request_key,payload)
    db.rollback()
    with pytest.raises(ValueError):ticket(db,ready,'another-identity',payload)
    db.rollback()
    with pytest.raises(ValueError,match='已使用'):gate.invoke(db,grant,'/v1/invoices/order/push','token',payload,context='isolated')
    assert posts==[1]


def test_late_original_evidence_survives_freeze_and_new_epoch(db,ready):
    grant=ticket(db,ready,'late-original',{'order_id':'2001'})
    held=db.get(InvoiceAuthority,ready.id);held.state='frozen';held.epoch=2;db.commit()
    gate.finish(db,grant.request_key,'succeeded',{'original_response':'accepted'},'2001');db.commit()
    saved=gate.find(db,grant.request_key);assert saved.epoch==1 and saved.external_id=='2001'
    gate.finish(db,grant.request_key,'succeeded',{'conflicting_response':True},'2002');db.commit()
    assert saved.external_id=='2001' and saved.state=='unknown'
    assert db.get(InvoiceAuthority,ready.id).state=='frozen'
    assert db.query(ClaimEvidence).filter_by(claim_id=saved.id).count()==2


def test_401_closes_original_before_distinct_second_claim(db,ready,monkeypatch):
    payload={'order_id':'2001'};calls=[];rounds=[]
    def post(*a,**k):
        calls.append(1)
        return httpx.Response(401) if len(calls)==1 else httpx.Response(200,json={'code':200,'data':{'order_id':'2001'}})
    monkeypatch.setattr(httpx,'post',post)
    def before():
        n=len(rounds)+1
        if n==2:
            first=gate.find(db,'auth:1');assert first.state=='failed' and first.active_invoice_key is None;db.rollback()
        grant=ticket(db,ready,f'auth:{n}',payload);rounds.append(grant.request_key);return grant
    assert okki_client.push_order(db,payload,before_send=before)['order_id']=='2001'
    assert rounds==['auth:1','auth:2'] and len(calls)==2
    assert [r.state for r in db.query(SendingClaim).order_by(SendingClaim.id)]==['failed','succeeded']


def test_uncommitted_or_duplicate_ticket_never_reaches_http(db,ready):
    grant=gate.start(db,ready,'not-committed','order_push',{'order_id':'2001'},{'task':1},1)
    with pytest.raises(ValueError,match='提交'):gate.invoke(db,grant,'/v1/invoices/order/push','token',{'order_id':'2001'},context='isolated')
    db.rollback()
    with pytest.raises(ValueError,match='未持久提交'):gate.invoke(db,grant,'/v1/invoices/order/push','token',{'order_id':'2001'},context='isolated')
    assert db.query(SendingClaim).count()==0


def receipt(db,invoice_id,key):
    row=Receipt(receipt_no=key,invoice_id=invoice_id,source='manual',request_key=key,request_hash='a'*64,amount=10,bank_charge=0,currency='USD',customer_id='101',collection_date=beijing_today(),payment_type='T/T',attachment_ids=[],xiaoman_order_id='2001',sync_status='pending',created_by=1,purpose='ordinary')
    db.add(row);db.commit();identity=row.id;db.rollback();return identity


def test_actual_legacy_order_followup_and_receipt_entrypoints_reject_local_before_http(db,ready):
    ready.transaction_mode='local';db.get(InvoiceAuthority,ready.id).route='local';db.commit();identity=ready.id;db.rollback()
    with pytest.raises(HTTPException) as rejected:order_sync_execution.run(db,identity,{'id':1},follow_outbound=False)
    assert rejected.value.status_code == 409
    db.rollback()
    with pytest.raises(ValueError):outbound_followup_execution.capture(db,db.get(Invoice,identity))
    db.rollback();receipt_id=receipt(db,identity,'local-do-not-send')
    with pytest.raises(ValueError):sync_service.deliver(db,receipt_id)
    assert db.query(SendingClaim).count()==0


def test_actual_receipt_delivery_uses_claim_and_original_result_identity(db,ready,monkeypatch):
    identity=receipt(db,ready.id,'actual-receipt-adapter')
    monkeypatch.setattr(remote,'order_snapshot',lambda db,invoice:{'rows':[],'exchange_rate':1,'invoice_binding':remote.invoice_binding(invoice)})
    monkeypatch.setattr(remote,'receipt_types',lambda db:['T/T']);monkeypatch.setattr(remote,'read',lambda *a,**k:[])
    monkeypatch.setattr(attachments,'bind',lambda *a,**k:None);monkeypatch.setattr(sync_service,'refresh_accepted',lambda *a:None)
    def post(*a,**k):
        assert not db.in_transaction()
        with Session(db.get_bind()) as observer:
            claim=observer.scalar(select(SendingClaim).where(SendingClaim.operation=='receipt_push'))
            assert claim and claim.state=='sending' and claim.responsibilities['receipt_id']==identity
        return httpx.Response(200,json={'code':200,'data':{'cash_collection_id':701,'cash_collection_no':'HK701'}})
    monkeypatch.setattr(httpx,'post',post)
    sync_service.deliver(db,identity)
    saved=db.get(Receipt,identity);assert saved.xiaoman_receipt_id=='701' and saved.sync_status=='synced'
    claim=db.scalar(select(SendingClaim).where(SendingClaim.operation=='receipt_push'))
    assert claim.state=='succeeded' and claim.external_id=='701' and claim.responsibilities['bank_identity_status']=='unmapped_legacy'


@pytest.fixture
def pushable(db,ready,monkeypatch):
    from app.auth.models import ArkUser, ArkUserExternalBinding
    from app.invoice.models import InvoiceItem, XiaomanSettings
    from app.invoice import xiaoman_service
    ready.okki_new_deal=0;ready.okki_free_shipping=1;ready.okki_first_return=0
    db.get(ArkUser,1).okki_department_id=0
    db.add(ArkUserExternalBinding(ark_user_id=1,provider='okki',external_account_id='1',binding_status='active',is_primary=True))
    db.add(XiaomanSettings(id=1,default_order_status='1',default_currency='USD'))
    ready.items=[InvoiceItem(item_type='stock',product_kind='hair',product_id=11,sku_id=12,product_name='Test hair',product_display='Test hair',model='B1',color='1',length='20',net_weight_grams='20',quantity=1,price_per_piece=100,total_price=100,xiaoman_unique_id='501')]
    db.commit();identity=ready.id;db.rollback()
    monkeypatch.setattr(xiaoman_service.get_settings(),'OKKI_OUTBOUND_AUTO_ENABLED',False)
    return identity


def test_actual_order_execution_keeps_normal_legacy_flow_and_durable_send(db,pushable,monkeypatch):
    posts=[]
    def post(*a,**k):
        assert not db.in_transaction()
        with Session(db.get_bind()) as observer:
            assert observer.scalar(select(SendingClaim).where(SendingClaim.operation=='order_push')).state=='sending'
        posts.append(k['json'])
        return httpx.Response(200,json={'code':200,'data':{'order_id':'2001','product_list':[{**line,'unique_id':line.get('unique_id') or 501} for line in k['json']['product_list']]}})
    monkeypatch.setattr(httpx,'post',post)
    result=order_sync_execution.run(db,pushable,{'id':1},follow_outbound=False)
    assert result['ok'] is True and len(posts)==1
    assert db.get(Invoice,pushable).sync_status=='synced'
    assert db.scalar(select(SendingClaim).where(SendingClaim.operation=='order_push')).external_id=='2001'


def test_actual_order_unknown_is_never_resent_by_new_entry_or_expiration(db,pushable,monkeypatch):
    posts=[]
    def timeout(*a,**k):posts.append(1);raise httpx.ReadTimeout('uncertain')
    monkeypatch.setattr(httpx,'post',timeout)
    result=order_sync_execution.run(db,pushable,{'id':1},follow_outbound=False)
    assert result['ok'] is False and len(posts)==1
    db.rollback()
    with pytest.raises(HTTPException):order_sync_execution.run(db,pushable,{'id':1},follow_outbound=False)
    assert len(posts)==1
    assert db.scalar(select(SendingClaim).where(SendingClaim.operation=='order_push')).state=='unknown'


@pytest.mark.parametrize('bound',[False,True])
def test_real_original_get_recovery_closes_same_claim_without_post(db,pushable,monkeypatch,bound):
    from app.invoice import sync_recovery, xiaoman_service
    invoice=db.get(Invoice,pushable)
    if not bound:
        invoice.xiaoman_order_id=None;invoice.status='ready';invoice.sync_status='not_synced'
        invoice.items[0].xiaoman_unique_id=None
    db.commit();db.rollback();payloads=[]
    def timeout(*a,**k):payloads.append(k['json']);raise httpx.ReadTimeout('original response lost')
    monkeypatch.setattr(httpx,'post',timeout)
    assert not order_sync_execution.run(db,pushable,{'id':1},follow_outbound=False)['ok']
    invoice=db.get(Invoice,pushable)
    original_key=invoice.sync_attempt['attempt_key']
    invoice.sync_attempt={**invoice.sync_attempt,'lease_until':(beijing_now()-timedelta(minutes=1)).isoformat()}
    db.commit();db.rollback()
    if not bound:
        with pytest.raises(HTTPException) as rejected:
            sync_recovery.resolve(db,pushable,{'id':1},resolution='confirm_not_created',reason='An operator note cannot prove no remote create')
        assert rejected.value.status_code==409
        assert db.scalar(select(SendingClaim)).state=='unknown'
        db.rollback()
        monkeypatch.setattr(xiaoman_service,'binding_order',lambda *a,**k:{'order_id':'2001','order_no':'REMOTE2001','company_id':'101','name':'legacy-gated'})
    reads=[]
    def read(method,url,**kwargs):
        assert method=='GET' and not db.in_transaction()
        reads.append(kwargs['params'])
        return httpx.Response(200,json={'code':200,'data':{'order_id':'2001','company_id':'101','currency':'USD','name':'legacy-gated','amount':'100.00',
            'product_list':[{**row,'unique_id':row.get('unique_id') or 501} for row in payloads[0]['product_list']]}})
    monkeypatch.setattr(httpx,'request',read)
    result=sync_recovery.resolve(db,pushable,{'id':1},resolution='confirm_existing' if bound else 'bind_order',
        reason='Original exact order and all commercial lines verified',xiaoman_order_id=None if bound else '2001')
    claim=db.scalar(select(SendingClaim))
    assert claim.state=='succeeded' and claim.external_id=='2001' and claim.active_invoice_key is None
    assert claim.responsibilities['task_key']==original_key and len(payloads)==1 and len(reads)==1
    assert result['xiaoman_order_id']=='2001'
    assert any(row.evidence.get('original_request_readback') for row in db.query(ClaimEvidence).filter_by(claim_id=claim.id))


@pytest.fixture
def presale_targets(db,ready):
    from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, Receivable
    from app.invoice.settlement_service import digest
    ready.order_type='presale'
    plan=ShipmentSettlement(invoice_id=ready.id,sequence=1,settlement_no='legacy-presale-1',state='outbound_pending',is_final=1,quote={},quote_hash='a'*64,request_key='presale-plan',request_hash='b'*64,created_by=1)
    db.add(plan);db.flush()
    outbound_payload={'order_id':'2001','serial_id':'presale-outbound','record_list':[]}
    outgoing=ShipmentOutbound(invoice_id=ready.id,settlement_id=plan.id,outbound_no='presale-outbound',status='pending',payload=outbound_payload,payload_hash=digest(outbound_payload))
    freight_payload={'company_id':101,'name':'presale-freight','product_list':[]}
    freight=Receivable(invoice_id=ready.id,settlement_id=plan.id,business_key='presale-freight',kind='freight',amount=10,currency='USD',customer_id='101',remote_status='unverified',remote_order_name='presale-freight',remote_payload=freight_payload,remote_payload_hash=digest(freight_payload))
    db.add_all([outgoing,freight]);db.commit();ids=(outgoing.id,freight.id);db.rollback();return ids


@pytest.mark.parametrize('kind',['shipment','freight'])
def test_actual_presale_adapters_send_only_after_committed_ownership_claim(db,ready,presale_targets,monkeypatch,kind):
    from app.invoice import shipment_delivery, freight_delivery
    from app.invoice.settlement_models import ShipmentOutbound, Receivable
    from app.invoice import stock_reservations
    outgoing,freight=presale_targets
    monkeypatch.setattr(shipment_delivery,'require_delivery',lambda:None)
    monkeypatch.setattr(freight_delivery,'require_delivery',lambda:None)
    monkeypatch.setattr(shipment_delivery,'_refresh_funding',lambda *a:True)
    monkeypatch.setattr(shipment_delivery,'_dispatchable',lambda *a,**k:True)
    monkeypatch.setattr(shipment_delivery,'_live_candidate',lambda *a:db.get(ShipmentOutbound,outgoing).payload)
    monkeypatch.setattr(shipment_delivery,'refresh',lambda *a:None)
    monkeypatch.setattr(stock_reservations,'require_additional',lambda *a,**k:None)
    monkeypatch.setattr(okki_client,'find_outbound_by_serial',lambda *a:None)
    monkeypatch.setattr(freight_delivery,'freeze',lambda *a:None)
    monkeypatch.setattr(freight_delivery,'_source_active',lambda *a:None)
    monkeypatch.setattr(freight_delivery,'_matching_active_orders',lambda *a:[])
    monkeypatch.setattr(freight_delivery,'refresh',lambda *a:None)
    posts=[]
    def post(*a,**k):
        assert not db.in_transaction()
        with Session(db.get_bind()) as observer:
            claim=observer.scalar(select(SendingClaim))
            assert claim and claim.state=='sending' and claim.responsibilities['actor_id']==1
        posts.append(k['json'])
        data={'outbound_invoice_id':'3001'} if kind=='shipment' else {'order_id':'4001'}
        return httpx.Response(200,json={'code':200,'data':data})
    monkeypatch.setattr(httpx,'post',post)
    (shipment_delivery.deliver if kind=='shipment' else freight_delivery.deliver)(db,outgoing if kind=='shipment' else freight)
    assert len(posts)==1
    assert db.scalar(select(SendingClaim)).state=='succeeded'
    row=db.get(ShipmentOutbound,outgoing) if kind=='shipment' else db.get(Receivable,freight)
    assert (row.remote_id if kind=='shipment' else row.remote_order_id)==('3001' if kind=='shipment' else '4001')


@pytest.mark.parametrize('kind',['shipment','freight'])
def test_local_presale_objects_cannot_use_old_adapter_post(db,ready,presale_targets,kind):
    from app.invoice import shipment_delivery, freight_delivery
    ready.transaction_mode='local';db.get(InvoiceAuthority,ready.id).route='local';db.commit()
    outgoing,freight=presale_targets
    with pytest.raises(ValueError):
        (shipment_delivery.deliver if kind=='shipment' else freight_delivery.deliver)(db,outgoing if kind=='shipment' else freight)
    assert db.query(SendingClaim).count()==0


@pytest.mark.parametrize('adapter', ['inspection', 'worker'])
@pytest.mark.parametrize('outcome', ['accepted', 'unknown', 'local'])
def test_actual_outbound_send_adapters_keep_original_claim_and_never_replay(db,ready,monkeypatch,adapter,outcome):
    """Exercise each production send method with real immutable facts and HTTP.

    Current mirror/stock reads are synthetic; send, claim, commit, and original
    observation persistence are the production implementations.
    """
    from types import SimpleNamespace
    from uuid import uuid4
    from app.invoice import outbound_worker as worker, outbound_create_facts as creation
    from app.invoice.models import OkkiOutboundTask
    from app.shipping_inspection import outbound_execution as inspection, outbound_facts as update, audit_service
    from app.shipping_inspection import outbound_sync_plan as common
    from app.shipping_inspection.outbound_prepare import row_state
    identity=ready.id;nonce=uuid4().hex;payload={'serial_id':'original-outbound','outbound_invoice_id':'3001','record_list':[]}
    if adapter=='inspection':
        record={'outbound_record_id':'9001','outbound_invoice_id':'3001'}
        plan={'invoice_id':identity,'before':{'outbound_invoice_id':'3001'},'local_binding_fingerprint':'a'*64}
        attempt=update.start(db,identity,record,1,plan,payload,False,'manual',True)
        state=audit_service.record(db,'sync_pending',1,'9001',context={'scope':'fixture-current'},payload={},result={})
        db.flush();state_id=state.id;db.commit()
        def current(*a,**k):
            gate.authorize(db,identity,attempt.data['authority_epoch'])
            update.validate(db,attempt)
            return {'id':1},record,db.get(Invoice,identity),db.get(type(state),state_id),None,None,{}
        monkeypatch.setattr(inspection,'local',current)
        monkeypatch.setattr(inspection,'before_send',lambda *a:None)
        monkeypatch.setattr(inspection,'verify',lambda *a,**k:{'verified':False})
        send=lambda:inspection.send_attempt(db,record,{'id':1},True,attempt,'token',{})
        fact=lambda:update.get(db,update.FACT,attempt.nonce)
    else:
        task=OkkiOutboundTask(invoice_id=identity,order_id='2001',status='running')
        db.add(task);db.flush();db.refresh(task);task_id=task.id;binding=('original-binding',)
        attempt=creation.Attempt(nonce,{'protocol':1,'nonce':nonce,'invoice_id':identity,'task_id':task_id,
            'actor_id':1,'authority_epoch':1,'order_id':'2001','order':{'order_id':'2001'},'payload':payload,
            'payload_fingerprint':common.digest(payload),'binding_fingerprint':common.digest(binding),
            'task_fingerprint':common.digest(row_state(task)),'lineage':[],'started_at':beijing_now().isoformat()})
        original=creation.append(db,creation.START,nonce,attempt,{})
        state=audit_service.record(db,'create_pending',1,'create:'+str(identity),context={'scope':creation.STATE,'source':'outbound_worker'},
            request_id=str(task_id),payload={'protocol':1,'nonce':nonce},result={'started_at':attempt.data['started_at']})
        db.flush();state_id=state.id;db.commit()
        def current(*a,**k):
            gate.authorize(db,identity,1)
            return {'id':1},db.get(Invoice,identity),db.get(OkkiOutboundTask,task_id),db.get(type(state),state_id),binding,None,None,{}
        monkeypatch.setattr(worker,'local',current)
        monkeypatch.setattr(worker,'evidence',lambda *a,**k:({'order_id':'2001'},[],payload,[]))
        monkeypatch.setattr(worker,'verify',lambda *a,**k:{'verified':False})
        send=lambda:worker.send(db,identity,attempt,'token')
        fact=lambda:creation.get(db,creation.FACT,nonce)
    posts=[]
    def post(*a,**k):
        assert not db.in_transaction()
        with Session(db.get_bind()) as observer:
            claim=observer.scalar(select(SendingClaim))
            assert claim and claim.state=='sending' and claim.responsibilities['actor_id']==1
        posts.append(k['json'])
        if outcome=='unknown':raise httpx.ReadTimeout('original response lost')
        return httpx.Response(200,json={'code':200,'data':{'outbound_invoice_id':'3001','serial_id':'original-outbound'}})
    monkeypatch.setattr(httpx,'post',post)
    if outcome=='local':
        db.get(Invoice,identity).transaction_mode='local';db.get(InvoiceAuthority,identity).route='local';db.commit()
        with pytest.raises(ValueError):send()
        assert not posts and db.query(SendingClaim).count()==0
        return
    send()
    claim=db.scalar(select(SendingClaim));assert claim.state==('succeeded' if outcome=='accepted' else 'unknown')
    assert fact().result['result_class']==outcome
    db.rollback()
    with pytest.raises((ValueError,HTTPException)):send()
    assert len(posts)==1


@pytest.mark.parametrize('kind',['order','receipt','outbound'])
@pytest.mark.parametrize('outcome',['accepted','unknown','local'])
def test_real_destructive_clients_require_committed_typed_claims_and_never_replay(db,ready,monkeypatch,kind,outcome):
    from app.invoice import lifecycle_remote
    from app.shipping_inspection import outbound_delete_client
    identity=ready.id
    if outcome=='local':
        ready.transaction_mode='local';db.get(InvoiceAuthority,identity).route='local';db.commit()
        with pytest.raises(ValueError):gate.start_removal(db,identity,'original-remove',kind,'3001',{'actor_id':1},1)
        assert not db.query(SendingClaim).count();return
    grant=gate.start_removal(db,identity,'original-remove',kind,'3001',{'actor_id':1,'original_task':'reviewed-delete'},1)
    db.commit();posts=[]
    def request(method,url,**kwargs):
        assert method=='POST' and not db.in_transaction()
        with Session(db.get_bind()) as observer:
            claim=observer.scalar(select(SendingClaim))
            assert claim.state=='sending' and claim.operation==kind+'_remove' and claim.epoch==1
        posts.append(kwargs['params'])
        if outcome=='unknown':raise httpx.ReadTimeout('delete response lost')
        return httpx.Response(200,json={'code':200,'data':{}})
    monkeypatch.setattr(httpx,'request',request)
    send=lambda:outbound_delete_client.remove('token','3001',db=db,ticket=grant) if kind=='outbound' else lifecycle_remote.request('token',kind,'3001',remove=True,db=db,ticket=grant)
    if outcome=='unknown':
        with pytest.raises(ValueError):send()
    else:assert send() is True
    claim=db.scalar(select(SendingClaim));assert claim.state==('unknown' if outcome=='unknown' else 'succeeded')
    db.rollback()
    with pytest.raises(ValueError):send()
    assert len(posts)==1


@pytest.mark.parametrize('kind',['order','receipt','outbound'])
def test_destructive_clients_cannot_post_without_persistent_executor(ready,kind):
    from app.invoice import lifecycle_remote
    from app.shipping_inspection import outbound_delete_client
    with pytest.raises(ValueError):
        if kind=='outbound':outbound_delete_client.remove('token','3001')
        else:lifecycle_remote.request('token',kind,'3001',remove=True)


def test_real_cancellation_executor_owns_remove_claim_and_closes_original_get_readback(db,ready,monkeypatch):
    from app.invoice import cancellation_execution, cancellation_service
    identity=ready.id;ready.status='cancel_pending'
    ready.cancellation={'status':'pending','reason':'Original reviewed cancellation','created_by':1,'previous_status':'synced'}
    db.commit();db.rollback()
    monkeypatch.setattr(cancellation_service,'inspect',lambda *a:{'remote_exists':True,'outbounds':[],'remote_receipt_count':0,'blockers':[]})
    calls=[]
    def request(method,url,**kwargs):
        assert not db.in_transaction()
        if method=='POST':
            with Session(db.get_bind()) as observer:assert observer.scalar(select(SendingClaim)).state=='sending'
            calls.append(1);return httpx.Response(200,json={'code':200,'data':{}})
        return httpx.Response(200,json={'code':404,'message':'Not Found Resource','data':None})
    monkeypatch.setattr(httpx,'request',request)
    result=cancellation_execution.remove_authorized(db,identity,{'id':1})
    assert result['status']=='remote_deleted' and len(calls)==1
    claim=db.scalar(select(SendingClaim));assert claim.state=='succeeded' and claim.external_id=='2001'
    assert any(row.evidence.get('original_request_readback') for row in db.query(ClaimEvidence).filter_by(claim_id=claim.id))


def test_real_receipt_deletion_unknown_can_only_read_original_task_without_second_post(db,ready,monkeypatch):
    from types import SimpleNamespace
    from app.receipt import deletion_service
    identity=receipt(db,ready.id,'original-receipt-delete')
    row=db.get(Receipt,identity);row.sync_status='synced';row.xiaoman_receipt_id='701';row.collect_status=1;db.commit();db.rollback()
    monkeypatch.setattr(deletion_service,'_read',lambda *a:{'status':'active','detail':{'cash_collection_id':'701','order_id':'2001','amount':'10.00','currency':'USD','collect_status':1}})
    preview=deletion_service.preview(db,identity,{'id':1});db.commit();posts=[]
    def request(method,url,**kwargs):
        assert method=='POST' and not db.in_transaction()
        with Session(db.get_bind()) as observer:assert observer.scalar(select(SendingClaim)).state=='sending'
        posts.append(1);raise httpx.ReadTimeout('original delete unknown')
    monkeypatch.setattr(httpx,'request',request)
    body=SimpleNamespace(confirmed=True,reason='Original reviewed receipt deletion',expected_version=preview['expected_version'])
    first=deletion_service.remove(db,identity,body,{'id':1});db.commit()
    assert first['status']=='uncertain'
    second=deletion_service.remove(db,identity,body,{'id':1});db.commit()
    assert second['status']=='uncertain' and len(posts)==1
    assert db.scalar(select(SendingClaim)).state=='unknown'


@pytest.mark.parametrize('outcome',['accepted','unknown','local'])
def test_real_outbound_delete_service_never_holds_locks_over_http_or_replays_unknown(db,ready,monkeypatch,outcome):
    from app.shipping_inspection import outbound_delete_service as deletion
    monkeypatch.setattr(deletion, 'ensure_access_token', lambda *a: 'isolated-token')
    record={'outbound_record_id':'9001','outbound_invoice_id':'3001','outbound_no':'ORIGINAL-OUTBOUND','company_id':'101'}
    monkeypatch.setattr(deletion,'_mirror_order_ids',lambda *a:['2001'])
    state={'exists':True};posts=[]
    def read(*a):
        assert not db.in_transaction()
        return {'outbound_invoice_id':'3001','serial_id':'ORIGINAL-OUTBOUND','status':1,'company_info':{'id':'101'},'record_list':[{'order_id':'2001'}]} if state['exists'] else None
    monkeypatch.setattr(deletion.remote,'read',read)
    def request(method,url,**kwargs):
        assert method=='POST' and not db.in_transaction()
        with Session(db.get_bind()) as observer:
            claim=observer.scalar(select(SendingClaim))
            assert claim.state=='sending' and claim.responsibilities['invoice_ids']==[ready.id]
        posts.append(1)
        if outcome=='unknown':raise httpx.ReadTimeout('original destructive response unknown')
        state['exists']=False
        return httpx.Response(200,json={'code':200,'data':{}})
    monkeypatch.setattr(httpx,'request',request)
    if outcome=='local':
        ready.transaction_mode='local';db.get(InvoiceAuthority,ready.id).route='local';db.commit()
        with pytest.raises(ValueError):deletion.delete_outbound(db,record,1)
        assert not posts and not db.query(SendingClaim).count();return
    if outcome=='unknown':
        with pytest.raises(deletion.OutboundDeleteError):deletion.delete_outbound(db,record,1)
        with pytest.raises(deletion.OutboundDeleteError):deletion.delete_outbound(db,record,1)
    else:
        assert deletion.delete_outbound(db,record,1)['deleted']
        assert deletion.delete_outbound(db,record,1)['deleted']
    claim=db.scalar(select(SendingClaim))
    assert claim.state==('unknown' if outcome=='unknown' else 'succeeded') and len(posts)==1
