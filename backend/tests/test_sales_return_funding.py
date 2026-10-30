"""Presale Q limits never borrow another batch's original principal."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, SettlementApplication, Receivable
from app.receipt.models import Receipt
from app.sales_return import funding
from app.sales_return.models import ReturnAllocation, ReturnEffect, ReturnItem, ReturnReceipt, SalesReturn


def _quote(goods, *, credit=False, pool=None):
    return {'funding_version':2,'payment_term':'ship_first' if credit else 'pay_first','currency':'USD',
        'goods_amount':str(goods),'packaging_amount':'0','handling_amount':'0','freight_amount':'0',
        'funding_total_amount':str(goods),'goods_payment_due':str(goods) if not pool else '0',
        'goods_payment_charge':'0','freight_payment_due':'0','new_payment_due':str(goods) if not pool else '0',
        'deposit_applied':'0','is_final':False,'pool_applications':pool or []}


@pytest.fixture
def funded(db):
    invoice = Invoice(invoice_no='PS-1', invoice_date=date(2026,10,1), customer_id='C1',
        customer_name='Company', order_type='presale', currency='USD', xiaoman_order_id='101')
    db.add(invoice)
    db.flush()
    receipt = Receipt(receipt_no='RC-1', invoice_id=invoice.id, purpose='presale_advance', source='manual',
        request_key='original-cash-1', request_hash='x', amount=300, currency='USD',
        collection_date=date(2026,10,1), payment_type='bank', bank_charge=0, customer_id='C1',
        xiaoman_order_id='101', xiaoman_receipt_id='PAY-1', collect_status=1, status='active',
        sync_status='synced', created_by=7)
    db.add(receipt)
    db.flush()
    settlements, outbounds, applications = [], [], []
    source_lines = []
    for number, value in ((1,100),(2,200)):
        settlement = ShipmentSettlement(invoice_id=invoice.id, sequence=number, settlement_no=f'SET-{number}',
            state='shipped', is_final=0, quote=_quote(value,pool=[{'receipt_id':receipt.id,'component':'goods',
                'purpose':'presale_advance','amount':str(value),'bank_charge':'0'}]), quote_hash='q',
            request_key=f'settlement-key-{number}', request_hash='h', created_by=7)
        db.add(settlement)
        db.flush()
        order_line = f'ORDER-LINE-{number}'
        outbound = ShipmentOutbound(invoice_id=invoice.id, settlement_id=settlement.id,
            outbound_no=f'OUT-{number}', status='shipped', remote_id=f'REMOTE-OUT-{number}', payload_hash='h',
            payload={'record_list':[{'order_record_id':order_line,'order_id':'101','product_id':'P1',
                'sku_id':'S1','outbound_count':1}]},
            remote_line_snapshot={order_line:{'outbound_record_id':f'REMOTE-LINE-{number}'}})
        app = SettlementApplication(settlement_id=settlement.id, receipt_id=receipt.id,
            component='goods', amount=value, bank_charge=0, status='applied')
        db.add_all([outbound,app])
        source_lines.append({'source_key':f'REMOTE-OUT-{number}:REMOTE-LINE-{number}',
            'outbound_id':f'REMOTE-OUT-{number}', 'outbound_line_id':f'REMOTE-LINE-{number}',
            'order_line_id':order_line, 'product_id':'P1','sku_id':'S1','quantity':1,
            'net_amount':str(value),'net_amount_usd':str(value)})
        settlements.append(settlement)
        outbounds.append(outbound)
        applications.append(app)
    db.flush()
    snapshot = {'invoice_id':invoice.id,'order_id':'101','customer_id':'C1','currency':'USD',
        'lines':source_lines,'payments':[{'payment_id':'PAY-1','principal':'300.00',
        'principal_usd':'300.00','collection_date':'2026-10-01','currency':'USD'}]}
    body = SimpleNamespace(lines=[SimpleNamespace(source_key=source_lines[0]['source_key'])])
    return db,invoice,receipt,settlements,outbounds,applications,snapshot,body


def test_only_selected_batch_principal_is_refundable_and_input_is_unchanged(funded):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    original = deepcopy(snapshot)
    result = funding.constrain(db,snapshot,body,{'refunds':{}})
    assert snapshot == original
    assert result['payments'][0]['principal'] == '300.00'
    assert Decimal(result['payments'][0]['refundable_amount']) == 100
    assert result['payments'][0]['funding_limits'] == [{'settlement_id':settlements[0].id,'amount':'100.00'}]
    assert result['funding_batches'] == [{'settlement_id':settlements[0].id,'outbound_id':'REMOTE-OUT-1'}]


def _previous(db, invoice, settlement_id, amount=40):
    previous = SalesReturn(return_no='RETURN-OLD',order_id='101',order_no='PS-1',invoice_id=invoice.id,
        customer_id='C1',customer_name='Company',owner_okki_user_id='70',return_type='return_refund',
        currency='USD',reduction_amount=amount,refund_amount=amount,waived_amount=0,
        reason_code='quality',reason='Previous refund',status='effective',request_key='previous-return',
        request_hash='old',created_by=7)
    db.add(previous)
    db.flush()
    allocation = ReturnAllocation(return_id=previous.id,original_payment_id='PAY-1',original_principal=300,
        original_principal_usd=300,refund_amount=amount,refund_amount_usd=amount,basis={},
        funding=[{'settlement_id':settlement_id,'amount':str(amount)}])
    db.add(allocation)
    number=1 if settlement_id==db.query(ShipmentSettlement.id).order_by(ShipmentSettlement.id).first()[0] else 2
    db.add(ReturnItem(return_id=previous.id,source_key=f'REMOTE-OUT-{number}:REMOTE-LINE-{number}',
        outbound_id=f'REMOTE-OUT-{number}',outbound_line_id=f'REMOTE-LINE-{number}',order_line_id=f'ORDER-LINE-{number}',
        product_id='P1',sku_id='S1',product_name='Hair',quantity=1,reduction_amount=amount,reduction_usd=amount,
        source_snapshot={'outbound_id':f'REMOTE-OUT-{number}'}))
    db.flush()
    return previous,allocation


def test_previous_refund_consumes_the_same_batch_edge(funded):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    _previous(db,invoice,settlements[0].id)
    result = funding.constrain(db,snapshot,body,{'refunds':{'PAY-1':Decimal(40)}})
    payment = result['payments'][0]
    assert Decimal(payment['refundable_amount']) - 40 == 60
    assert Decimal(payment['funding_limits'][0]['amount']) == 60


def test_other_batch_refund_does_not_reduce_selected_edge_but_counts_in_total_p(funded):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    _previous(db,invoice,settlements[1].id)
    result = funding.constrain(db,snapshot,body,{'refunds':{'PAY-1':Decimal(40)}})
    payment = result['payments'][0]
    assert Decimal(payment['refundable_amount']) - 40 == 100
    assert Decimal(payment['funding_limits'][0]['amount']) == 100


@pytest.mark.parametrize('change', ['missing_line_snapshot','wrong_remote_line','unapplied','wrong_receipt','wrong_quote_currency','unshipped'])
def test_unverified_funding_never_borrows_another_batch(funded,change):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    if change == 'missing_line_snapshot': outbounds[0].remote_line_snapshot = None
    if change == 'wrong_remote_line': outbounds[0].remote_line_snapshot = {'ORDER-LINE-1':{'outbound_record_id':'WRONG'}}
    if change == 'unapplied': apps[0].status = 'reserved'
    if change == 'wrong_receipt': receipt.currency = 'EUR'
    if change == 'wrong_quote_currency': settlements[0].quote = {'currency':'EUR'}
    if change == 'unshipped': settlements[0].state = 'outbound_pending'
    db.flush()
    with pytest.raises(HTTPException) as error:
        funding.constrain(db,snapshot,body,{'refunds':{}})
    assert error.value.status_code == 409


def test_missing_legacy_funding_record_blocks_repeated_refund(funded):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    previous,allocation = _previous(db,invoice,settlements[0].id)
    allocation.funding = []
    db.flush()
    with pytest.raises(HTTPException) as error:
        funding.constrain(db,snapshot,body,{'refunds':{'PAY-1':Decimal(40)}})
    assert error.value.status_code == 409


def test_reversal_releases_prior_batch_refund_occupancy(funded):
    db,invoice,receipt,settlements,outbounds,apps,snapshot,body = funded
    previous,allocation = _previous(db,invoice,settlements[0].id)
    previous.status = 'reversed'
    db.flush()
    payment = funding.constrain(db,snapshot,body,{'refunds':{}})['payments'][0]
    assert Decimal(payment['refundable_amount']) == 100


def _unpaid_credit(db, *, pending=False):
    invoice=Invoice(invoice_no='CREDIT-PS',invoice_date=date(2026,10,1),customer_id='C1',customer_name='Company',
        order_type='presale',currency='USD',xiaoman_order_id='CREDIT-101',total_amount=1000)
    db.add(invoice)
    db.flush()
    settlement=ShipmentSettlement(invoice_id=invoice.id,sequence=1,settlement_no='CREDIT-SET',state='shipped',
        is_final=0,quote=_quote(1000,credit=True),quote_hash='frozen-credit-quote',request_key='credit-batch-key',
        request_hash='frozen',created_by=7)
    db.add(settlement)
    db.flush()
    outbound=ShipmentOutbound(invoice_id=invoice.id,settlement_id=settlement.id,outbound_no='CREDIT-OUT',
        status='shipped',remote_id='CREDIT-REMOTE',payload_hash='frozen',
        payload={'record_list':[{'order_record_id':'CL1','order_id':'CREDIT-101','product_id':'1','sku_id':'1','outbound_count':10}]},
        remote_line_snapshot={'CL1':{'outbound_record_id':'CREDIT-LINE'}})
    db.add(outbound)
    receipt=None
    if pending:
        target=Receivable(invoice_id=invoice.id,business_key=f'invoice:{invoice.id}:goods',kind='goods',
            amount=1000,handling_amount=0,currency='USD',customer_id='C1',remote_order_id='CREDIT-101',remote_status='bound')
        db.add(target)
        db.flush()
        receipt=Receipt(receipt_no='CREDIT-UNPAID',invoice_id=invoice.id,receivable_id=target.id,purpose='presale_goods',
            source='manual',request_key='credit-unpaid-key',request_hash='frozen',amount=1000,currency='USD',
            collection_date=date(2026,10,1),payment_type='bank',bank_charge=0,customer_id='C1',
            xiaoman_order_id='CREDIT-101',xiaoman_receipt_id='UNPAID-PAY',collect_status=0,status='active',
            sync_status='synced',created_by=7)
        db.add(receipt)
        db.flush()
        db.add(SettlementApplication(settlement_id=settlement.id,receipt_id=receipt.id,component='goods',
            amount=1000,bank_charge=0,status='reserved'))
    db.flush()
    snapshot={'invoice_id':invoice.id,'order_id':'CREDIT-101','order_no':'CREDIT-PS','customer_id':'C1','customer_name':'Company',
        'owner_okki_user_id':'70','sales_user_id':7,'currency':'USD','goods_amount':'1000.00','goods_amount_usd':'1000.00',
        'order_role':'repeat','gmv_eligible':True,'departments':[{'department_id':1,'rate':100}],
        'binding_hash':'frozen-credit-source','payments':[],
        'lines':[{'source_key':'CREDIT-REMOTE:CREDIT-LINE','outbound_id':'CREDIT-REMOTE','outbound_line_id':'CREDIT-LINE',
        'order_line_id':'CL1','product_id':'1','sku_id':'1','product_name':'Hair','specification':'',
        'quantity':10,'net_amount':'1000.00','net_amount_usd':'1000.00'}]}
    from app.sales_return.schemas import Create
    body=Create(order_id='CREDIT-101',return_type='return_refund',reason_code='quality',reason='Unpaid credit goods returned',
        request_key='credit-return-request-1',lines=[{'source_key':'CREDIT-REMOTE:CREDIT-LINE','quantity':10,'reduction_amount':'1000.00'}])
    return invoice,settlement,receipt,snapshot,body


@pytest.mark.parametrize('pending',[False,True])
def test_verified_ship_first_without_cash_activates_full_goods_waiver(db,monkeypatch,pending):
    from app.sales_return import schemas,service,sources
    from app.models.commission import SyncedPayment
    invoice,batch,receipt,snapshot,body=_unpaid_credit(db,pending=pending)
    monkeypatch.setattr(sources,'snapshot',lambda *_args,**_kwargs:deepcopy(snapshot))
    admin={'id':7,'roles':['super_admin'],'permissions':[]}
    quote=service.preview(db,body,admin)
    assert Decimal(quote['reduction_amount'])==1000 and Decimal(quote['refund_amount'])==0 and Decimal(quote['waived_amount'])==1000
    assert quote['order']['payments']==[] and quote['allocations']==[]
    assert quote['order']['funding_batches']==[{'settlement_id':batch.id,'outbound_id':'CREDIT-REMOTE'}]
    row=service.create(db,body,admin)
    service.activate(db,row.id,schemas.Activate(version=row.version,quote_version=quote['quote_version'],request_key='credit-return-activate'),admin)
    assert row.status=='effective' and row.refund_amount==0 and row.waived_amount==1000
    assert db.query(ReturnEffect).one().amount_usd==-1000
    assert db.query(ReturnReceipt).count()==db.query(ReturnAllocation).count()==0
    assert db.query(SyncedPayment).filter_by(source='ark_return').count()==0
    if receipt is not None:
        assert receipt.collect_status==0 and receipt.amount==1000


@pytest.mark.parametrize('invalid',['pay_first','incomplete_quote','was_effective','wrong_remote_line'])
def test_unpaid_return_never_invents_credit_authority_from_missing_evidence(db,invalid):
    from app.receipt.models import ReceiptLog
    invoice,batch,receipt,snapshot,body=_unpaid_credit(db,pending=invalid=='was_effective')
    if invalid=='pay_first': batch.quote={**batch.quote,'payment_term':'pay_first'}
    if invalid=='incomplete_quote': batch.quote={'funding_version':2,'payment_term':'ship_first','currency':'USD'}
    if invalid=='was_effective':
        db.add(ReceiptLog(receipt_id=receipt.id,action='credit_effective',message='Previously real cash',created_by=7))
    if invalid=='wrong_remote_line':
        db.query(ShipmentOutbound).one().remote_line_snapshot={'CL1':{'outbound_record_id':'WRONG'}}
    db.flush()
    with pytest.raises(HTTPException) as error:
        funding.constrain(db,snapshot,body,{'refunds':{}})
    assert error.value.status_code==409


def test_second_refund_uses_unborrowed_original_payment_not_consumed_credit(funded):
    from app.sales_return import policy,schemas
    from app.sales_return.presale_adjustments import projection
    db,invoice,receipt_a,batches,outbounds,apps,snapshot,_=funded
    receipt_a.amount=200
    receipt_a.purpose='presale_goods'
    apps[0].amount=200
    batches[0].quote=_quote(400)
    receipt_b=Receipt(receipt_no='EARLIER-RC-B',invoice_id=invoice.id,purpose='presale_goods',source='manual',
        request_key='original-cash-b',request_hash='h',amount=200,currency='USD',collection_date=date(2026,9,1),
        payment_type='bank',bank_charge=0,customer_id='C1',xiaoman_order_id='101',xiaoman_receipt_id='PAY-B',
        collect_status=1,status='active',sync_status='synced',created_by=7)
    db.add(receipt_b)
    db.flush()
    original_b=SettlementApplication(settlement_id=batches[0].id,receipt_id=receipt_b.id,component='goods',
        amount=200,bank_charge=0,status='applied')
    db.add(original_b)
    previous,old_cash_allocation=_previous(db,invoice,batches[0].id,amount=200)
    previous.return_type='refund_only'
    previous.refund_amount=0
    previous.waived_amount=200
    db.delete(old_cash_allocation)
    # The first D200/R0 return releases B200. A later batch consumes exactly B's
    # documented credit; it must not become the next FIFO cash-refund source.
    batches[1].quote={**_quote(200,pool=[{'receipt_id':receipt_b.id,'component':'goods',
        'purpose':'presale_advance','amount':'200','bank_charge':'0'}]),
        'return_credit_sources':{str(receipt_b.id):{'return_ids':[previous.id]}}}
    apps[1].receipt_id=receipt_b.id
    db.flush()
    data=projection(db,invoice)
    assert data['releases'][original_b.id]==200 and data['credit_used'][receipt_b.id]==200
    snapshot.update(goods_amount='1000.00',goods_amount_usd='1000.00')
    snapshot['lines'][0].update(net_amount='400.00',net_amount_usd='400.00')
    snapshot['payments']=[{'payment_id':identity,'principal':'200.00','principal_usd':'200.00',
        'collection_date':day,'currency':'USD'} for identity,day in [('PAY-B','2026-09-01'),('PAY-1','2026-10-01')]]
    selected=snapshot['lines'][0]['source_key']
    body=schemas.Draft(order_id='101',return_type='refund_only',reason_code='quality',reason='Second partial goods credit',
        lines=[{'source_key':selected,'quantity':1,'reduction_amount':'100.00'}])
    history={'refunds':{},'reductions':{selected:Decimal(200)},'reductions_usd':{selected:Decimal(200)},
        'reduction_amount':Decimal(200)}
    limited=funding.constrain(db,snapshot,body,history)
    by_payment={p['payment_id']:p for p in limited['payments']}
    assert Decimal(by_payment['PAY-B']['refundable_amount'])==0
    assert Decimal(by_payment['PAY-1']['refundable_amount'])==200
    quote=policy.price(limited,body,history)
    assert Decimal(quote['refund_amount'])==100
    assert [(row['original_payment_id'],Decimal(row['refund_amount'])) for row in quote['allocations']]==[('PAY-1',Decimal(100))]
