"""Isolated ledger tests. All remote reads are explicit fixtures; no live network."""
from decimal import Decimal
from datetime import date, timedelta
from types import SimpleNamespace
import pytest

from app.invoice.models import Invoice, InvoiceItem
from app.invoice import settlement_service as service
from app.invoice.settlement_models import ShipmentSettlement, SettlementApplication, Receivable, ReceiptBatch, ShipmentOutbound
from app.invoice.settlement_schemas import ShipmentCreate, ShipmentQuote
from app.receipt.models import Receipt
from app.core.time import beijing_now

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


@pytest.fixture
def presale(db, monkeypatch):
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    invoice = Invoice(invoice_no="PRE-1", order_type="presale", customer_id="C1", customer_name="Customer",
        sales_user_id=1, invoice_date=date(2026, 9, 23), currency="USD", product_amount=10000,
        total_amount=10000, surcharge_amount=0, shipping_fee=0, internal_accessory=0,
        status="synced", sync_status="synced", xiaoman_order_id="100")
    invoice.items = [InvoiceItem(product_id=1, sku_id=2, product_name="Hair", product_display="Hair",
        color="Black", quantity=10, price_per_piece=1000, total_price=10000, xiaoman_unique_id="11")]
    db.add(invoice); db.flush()
    deposit = Receipt(invoice_id=invoice.id, receipt_no="DEP", source="auto", purpose="presale_deposit",
        request_key="deposit_request_001", request_hash="x"*64, amount=3000, bank_charge=0,
        currency="USD", collection_date=date(2026,9,23), payment_type="TT", customer_id="C1",
        xiaoman_order_id="100", xiaoman_receipt_id="201", collect_status=1,
        sync_status="synced", created_by=1, attachment_ids=[])
    db.add(deposit); db.commit()
    monkeypatch.setattr(service, "fetch_evidence", lambda *_: {"receipt": {"rows": [{
        "cash_collection_id":"201", "amount":"3000.00", "currency":"USD", "collect_status":1}]},
        "outbounds": [], "order": {"order_id":"100"}})
    return invoice


def financial_quote(db,invoice_id,body,user):
    # SQLite financial units do not simulate current Ark employee authority.
    service.require_enabled()
    invoice=service.get_order(db,invoice_id,user)
    return service.build_quote(db,invoice,body,service.fetch_evidence(db,invoice))


def financial_create(db, invoice_id, body, user):
    # These SQLite units retain the original financial assertions. Real current
    # employee/authority/locks are covered through main/JWT/MySQL separately.
    from app.invoice import shipment_create_service
    from app.receipt import attachments, batch_service
    invoice=service.get_order(db,invoice_id,user)
    existing=db.query(ShipmentSettlement).filter_by(request_key=body.request_key).first()
    if existing is not None:
        shipment_create_service._replay(db,invoice,existing,invoice_id,body,user)
        return existing
    evidence=service.fetch_evidence(db,invoice)
    proof_evidence=None
    if body.payment:
        proof_evidence=attachments.verify_storage(attachments._bindings(
            batch_service._proof_rows(db,body.payment.attachment_ids,int(user['sub']))))
    return service._create_verified(db,invoice,body,user,evidence,proof_evidence)


def financial_state(db, row, user, action, version, reason):
    # Explicit isolated financial algorithm; not a current employee simulator.
    from app.invoice.shipment_state_service import StateGraph
    applications = tuple(db.query(SettlementApplication).filter_by(settlement_id=row.id).all())
    receipts = {app.receipt_id: db.get(Receipt, app.receipt_id) for app in applications}
    freight = db.query(Receivable).filter_by(settlement_id=row.id, kind="freight").first()
    outbound = db.query(ShipmentOutbound).filter_by(settlement_id=row.id).first()
    balance = service.funding_balance(db, row) if action == "resume" else None
    return service._change_state_verified(db, row, user, action, version, reason,
        StateGraph(applications, receipts, freight, outbound, balance))


def make(db, invoice, quantity=4, freight="200.00", key="shipment_request_001"):
    draft=ShipmentQuote(items=[{"invoice_item_id":invoice.items[0].id,"quantity":quantity}],freight_amount=freight)
    quote=financial_quote(db,invoice.id,draft,USER)
    return financial_create(db,invoice.id,ShipmentCreate(**draft.model_dump(),quote_hash=quote["quote_hash"],request_key=key),USER)


def test_partial_keeps_deposit_and_original_total(db,presale):
    row=make(db,presale)
    assert row.quote["new_payment_due"]=="4200.00"
    assert row.quote["deposit_applied"]=="0.00"
    assert presale.total_amount==Decimal("10000")
    assert db.query(SettlementApplication).count()==0


def test_presale_quote_rejects_unmapped_or_shared_okki_product_line(db,presale):
    presale.items[0].product_id = None
    with pytest.raises(ValueError, match="独立 OKKI 产品行"):
        make(db,presale)
    presale.items[0].product_id = 1
    presale.items.append(InvoiceItem(product_id=1, sku_id=2, product_name="Other", product_display="Other",
        color="Black", quantity=1, price_per_piece=100, total_price=100, xiaoman_unique_id="11"))
    db.flush()
    with pytest.raises(ValueError, match="共享 OKKI 明细"):
        make(db,presale)


