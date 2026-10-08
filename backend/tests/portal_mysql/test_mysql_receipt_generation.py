"""Actual ready-intent generation on owned MySQL; no supplier POST or cloud IO."""
from decimal import Decimal
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.core.time import beijing_today
from app.invoice.models import Invoice
from app.receipt import attachments,remote,sync_service
from app.receipt.models import Receipt,ReceiptIntent,ReceiptLog
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app,login,change_user  # noqa: F401
from test_mysql_receipt_reads import read_app,read_snapshot  # noqa: F401


@pytest.fixture
def generation_app(read_app,monkeypatch):
    c=read_app
    with c.ctx.engine.begin() as connection:
        for name,column in [('uq_owned_generation_request','request_key'),('uq_owned_generation_auto','auto_key')]:
            index=connection.execute(text(f"SHOW INDEX FROM ark_receipts WHERE Key_name='{name}'")).mappings().all()
            if index:
                assert [row['Column_name'] for row in index]==[column]
                assert all(row['Non_unique']==0 for row in index)
            else:
                connection.execute(text(f'ALTER TABLE ark_receipts ADD UNIQUE KEY {name}({column})'))
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id)
        invoice.surcharge_amount=Decimal('8')
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        intent.status='ready';intent.eligible=1;intent.created_by=c.ctx.actor
        intent.amount=Decimal('32');intent.currency=invoice.currency;intent.customer_id=invoice.customer_id
        intent.collection_date=beijing_today();intent.payment_type='T/T';intent.remark='Ready original intent'
        intent.attempt_token=None;intent.lease_until=None;intent.receipt_id=None;intent.last_error=None
        db.commit()
    def order_receipts(db,identity):c.io.append(('fees',str(identity)));return []
    monkeypatch.setattr(remote,'order_receipts',order_receipts)
    return c


def run_worker(c):
    with Session(c.ctx.engine,autoflush=False,expire_on_commit=False) as db:
        sync_service.generate_ready(db)


def assert_converted(c,amount='32',charge='2'):
    with Session(c.ctx.engine) as db:
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
        rows=db.scalars(select(Receipt).where(Receipt.source=='auto',Receipt.invoice_id==c.invoice_id)).all()
        assert len(rows)==1
        row=rows[0]
        assert intent.status=='converted' and intent.receipt_id==row.id
        assert row.amount==Decimal(amount) and row.bank_charge==Decimal(charge)
        assert row.created_by==c.ctx.actor and row.auto_key==f'invoice:{c.invoice_id}:initial'
        assert row.request_key==f'auto_invoice_{c.invoice_id}'
        assert row.status=='active' and row.sync_status=='pending' and row.source=='auto'
        assert row.attachment_ids==intent.attachment_ids==[c.proofs['intent']]
        assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='created')).all())==1
        return row.id


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_generation_current_revocation_denies_before_evidence(generation_app,revoke):
    c=generation_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
                    {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);c.io.clear()
        run_worker(c)
        assert read_snapshot(c)==before
        assert c.io==[] and c.calls==[]


def test_generation_actual_invoice_scope_not_portal_owner(generation_app):
    c=generation_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.roles['both'],c.roles['invoice:read_all']]})
    with Session(c.ctx.engine) as db:
        db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
    before=read_snapshot(c);c.io.clear();run_worker(c)
    assert read_snapshot(c)==before and c.io==[] and c.calls==[]


def test_generation_missing_original_actor_is_not_implicit_system(generation_app):
    c=generation_app
    with Session(c.ctx.engine) as db:
        db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).created_by=None;db.commit()
    before=read_snapshot(c);c.io.clear();run_worker(c)
    assert read_snapshot(c)==before and c.io==[] and c.calls==[]


def test_generation_file_evidence_releases_invoice_lock(generation_app,monkeypatch):
    c=generation_app;observed=[];original=attachments.verify_storage
    def unlocked(bindings):
        with Session(c.ctx.engine) as other:
            try:
                invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                assert invoice is not None
                observed.append('unlocked')
            except OperationalError:
                observed.append('locked')
        return original(bindings)
    monkeypatch.setattr(attachments,'verify_storage',unlocked)
    run_worker(c)
    assert observed==['unlocked']
    assert_converted(c)
    assert c.calls==[]
