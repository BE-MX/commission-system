"""Audited V1 funding upgrade; isolated SQLite, synthetic complete GET evidence."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import pytest
from fastapi import HTTPException

from app.invoice import funding_upgrade_service as upgrades, settlement_service as shipments
from app.invoice import shipment_create_service, shipment_state_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, Receivable,
    SettlementApplication, SettlementFundingAmendment, ShipmentOutbound)
from app.invoice.settlement_pricing import quote_settlement
from app.invoice.settlement_schemas import FundingUpgrade, ShipmentCreate
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog, ReceiptAttempt
from app.core.time import beijing_now
from datetime import timedelta
from app.receipt import authority, remote

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


@pytest.fixture
def legacy(db, monkeypatch):
    monkeypatch.setattr(upgrades, "lock_authority", lambda *_a, **_kw: None)
    monkeypatch.setattr(authority, "current_user", lambda _db, _user, *_a, **_kw: USER)
    monkeypatch.setattr(shipments, "require_enabled", lambda: None)
    invoice = Invoice(invoice_no="UPGRADE", order_type="presale", customer_id="123", customer_name="Veronika",
        sales_user_id=1, invoice_date=date(2026, 10, 9), currency="USD", product_amount=2090,
        total_amount=2090, surcharge_amount=0, shipping_fee=0, internal_accessory=0,
        sync_status="synced", xiaoman_order_id="100")
    invoice.items = [InvoiceItem(product_id=1, sku_id=2, product_name="Hair", product_display="Hair",
        color="Black", quantity=10, price_per_piece=209, total_price=2090, xiaoman_unique_id="11")]
    db.add(invoice); db.flush()
    monkeypatch.setattr(upgrades.edit_authority, "lock_document", lambda _db, identity, **_kw: _db.get(Invoice, identity))
    receipt = Receipt(invoice_id=invoice.id, receipt_no="ORIGINAL", source="auto", purpose="presale_deposit",
        request_key="original_receipt_001", request_hash="b"*64, amount=1077, bank_charge=0,
        currency="USD", collection_date=date(2026, 10, 8), payment_type="TT", customer_id="123",
        xiaoman_order_id="100", xiaoman_receipt_id="201", collect_status=1, sync_status="synced",
        created_by=1, attachment_ids=[])
    db.add(receipt); db.flush()
    intent = ReceiptIntent(invoice_id=invoice.id, receipt_id=receipt.id, eligible=1, status="converted",
        amount=1077, collection_date=receipt.collection_date, payment_type="TT", customer_id="123",
        currency="USD", attachment_ids=[], created_by=1)
    db.add(intent)
    quote = quote_settlement([{"invoice_item_id": invoice.items[0].id, "quantity": 10,
        "total_price": "2090", "requested_quantity": 3}], "0", "0", "1077", "0", freight="38")
    quote.update(currency="USD", customer_id="123", invoice_id=invoice.id, invoice_no=invoice.invoice_no,
        deposit_receipt_id=receipt.id, quote_hash="a"*64)
    row = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="UPGRADE-01",
        is_final=0, quote=quote, quote_hash=quote["quote_hash"], request_key="original_shipment_001",
        request_hash="a"*64, created_by=1)
    db.add(row); db.flush()
    original_body = ShipmentCreate(items=[{"invoice_item_id": invoice.items[0].id, "quantity": 3}],
        freight_amount="38", quote_hash=row.quote_hash, request_key=row.request_key)
    row.request_hash = shipments.digest(original_body.model_dump(mode="json", exclude={"is_final"}))
    db.add(SettlementItem(settlement_id=row.id, invoice_item_id=invoice.items[0].id, quantity=3,
        line_amount=627, snapshot={"order_id":"100", "order_record_id":"11", "product_id":1,
            "sku_id":2, "product_name":"Hair", "outbound_count":3, "sale_price":"209.00"}))
    freight = shipments.target(db, invoice, row)
    freight.remote_order_id = "300"; freight.remote_status = "bound"
    freight.remote_payload = {"name":freight.remote_order_name, "amount":"38", "product_list":[]}
    freight.remote_payload_hash = shipments.digest(freight.remote_payload)
    db.commit()
    main = {"order_id":"100", "company_id":"123", "currency":"USD", "amount":"2090",
        "create_time":"2026-10-01 12:00:00"}
    fr = {"order_id":"300", "name":freight.remote_order_name, "company_id":"123", "currency":"USD",
        "amount":"38", "product_total_amount":"0", "product_total_count":0, "product_list":[],
        "create_time":"2026-10-01 12:00:00"}
    cash = {"cash_collection_id":"201", "order_id":"100", "currency":"USD", "amount":"1077",
        "real_amount":"1077", "bank_charge":"0", "bank_charge_rmb":"0", "bank_charge_usd":"0",
        "collection_date":"2026-10-08", "collect_status":1}
    monkeypatch.setattr(remote, "read", lambda _db, _path, params: deepcopy(main if params["order_id"]=="100" else fr))
    monkeypatch.setattr(remote, "order_active", lambda *_: True)
    monkeypatch.setattr(remote, "order_snapshot", lambda *_: {"invoice_binding":remote.invoice_binding(invoice),
        "rows":[deepcopy(cash)]})
    monkeypatch.setattr(remote, "receipt_info", lambda *_: deepcopy(cash))
    monkeypatch.setattr(remote, "target_snapshot", lambda *_: {"rows":[], "target_binding":[freight.id,
        "300", str(freight.amount), "USD", "123", freight.version]})
    monkeypatch.setattr(upgrades.linked_outbound_service, "find_related", lambda *_: [])
    body = FundingUpgrade(version=row.version, receipt_id=receipt.id, receipt_version=receipt.version,
        purpose="presale_advance", reason="Customer confirmed this payment is reusable goods advance",
        request_key="upgrade_funding_0001")
    return invoice, row, receipt, freight, intent, body, original_body


def run_upgrade(db,row,body,user=USER):
    identity=row.id
    assert not db.new and not db.dirty and not db.deleted
    db.rollback()  # End fixture/assertion reads; production starts fresh.
    return upgrades.upgrade(db,identity,body,user)


@pytest.mark.parametrize("paused", [False, True])
def test_1077_upgrade_preserves_original_bound_freight_and_cash(db, legacy, paused):
    invoice, row, receipt, freight, intent, body, original_body = legacy
    if paused:
        row.state="paused"; db.commit()
    frozen_quote, frozen_freight = deepcopy(row.quote), upgrades.values(freight)
    frozen_cash = upgrades.cash_facts(receipt)
    result = run_upgrade(db,row,body); db.commit()
    assert result["settlement"]["id"] == row.id
    assert row.state == ("paused" if paused else "awaiting_payment")
    assert row.quote["funding_version"] == 2 and row.quote["new_payment_due"] == "0.00"
    assert row.quote["pool_balances"][0]["remaining_amount"] == "412.00"
    assert upgrades.values(freight) == frozen_freight
    assert upgrades.cash_facts(receipt) == frozen_cash
    assert receipt.purpose == intent.purpose == "presale_advance" and intent.bank_charge == 0
    apps = db.query(SettlementApplication).filter_by(settlement_id=row.id).all()
    assert sorted((a.component,a.amount,a.bank_charge,a.status) for a in apps) == [
        ("freight",Decimal("38"),Decimal("0"),"reserved"), ("goods",Decimal("627"),Decimal("0"),"reserved")]
    amendment = db.query(SettlementFundingAmendment).one()
    assert amendment.before_snapshot["settlement"]["quote"] == frozen_quote
    assert amendment.before_snapshot["settlement"]["request_key"] == row.request_key == original_body.request_key
    assert db.query(Receipt).count() == 1 and db.query(ShipmentOutbound).count() == 0
    assert db.query(ReceiptLog).filter_by(action="purpose_changed").count() == 1
    assert run_upgrade(db,row,body)["amendment"]["id"] == amendment.id
    assert db.query(SettlementFundingAmendment).count() == 1 and db.query(SettlementApplication).count() == 2
    with pytest.raises(HTTPException) as old:
        shipment_create_service._replay(db,invoice,row,invoice.id,original_body,USER)
    assert old.value.status_code == 409 and "读取原批" in str(old.value.detail)


@pytest.mark.parametrize("field,value", [("amount",Decimal("1076")), ("bank_charge",Decimal("1")),
    ("collection_date",date(2026,10,7)), ("attachment_ids",["changed"]), ("xiaoman_receipt_id","999")])
def test_upgrade_replay_rejects_changed_cash_facts(db,legacy,field,value):
    _,row,receipt,_,_,body,_=legacy
    run_upgrade(db,row,body); db.commit()
    setattr(receipt,field,value); db.commit()
    with pytest.raises((ValueError,HTTPException)):
        run_upgrade(db,row,body)


def test_upgrade_replay_allows_scheduler_versions_and_application_progress(db,legacy):
    _,row,receipt,_,_,body,_=legacy
    run_upgrade(db,row,body); db.commit()
    row.version += 2; receipt.version += 3; row.state="shipped"
    db.query(SettlementApplication).filter_by(settlement_id=row.id).update({"status":"applied"})
    db.commit()
    assert run_upgrade(db,row,body)["settlement"]["state"] == "shipped"


def test_upgrade_rejects_fresh_app_and_second_key(db,legacy):
    _,row,receipt,_,_,body,_=legacy
    shipments.application(db,row,receipt,"deposit",Decimal("1"),Decimal("0")); db.commit()
    with pytest.raises((ValueError,HTTPException)):
        run_upgrade(db,row,body)
    assert db.query(SettlementFundingAmendment).count()==0 and receipt.purpose=="presale_deposit"


@pytest.mark.parametrize("change", ["receipt", "application", "outbound", "freight_version", "late_result"])
def test_upgrade_rejects_local_changes_during_unlocked_gets(db,legacy,monkeypatch,change):
    invoice,row,receipt,freight,_,body,_=legacy
    original=upgrades._read_evidence
    def read_then_change(session,lookup):
        assert not session.in_transaction()
        result=original(session,lookup)
        if change=="receipt":
            session.add(Receipt(invoice_id=invoice.id,receipt_no="CONCURRENT",source="manual",purpose="presale_advance",
                request_key="concurrent_receipt_001",request_hash="b"*64,amount=1,bank_charge=0,currency="USD",
                customer_id="123",collection_date=date(2026,10,9),payment_type="TT",created_by=1,attachment_ids=[]))
        elif change=="application":
            shipments.application(session,row,receipt,"deposit",Decimal("1"),Decimal("0"))
        elif change=="outbound":
            session.add(ShipmentOutbound(settlement_id=row.id,invoice_id=invoice.id,outbound_no="CONCURRENT",
                status="pending",payload={},payload_hash="c"*64))
        elif change=="freight_version":freight.version+=1
        else:session.add(ReceiptLog(receipt_id=receipt.id,action="late_result",message="Concurrent result",created_by=1))
        session.commit()
        return result
    monkeypatch.setattr(upgrades,"_read_evidence",read_then_change)
    with pytest.raises(HTTPException) as rejected:run_upgrade(db,row,body)
    assert rejected.value.status_code==409
    assert db.query(SettlementFundingAmendment).count()==0 and receipt.purpose=="presale_deposit"


def test_upgrade_rechecks_all_three_permissions_after_gets(db,legacy,monkeypatch):
    _,row,receipt,_,_,body,_=legacy
    calls=[]
    def current(_db,_user,*rights,**_kw):
        calls.append(rights)
        if len(calls)==2:raise HTTPException(403,"Revoked permission")
        return USER
    monkeypatch.setattr(authority,"current_user",current)
    with pytest.raises(HTTPException) as rejected:run_upgrade(db,row,body)
    assert rejected.value.status_code==403
    assert calls==[("invoice:write","shipment:write","receipt:write")]*2
    assert receipt.purpose=="presale_deposit" and db.query(SettlementFundingAmendment).count()==0


@pytest.mark.parametrize("kind", ["main_outbound", "freight_outbound", "freight_receipt", "cash_date", "cash_status",
    "cash_amount", "cash_moved", "freight_product", "freight_inactive", "incomplete_receipts"])
def test_upgrade_requires_complete_remote_absence_and_original_cash(db,legacy,monkeypatch,kind):
    _,row,receipt,freight,_,body,_=legacy
    if kind.endswith("outbound"):
        identity="100" if kind=="main_outbound" else "300"
        monkeypatch.setattr(upgrades.linked_outbound_service,"find_related",lambda _db,order:
            [{"outbound_invoice_id":"777","status":1,"record_list":[]}] if order["order_id"]==identity else [])
    elif kind in {"freight_receipt","incomplete_receipts"}:
        monkeypatch.setattr(remote,"target_snapshot",lambda *_:{"rows":[] if kind=="incomplete_receipts" else [
            {"cash_collection_id":"301","currency":"USD","amount":"1","collect_status":1}],
            "target_binding":[] if kind=="incomplete_receipts" else [freight.id,"300",str(freight.amount),"USD","123",freight.version]})
    elif kind.startswith("cash_"):
        original=remote.receipt_info
        fields={"cash_date":("collection_date","2026-10-07"),"cash_status":("collect_status",0),
            "cash_amount":("amount","1076"),"cash_moved":("order_id","999")}
        def bad(*args):
            data=original(*args); key,value=fields[kind]; data[key]=value; return data
        monkeypatch.setattr(remote,"receipt_info",bad)
    elif kind=="freight_product":
        original=remote.read
        def bad_read(*args):
            data=original(*args)
            if data["order_id"]=="300":data["product_total_count"]=1
            return data
        monkeypatch.setattr(remote,"read",bad_read)
    else:monkeypatch.setattr(remote,"order_active",lambda _db,order:order["order_id"]!="300")
    with pytest.raises(HTTPException) as rejected:run_upgrade(db,row,body)
    assert rejected.value.status_code==503
    assert receipt.purpose=="presale_deposit" and db.query(SettlementFundingAmendment).count()==0


@pytest.mark.parametrize("kind",["quote_amount","item_amount","item_identity","original_hash","extra_active","wrong_version"])
def test_upgrade_uses_only_consistent_original_quote_and_item_money(db,legacy,kind):
    invoice,row,receipt,_,_,body,_=legacy
    if kind=="quote_amount":row.quote={**row.quote,"goods_amount":"626"}
    elif kind=="item_amount":db.query(SettlementItem).one().line_amount=626
    elif kind=="item_identity":
        part=db.query(SettlementItem).one(); part.snapshot={**part.snapshot,"order_record_id":"99"}
    elif kind=="original_hash":row.request_hash="f"*64
    elif kind=="extra_active":
        db.add(ShipmentSettlement(invoice_id=invoice.id,sequence=2,settlement_no="OTHER",state="paused",is_final=0,
            quote={},quote_hash="b"*64,request_key="other_original_001",request_hash="b"*64,created_by=1))
    else:body=body.model_copy(update={"receipt_version":body.receipt_version+1})
    db.commit()
    with pytest.raises(ValueError):run_upgrade(db,row,body)
    assert receipt.purpose=="presale_deposit" and db.query(SettlementFundingAmendment).count()==0


def test_upgrade_does_not_reprice_current_invoice_or_confirm_outbound(db,legacy,monkeypatch):
    _,row,_,_,_,body,_=legacy
    item=db.query(InvoiceItem).one(); item.price_per_piece=999; item.total_price=9990; db.commit()
    monkeypatch.setattr(shipments,"build_quote",lambda *_a,**_kw:pytest.fail("Current pricing must not be used"))
    run_upgrade(db,row,body); db.commit()
    assert row.quote["goods_amount"]=="627.00" and row.quote["is_final"] is False
    assert db.query(ShipmentOutbound).count()==0


@pytest.mark.parametrize("kind",["second_key","reason","actor","application_amount","freight_name"])
def test_upgrade_replay_rejects_other_command_or_frozen_graph_tampering(db,legacy,monkeypatch,kind):
    _,row,_,freight,_,body,_=legacy
    run_upgrade(db,row,body); db.commit()
    if kind=="second_key":body=body.model_copy(update={"request_key":"second_upgrade_0001"})
    elif kind=="reason":body=body.model_copy(update={"reason":"Different confirmed payment intent"})
    elif kind=="actor":monkeypatch.setattr(authority,"current_user",lambda *_a,**_kw:{**USER,"sub":"2"})
    elif kind=="application_amount":db.query(SettlementApplication).filter_by(component="goods").one().amount=626
    else:freight.remote_order_name="CHANGED"
    db.commit()
    with pytest.raises((ValueError,HTTPException)):run_upgrade(db,row,body)
    assert db.query(SettlementFundingAmendment).count()==1 and db.query(SettlementApplication).count()==2


def test_upgrade_preserves_actual_bank_fee_and_residual(db,legacy,monkeypatch):
    _,row,receipt,_,intent,body,_=legacy
    receipt.bank_charge=3
    row.quote={**row.quote,"handling_amount":"5.00","goods_payment_charge":"5.00",
        "goods_payment_due":"632.00","new_payment_due":"670.00"}
    db.commit()
    original_info=remote.receipt_info; original_snapshot=remote.order_snapshot
    def info(*args):data=original_info(*args); data.update(amount='1074',real_amount='1074'); return data
    def snapshot(*args):data=original_snapshot(*args); data['rows'][0].update(amount='1074',real_amount='1074'); return data
    monkeypatch.setattr(remote,'receipt_info',info); monkeypatch.setattr(remote,'order_snapshot',snapshot)
    run_upgrade(db,row,body); db.commit()
    assert receipt.amount==1077 and receipt.bank_charge==intent.bank_charge==3
    apps=db.query(SettlementApplication).order_by(SettlementApplication.component).all()
    assert [(app.component,app.amount,app.bank_charge) for app in apps]==[
        ('freight',Decimal('38'),Decimal('0')),('goods',Decimal('632'),Decimal('3'))]
    assert row.quote['pool_balances'][0]['remaining_amount']=='407.00'


def test_verified_terminal_receipt_and_bound_freight_retain_historical_fences(db,legacy):
    _,row,receipt,freight,_,body,_=legacy
    receipt.send_phase='verified'; receipt.attempt_token='completed_receipt_token'
    receipt.lease_until=beijing_now()-timedelta(minutes=10)
    freight.attempt_token='completed_freight_token'
    db.add(ReceiptAttempt(token=receipt.attempt_token,receipt_id=receipt.id,
        payload_hash='a'*64,remote_id=receipt.xiaoman_receipt_id,handled_at=beijing_now()-timedelta(minutes=15)))
    db.commit()
    frozen=(receipt.attempt_token,receipt.lease_until,freight.attempt_token,freight.lease_until)
    run_upgrade(db,row,body); db.commit()
    assert (receipt.attempt_token,receipt.lease_until,freight.attempt_token,freight.lease_until)==frozen
    assert row.quote['new_payment_due']=='0.00' and db.query(ReceiptAttempt).count()==1


@pytest.mark.parametrize('kind',['receipt_future_lease','freight_future_lease','unhandled','unmatched_token','wrong_attempt_remote'])
def test_active_lease_or_unresolved_receipt_attempt_blocks_upgrade(db,legacy,kind):
    _,row,receipt,freight,_,body,_=legacy
    if kind=='receipt_future_lease':receipt.lease_until=beijing_now()+timedelta(minutes=10)
    elif kind=='freight_future_lease':freight.lease_until=beijing_now()+timedelta(minutes=10)
    else:
        receipt.attempt_token='unfinished_receipt_token'; receipt.send_phase='verified'
        if kind!='unmatched_token':
            db.add(ReceiptAttempt(token=receipt.attempt_token,receipt_id=receipt.id,payload_hash='a'*64,
                remote_id='999' if kind=='wrong_attempt_remote' else receipt.xiaoman_receipt_id,
                handled_at=None if kind=='unhandled' else beijing_now()))
    db.commit()
    with pytest.raises(ValueError):run_upgrade(db,row,body)
    assert receipt.purpose=='presale_deposit' and db.query(SettlementFundingAmendment).count()==0


@pytest.mark.parametrize('wire',['38','38.00'])
def test_original_creation_hash_retains_exact_equal_decimal_wire_candidate(db,legacy,wire):
    _,row,_,_,_,body,original=legacy
    original=original.model_copy(update={'freight_amount':Decimal(wire)})
    row.request_hash=shipments.digest(original.model_dump(mode='json',exclude={'is_final'}))
    db.commit()
    frozen=row.request_hash
    run_upgrade(db,row,body); db.commit()
    assert row.request_hash==frozen and row.quote['new_payment_due']=='0.00'


def test_original_creation_hash_uses_frozen_quote_item_order_not_primary_key_order(db,legacy):
    invoice,row,_,_,_,body,original=legacy
    first=db.query(SettlementItem).one()
    first.quantity=2; first.line_amount=418; first.snapshot={**first.snapshot,'outbound_count':2}
    current=InvoiceItem(invoice_id=invoice.id,product_id=1,sku_id=3,product_name='Other',product_display='Other',
        color='Black',quantity=1,price_per_piece=209,total_price=209,xiaoman_unique_id='12')
    db.add(current); db.flush()
    db.add(SettlementItem(settlement_id=row.id,invoice_item_id=current.id,quantity=1,line_amount=209,
        snapshot={**first.snapshot,'order_record_id':'12','sku_id':3,'outbound_count':1}))
    ordered=[{'invoice_item_id':current.id,'quantity':1,'line_amount':'209.00'},
        {'invoice_item_id':first.invoice_item_id,'quantity':2,'line_amount':'418.00'}]
    row.quote={**row.quote,'items':ordered}
    original=ShipmentCreate(items=[{'invoice_item_id':part['invoice_item_id'],'quantity':part['quantity']} for part in ordered],
        freight_amount='38',quote_hash=row.quote_hash,request_key=row.request_key)
    row.request_hash=shipments.digest(original.model_dump(mode='json',exclude={'is_final'}))
    db.commit()
    frozen=row.request_hash
    run_upgrade(db,row,body); db.commit()
    assert row.request_hash==frozen and row.quote['items']==ordered
    assert row.quote['goods_amount']=='627.00' and row.quote['new_payment_due']=='0.00'


def test_remote_audit_projects_financial_facts_and_omits_private_urls_and_extensions(db,legacy,monkeypatch):
    import json
    _,row,receipt,_,_,body,_=legacy
    secret_url='https://private.example.test/proof.png?signature=FAKE_PRIVATE_VALUE'
    calls=[]
    def contaminate(fn):
        def call(*args):
            data=fn(*args)
            data.update(file_list=[{'url':secret_url}],pictures=[secret_url],provider_custom={'secret':secret_url})
            for part in data.get('rows',[]):part['custom_url']=secret_url
            calls.append(deepcopy(data))
            return data
        return call
    for name in ('read','receipt_info','order_snapshot','target_snapshot'):
        monkeypatch.setattr(remote,name,contaminate(getattr(remote,name)))
    run_upgrade(db,row,body); db.commit()
    amendment=db.query(SettlementFundingAmendment).one()
    serialized=json.dumps(amendment.evidence)
    assert secret_url not in serialized and 'file_list' not in serialized and 'pictures' not in serialized
    assert 'provider_custom' not in serialized and 'custom_url' not in serialized
    assert amendment.evidence['receipt']['amount']=='1077' and amendment.evidence['receipt']['collect_status']==1
    assert amendment.evidence['freight']['product_total_count']==0 and amendment.evidence['freight']['product_list']==[]
    assert amendment.evidence['main_receipts']['count']==1 and amendment.evidence['freight_receipts']['count']==0
    assert amendment.evidence['main_outbounds']==amendment.evidence['freight_outbounds']=={'count':0}
    assert amendment.evidence['digests']['receipt']==shipments.digest(next(part for part in calls
        if 'cash_collection_id' in part))
    assert amendment.before_snapshot['receipt']['attachment_ids']==receipt.attachment_ids
    assert len(amendment.evidence['digests'])==7 and amendment.evidence['verified_at']


@pytest.mark.parametrize('field,value',[('real_amount','1076'),('bank_charge','1'),('bank_charge_rmb','1'),
    ('bank_charge_usd','1'),('real_amount',None),('bank_charge',None)])
def test_upgrade_rejects_changed_or_missing_remote_net_and_bank_fee_facts(db,legacy,monkeypatch,field,value):
    _,row,receipt,_,_,body,_=legacy
    original=remote.receipt_info
    def mismatching(*args):
        data=original(*args)
        if value is None:del data[field]
        else:data[field]=value
        return data
    monkeypatch.setattr(remote,'receipt_info',mismatching)
    with pytest.raises(HTTPException) as rejected:run_upgrade(db,row,body)
    assert rejected.value.status_code==503 and receipt.purpose=='presale_deposit'
    assert db.query(SettlementApplication).count()==db.query(SettlementFundingAmendment).count()==0