def test_duplicate_returns_same_and_blocks_second_batch(db,presale):
    first=make(db,presale); db.commit()
    assert db.query(ShipmentSettlement).count()==1
    with pytest.raises(ValueError,match="活动|未完成"):
        make(db,presale,key="shipment_request_002")
    assert first.sequence==1


def test_partial_cannot_spend_last_deposit(db,presale):
    with pytest.raises(ValueError): make(db,presale,quantity=8)


def test_final_reserves_deposit_without_new_receipt(db,presale):
    row=make(db,presale,quantity=10,freight="150.00")
    assert row.quote["new_payment_due"]=="7150.00"
    assert db.query(Receipt).count()==1
    assert db.query(SettlementApplication).one().amount==3000


def test_cancel_unpaid_final_releases_only_application(db,presale):
    row=make(db,presale,quantity=10,freight="0.00")
    financial_state(db,row,USER,"cancel",row.version,"暂不发货")
    assert row.state=="cancelled"
    assert db.query(Receipt).one().status=="active"
    assert db.query(SettlementApplication).one().status=="released"


def test_cancel_cannot_race_freight_target_send(db,presale):
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_status="sending"
    with pytest.raises(ValueError,match="运费目标"):
        financial_state(db,row,USER,"cancel",row.version,"取消测试")
    assert row.state=="awaiting_payment"


def test_unknown_remote_payment_freezes_new_settlement(db,presale,monkeypatch):
    evidence=service.fetch_evidence(db,presale)
    evidence["receipt"]["rows"].append({"cash_collection_id":"999", "amount":"4000",
        "currency":"USD", "collect_status":1})
    monkeypatch.setattr(service,"fetch_evidence",lambda *a:evidence)
    with pytest.raises(ValueError,match="未分配的远端回款"):
        make(db,presale)
    assert db.query(ShipmentSettlement).count()==0


def test_create_replay_uses_same_settlement_and_does_not_reserve_twice(db,presale):
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":10}])
    quoted=financial_quote(db,presale.id,draft,USER)
    body=ShipmentCreate(**draft.model_dump(),quote_hash=quoted["quote_hash"],request_key="shipment_replay_001")
    first=financial_create(db,presale.id,body,USER); db.commit()
    replay=financial_create(db,presale.id,body,USER)
    assert replay.id==first.id
    assert db.query(SettlementApplication).count()==1


def test_quote_hash_cannot_hide_contract_or_quantity_change(db,presale):
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":4}])
    quoted=financial_quote(db,presale.id,draft,USER)
    body=ShipmentCreate(items=[{"invoice_item_id":presale.items[0].id,"quantity":5}],
        quote_hash=quoted["quote_hash"],request_key="shipment_stale_001")
    with pytest.raises(ValueError,match="QUOTE_STALE"):
        financial_create(db,presale.id,body,USER)
    assert db.query(ShipmentSettlement).count()==0


def test_partial_embedded_payment_stays_awaiting_payment(db,presale,monkeypatch):
    from app.receipt import attachments, remote
    monkeypatch.setattr(attachments,"origin",lambda: "https://proofs.invalid")
    from app.receipt.models import ReceiptAttachment
    proof=ReceiptAttachment(id="p1",filename="proof.png",storage_key="p1",content_type="image/png",
        size=100,sha256="a"*64,created_by=1)
    db.add(proof); db.commit()
    monkeypatch.setattr(remote,"receipt_types",lambda db:["TT"])
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":4}],freight_amount="200")
    quoted=financial_quote(db,presale.id,draft,USER)
    body=ShipmentCreate(**draft.model_dump(),quote_hash=quoted["quote_hash"],request_key="shipment_partial_001",
        payment=dict(amount="1000",collection_date="2026-09-23",payment_type="TT",attachment_ids=["p1"]))
    row=financial_create(db,presale.id,body,USER)
    assert row.state=="awaiting_payment"
    assert Decimal(service.funding_balance(db,row)["remaining_amount"])==3200
    assert Decimal(service.funding_balance(db,row)["effective_amount"])==0


@pytest.mark.parametrize("settlement,delivery,warehouse,expected", [
    (False, False, None, False),
    (True, False, 123, False),
    (True, True, None, False),
    (True, True, True, False),
    (True, True, -1, False),
    (True, True, 123, True),
])
def test_presale_capabilities_require_all_rollout_settings(monkeypatch, settlement, delivery, warehouse, expected):
    from app.invoice import settlement_policy
    monkeypatch.setattr(settlement_policy, "get_settings", lambda: SimpleNamespace(
        PRESALE_SETTLEMENT_ENABLED=settlement, PRESALE_DELIVERY_ENABLED=delivery,
        OKKI_PRESALE_WAREHOUSE_ID=warehouse))
    result = settlement_policy.capabilities()
    assert result["enabled"] is expected
    assert result["freight_delivery_enabled"] is expected
    assert result["outbound_delivery_enabled"] is expected
    if expected:
        settlement_policy.require_enabled()
        settlement_policy.require_delivery()
    else:
        with pytest.raises(ValueError, match="尚未启用"):
            settlement_policy.require_enabled()
        with pytest.raises(ValueError, match="尚未启用"):
            settlement_policy.require_delivery()


def test_history_remains_readable_after_order_not_ready(db,presale):
    row=make(db,presale); db.commit()
    presale.sync_status="failed"; db.commit()
    assert service.get(db,row.id,USER).id==row.id
    with pytest.raises(ValueError):
        service.get(db,row.id,USER,lock=True)


