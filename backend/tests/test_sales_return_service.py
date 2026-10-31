"""End-to-end local finance/state tests; only source facts are fixture-controlled."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserExternalBinding
from app.core.database import get_db
from app.invoice.models import Invoice
from app.models.commission import CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus
from app.models.customer import CustomerCommissionSnapshot
from app.receipt.models import Receipt
from app.receipt import service as receipts
from app.sales_return import balance, commission, read_service, receiving_service, schemas, service, sources
from app.sales_return.models import SalesReturn, ReturnAllocation, ReturnEffect, ReturnItem, ReturnReceipt, ReturnReceiving
from app.sales_return.router import router, execute
from tests.test_sales_return_sources import source_db  # noqa: F401 - real isolated mirror fixture

PERMISSIONS = ['sales_return:read','sales_return:write','sales_return:delete','sales_return:admin',
               'sales_return_receiving:write','receipt:read']
USER = {'id':7,'sub':'7','roles':['returns_test'],'permissions':PERMISSIONS}


def facts(paid='600.00'):
    return {'order_id':'101','order_no':'PI-101','customer_id':'C1','customer_name':'Company',
        'owner_okki_user_id':'70','sales_user_id':7,'invoice_id':None,'currency':'USD',
        'goods_amount':'1000.00','goods_amount_usd':'1000.00','gmv_eligible':True,
        'order_role':'repeat','departments':[{'department_id':1,'name':'Original team','rate':100}],
        'binding_hash':'original-facts','lines':[{'source_key':'OUT-1:LINE-1','outbound_id':'OUT-1',
        'outbound_line_id':'LINE-1','order_line_id':'ORDER-LINE-1','product_id':'P1','sku_id':'S1',
        'product_name':'Hair','specification':'Black','quantity':10,'net_amount':'1000.00','net_amount_usd':'1000.00'}],
        'payments':[{'payment_id':'PAY-1','principal':paid,'principal_usd':paid,'collection_date':'2025-12-01','currency':'USD'}]}


def draft(key='create-return-key-0001',**changes):
    values={'order_id':'101','return_type':'return_refund','reason_code':'quality','reason':'Verified quality return',
        'lines':[{'source_key':'OUT-1:LINE-1','quantity':10,'reduction_amount':'1000.00'}],
        'request_key':key}
    values.update(changes)
    return schemas.Create(**values)


@pytest.fixture
def env(db,monkeypatch):
    snapshot = facts()
    monkeypatch.setattr(sources,'snapshot',lambda *_args,**_kwargs:deepcopy(snapshot))
    role = ArkRole(name='returns_test',label='Return test')
    role.permissions = [ArkPermission(code=code,module=code.split(':')[0],action=code.split(':')[1],label=code) for code in PERMISSIONS]
    user = ArkUser(id=7,username='return-test',password_hash='test-only',real_name='Test',roles=[role])
    db.add_all([user,ArkUserExternalBinding(ark_user_id=7,provider='okki',external_account_id='70',binding_status='active',is_primary=True)])
    db.commit()
    return db,snapshot,monkeypatch


def activate(db,body=None,key='activate-return-key-0001'):
    body = body or draft()
    quote = service.preview(db,body,USER)
    row = service.create(db,body,USER)
    command = schemas.Activate(version=row.version,quote_version=quote['quote_version'],request_key=key)
    service.activate(db,row.id,command,USER)
    return row,command


def count(db,model):
    return db.scalar(select(func.count()).select_from(model))


def test_create_idempotency_and_preview_none_refund_activates_once(env):
    db,snapshot,_ = env
    body = draft()
    before = service.preview(db,body,USER)
    assert before['refund_amount'] == '600.00'
    row = service.create(db,body,USER)
    assert service.create(db,body,USER).id == row.id
    assert count(db,SalesReturn) == 1
    command=schemas.Activate(version=row.version,quote_version=before['quote_version'],request_key='activate-return-key-0001')
    service.activate(db,row.id,command,USER)
    assert service.activate(db,row.id,command,USER).id == row.id
    assert count(db,ReturnEffect) == count(db,ReturnReceipt) == count(db,ReturnAllocation) == 1
    assert db.scalar(select(ReturnEffect.amount_usd)) == Decimal('-1000')
    assert db.scalar(select(ReturnReceipt.amount)) == Decimal('-600')
    assert row.waived_amount == Decimal('400')
    payment=db.scalar(select(SyncedPayment).where(SyncedPayment.source=='ark_return'))
    assert payment.payment_amount == Decimal('-600')
    assert payment.payment_id == f'ark_return:{db.scalar(select(ReturnReceipt.id))}'
    assert payment.service_fee == 0
    assert count(db,Receipt) == 0  # no remote receipt outbox ever created
    with pytest.raises(HTTPException) as error:
        service.create(db,draft(reason='Different content same key'),USER)
    assert error.value.status_code == 409


def test_stale_quote_cannot_activate_changed_source(env):
    db,snapshot,_=env
    body=draft()
    quote=service.preview(db,body,USER)
    row=service.create(db,body,USER)
    snapshot['lines'][0]['net_amount']='1100.00'
    with pytest.raises(HTTPException) as error:
        service.activate(db,row.id,schemas.Activate(version=1,quote_version=quote['quote_version'],request_key='stale-activate-key-1'),USER)
    assert error.value.status_code == 409
    assert row.status == 'draft'
    assert count(db,ReturnEffect) == count(db,ReturnReceipt) == 0


def test_two_drafts_cannot_consume_same_return_quota(env):
    db,_,_=env
    first=service.create(db,draft('first-draft-key-0001'),USER)
    second=service.create(db,draft('second-draft-key-001'),USER)
    quote=service.preview(db,read_service.draft_body(db,first),USER)
    service.activate(db,first.id,schemas.Activate(version=1,quote_version=quote['quote_version'],request_key='first-activate-key-01'),USER)
    with pytest.raises((ValueError,HTTPException)):
        service.activate(db,second.id,schemas.Activate(version=1,quote_version=quote['quote_version'],request_key='second-activate-key-1'),USER)
    assert second.status == 'draft'
    assert count(db,ReturnEffect) == count(db,ReturnReceipt) == 1


def test_execute_rolls_back_all_financial_rows_on_projection_failure(env):
    db,snapshot,_=env
    row=service.create(db,draft(),USER)
    db.commit()
    quote=service.preview(db,read_service.draft_body(db,row),USER)
    identity=row.id
    command=schemas.Activate(version=1,quote_version=quote['quote_version'],request_key='failure-activate-key')
    def fail_insert(_mapper,_connection,_target):
        raise ValueError('Injected storage failure before transaction commit')
    event.listen(SyncedPayment,'before_insert',fail_insert)
    try:
        with pytest.raises(HTTPException) as error:
            execute(db,USER,'sales_return:write',lambda current: service.activate(db,identity,command,current),write=True)
    finally:
        event.remove(SyncedPayment,'before_insert',fail_insert)
    assert error.value.status_code == 409
    assert db.get(SalesReturn,identity).status == 'draft'
    assert count(db,ReturnEffect)==count(db,ReturnReceipt)==count(db,ReturnAllocation)==0
    assert count(db,SyncedPayment)==0


def test_refund_only_rejects_receiving_and_does_not_make_inventory_records(env):
    db,_,_=env
    row,_=activate(db,draft(return_type='refund_only'))
    item=db.scalar(select(ReturnItem).where(ReturnItem.return_id==row.id))
    with pytest.raises(HTTPException) as error:
        receiving_service.receive(db,row.id,schemas.Receiving(item_id=item.id,quantity=1,accepted_quantity=1,
            rejected_quantity=0,pending_quantity=0,request_key='refund-only-receive-key'),USER)
    assert error.value.status_code==409
    assert count(db,ReturnReceiving)==0
    assert read_service.describe(db,row)['receiving_status']=='not_required'


def test_receiving_is_cumulative_inspection_is_real_and_stock_not_fabricated(env):
    db,_,_=env
    row,_=activate(db)
    item=db.scalar(select(ReturnItem).where(ReturnItem.return_id==row.id))
    body=schemas.Receiving(item_id=item.id,quantity=6,accepted_quantity=3,rejected_quantity=2,
        pending_quantity=1,request_key='partial-receive-key-01')
    receiving_service.receive(db,row.id,body,USER)
    receiving_service.receive(db,row.id,body,USER)
    assert count(db,ReturnReceiving)==1
    assert read_service.describe(db,row)['receiving_status']=='partially_received'
    with pytest.raises(HTTPException):
        receiving_service.receive(db,row.id,schemas.Receiving(item_id=item.id,quantity=5,accepted_quantity=5,
            rejected_quantity=0,pending_quantity=0,request_key='over-receive-key-0001'),USER)
    receiving_service.receive(db,row.id,schemas.Receiving(item_id=item.id,quantity=4,accepted_quantity=4,
        rejected_quantity=0,pending_quantity=0,request_key='complete-receive-key-01'),USER)
    assert db.scalar(select(func.sum(ReturnReceiving.quantity)))==10
    assert read_service.describe(db,row)['receiving_status']=='pending_inspection'
    event=db.scalar(select(ReturnReceiving))
    with pytest.raises(HTTPException) as error:
        receiving_service.stock(db,row.id,event.id,schemas.Stock(reference='unverified-inbound',request_key='stock-unverified-key-01'),USER)
    assert error.value.status_code==409
    assert event.stock_status=='not_stocked'
    with pytest.raises(HTTPException):
        service.reverse(db,row.id,schemas.Reverse(version=row.version,request_key='reverse-stock-key-01',reason='Physical received requires warehouse reversal'),USER)


def test_paid_cash_requires_recovery_before_reversal_and_restores_net_balance(env):
    db,_,_=env
    row,_=activate(db)
    original={'total_amount':'1000','registered_amount':'600','effective_amount':'600','remaining_amount':'400','version':'v1'}
    adjusted=balance.overlay(db,'101',original)
    assert Decimal(adjusted['total_amount'])==Decimal(adjusted['registered_amount'])==Decimal(adjusted['remaining_amount'])==0
    service.cash(db,row.id,schemas.Cash(version=row.version,status='paid',evidence='Verified bank refund transaction'),USER)
    with pytest.raises(HTTPException):
        service.reverse(db,row.id,schemas.Reverse(version=row.version,request_key='reverse-before-recover',reason='Must recover money first'),USER)
    service.cash(db,row.id,schemas.Cash(version=row.version,status='recovered',evidence='Verified recovered cash transaction'),USER)
    command=schemas.Reverse(version=row.version,request_key='reverse-after-recover',reason='Actual refund recovered and corrected')
    service.reverse(db,row.id,command,USER)
    assert service.reverse(db,row.id,command,USER).status=='reversed'
    assert count(db,ReturnEffect)==count(db,ReturnReceipt)==2
    assert balance.overlay(db,'101',original)==original
    assert sum(db.scalars(select(SyncedPayment.payment_amount)).all())==0


def test_original_cross_period_commission_people_and_actual_amount_are_preserved(env):
    db,_,_=env
    payment=SyncedPayment(payment_id='PAY-1',source='okki',order_id='101',customer_id='C1',
        payment_date=date(2025,12,1),payment_amount=600,service_fee=0)
    batch=CommissionBatch(batch_name='Old paid commission',period_start=date(2025,12,1),period_end=date(2025,12,31),status='confirmed')
    db.add_all([payment,batch])
    db.flush()
    db.add(CommissionDetail(batch_id=batch.id,payment_id='PAY-1',order_id='101',customer_id='C1',payment_amount=600,
        salesperson_id='old-sales',salesperson_rate=Decimal('.02'),salesperson_commission=Decimal('12'),
        supervisor_id='old-supervisor',supervisor_rate=Decimal('.01'),supervisor_commission=Decimal('9'),
        second_supervisor_id='old-second',second_supervisor_rate=Decimal('.005'),second_supervisor_commission=Decimal('3'),status='paid'))
    db.add(CustomerCommissionSnapshot(customer_id='C1',salesperson_id='new-sales',salesperson_rate=Decimal('.5'),
        is_current=True,is_complete=True,source='manual'))
    db.add(PaymentCommissionStatus(payment_id='PAY-1',batch_id=batch.id))
    db.flush()
    row,_=activate(db)
    negative=db.scalar(select(SyncedPayment).where(SyncedPayment.source=='ark_return'))
    rows=commission.return_rows(db,negative)
    assert len(rows)==1
    result=rows[0]
    assert result['salesperson_id']=='old-sales' and result['supervisor_id']=='old-supervisor'
    assert result['second_supervisor_id']=='old-second'
    assert result['salesperson_commission']==Decimal('-12')
    assert result['supervisor_commission']==Decimal('-9')
    assert result['second_supervisor_commission']==Decimal('-3')
    assert negative.payment_date>date(2025,12,31)
    from app.services.commission_calculator import calculate_commission
    refund_batch=CommissionBatch(batch_name='Current refund commission',period_start=negative.payment_date,
        period_end=negative.payment_date,status='draft')
    db.add(refund_batch)
    db.flush()
    calculated=calculate_commission(db,refund_batch.id)
    assert calculated.errors==[]
    assert calculated.total_payments==1
    actual=db.scalar(select(CommissionDetail).where(CommissionDetail.batch_id==refund_batch.id))
    assert actual.salesperson_id=='old-sales' and actual.supervisor_id=='old-supervisor'
    assert actual.salesperson_commission==Decimal('-12') and actual.supervisor_commission==Decimal('-9')
    assert actual.second_supervisor_id=='old-second' and actual.second_supervisor_commission==Decimal('-3')


def test_receipt_union_uses_single_pagination_and_original_owner_scope(env):
    db,_,_=env
    row,_=activate(db)
    invoice=Invoice(invoice_no='ORDINARY-PI',invoice_date=date(2026,10,1),customer_id='C1',customer_name='Company',
        sales_user_id=7,currency='USD',xiaoman_order_id='102')
    db.add(invoice)
    db.flush()
    db.add(Receipt(receipt_no='POSITIVE-RECEIPT',invoice_id=invoice.id,source='manual',request_key='positive-receipt-key',
        request_hash='h',amount=100,currency='USD',collection_date=date(2026,10,1),payment_type='bank',bank_charge=0,
        customer_id='C1',xiaoman_order_id='102',created_by=7,status='active',sync_status='pending'))
    db.flush()
    first=receipts.list_receipts(db,USER,page=1,page_size=1,sort_field='amount',sort_order='asc')
    second=receipts.list_receipts(db,USER,page=2,page_size=1,sort_field='amount',sort_order='asc')
    assert first['total']==second['total']==2
    assert first['items'][0]['source']=='sales_return' and Decimal(first['items'][0]['amount'])==-600
    assert second['items'][0]['source']=='manual'
    other={'id':8,'sub':'8','roles':['other'],'permissions':['receipt:read']}
    db.add(ArkUserExternalBinding(ark_user_id=8,provider='okki',external_account_id='OTHER',binding_status='active',is_primary=True))
    db.flush()
    assert receipts.list_receipts(db,other)['total']==0
    filtered=receipts.list_receipts(db,USER,source='sales_return')
    assert filtered['total']==1 and filtered['items'][0]['editable'] is False


def test_http_create_preview_activate_and_live_permission_revocation(env):
    db,snapshot,_=env
    app=FastAPI()
    app.include_router(router,prefix='/api/sales-returns')
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:USER
    client=TestClient(app)
    body=draft().model_dump(mode='json')
    response=client.post('/api/sales-returns/preview',json={key:value for key,value in body.items() if key!='request_key'})
    assert response.status_code==200,response.text
    quote=response.json()['data']
    created=client.post('/api/sales-returns',json=body)
    assert created.status_code==200,created.text
    document=created.json()['data']
    activated=client.post(f"/api/sales-returns/{document['id']}/activate",json={'version':document['version'],
        'quote_version':quote['quote_version'],'request_key':'http-activate-key-0001'})
    assert activated.status_code==200,activated.text
    assert activated.json()['data']['status']=='effective'
    user=db.get(ArkUser,7)
    user.roles=[]
    db.commit()
    denied=client.get(f"/api/sales-returns/{document['id']}")
    assert denied.status_code==403,denied.text


def test_real_mirror_sources_create_and_activate_without_pi(source_db):
    db=source_db
    body=draft('actual-mirror-key-0001',lines=[{'source_key':'OUT-1:REMOTE-LINE','quantity':2,'reduction_amount':'50.00'}])
    row,_=activate(db,body)
    assert row.invoice_id is None
    assert row.refund_amount==50 and row.reduction_amount==50
    assert db.scalar(select(ReturnEffect.amount_usd))==-50
    assert db.scalar(select(ReturnReceipt.amount))==-50


def test_actual_receipt_balance_blocks_recollecting_waived_debt(env):
    from app.receipt import balance as receipt_balance
    db,_,_=env
    activate(db)
    invoice=Invoice(invoice_no='EXISTING-ORIGINAL',invoice_date=date(2025,12,1),customer_id='C1',
        customer_name='Company',sales_user_id=7,currency='USD',total_amount=1000,xiaoman_order_id='101')
    db.add(invoice)
    db.flush()
    summary=receipt_balance.calculate(db,invoice,{'rows':[{'cash_collection_id':'PAY-1','currency':'USD',
        'amount':'600.00','collect_status':1}]})
    assert Decimal(summary['total_amount'])==Decimal(summary['registered_amount'])==Decimal(summary['remaining_amount'])==0
    with pytest.raises(ValueError):
        receipt_balance.ensure_available(summary,Decimal('.01'))


@pytest.mark.parametrize('changed',['customer_id','currency','owner_okki_user_id','invoice_id','sales_user_id'])
def test_admin_cannot_activate_saved_draft_with_changed_identity_even_with_fresh_quote(env,changed):
    db,snapshot,_=env
    admin={'id':7,'sub':'7','roles':['super_admin'],'permissions':[]}
    row=service.create(db,draft(),admin)
    if changed=='customer_id': snapshot['customer_id']='OTHER-CUSTOMER'
    if changed=='currency':
        snapshot['currency']='EUR'
        snapshot['payments'][0]['currency']='EUR'
    if changed=='owner_okki_user_id': snapshot['owner_okki_user_id']='OTHER-OWNER'
    if changed=='sales_user_id': snapshot['sales_user_id']=8
    if changed=='invoice_id':
        invoice=Invoice(invoice_no='NEW-LINKED-PI',invoice_date=date(2026,10,1),customer_id='C1',
            customer_name='Company',sales_user_id=7,currency='USD',xiaoman_order_id='101')
        db.add(invoice)
        db.flush()
        snapshot['invoice_id']=invoice.id
    fresh=service.preview(db,read_service.draft_body(db,row),admin)
    with pytest.raises(HTTPException) as error:
        service.activate(db,row.id,schemas.Activate(version=row.version,quote_version=fresh['quote_version'],
            request_key='changed-identity-activate'),admin)
    assert error.value.status_code==409
    assert '更新草稿' in error.value.detail
    assert row.status=='draft'
    assert count(db,ReturnEffect)==count(db,ReturnReceipt)==0


@pytest.mark.parametrize('binding_mode',['unbound','ambiguous'])
def test_ordinary_receipts_remain_readable_without_unique_okki_binding(env,binding_mode):
    db,_,_=env
    row,_=activate(db)
    # Historical return has no known Ark salesperson: only an unambiguous exact
    # external identity could grant access; ordinary invoices already know it.
    row.sales_user_id=None
    db.query(ArkUserExternalBinding).filter(ArkUserExternalBinding.ark_user_id==7).delete()
    if binding_mode=='ambiguous':
        for external in ('70','OTHER'):
            db.add(ArkUserExternalBinding(ark_user_id=7,provider='okki',external_account_id=external,
                binding_status='active',is_primary=external=='70'))
    invoice=Invoice(invoice_no='OWN-ORDINARY-PI',invoice_date=date(2026,10,1),customer_id='C1',
        customer_name='Company',sales_user_id=7,currency='USD',xiaoman_order_id='102')
    db.add(invoice)
    db.flush()
    db.add(Receipt(receipt_no='OWN-ORDINARY-CASH',invoice_id=invoice.id,source='manual',
        request_key='own-cash-without-binding',request_hash='h',amount=100,currency='USD',
        collection_date=date(2026,10,1),payment_type='bank',bank_charge=0,customer_id='C1',
        xiaoman_order_id='102',created_by=7,status='active',sync_status='pending'))
    db.flush()
    result=receipts.list_receipts(db,USER)
    assert result['total']==1
    assert result['items'][0]['receipt_no']=='OWN-ORDINARY-CASH'
    assert result['items'][0]['source']=='manual'
