"""Explicit-actor generation core only; legacy scheduler is deliberately not patched."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import threading
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import event,select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.invoice.models import Invoice,InvoiceItem
from app.portal.models import Conversion,OrderRequest
from app.receipt import attachments,generation_service,remote
from app.receipt.models import Receipt,ReceiptIntent,ReceiptLog,ReceiptAttachment
from app.semifinished.models import InvoiceAllocation
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app,login,change_user  # noqa: F401
from test_mysql_receipt_reads import read_app,read_snapshot  # noqa: F401
from test_mysql_receipt_generation import generation_app,assert_converted  # noqa: F401


def assert_conversion_delta(before,after,c,identity):
    # All columns of the explicitly finite 15-model graph; not the entire database.
    models=(Receipt,ReceiptLog,ReceiptAttachment,ReceiptIntent)
    old_receipts={row[0]:row for row in before[0]}
    new_receipts={row[0]:row for row in after[0]}
    assert set(new_receipts)==set(old_receipts)|{identity}
    assert all(new_receipts[key]==row for key,row in old_receipts.items())
    old_logs={row[0]:row for row in before[1]};new_logs={row[0]:row for row in after[1]}
    assert len(new_logs)==len(old_logs)+1
    assert all(new_logs[key]==row for key,row in old_logs.items())
    for index,allowed in [(2,{'receipt_id'}),(3,{'status','receipt_id','last_error','updated_at'})]:
        names=list(models[index].__table__.columns.keys())
        previous={row[0]:row for row in before[index]};current={row[0]:row for row in after[index]}
        assert set(previous)==set(current)
        for key,values in previous.items():
            selected=key==c.proofs['intent'] if index==2 else values[names.index('invoice_id')]==c.invoice_id
            for name,old,new in zip(names,values,current[key]):
                if not selected or name not in allowed:assert old==new,(index,key,name,old,new)
    assert before[4:]==after[4:]


def generate(c,actor=None):
    with Session(c.ctx.engine,autoflush=False,expire_on_commit=False) as db:
        row=generation_service.generate(db,c.invoice_id,c.ctx.actor if actor is None else actor)
        identity=row.id if row else None
        db.commit()
        return identity


@pytest.mark.parametrize('kind,amount,charge',[('stock','32','2'),('stock','108','8'),('presale','32','2'),('presale','86.40','5.40')])
def test_core_original_partial_final_fee_and_presale_purpose(generation_app,kind,amount,charge):
    c=generation_app
    with Session(c.ctx.engine) as db:
        db.get(Invoice,c.invoice_id).order_type=kind
        db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).amount=Decimal(amount)
        db.commit()
    before=read_snapshot(c)
    identity=generate(c);assert identity==assert_converted(c,amount,charge)
    assert_conversion_delta(before,read_snapshot(c),c,identity)
    with Session(c.ctx.engine) as db:
        assert db.get(Receipt,identity).purpose==('presale_deposit' if kind=='presale' else 'ordinary')
        assert db.get(ReceiptAttachment,c.proofs['intent']).receipt_id==identity
    before=read_snapshot(c);c.io.clear();assert generate(c)==identity
    assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_core_current_action_before_evidence(generation_app,revoke):
    c=generation_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
            {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);c.io.clear()
        with pytest.raises(HTTPException) as error:generate(c)
        assert error.value.status_code==403
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('identity',[None,0,'invalid'])
def test_core_requires_explicit_actor_not_audit_inference(generation_app,identity):
    c=generation_app;before=read_snapshot(c);c.io.clear()
    with Session(c.ctx.engine,autoflush=False) as db:
        with pytest.raises(HTTPException) as error:generation_service.generate(db,c.invoice_id,identity)
        assert error.value.status_code==403
    assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('global_role',[None,'all','super_admin'])
def test_core_actual_invoice_finance_scope(generation_app,global_role):
    c=generation_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        if global_role=='super_admin':
            with Session(c.ctx.engine) as db:role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id
        else:role=c.roles[global_role] if global_role else c.roles['invoice:read_all']
        change_user(client,c,root,{'role_ids':[c.roles['both'],role]})
    with Session(c.ctx.engine) as db:
        db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
    if global_role:
        assert generate(c)==assert_converted(c)
    else:
        before=read_snapshot(c);c.io.clear()
        with pytest.raises(HTTPException) as error:generate(c)
        assert error.value.status_code==404
        assert read_snapshot(c)==before and c.io==[]
    assert c.calls==[]


@pytest.mark.parametrize('point',['balance','fees','files'])
def test_core_invoice_unlocked_during_every_external_stage(generation_app,monkeypatch,point):
    c=generation_app;observed=[]
    module,name=(remote,'order_snapshot') if point=='balance' else (remote,'order_receipts') if point=='fees' else (attachments,'verify_storage')
    original=getattr(module,name)
    def unlocked(*args,**kwargs):
        with Session(c.ctx.engine) as other:
            invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
            assert invoice is not None;observed.append(point)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,name,unlocked)
    assert generate(c)==assert_converted(c)
    assert observed==[point] and c.calls==[]


@pytest.mark.parametrize('change',['disabled','roles','owner','intent_amount','intent_actor','intent_status',
    'intent_currency','invoice_fee','invoice_order','receipt_amount','allocation','proof_meta','proof_key','item','lineage','request','log'])
def test_core_during_evidence_current_authority_and_full_binding(generation_app,monkeypatch,change):
    c=generation_app;original=attachments.verify_storage;committed=[]
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        def changed(bindings):
            if change in {'disabled','roles'}:
                change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[]})
            else:
                with Session(c.ctx.engine) as db:
                    invoice=db.get(Invoice,c.invoice_id)
                    intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
                    if change=='owner':invoice.sales_user_id=c.other_id
                    elif change=='intent_amount':intent.amount=Decimal('33')
                    elif change=='intent_actor':intent.created_by=c.other_id
                    elif change=='intent_status':intent.status='armed'
                    elif change=='intent_currency':intent.currency='EUR'
                    elif change=='invoice_fee':invoice.surcharge_amount=Decimal('9')
                    elif change=='invoice_order':invoice.xiaoman_order_id='9999999'
                    elif change=='receipt_amount':db.get(Receipt,c.receipts['victim']).amount=Decimal('11')
                    elif change=='allocation':db.add(InvoiceAllocation(invoice_id=invoice.id,status='pending'))
                    elif change=='proof_meta':db.get(ReceiptAttachment,c.proofs['intent']).filename='changed.png'
                    elif change=='proof_key':db.get(ReceiptAttachment,c.proofs['intent']).storage_key='changed.png'
                    elif change=='item':db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id)).quantity=Decimal('2')
                    elif change=='lineage':db.scalar(select(Conversion).where(Conversion.invoice_id==invoice.id)).status='tombstoned'
                    elif change=='request':
                        request=db.scalar(select(OrderRequest).where(OrderRequest.invoice_id==invoice.id))
                        assert 'servicing_user_id' in request.__table__.columns
                        request.servicing_user_id=c.other_id
                    elif change=='log':db.add(ReceiptLog(receipt_id=c.receipts['victim'],action='test_external',message='Independent committed write',created_by=c.ctx.actor))
                    db.commit()
            committed.append(read_snapshot(c))
            return original(bindings)
        monkeypatch.setattr(attachments,'verify_storage',changed)
        with pytest.raises((HTTPException,ValueError)) as error:generate(c)
        if change in {'disabled','roles','owner'}:
            assert isinstance(error.value,HTTPException)
            assert error.value.status_code==(404 if change=='owner' else 403)
        else:
            assert isinstance(error.value,(HTTPException,ValueError))
            if isinstance(error.value,HTTPException):assert error.value.status_code==409
        assert len(committed)==1 and read_snapshot(c)==committed[0] and c.calls==[]


@pytest.mark.parametrize('fault',['mismatched_fee_rows','missing_fee_fields','missing_file','payment_type','over_amount'])
def test_core_bad_evidence_and_balance_never_convert(generation_app,monkeypatch,fault):
    c=generation_app
    if fault in {'mismatched_fee_rows','missing_fee_fields'}:
        monkeypatch.setattr(remote,'order_receipts',lambda *args:[{'cash_collection_id':'9001','amount':'10'}])
        monkeypatch.setattr(remote,'receipt_info',lambda db,identity:{'order_id':str(c.invoice_id+1000000),
            'currency':'USD','amount':'10','bank_charge':'1','real_amount':'9'} if fault=='mismatched_fee_rows' else {})
    elif fault=='missing_file':attachments.path_for(type('File',(),{'storage_key':c.proofs['intent']+'.png'})()).unlink()
    else:
        with Session(c.ctx.engine) as db:
            intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
            if fault=='payment_type':intent.payment_type='unknown'
            else:intent.amount=Decimal('109')
            db.commit()
    before=read_snapshot(c)
    with pytest.raises((HTTPException,ValueError)) as error:generate(c)
    if fault in {'mismatched_fee_rows','missing_fee_fields','missing_file'}:
        assert isinstance(error.value,HTTPException) and error.value.status_code==503
    assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('inactive',['draft','armed','ineligible','cancelled','linked'])
def test_core_original_inactive_does_not_convert(generation_app,inactive):
    c=generation_app
    with Session(c.ctx.engine) as db:
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
        if inactive in {'draft','armed'}:intent.status=inactive
        elif inactive=='ineligible':intent.eligible=0
        elif inactive=='cancelled':db.get(Invoice,c.invoice_id).status='cancelled'
        else:db.get(Invoice,c.invoice_id).linked_sync_id=987654
        db.commit()
    before=read_snapshot(c);c.io.clear()
    assert generate(c) is None
    assert read_snapshot(c)==before and c.io==[]


@pytest.mark.parametrize('fault',['before_commit','after_commit'])
def test_core_exact_conversion_commit_fault_recovery(generation_app,fault):
    c=generation_app;before=read_snapshot(c);fired=[]
    with Session(c.ctx.engine,autoflush=False,expire_on_commit=False) as db:
        row=generation_service.generate(db,c.invoice_id,c.ctx.actor)
        identity=row.id
        def fail(session):
            assert session is db
            fired.append(fault);raise RuntimeError('synthetic-original-commit-ack')
        event.listen(db,'before_commit' if fault=='before_commit' else 'after_commit',fail,once=True)
        with pytest.raises(RuntimeError,match='synthetic-original-commit-ack'):db.commit()
    assert fired==[fault]
    if fault=='before_commit':assert read_snapshot(c)==before
    recovered=generate(c);assert recovered==assert_converted(c)
    if fault=='after_commit':assert recovered==identity
    again=read_snapshot(c);c.io.clear();assert generate(c)==recovered
    assert read_snapshot(c)==again and c.io==[] and c.calls==[]


def test_core_competing_generation_replays_original_winner(generation_app,monkeypatch):
    c=generation_app;entered=threading.Event();release=threading.Event();original=attachments.verify_storage
    def first_slow(bindings):
        if threading.current_thread().name.startswith('slow-generation'):
            entered.set();assert release.wait(10),'Original file gate never released'
        return original(bindings)
    monkeypatch.setattr(attachments,'verify_storage',first_slow)
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='slow-generation') as pool:
        first=pool.submit(generate,c)
        try:
            assert entered.wait(5)
            winner=generate(c)
        finally:release.set()
        assert first.result(timeout=5)==winner==assert_converted(c)
    assert c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','roles','scope'])
def test_core_converted_replay_authorizes_before_original_result(generation_app,revoke):
    c=generation_app;identity=generate(c)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        if revoke!='scope':change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[]})
        else:
            with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
    before=read_snapshot(c);c.io.clear()
    with pytest.raises(HTTPException) as error:generate(c)
    assert error.value.status_code==(404 if revoke=='scope' else 403)
    assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('state',['cancelled','not_synced','removed_file'])
def test_core_valid_converted_history_does_not_need_new_ready_or_io(generation_app,state):
    c=generation_app;identity=generate(c)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id)
        if state=='cancelled':invoice.status='cancelled'
        elif state=='not_synced':invoice.sync_status='not_synced'
        else:attachments.path_for(db.get(ReceiptAttachment,c.proofs['intent'])).unlink()
        db.commit()
    before=read_snapshot(c);c.io.clear()
    assert generate(c)==identity and read_snapshot(c)==before and c.io==[] and c.calls==[]



@pytest.mark.parametrize('invalid',['over_product','zero_net'])
def test_core_presale_net_guard_rechecked_with_actual_fee(generation_app,invalid):
    c=generation_app
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);invoice.order_type='presale'
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        if invalid=='over_product':intent.amount=Decimal('108')  # Actual charge8, net100 > product81.
        else:
            # Consistent original product1 + surcharge2 = total3. Cent rounding
            # makes gross0.01 entirely fee; such a deposit must never be recorded.
            invoice.total_amount=Decimal('3');invoice.product_amount=Decimal('1')
            invoice.surcharge_amount=Decimal('2');invoice.shipping_fee=0;invoice.internal_accessory=0
            for row in db.scalars(select(Receipt).where(Receipt.invoice_id==invoice.id)):row.status='void'
            item=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
            item.quantity=1;item.price_per_piece=Decimal('1');item.total_price=Decimal('1')
            assert all(name in item.__table__.columns for name in ('price_per_piece','total_price'))
            intent.amount=Decimal('0.01')
        db.commit()
    before=read_snapshot(c)
    with pytest.raises(ValueError,match='预付款净额'):generate(c)
    assert read_snapshot(c)==before and c.calls==[]