def test_freight_target_sender_binds_exact_readback_once(db,presale,monkeypatch):
    from app.invoice import freight_delivery
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_payload={"name":target.remote_order_name,"product_list":[]}
    target.remote_payload_hash=service.digest(target.remote_payload)
    db.commit()
    monkeypatch.setattr(freight_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(freight_delivery,"_source_active",lambda *_args:None)
    monkeypatch.setattr(freight_delivery,"_matching_active_orders",lambda *_args:set())
    sent=[]
    def push(_db,payload,before_send):
        before_send()
        sent.append(payload)
        return {"order_id": "301"}
    monkeypatch.setattr(freight_delivery.okki_client,"push_order",push)
    monkeypatch.setattr(freight_delivery.remote,"order_active",lambda *_args:True)
    monkeypatch.setattr(freight_delivery.remote,"read",lambda *_args:{
        "order_id":"301","name":target.remote_order_name,"company_id":"C1",
        "currency":"USD","amount":"200.00","product_total_amount":"0.00",
        "product_total_count":0,"product_list":[]})
    freight_delivery.deliver(db,target.id)
    db.refresh(target)
    assert target.remote_status=="bound"
    assert target.remote_order_id=="301"
    freight_delivery.deliver(db,target.id)
    assert len(sent)==1


def test_freight_target_timeout_is_quarantined_without_retry(db,presale,monkeypatch):
    from app.invoice import freight_delivery, okki_client
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_payload={"name":target.remote_order_name,"product_list":[]}
    target.remote_payload_hash=service.digest(target.remote_payload)
    db.commit()
    monkeypatch.setattr(freight_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(freight_delivery,"_source_active",lambda *_args:None)
    monkeypatch.setattr(freight_delivery,"_matching_active_orders",lambda *_args:set())
    sent=[]
    def push(_db,payload,before_send):
        before_send()
        sent.append(payload)
        raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(freight_delivery.okki_client,"push_order",push)
    freight_delivery.deliver(db,target.id)
    db.refresh(target)
    assert target.remote_status=="uncertain"
    assert target.remote_order_id is None
    freight_delivery.deliver(db,target.id)
    assert len(sent)==1


def test_freight_target_readback_failure_keeps_remote_identity(db,presale,monkeypatch):
    from app.invoice import freight_delivery
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_payload={"name":target.remote_order_name,"product_list":[]}
    target.remote_payload_hash=service.digest(target.remote_payload)
    db.commit()
    monkeypatch.setattr(freight_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(freight_delivery,"_source_active",lambda *_args:None)
    monkeypatch.setattr(freight_delivery,"_matching_active_orders",lambda *_args:set())
    sent=[]
    def push(_db,payload,before_send):
        before_send()
        sent.append(payload)
        return {"order_id":"301"}
    monkeypatch.setattr(freight_delivery.okki_client,"push_order",push)
    monkeypatch.setattr(freight_delivery.remote,"read",lambda *_args: (_ for _ in ()).throw(ValueError("read failed")))
    freight_delivery.deliver(db,target.id)
    db.refresh(target)
    assert target.remote_order_id=="301"
    assert target.remote_status=="uncertain"
    freight_delivery.deliver(db,target.id)
    assert len(sent)==1


def test_deleted_source_order_blocks_freight_post(db,presale,monkeypatch):
    from app.invoice import freight_delivery
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_payload={"name":target.remote_order_name,"product_list":[]}
    target.remote_payload_hash=service.digest(target.remote_payload)
    db.commit()
    monkeypatch.setattr(freight_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(freight_delivery,"_source_active",
        lambda *_args: (_ for _ in ()).throw(ValueError("source order deleted")))
    pushed=[]
    monkeypatch.setattr(freight_delivery.okki_client,"push_order",
        lambda *_args,**_kwargs:pushed.append(True))
    freight_delivery.deliver(db,target.id)
    db.refresh(target)
    assert target.remote_status=="failed" and pushed==[]


def test_failed_freight_retry_requires_absent_reserved_name(db,presale,monkeypatch):
    from app.invoice import freight_delivery, shipment_retry_service
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_status="failed"; db.commit()
    monkeypatch.setattr(freight_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(freight_delivery,"_matching_active_orders",lambda *_args:{"301"})
    with pytest.raises(ValueError,match="同名运费订单"):
        shipment_retry_service._require_absent(shipment_retry_service._read_evidence(db,shipment_retry_service.RetryTarget('freight',target.id,target.remote_order_name,target.created_at)))
    db.rollback(); db.refresh(target)
    assert target.remote_status=="failed"


def test_freight_receipt_uses_separate_target_balance(db,presale,monkeypatch):
    from app.receipt import balance, remote
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_order_id="301"
    target.remote_status="bound"
    db.flush()
    monkeypatch.setattr(remote,"read",lambda *_args:{
        "order_id":"301","name":target.remote_order_name,"company_id":"C1",
        "currency":"USD","amount":"200.00","product_total_amount":"0.00",
        "product_list":[],"exchange_rate":"100"})
    monkeypatch.setattr(remote,"order_receipts",lambda *_args:[])
    monkeypatch.setattr(remote,"order_active",lambda *_args:True)
    snapshot=remote.target_snapshot(db,target)
    payment=Receipt(invoice_id=presale.id,receivable_id=target.id,receipt_no="FREIGHT-1",
        source="manual",purpose="freight",request_key="freight_balance_001",request_hash="x"*64,
        amount=50,bank_charge=0,currency="USD",collection_date=date(2026,9,23),
        payment_type="TT",customer_id="C1",xiaoman_order_id="301",
        sync_status="pending",created_by=1,attachment_ids=[])
    db.add(payment); db.flush()
    assert balance.calculate_target(db,target,snapshot)["remaining_amount"]=="150.00"
    assert balance.calculate_target(db,target,snapshot,exclude_receipt=payment.id)["remaining_amount"]=="200.00"
    assert balance.calculate(db,presale,{"rows":[{"cash_collection_id":"201","amount":"3000.00",
        "currency":"USD","collect_status":1}],"exchange_rate":"100"})["remaining_amount"]=="7000.00"


def test_verified_funding_queues_one_frozen_partial_outbound(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    goods=db.query(Receivable).filter_by(invoice_id=presale.id,kind="goods").one()
    payment=Receipt(invoice_id=presale.id,receivable_id=goods.id,receipt_no="GOODS-1",
        source="manual",purpose="presale_goods",request_key="goods_funding_001",request_hash="x"*64,
        amount=4000,bank_charge=0,currency="USD",collection_date=date(2026,9,23),
        payment_type="TT",customer_id="C1",xiaoman_order_id="100",
        xiaoman_receipt_id="202",collect_status=1,sync_status="synced",
        created_by=1,attachment_ids=[])
    db.add(payment); db.flush()
    service.application(db,row,payment,"goods",payment.amount,0)
    db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,"order_record_id":11,
        "product_id":1,"sku_id":2,"outbound_count":4}]}
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args:payload)
    first=shipment_delivery.queue_ready(db,row.id)
    second=shipment_delivery.queue_ready(db,row.id)
    task=db.get(ShipmentOutbound,first)
    assert second is None
    assert task.status=="pending"
    assert task.payload==payload
    assert task.payload_hash==service.digest(payload)
    assert db.get(ShipmentSettlement,row.id).state=="outbound_pending"


def test_first_batch_candidate_counts_unoccupied_remote_line_as_zero(db,presale,monkeypatch):
    from app.invoice import shipment_delivery

    row=make(db,presale,quantity=4,freight="0.00")
    presale.customer_id="10"
    order={"order_id":"100","company_id":"10","currency":"USD","amount":"10000.00",
        "users":[{"user_id":"42"}],"exchange_rate":"100",
        "exchange_rate_usd":"100","product_list":[{
            "unique_id":"11","product_id":"1","sku_id":"2","count":10,
            "unit_price":"1000","unit":"Piece","to_outbound_count":0,
            "task_outbound_count":0}]}
    monkeypatch.setattr(shipment_delivery,"get_settings",
        lambda: SimpleNamespace(OKKI_PRESALE_WAREHOUSE_ID=123))
    monkeypatch.setattr(shipment_delivery,"_live_funding",lambda *_:order)
    monkeypatch.setattr(shipment_delivery.remote,"order_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.linked_outbound_service,"find_related",lambda *_:[])
    monkeypatch.setattr(shipment_delivery.xiaoman_service,"resolve_okki_user_id",lambda *_:42)

    payload=shipment_delivery._live_candidate(db,presale,row)
    assert payload["serial_id"]==row.settlement_no
    assert payload["record_list"][0]["outbound_count"]==4
    assert payload["record_list"][0]["order_record_id"]==11


def test_next_batch_candidate_counts_existing_remote_outbound(db,presale,monkeypatch):
    from app.invoice import shipment_delivery

    row=make(db,presale,quantity=4,freight="0.00")
    presale.customer_id="10"
    order={"order_id":"100","company_id":"10","currency":"USD","amount":"10000.00",
        "users":[{"user_id":"42"}],"exchange_rate":"100",
        "exchange_rate_usd":"100","product_list":[{
            "unique_id":"11","product_id":"1","sku_id":"2","count":10,
            "unit_price":"1000","unit":"Piece","to_outbound_count":0,
            "task_outbound_count":0}]}
    related=[{"outbound_invoice_id":"500","status":2,"record_list":[{
        "order_id":"100","order_record_id":"11","outbound_count":4}]}]
    monkeypatch.setattr(shipment_delivery,"get_settings",
        lambda: SimpleNamespace(OKKI_PRESALE_WAREHOUSE_ID=123))
    monkeypatch.setattr(shipment_delivery,"_live_funding",lambda *_:order)
    monkeypatch.setattr(shipment_delivery.remote,"order_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.linked_outbound_service,"find_related",lambda *_:related)
    monkeypatch.setattr(shipment_delivery,"check_outbounds",lambda *_args,**_kwargs:None)
    monkeypatch.setattr(shipment_delivery.xiaoman_service,"resolve_okki_user_id",lambda *_:42)

    assert shipment_delivery._live_candidate(db,presale,row)["record_list"][0]["outbound_count"]==4
    related[0]["record_list"][0]["outbound_count"]=7
    with pytest.raises(ValueError,match="剩余"):
        shipment_delivery._live_candidate(db,presale,row)


def test_partial_outbound_is_shipped_only_after_active_remote_status_two(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending",payload=payload,payload_hash=service.digest(payload))
    row.state="outbound_pending"
    db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_live_funding",lambda *_args:None)
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args:payload)
    monkeypatch.setattr(shipment_delivery.okki_client,"find_outbound_by_serial",lambda *_args:None)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_args:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_args:True)
    sent=[]
    def push(_db,body,before_send):
        before_send(); sent.append(body); return {"outbound_invoice_id":"401"}
    monkeypatch.setattr(shipment_delivery.okki_client,"push_outbound",push)
    state={"status":1}
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,
        "status":state["status"],"create_time":"2026-09-23 12:00:00",
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"12.50"}]})
    shipment_delivery.deliver(db,task.id)
    db.refresh(task); db.refresh(row)
    assert task.remote_id=="401" and task.status=="pending_remote"
    assert row.state=="outbound_pending"
    state["status"]=2
    shipment_delivery.refresh(db,task.id)
    db.refresh(task); db.refresh(row)
    assert task.status=="shipped" and row.state=="shipped"
    shipment_delivery.deliver(db,task.id)
    assert len(sent)==1


