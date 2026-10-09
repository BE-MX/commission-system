"""Presale batch financial contract via actual HTTP; synthetic settled quote/provider facts."""
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice import settlement_policy, settlement_service as shipments
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable, ShipmentSettlement, SettlementApplication
from app.receipt import attachments, fees
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app, financial_snapshot  # noqa: F401


@pytest.fixture
def presale_batch_app(batch_create_app,monkeypatch):
    c=batch_create_app
    c.app.settings.PRESALE_SETTLEMENT_ENABLED=True;c.app.settings.PRESALE_DELIVERY_ENABLED=True
    c.app.settings.OKKI_PRESALE_WAREHOUSE_ID=17
    monkeypatch.setattr(settlement_policy,'get_settings',lambda:c.app.settings)
    assert settlement_policy.capabilities()['enabled'] is True
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);invoice.order_type='presale'
        invoice.total_amount=70;invoice.product_amount=60;invoice.surcharge_amount=10;invoice.shipping_fee=0
        row=ShipmentSettlement(invoice_id=invoice.id,sequence=1,settlement_no='SET-'+uuid4().hex,
            state='awaiting_payment',version=1,is_final=0,quote={'goods_payment_due':'50.00',
                'freight_amount':'20.00','goods_payment_charge':'5.00','new_payment_due':'70.00','currency':'USD'},
            quote_hash='a'*64,request_key=uuid4().hex,request_hash='b'*64,created_by=c.ctx.actor)
        db.add(row);db.commit();c.settlement_id=row.id
    def forbidden(*args):raise AssertionError('Presale uses settlement fee, not ordinary remote fee allocation')
    monkeypatch.setattr(fees,'read_evidence',forbidden)
    return c


def presale_payload(client,c,headers,amount):
    # Actual API already returns the compound presale version used by the frontend.
    response=client.get('/api/receipts/order-balance/'+str(c.invoice_id),headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['data']['settlement_id']==c.settlement_id
    version=response.json()['data']['version']
    return {'request_key':uuid4().hex,'amount':str(amount),'bank_charge':'0','collection_date':'2026-10-06',
        'payment_type':'T/T','remark':'Presale shipment payment','attachment_ids':[c.proofs['unbound']],
        'allocations':[{'invoice_id':c.invoice_id,'settlement_id':c.settlement_id,'amount':str(amount),'balance_version':version}]}


def separate_proof(c):
    identity=uuid4().hex
    with Session(c.ctx.engine) as db:
        proof=db.get(ReceiptAttachment,c.proofs['unbound'])
        db.add(ReceiptAttachment(id=identity,filename='next-payment.png',storage_key=identity+'.png',
            content_type='image/png',size=proof.size,sha256=proof.sha256,created_by=c.ctx.actor));db.commit()
    (attachments.STORAGE_ROOT/(identity+'.png')).write_bytes(c.image)
    return identity


def assert_presale_created(c,body,response,goods,freight,charge,state):
    assert response.status_code==200,response.text
    batch_id=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        batch=db.get(ReceiptBatch,batch_id);assert batch.gross_amount==Decimal(body['amount'])
        assert batch.bank_charge_total==Decimal(charge) and batch.request_key==body['request_key']
        rows=db.scalars(select(Receipt).where(Receipt.batch_id==batch_id)).all()
        actual={r.purpose:(r.amount,r.bank_charge) for r in rows}
        expected={purpose:(Decimal(value),Decimal(charge) if purpose=='presale_goods' else Decimal('0'))
            for purpose,value in [('presale_goods',goods),('freight',freight)] if Decimal(value)>0}
        assert actual==expected and len(rows)==len(expected)
        assert all(r.invoice_id==c.invoice_id and r.sync_status=='waiting_target' and r.attachment_ids==body['attachment_ids'] for r in rows)
        apps=db.scalars(select(SettlementApplication).where(SettlementApplication.receipt_id.in_([r.id for r in rows]))).all()
        assert len(apps)==len(rows) and {a.component for a in apps}=={'goods' if r.purpose=='presale_goods' else 'freight' for r in rows}
        for row in rows:
            target=db.get(Receivable,row.receivable_id)
            app=next(a for a in apps if a.receipt_id==row.id)
            assert app.settlement_id==c.settlement_id and app.amount==row.amount and app.bank_charge==row.bank_charge
            assert target.invoice_id==c.invoice_id and target.kind==app.component
            assert target.business_key==(f'invoice:{c.invoice_id}:goods' if app.component=='goods' else f'settlement:{c.settlement_id}:freight')
        assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([r.id for r in rows]),ReceiptLog.action=='created').count()==len(rows)
        assert db.get(ShipmentSettlement,c.settlement_id).state==state
    assert c.calls==[]
    return batch_id


@pytest.mark.parametrize('case',['partial','full','tie_cent','deposit','prior_goods'])
def test_presale_split_goods_cap_and_original_funding(presale_batch_app,case):
    c=presale_batch_app
    with Session(c.ctx.engine) as db:
        if case=='tie_cent':
            db.get(ShipmentSettlement,c.settlement_id).quote={'goods_payment_due':'1.00','freight_amount':'1.00',
                'goods_payment_charge':'0.10','new_payment_due':'2.00','currency':'USD'}
        if case in {'deposit','prior_goods'}:
            receipt=db.get(Receipt,c.receipts['victim']);receipt.purpose='presale_deposit' if case=='deposit' else 'presale_goods'
            receipt.bank_charge=0 if case=='deposit' else 1
            db.add(SettlementApplication(settlement_id=c.settlement_id,receipt_id=receipt.id,
                component='deposit' if case=='deposit' else 'goods',amount=5 if case=='deposit' else 10,
                bank_charge=0 if case=='deposit' else 1,status='reserved'))
        db.commit()
    amount,goods,freight,charge,state={'partial':('35','25','10','2.50','awaiting_payment'),
        'full':('70','50','20','5','awaiting_verification'),'tie_cent':('.01','.01','0','0','awaiting_payment'),
        'deposit':('70','50','20','5','awaiting_verification'),'prior_goods':('30','20','10','2','awaiting_payment')}[case]
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=presale_payload(client,c,owner,amount)
        identity=assert_presale_created(c,body,client.post('/api/receipts/batches',headers=owner,json=body),goods,freight,charge,state)
        before=financial_snapshot(c);c.io.clear()
        restored=client.post('/api/receipts/batches',headers=owner,json=body)
        assert restored.status_code==200 and restored.json()['data']['id']==identity,restored.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


