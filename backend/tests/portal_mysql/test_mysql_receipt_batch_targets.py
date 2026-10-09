"""Actual HTTP target association guards; same-customer counterexamples and legal absence."""
from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable
from app.receipt import attachments
from app.receipt.models import Receipt
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app, payload, created, financial_snapshot  # noqa: F401


def goods_target(c, *, wrong_invoice=False):
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id)
        row=Receivable(invoice_id=c.second_invoice_id if wrong_invoice else invoice.id,
            business_key=f'invoice:{invoice.id}:goods',kind='goods',currency=invoice.currency,
            customer_id=invoice.customer_id,amount=invoice.total_amount,handling_amount=invoice.surcharge_amount,
            remote_order_id=invoice.xiaoman_order_id,remote_status='bound')
        db.add(row);db.commit();return row.id


@pytest.mark.parametrize('condition',['wrong_invoice','correct_existing','missing'])
def test_expected_goods_key_owns_exact_invoice_not_just_customer(batch_create_app,condition,monkeypatch):
    c=batch_create_app;storage_hits=[];original=attachments.verify_storage
    def storage(*args):storage_hits.append(True);return original(*args)
    monkeypatch.setattr(attachments,'verify_storage',storage)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        target_id=goods_target(c,wrong_invoice=condition=='wrong_invoice') if condition!='missing' else None
        with Session(c.ctx.engine) as db:
            a,b=db.get(Invoice,c.invoice_id),db.get(Invoice,c.second_invoice_id)
            assert a.customer_id==b.customer_id and a.currency==b.currency
        before=financial_snapshot(c);c.io.clear();storage_hits.clear()
        response=client.post('/api/receipts/batches',headers=owner,json=body)
        if condition=='wrong_invoice':
            assert response.status_code==409,response.text
            assert financial_snapshot(c)==before and c.io==[] and c.calls==[] and storage_hits==[]
        else:
            batch_id=created(c,body,response)
            assert storage_hits==[True]
            with Session(c.ctx.engine) as db:
                row=db.scalar(select(Receipt).where(Receipt.batch_id==batch_id,Receipt.invoice_id==c.invoice_id))
                target=db.get(Receivable,row.receivable_id)
                assert target.invoice_id==c.invoice_id and target.business_key==f'invoice:{c.invoice_id}:goods'
                assert target.kind=='goods' and target.settlement_id is None
                if target_id:assert target.id==target_id
                assert db.query(Receivable).filter_by(business_key=f'invoice:{c.invoice_id}:goods').count()==1


@pytest.mark.parametrize('change',['missing','wrong_invoice','wrong_key'])
def test_replay_missing_or_changed_original_target_never_rebuilds(batch_create_app,change,monkeypatch):
    c=batch_create_app;storage_hits=[];original=attachments.verify_storage
    def storage(*args):storage_hits.append(True);return original(*args)
    monkeypatch.setattr(attachments,'verify_storage',storage)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        batch_id=created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        with Session(c.ctx.engine) as db:
            row=db.scalar(select(Receipt).where(Receipt.batch_id==batch_id,Receipt.invoice_id==c.invoice_id))
            target=db.get(Receivable,row.receivable_id)
            if change=='missing':db.delete(target)
            elif change=='wrong_invoice':target.invoice_id=c.second_invoice_id
            else:target.business_key=f'invoice:{c.invoice_id}:unexpected-goods'
            db.commit()
        before=financial_snapshot(c);c.io.clear();storage_hits.clear()
        response=client.post('/api/receipts/batches',headers=owner,json=body)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[] and storage_hits==[]