def test_deleted_freight_order_detail_is_not_accepted(db,monkeypatch):
    from app.receipt import remote
    detail={"order_id":"301","create_time":"2026-09-23 12:00:00"}
    calls=[]
    def listing(_db,path,params):
        calls.append((path,params["time_type"],params["start_time"]))
        return {"list":[{"order_id":"302"}],"count":1}
    monkeypatch.setattr(remote,"read",listing)
    assert remote.order_active(db,detail) is False
    assert len(calls)==2


def test_partial_outbound_unknown_result_cannot_send_again(db,presale,monkeypatch):
    from app.invoice import okki_client, shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending",payload=payload,payload_hash=service.digest(payload))
    row.state="outbound_pending"
    db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args:payload)
    monkeypatch.setattr(okki_client,"find_outbound_by_serial",lambda *_args:None)
    sent=[]
    def push(_db,body,before_send):
        before_send(); sent.append(body)
        raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(okki_client,"push_outbound",push)
    shipment_delivery.deliver(db,task.id)
    db.refresh(task); db.refresh(row)
    assert task.status=="uncertain" and row.state=="outbound_uncertain"
    shipment_delivery.deliver(db,task.id)
    assert len(sent)==1


def test_actual_outbound_confirmation_is_explicit_and_exact(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending_remote",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"12.50"}})
    row.state="outbound_pending"
    db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_live_funding",lambda *_args:None)
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args,**_kwargs:payload)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_args:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_args:True)
    state={"status":1}
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,
        "status":state["status"],"create_time":"2026-09-23 12:00:00",
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"12.50"}]})
    sent=[]
    def push(_db,body,before_send):
        before_send(); sent.append(body); state["status"]=2
        return {"outbound_invoice_id":"401"}
    monkeypatch.setattr(shipment_delivery.okki_client,"push_outbound",push)
    assert shipment_delivery.confirm(db,task.id,row.version,1,"Verified physical release") == "shipped"
    assert sent[0]["status"]==2 and sent[0]["outbound_invoice_id"]==401
    assert sent[0]["record_list"][0]["outbound_record_id"]==501
    assert sent[0]["record_list"][0]["cost_unit_price_rmb"]==12.5
    assert len(sent)==1
    with pytest.raises(ValueError,match="已变化"):
        shipment_delivery.confirm(db,task.id,row.version,1,"Duplicate release")