def test_presale_final_goods_payment_takes_remaining_fee_cent(presale_batch_app):
    c=presale_batch_app
    with Session(c.ctx.engine) as db:
        db.get(ShipmentSettlement,c.settlement_id).quote={'goods_payment_due':'.03','freight_amount':'.01',
            'goods_payment_charge':'.01','new_payment_due':'.04','currency':'USD'};db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);first=presale_payload(client,c,owner,'.01')
        assert_presale_created(c,first,client.post('/api/receipts/batches',headers=owner,json=first),'.01','0','0','awaiting_payment')
        second=presale_payload(client,c,owner,'.03');second['attachment_ids']=[separate_proof(c)]
        assert_presale_created(c,second,client.post('/api/receipts/batches',headers=owner,json=second),'.02','.01','.01','awaiting_verification')
        with Session(c.ctx.engine) as db:
            summary=shipments.funding_balance(db,db.get(ShipmentSettlement,c.settlement_id))
            assert Decimal(summary['goods_remaining'])==0 and Decimal(summary['freight_remaining'])==0 and Decimal(summary['charge_remaining'])==0


@pytest.mark.parametrize('guard',['settlement_invoice','settlement_currency','settlement_state','freight_invoice','freight_kind','freight_settlement'])
def test_presale_initial_association_guards_do_not_read_files_or_write(presale_batch_app,guard,monkeypatch):
    c=presale_batch_app;hits=[];original=attachments.verify_storage
    def storage(*args):hits.append(True);return original(*args)
    monkeypatch.setattr(attachments,'verify_storage',storage)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=presale_payload(client,c,owner,'35')
        with Session(c.ctx.engine) as db:
            settlement=db.get(ShipmentSettlement,c.settlement_id)
            if guard=='settlement_invoice':settlement.invoice_id=c.second_invoice_id
            elif guard=='settlement_currency':settlement.quote=dict(settlement.quote,currency='EUR')
            elif guard=='settlement_state':settlement.state='ready'
            else:
                invoice=db.get(Invoice,c.invoice_id)
                db.add(Receivable(invoice_id=c.second_invoice_id if guard=='freight_invoice' else c.invoice_id,
                    business_key=f'settlement:{c.settlement_id}:freight',kind='goods' if guard=='freight_kind' else 'freight',
                    settlement_id=None if guard=='freight_settlement' else c.settlement_id,currency='USD',
                    customer_id=invoice.customer_id,amount=20,handling_amount=0,remote_status='unverified'))
            db.commit()
        before=financial_snapshot(c);c.io.clear()
        response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[] and hits==[]


@pytest.mark.parametrize('change',['missing_settlement','wrong_settlement_invoice','wrong_component','missing_application'])
def test_replay_settlement_actual_association_before_any_new_evidence(presale_batch_app,change,monkeypatch):
    c=presale_batch_app;storage_hits=[];original=attachments.verify_storage
    def storage(*args):storage_hits.append(True);return original(*args)
    monkeypatch.setattr(attachments,'verify_storage',storage)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=presale_payload(client,c,owner,'35')
        identity=assert_presale_created(c,body,client.post('/api/receipts/batches',headers=owner,json=body),'25','10','2.5','awaiting_payment')
        with Session(c.ctx.engine) as db:
            if change=='missing_settlement':db.delete(db.get(ShipmentSettlement,c.settlement_id))
            elif change=='wrong_settlement_invoice':db.get(ShipmentSettlement,c.settlement_id).invoice_id=c.second_invoice_id
            else:
                receipt=db.scalar(select(Receipt).where(Receipt.batch_id==identity,Receipt.purpose=='presale_goods'))
                app=db.scalar(select(SettlementApplication).where(SettlementApplication.receipt_id==receipt.id))
                if change=='missing_application':db.delete(app)
                else:app.component='freight'
            db.commit()
        before=financial_snapshot(c);c.io.clear();storage_hits.clear()
        response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[] and storage_hits==[]


@pytest.mark.parametrize('state',['paused','shipped','released','disabled'])
def test_replay_valid_original_graph_ignores_new_settlement_readiness(presale_batch_app,state,monkeypatch):
    c=presale_batch_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=presale_payload(client,c,owner,'35')
        identity=assert_presale_created(c,body,client.post('/api/receipts/batches',headers=owner,json=body),'25','10','2.5','awaiting_payment')
        if state=='disabled':
            c.app.settings.PRESALE_SETTLEMENT_ENABLED=False
            assert settlement_policy.capabilities()['enabled'] is False
        else:
            with Session(c.ctx.engine) as db:
                if state=='released':
                    for app in db.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id==c.settlement_id)):
                        app.status='released'
                else:db.get(ShipmentSettlement,c.settlement_id).state=state
                db.commit()
        def forbidden(*args):raise AssertionError('Original replay must not read new external evidence')
        monkeypatch.setattr(attachments,'verify_storage',forbidden)
        before=financial_snapshot(c);c.io.clear()
        response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==200 and response.json()['data']['id']==identity,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]
