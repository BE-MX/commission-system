"""Lifecycle tests use only SQLite and mocked remote boundaries."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.auth.dependencies import get_current_user
from app.invoice import cancellation_service as cancel, lifecycle_remote, linked_outbound_service, sync_coordinator, okki_client
from app.invoice import linked_sync_service, service as invoices
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import Receipt, ReceiptLog
from app.receipt import remote, balance, remote_change_service as changes
from app.receipt.schemas import RemoteChange


@pytest.fixture
def order(db):
    row=Invoice(invoice_no="LIFECYCLE",order_type="production",customer_id="101",customer_name="Test",sales_user_id=1,
        created_by=1,invoice_date=date(2026,9,20),currency="USD",total_amount=100,xiaoman_order_id="123",sync_status="synced",status="synced")
    db.add(row);db.commit();return row


@pytest.fixture(autouse=True)
def no_remote(monkeypatch):
    def forbidden(*a,**kw): raise AssertionError("Unexpected network")
    monkeypatch.setattr(lifecycle_remote,"read",forbidden)
    monkeypatch.setattr(lifecycle_remote,"request",forbidden)
    monkeypatch.setattr(okki_client,"ensure_access_token",lambda *a,**kw:"test")
    monkeypatch.setattr(remote,"order_receipts",lambda *a:[])
    monkeypatch.setattr(linked_outbound_service,"find_related",lambda *a:[])


def receipt(db,order):
    row=Receipt(receipt_no="HK-1",invoice_id=order.id,source="manual",request_key="receipt-test-key",request_hash="x"*64,
        amount=100,currency="USD",collection_date=order.invoice_date,payment_type="T/T",bank_charge=0,customer_id="101",
        xiaoman_order_id="123",xiaoman_receipt_id="88",sync_status="synced",created_by=1,attachment_ids=["proof-retained"])
    db.add(row);db.commit();return row


def start(db,order):
    return cancel.begin(db,order,"客户确认取消订单，开始核对原单",1,linked_sync_service.edit_version(order))


def live_order(monkeypatch):
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:{"order_id":"123","company_id":"101","currency":"USD","status":"draft"})


def body(row,proof):
    return RemoteChange(version=row.version,evidence_hash=proof["evidence_hash"],reason="已核对实际资金和远端原单变更依据",confirmed=True)


@pytest.mark.parametrize("status",["running","uncertain"])
def test_edit_and_sync_block_active_outbound(db,order,status):
    db.add(OkkiOutboundTask(invoice_id=order.id,order_id="123",status=status));db.commit()
    with pytest.raises(ValueError,match="出库"): invoices.update_invoice(db,order,NS(),1)
    with pytest.raises(sync_coordinator.BeforeSendError) as error: sync_coordinator.synchronize(db,order,1)
    assert error.value.status_code==409


def test_unknown_result_preserves_inventory(db,order,monkeypatch):
    inventory=sync_coordinator.semifinished_invoice_service
    monkeypatch.setattr(inventory,"prepare_invoice_sync",lambda *a:"op")
    monkeypatch.setattr(inventory,"ensure_pending_matches_invoice",lambda *a:None)
    monkeypatch.setattr(inventory,"release_invoice_sync",lambda *a:pytest.fail("Must not release"))
    def uncertain(db,inv,**kw):
        inv.sync_status="sync_uncertain";return {"ok":False,"message":"timeout"}
    monkeypatch.setattr(sync_coordinator.xiaoman_service,"sync_invoice",uncertain)
    assert sync_coordinator.synchronize(db,order,1)["inventory_pending"]


def test_prepare_commit_hides_previous_synced_version(db,order,monkeypatch):
    def prepare(db,inv,actor):
        db.commit();db.refresh(inv);assert inv.sync_status=="not_synced"
    monkeypatch.setattr(sync_coordinator.semifinished_invoice_service,"prepare_invoice_sync",prepare)
    monkeypatch.setattr(sync_coordinator.xiaoman_service,"sync_invoice",lambda *a,**k:{"ok":False})
    sync_coordinator.synchronize(db,order,1)


def test_cancel_freezes_and_abort_restores(db,order):
    start(db,order)
    with pytest.raises(ValueError): ensure_mutable(db,order)
    cancel.abort(db,order,1,"客户撤回取消申请，继续原订单")
    assert order.status=="synced" and order.cancellation["status"]=="aborted"
    ensure_mutable(db,order)


def test_cancel_receipt_blocks_remote_post(db,order,monkeypatch):
    receipt(db,order);live_order(monkeypatch);start(db,order)
    assert cancel.remove_remote(db,order,1)["status"]=="blocked"


def test_cancel_delete_intent_idempotency(db,order,monkeypatch):
    live_order(monkeypatch);start(db,order);calls=[]
    def request(token,kind,identity,remove=False):
        if remove:
            db.refresh(order);assert order.cancellation["status"]=="deleting"
            calls.append(identity);return True
        return None
    monkeypatch.setattr(lifecycle_remote,"request",request)
    assert cancel.remove_remote(db,order,1)["status"]=="remote_deleted"
    assert cancel.remove_remote(db,order,1)["status"]=="remote_deleted"
    assert calls==["123"] and order.xiaoman_order_id=="123" and order.status=="cancelled"
    assert db.query(InvoiceSyncLog).filter_by(invoice_id=order.id).count()>=3


def test_cancel_timeout_never_replays(db,order,monkeypatch):
    live_order(monkeypatch);start(db,order);calls=[]
    def request(*a,**kw):
        calls.append(1);raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(lifecycle_remote,"request",request)
    assert cancel.remove_remote(db,order,1)["status"]=="uncertain"
    assert cancel.remove_remote(db,order,1)["status"]=="uncertain"
    with pytest.raises(ValueError): cancel.abort(db,order,1,"cannot abort")
    assert calls==[1]


def test_retain_is_not_refund(db,order):
    row=receipt(db,order);start(db,order)
    cancel.retain(db,order,"客户取消后另行办理退款，保留原收款凭证",1,True)
    assert order.status=="cancelled" and row.status=="active" and row.amount==100 and row.xiaoman_receipt_id=="88"


def test_deleted_receipt_frozen_until_review_releases_once(db,order,monkeypatch):
    row=receipt(db,order)
    with pytest.raises(ValueError,match="缺失"): balance.calculate(db,order,{"rows":[]})
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:None)
    proof=changes.evidence(db,row);review=body(row,proof)
    changes.accept(db,row,review,1);db.commit()
    assert row.status=="remote_deleted" and row.xiaoman_receipt_id=="88" and row.attachment_ids==["proof-retained"]
    assert Decimal(balance.calculate(db,order,{"rows":[]})["remaining_amount"])==100
    with pytest.raises(ValueError): changes.accept(db,row,review,1)
    assert db.query(ReceiptLog).filter_by(receipt_id=row.id,action="remote_change").count()==1


def test_detail_absence_with_active_index_is_not_deletion(db,order,monkeypatch):
    row=receipt(db,order)
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:None)
    monkeypatch.setattr(remote,"order_receipts",lambda *a:[{"cash_collection_id":"88"}])
    with pytest.raises(ValueError,match="证据不一致"): changes.evidence(db,row)


@pytest.mark.parametrize("changed",["remote","local","unchanged"])
def test_review_version_and_audit(db,order,monkeypatch,changed):
    row=receipt(db,order)
    row.bank_charge=2;db.commit()
    data={"order_id":"123","currency":"USD","amount":"78","bank_charge":"0","real_amount":"78","collection_date":"2026-09-20","collect_status":1}
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:data)
    proof=changes.evidence(db,row);review=body(row,proof)
    if changed=="remote": data.update(amount="88",real_amount="88")
    elif changed=="local": row.version+=1;db.commit()
    if changed!="unchanged":
        with pytest.raises(ValueError,match="变化"): changes.accept(db,row,review,1)
        assert row.amount==100
    else:
        changes.accept(db,row,review,1);db.commit()
        assert row.amount==80 and row.bank_charge==2
        assert '100' in db.query(ReceiptLog).filter_by(receipt_id=row.id).one().message


def test_admin_and_scope_enforced(db,order):
    from app.invoice.router import router
    app=FastAPI();app.include_router(router,prefix="/api/invoice")
    app.dependency_overrides[get_db]=lambda:db
    user={"sub":"1","roles":[],"permissions":["invoice:write"]}
    app.dependency_overrides[get_current_user]=lambda:user
    with TestClient(app) as client:
        assert client.get(f"/api/invoice/invoices/{order.id}/lifecycle").status_code==403
        user.update(sub="2",permissions=["invoice:admin"])
        assert client.get(f"/api/invoice/invoices/{order.id}/lifecycle").status_code in (403,404)
        user.update(sub="1")
        assert client.get(f"/api/invoice/invoices/{order.id}/lifecycle").status_code==200


@pytest.mark.parametrize("clock",["2026-09-20T23:59:59","2026-09-21T00:00:01"])
def test_cancel_lease_beijing_midnight(db,order,monkeypatch,clock):
    now=datetime.fromisoformat(clock);monkeypatch.setattr(cancel,"beijing_now",lambda:now)
    live_order(monkeypatch);start(db,order)
    def timeout(*a,**kw): raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(lifecycle_remote,"request",timeout)
    cancel.remove_remote(db,order,1)
    assert datetime.fromisoformat(order.cancellation["lease_until"])==now+timedelta(minutes=5)

def test_old_sender_cannot_overwrite_cancellation(db, order):
    from app.invoice import push_attempt
    from sqlalchemy import update
    db.execute(update(Invoice).where(Invoice.id == order.id).values(status="cancel_pending"), execution_options={"synchronize_session": False})
    # Deliberately leave the ORM object stale.
    assert order.status == "synced"
    with pytest.raises(linked_sync_service.LostExecution):
        push_attempt.begin(db, order)
    db.refresh(order)
    assert order.status == "cancel_pending" and order.sync_attempt is None


def test_push_lease_and_invalidated_old_sender(db, order, monkeypatch):
    from app.invoice import push_attempt
    now = datetime(2026, 9, 20, 23, 59, 59)
    monkeypatch.setattr(push_attempt, "beijing_now", lambda: now)
    token = push_attempt.begin(db, order)
    with pytest.raises(ValueError, match="租约"):
        push_attempt.allow_recovery(order)
    push_attempt.ensure(db, order, token)
    now += timedelta(minutes=6)
    push_attempt.allow_recovery(order)
    with pytest.raises(linked_sync_service.LostExecution):
        push_attempt.ensure(db, order, token)
    push_attempt.finish(order)
    db.commit()
    token2 = push_attempt.begin(db, order)
    assert token2 != token
    with pytest.raises(linked_sync_service.LostExecution):
        push_attempt.ensure(db, order, token)
    push_attempt.ensure(db, order, token2)


@pytest.mark.parametrize("status", ["cancel_pending", "cancelled"])
def test_cancelled_receipt_is_not_claimed(db, order, status):
    from app.receipt import sync_service
    row = receipt(db, order)
    row.sync_status = "pending"
    order.status = status
    db.commit()
    sync_service.deliver(db, row.id)
    db.refresh(row)
    assert row.sync_status == "pending" and row.attempts == 0


def test_cancellation_between_prepare_and_push(db, order, monkeypatch):
    def prepare(db, inv, actor):
        db.commit()
        start(db, inv)
        return "pending-preserved"
    monkeypatch.setattr(sync_coordinator.semifinished_invoice_service, "prepare_invoice_sync", prepare)
    monkeypatch.setattr(sync_coordinator.xiaoman_service, "sync_invoice", lambda *a, **kw: pytest.fail("Must not push"))
    with pytest.raises(linked_sync_service.LostExecution):
        sync_coordinator.synchronize(db, order, 1)
    assert order.status == "cancel_pending"

@pytest.mark.parametrize('task_status,allowed',[('failed',True),('skipped',True),('done',False),('uncertain',False)])
def test_explicit_outbound_recovery_only_unsent(db,order,monkeypatch,task_status,allowed):
    from app.invoice import outbound_task_service as tasks
    monkeypatch.setattr(remote,'order_snapshot',lambda *a:{})
    monkeypatch.setattr(remote,'read',lambda *a:{'order_id':'123'})
    task=OkkiOutboundTask(invoice_id=order.id,order_id='123',status=task_status,reason=tasks.SKIP_REASON_GENERIC_MERGE)
    db.add(task);db.commit()
    if allowed:
        tasks.retry_reviewed(db,order,1,'已核对原订单无出库记录',linked_sync_service.edit_version(order))
        assert task.status=='pending' and order.outbound_auto_requested==1
    else:
        with pytest.raises(ValueError): tasks.retry_reviewed(db,order,1,'已核对原订单无出库记录',linked_sync_service.edit_version(order))


def test_equal_sku_totals_cannot_hide_wrong_order_line(db,order,monkeypatch):
    from app.invoice import xiaoman_service
    rows=[{'unique_id':'line1','product_id':'P','sku_id':'S','count':2},{'unique_id':'line2','product_id':'P','sku_id':'S','count':3}]
    monkeypatch.setattr(xiaoman_service,'_build_product_rows',lambda *a,**kw:(rows,{},[],{}))
    monkeypatch.setattr(linked_outbound_service,'find_related',lambda *a:[{'outbound_invoice_id':'7','status':1,'record_list':[
        {'order_id':'123','order_record_id':'line1','product_id':'P','sku_id':'S','outbound_count':5}]}])
    result=linked_outbound_service.summarize(db,order,{'order_id':'123'})
    assert len(result['differences'])==2 and result['category']=='quantity_or_link_difference'

@pytest.mark.parametrize('remote_uid,accepted',[('line1',True),('replaced',False)])
def test_uncertain_update_preserves_linked_fence_and_original_line(db,order,monkeypatch,remote_uid,accepted):
    from app.invoice import uncertain_recovery, xiaoman_service
    from app.invoice.models import InvoiceLinkedSync
    row=InvoiceLinkedSync(id='recover-linked',invoice_id=order.id,request_key='recover-key',request_hash='a'*64,
        created_by=1,status='uncertain',before={},after={},steps={},lease_until=datetime(2020,1,1))
    db.add(row);order.linked_sync_id=row.id;order.sync_status='sync_uncertain';db.commit()
    product={'unique_id':'line1','product_id':'P','sku_id':'S','count':1,'unit_price':100,'cost_amount':100}
    monkeypatch.setattr(xiaoman_service,'_build_product_rows',lambda *a,**kw:([product],[],[],{}))
    monkeypatch.setattr(lifecycle_remote,'read',lambda *a:{'order_id':'123','company_id':'101','currency':'USD',
        'amount':100,'product_list':[{**product,'unique_id':remote_uid}]})
    if accepted:
        uncertain_recovery.confirm_existing(db,order,'已核对原订单明细和金额完全一致',1)
        db.commit()
        assert order.linked_sync_id==row.id and order.sync_status=='not_synced'
        assert db.query(InvoiceSyncLog).filter_by(invoice_id=order.id,action='verify_update',success=1).count()==1
    else:
        with pytest.raises(ValueError): uncertain_recovery.confirm_existing(db,order,'已核对原订单明细和金额完全一致',1)
        assert order.sync_status=='sync_uncertain'


def test_remote_fee_cannot_replace_local_allocation(db,order,monkeypatch):
    row=receipt(db,order);row.bank_charge=2;db.commit()
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:{"order_id":"123","currency":"USD","amount":"80",
        "bank_charge":"1","real_amount":"79","collection_date":"2026-09-20","collect_status":1})
    with pytest.raises(ValueError,match="手续费非零"):
        changes.evidence(db,row)
    assert row.amount==100 and row.bank_charge==2


@pytest.mark.parametrize("net,fee,extra,accepted", [("0",2,{},True),("0",0,{},False),("78",2,{"bank_charge_usd":"1"},False),("78",2,{"bank_charge_rmb":"1"},False)])
def test_remote_net_amount_boundaries(db,order,monkeypatch,net,fee,extra,accepted):
    row=receipt(db,order);row.bank_charge=fee;db.commit()
    monkeypatch.setattr(lifecycle_remote,"read",lambda *a:{"order_id":"123","currency":"USD","amount":net,
        "bank_charge":"0","real_amount":net,"collection_date":"2026-09-20","collect_status":1,**extra})
    if accepted:
        proof=changes.evidence(db,row);changes.accept(db,row,body(row,proof),1)
        assert row.amount==Decimal(net)+fee and row.bank_charge==fee
    else:
        with pytest.raises(ValueError): changes.evidence(db,row)