def test_ambiguous_actual_outbound_confirmation_never_reposts(db,presale,monkeypatch):
    from app.invoice import okki_client, shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending_remote",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"12.50"}})
    row.state="outbound_pending"
    db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args,**_kwargs:payload)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_args:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,
        "status":1,"create_time":"2026-09-23 12:00:00",
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"12.50"}]})
    sent=[]
    def push(_db,body,before_send):
        before_send(); sent.append(body)
        raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(shipment_delivery.okki_client,"push_outbound",push)
    assert shipment_delivery.confirm(db,task.id,row.version,1,"Verified physical release") == "confirm_uncertain"
    assert db.get(ShipmentSettlement,row.id).state=="outbound_uncertain"
    with pytest.raises(ValueError,match="已变化"):
        shipment_delivery.confirm(db,task.id,row.version,1,"Duplicate release")
    assert len(sent)==1


def test_actual_outbound_edit_needs_existing_remote_line_id(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending_remote",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"12.50"}})
    row.state="outbound_pending"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_args:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_args:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,
        "status":1,"create_time":"2026-09-23 12:00:00",
            "record_list":[{**payload["record_list"][0],"cost_unit_price_rmb":"12.50"}]})
    sent=[]
    monkeypatch.setattr(shipment_delivery.okki_client,"push_outbound",lambda *_args,**_kwargs:sent.append(True))
    with pytest.raises(ValueError,match="已变化"):
        shipment_delivery.confirm(db,task.id,row.version,1,"Checked stock")
    assert sent==[]


def test_paused_presale_batch_cannot_release_send_or_retry_payment(db,presale,monkeypatch):
    from app.receipt import service as receipt_service, sync_service
    row=make(db,presale,freight="0.00")
    batch=ReceiptBatch(batch_no="HB-PAUSED",customer_id="C1",currency="USD",
        gross_amount=4000,bank_charge_total=0,collection_date=date(2026,9,23),
        payment_type="TT",request_key="paused_batch_001",request_hash="x"*64,created_by=1)
    db.add(batch); db.flush()
    target=db.query(Receivable).filter_by(invoice_id=presale.id,kind="goods").one()
    payment=Receipt(invoice_id=presale.id,batch_id=batch.id,receivable_id=target.id,
        receipt_no="PAUSED-GOODS",source="manual",purpose="presale_goods",
        request_key="paused_goods_001",request_hash="x"*64,amount=4000,bank_charge=0,
        currency="USD",collection_date=date(2026,9,23),payment_type="TT",
        customer_id="C1",xiaoman_order_id="100",sync_status="waiting_target",
        created_by=1,attachment_ids=[])
    db.add(payment); db.flush()
    service.application(db,row,payment,"goods",payment.amount,0)
    row.state="paused"
    db.commit()
    sync_service.release_targets(db)
    db.refresh(payment)
    assert payment.sync_status=="waiting_target"
    payment.sync_status="pending"; db.commit()
    pushed=[]
    monkeypatch.setattr(sync_service.remote,"push",lambda *_args,**_kwargs:pushed.append(True))
    sync_service.deliver(db,payment.id)
    db.refresh(payment)
    assert payment.sync_status=="pending" and not pushed
    payment.sync_status="failed"; db.commit()
    with pytest.raises(ValueError,match="已暂停"):
        receipt_service._retry(db,payment,db.get(Invoice,payment.invoice_id),1,None)


def test_unknown_freight_target_only_binds_exact_active_existing_order(db,presale,monkeypatch):
    from app.invoice import freight_delivery, freight_reconciliation_service
    from app.invoice.settlement_schemas import SettlementRemoteReview
    row=make(db,presale,freight="200.00")
    target=db.query(Receivable).filter_by(settlement_id=row.id,kind="freight").one()
    target.remote_status="uncertain"; db.commit()
    before=(target.version,row.version,target.amount,target.handling_amount)
    lookup=freight_reconciliation_service.FreightTarget(target.id,"301",target.remote_order_name,
        target.customer_id,target.currency,Decimal(target.amount))
    body=SettlementRemoteReview(version=row.version,reason="Recover original freight",remote_id="301")
    detail={"order_id":"301","name":target.remote_order_name,"company_id":"C1",
            "currency":"USD","amount":"200.00","product_total_amount":"0.00",
            "product_total_count":0,"product_list":[],"create_time":"2026-09-23 12:00:00"}
    monkeypatch.setattr(freight_delivery.remote,"read",lambda *_args:detail)
    active={"value":False}
    monkeypatch.setattr(freight_delivery.remote,"order_active",lambda *_args:active["value"])
    evidence=freight_reconciliation_service._read_evidence(db,lookup)
    with pytest.raises(ValueError,match="不匹配"):
        freight_reconciliation_service._apply(target,body,evidence)
    db.rollback(); db.refresh(target)
    assert target.remote_order_id is None
    active["value"]=True
    evidence=freight_reconciliation_service._read_evidence(db,lookup)
    freight_reconciliation_service._apply(target,body,evidence); db.commit()
    assert target.remote_order_id=="301" and target.remote_status=="bound"
    assert (target.version,row.version,target.amount,target.handling_amount)==(before[0]+2,before[1],before[2],before[3])


def test_unknown_outbound_only_binds_exact_active_existing_note(db,presale,monkeypatch):
    import json
    from app.invoice import shipment_delivery, outbound_reconciliation_service as reconcile
    from app.invoice.settlement_schemas import SettlementRemoteReview
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="uncertain",payload=payload,
        payload_hash=service.digest(payload))
    row.state="outbound_uncertain"
    db.add(task); db.commit()
    detail={"outbound_invoice_id":"401","serial_id":row.settlement_no,"status":1,
            "create_time":"2026-09-23 12:00:00","record_list":[{
                **payload["record_list"][0],"outbound_record_id":"501",
                "cost_unit_price_rmb":"12.50"}]}
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:detail)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_args:"token")
    active={"value":False}
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_args:active["value"])
    before=(task.version,row.version,presale.total_amount,presale.surcharge_amount)
    body=SettlementRemoteReview(version=row.version,reason="Recover original outbound",remote_id="401")
    lookup=reconcile.OutboundTarget(task.id,"401",task.outbound_no,json.dumps(payload),json.dumps(None),None)
    graph=SimpleNamespace(outbound=task)
    evidence=reconcile._read_evidence(db,lookup)
    with pytest.raises(ValueError,match="不匹配"):
        reconcile._apply(db,presale,row,graph,body,evidence)
    db.rollback(); db.refresh(task)
    assert task.remote_id is None
    active["value"]=True
    evidence=reconcile._read_evidence(db,lookup)
    reconcile._apply(db,presale,row,graph,body,evidence); db.commit()
    assert task.remote_id=="401" and task.status=="pending_remote"
    assert (task.version,row.version,presale.total_amount,presale.surcharge_amount)==(before[0]+2,before[1]+2,before[2],before[3])


def test_outbound_readback_rejects_price_unit_and_cost_changes():
    from app.invoice import shipment_delivery
    frozen={"serial_id":"PRE-1-01","record_list":[{"order_id":100,"order_record_id":11,
        "product_id":1,"sku_id":2,"outbound_count":4,"sale_price":10,"product_unit":"Piece"}]}
    task=SimpleNamespace(remote_id="401",outbound_no="PRE-1-01",payload=frozen,
        remote_line_snapshot={"11":{"outbound_record_id":"501","cost_unit_price_rmb":"2.50"}})
    detail={"outbound_invoice_id":"401","serial_id":"PRE-1-01","status":1,
        "record_list":[{**frozen["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"2.50"}]}
    assert shipment_delivery._verify(task,detail)
    for field,value in [("sale_price","11.00"),("product_unit","Box"),
                        ("cost_unit_price_rmb","3.50"),("outbound_record_id","502")]:
        changed={**detail,"record_list":[{**detail["record_list"][0],field:value}]}
        assert not shipment_delivery._verify(task,changed), field


def test_remote_shipped_with_invalid_funding_stays_blocked(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending_remote",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"2.50"}})
    row.state="outbound_pending"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_:False)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,"status":2,
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"2.50"}]})
    assert shipment_delivery.refresh(db,task.id)=="shipped_unfunded"
    assert db.get(ShipmentSettlement,row.id).state=="outbound_uncertain"
    with pytest.raises(ValueError,match="活动|未完成"):
        make(db,presale,key="shipment_request_after_unfunded")


def test_status_two_requires_a_prior_pending_line_baseline(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="verifying",remote_id="401",
        payload=payload,payload_hash=service.digest(payload))
    row.state="outbound_pending"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_:True)
    monkeypatch.setattr(shipment_delivery,"_live_funding",lambda *_:None)
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,"status":2,
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"2.50"}]})
    assert shipment_delivery.refresh(db,task.id)=="uncertain"
    assert db.get(ShipmentSettlement,row.id).state=="outbound_uncertain"


def test_status_two_funding_reconciles_all_active_remote_receipts(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    monkeypatch.setattr(shipment_delivery.remote,"order_snapshot",lambda *_:{"rows":[
        {"cash_collection_id":"201","amount":"3000.00","currency":"USD","collect_status":1},
        {"cash_collection_id":"999","amount":"1.00","currency":"USD","collect_status":1}]})
    with pytest.raises(ValueError,match="未分配的远端回款"):
        shipment_delivery._live_funding(db,presale,row)


def test_remote_list_pending_status_blocks_outbound_even_if_receipt_detail_is_effective(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payment=Receipt(invoice_id=presale.id,receipt_no="PAY-1",source="manual",
        purpose="goods",request_key="pending_remote_payment_001",request_hash="p"*64,
        amount=4000,bank_charge=0,currency="USD",collection_date=date(2026,9,23),
        payment_type="TT",customer_id="C1",xiaoman_order_id="100",
        xiaoman_receipt_id="202",collect_status=1,sync_status="synced",
        created_by=1,attachment_ids=[])
    db.add(payment); db.flush()
    db.add(SettlementApplication(settlement_id=row.id,receipt_id=payment.id,
        component="goods",amount=4000,bank_charge=0,status="reserved"))
    db.commit()
    monkeypatch.setattr(shipment_delivery.remote,"order_snapshot",lambda *_:{"rows":[
        {"cash_collection_id":"201","amount":"3000.00","currency":"USD","collect_status":1},
        {"cash_collection_id":"202","amount":"4000.00","currency":"USD","collect_status":0}]})
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{"order_id":"100"})
    monkeypatch.setattr(shipment_delivery.remote,"order_active",lambda *_:True)
    with pytest.raises(ValueError,match="远端有效回款已缺失或未生效"):
        shipment_delivery._live_funding(db,presale,row)


def test_shipped_outbound_cannot_reopen_when_remote_returns_to_pending(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="shipped",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"2.50"}})
    row.state="shipped"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,"status":1,
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"2.50"}]})
    assert shipment_delivery.refresh(db,task.id)=="uncertain"
    assert db.get(ShipmentSettlement,row.id).state=="outbound_uncertain"


def test_prior_shipped_receipt_losing_effective_status_blocks_next_batch(db,presale):
    row=make(db,presale,freight="0.00")
    payment=Receipt(invoice_id=presale.id,receipt_no="PARTIAL",source="manual",
        purpose="goods",request_key="historical_payment_001",request_hash="y"*64,
        amount=4000,bank_charge=0,currency="USD",collection_date=date(2026,9,23),
        payment_type="TT",customer_id="C1",xiaoman_order_id="100",
        xiaoman_receipt_id="202",collect_status=1,sync_status="synced",
        created_by=1,attachment_ids=[])
    db.add(payment); db.flush()
    db.add(SettlementApplication(settlement_id=row.id,receipt_id=payment.id,
        component="goods",amount=4000,bank_charge=0,status="applied"))
    row.state="shipped"; db.commit()
    evidence={"receipt":{"rows":[
        {"cash_collection_id":"201","amount":"3000.00","currency":"USD","collect_status":1},
        {"cash_collection_id":"202","amount":"4000.00","currency":"USD","collect_status":0}]}}
    with pytest.raises(ValueError,match="历史已出库批次的回款已失效"):
        service.check_shipped_funding(db,presale,evidence,[row])


def test_failed_shipped_readbacks_rotate_to_later_tasks(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    old=beijing_now()-timedelta(hours=2)
    identities=[]
    for number in range(21):
        row=ShipmentSettlement(invoice_id=presale.id,sequence=number+1,
            settlement_no=f"PRESALE-CHECK-{number}",state="shipped",is_final=0,
            quote={},quote_hash="q"*64,request_key=f"check_{number}",
            request_hash="r"*64,created_by=1)
        db.add(row); db.flush()
        task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
            outbound_no=row.settlement_no,status="shipped",remote_id=str(1000+number),
            payload={},payload_hash="h"*64,verified_at=old)
        db.add(task); db.flush(); identities.append(task.id)
    db.commit()
    checked=[]
    def fail(_db,identity):
        checked.append(identity)
        raise ValueError("temporary OKKI read error")
    monkeypatch.setattr(shipment_delivery,"refresh",fail)
    shipment_delivery.process_pending(db)
    assert checked==identities[:20]
    assert all(db.get(ShipmentOutbound,identity).last_check_attempt_at for identity in identities[:20])
    shipment_delivery.process_pending(db)
    assert checked[-1]==identities[20]


def test_active_confirmation_lease_cannot_be_stolen_by_refresh(db,presale,monkeypatch):
    from app.invoice import shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="confirming",remote_id="401",
        attempt_token="attempt",lease_until=beijing_now()+timedelta(minutes=5),
        payload=payload,payload_hash=service.digest(payload))
    row.state="outbound_pending"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery.okki_client,"ensure_access_token",lambda *_:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,"status":1,
        "record_list":payload["record_list"]})
    with pytest.raises(ValueError,match="仍在发送"):
        shipment_delivery.refresh(db,task.id)
    db.rollback(); db.refresh(task)
    assert task.status=="confirming" and task.attempt_token=="attempt"
    assert task.remote_id=="401"


def test_explicit_outbound_edit_rejection_can_be_retried_after_exact_readback(db,presale,monkeypatch):
    from app.invoice import okki_client, shipment_delivery
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4,
        "sale_price":10,"product_unit":"Piece"}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="pending_remote",remote_id="401",
        payload=payload,payload_hash=service.digest(payload),remote_line_snapshot={
            "11":{"outbound_record_id":"501","cost_unit_price_rmb":"2.50"}})
    row.state="outbound_pending"; db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    monkeypatch.setattr(shipment_delivery,"_refresh_funding",lambda *_:True)
    monkeypatch.setattr(shipment_delivery,"_funded",lambda *_:True)
    monkeypatch.setattr(shipment_delivery,"_live_candidate",lambda *_args,**_kwargs:payload)
    monkeypatch.setattr(okki_client,"ensure_access_token",lambda *_:"token")
    monkeypatch.setattr(shipment_delivery.outbound_presence,"is_active",lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote,"read",lambda *_args:{
        "outbound_invoice_id":"401","serial_id":row.settlement_no,"status":1,
        "record_list":[{**payload["record_list"][0],"outbound_record_id":"501",
                        "cost_unit_price_rmb":"2.50"}]})
    attempts=[]
    def reject(_db,body,before_send):
        before_send(); attempts.append(body)
        raise okki_client.OkkiApiError("stock rejected")
    monkeypatch.setattr(okki_client,"push_outbound",reject)
    assert shipment_delivery.confirm(db,task.id,row.version,1,"Checked stock") == "pending_remote"
    db.refresh(row); db.refresh(task)
    assert row.state=="outbound_pending" and len(attempts)==1
    assert "明确拒绝" in task.last_error
    assert shipment_delivery.confirm(db,task.id,row.version,1,"Stock restored") == "pending_remote"
    assert len(attempts)==2


def test_failed_outbound_retry_requires_exact_serial_absence(db,presale,monkeypatch):
    from app.invoice import shipment_delivery, shipment_retry_service
    row=make(db,presale,freight="0.00")
    payload={"serial_id":row.settlement_no,"record_list":[{"order_id":100,
        "order_record_id":11,"product_id":1,"sku_id":2,"outbound_count":4}]}
    task=ShipmentOutbound(settlement_id=row.id,invoice_id=presale.id,
        outbound_no=row.settlement_no,status="failed",payload=payload,
        payload_hash=service.digest(payload))
    row.state="review_required"
    db.add(task); db.commit()
    monkeypatch.setattr(shipment_delivery,"require_delivery",lambda:None)
    found={"value":{"outbound_invoice_id":"401"}}
    monkeypatch.setattr(shipment_delivery.okki_client,"find_outbound_by_serial",lambda *_args:found["value"])
    with pytest.raises(ValueError,match="已有同编号"):
        shipment_retry_service._require_absent(shipment_retry_service._read_evidence(db,shipment_retry_service.RetryTarget('outbound',task.id,task.outbound_no,task.created_at)))
    db.rollback(); db.refresh(task)
    assert task.status=="failed"
    found["value"]=None
    before=(row.version,task.version)
    proof=shipment_retry_service._read_evidence(db,shipment_retry_service.RetryTarget('outbound',task.id,task.outbound_no,task.created_at))
    assert proof.target.kind=='outbound' and proof.target.target_id==task.id and not proof.exists
    shipment_retry_service._require_absent(proof)
    shipment_retry_service._apply(row,task,'outbound');db.commit()
    assert task.status=='pending' and (row.version,task.version)==(before[0]+1,before[1]+1)
    assert db.get(ShipmentSettlement,row.id).state=="outbound_pending"
