"""SQLite-only invoice viewer regressions. All external evidence is mocked."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.invoice.settlement_models import ShipmentSettlement, Receivable
from app.invoice import detail_access, detail_receipts, detail_outbounds, detail_router, document_anomalies
from app.receipt import remote
from app.receipt.models import Receipt

ADMIN = {"sub": "1", "roles": ["super_admin"], "permissions": []}
SELF = {"sub": "1", "roles": [], "permissions": ["invoice:read", "receipt:read"]}


@pytest.fixture(autouse=True)
def no_remote(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected remote access")
    from app.invoice import okki_client
    monkeypatch.setattr(okki_client, "ensure_access_token", blocked)
    monkeypatch.setattr(detail_access, "outbound_scope", lambda *a: None)


@pytest.fixture(autouse=True)
def outbound_current_schema(db):
    from sqlalchemy import text
    from app.shipping_inspection import outbound_service
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN company_id TEXT"))
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT"))
    outbound_service._columns_cache.clear()
    yield
    outbound_service._columns_cache.clear()


def order(db, number="INV-1", owner=1, kind="stock", state="synced"):
    row = Invoice(invoice_no=number, order_type=kind, customer_id="101", customer_name="Example",
        sales_user_id=owner, created_by=owner, invoice_date=date(2026, 10, 8), currency="USD",
        product_amount=100, total_amount=100, xiaoman_order_id=str(2000+owner), sync_status=state, status=state)
    db.add(row); db.flush()
    return row


def receipt(db, invoice, number="HK-1", **values):
    fields = dict(receipt_no=number, invoice_id=invoice.id, source="manual", currency="USD", customer_id="101",
        amount=Decimal("50"), bank_charge=Decimal("2"), collection_date=date(2026, 10, 8), payment_type="T/T",
        request_key=number, request_hash=number, sync_status="synced", status="active", purpose="ordinary", attachment_ids=[], created_by=1)
    fields.update(values)
    row = Receipt(**fields); db.add(row); db.flush(); return row


def snapshot(invoice, rows):
    return {"rows": rows, "invoice_binding": remote.invoice_binding(invoice)}


def rr(identity="701", amount="48", status=1):
    return dict(cash_collection_id=identity, cash_collection_no="REMOTE-"+identity, currency="USD", amount=amount, collect_status=status)


def test_receipt_gross_dedupe_failed_reservation_and_remote_only(db, monkeypatch):
    invoice = order(db)
    receipt(db, invoice, xiaoman_receipt_id="701")
    receipt(db, invoice, "HK-2", amount=10, bank_charge=0, sync_status="failed")
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: snapshot(invoice, [rr(), rr("702", "5", 0)]))
    data = detail_receipts.read(db, invoice, ADMIN)
    assert data["state"] == "ready"
    assert Decimal(data["summary"]["effective_amount"]) == 50
    assert Decimal(data["summary"]["registered_amount"]) == 65
    assert Decimal(data["summary"]["pending_amount"]) == 15
    assert len(data["items"]) == 3
    assert sum(r.get("xiaoman_receipt_id") == "701" for r in data["items"]) == 1


@pytest.mark.parametrize("rows", [[], [rr(amount="47")], [rr(amount="48", status=0), rr("701")]])
def test_changed_deleted_duplicate_receipts_keep_local_but_hide_totals(db, monkeypatch, rows):
    invoice = order(db); receipt(db, invoice, xiaoman_receipt_id="701")
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: snapshot(invoice, rows))
    data = detail_receipts.read(db, invoice, ADMIN)
    assert data["state"] == "unverified" and data["summary"] is None
    assert len(data["items"]) == 1 and data["items"][0]["collect_status"] is None


def test_historical_remote_id_reappears_is_unverified_not_duplicate(db, monkeypatch):
    invoice = order(db); receipt(db, invoice, xiaoman_receipt_id="701", status="remote_deleted")
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: snapshot(invoice, [rr()]))
    data = detail_receipts.read(db, invoice, ADMIN)
    assert data["summary"] is None and len(data["items"]) == 1
    assert "历史" in data["message"]


def test_permissions_are_domain_specific_and_checked_before_remote(db):
    invoice = order(db, owner=2)
    broad_order_only = {"sub":"1", "permissions":["invoice:read", "invoice:read_all"], "roles":[]}
    assert detail_access.get_order(db, invoice.id, broad_order_only).id == invoice.id
    with pytest.raises(HTTPException): detail_receipts.read(db, invoice, broad_order_only)
    with pytest.raises(HTTPException): detail_receipts.read(db, invoice, SELF)
    assert document_anomalies.summary(db, broad_order_only)["domains"]["receipt"]["state"] == "restricted"


def test_header_excludes_editor_fund_snapshots(db):
    invoice = order(db)
    invoice.internal_received = 10; invoice.internal_balance = 90
    data = detail_router.header(invoice.id, db, ADMIN)["data"]["order"]
    assert not {"receipt_draft", "internal_received", "internal_balance"} & data.keys()


def test_global_scope_not_paginated_and_voided_excluded(db):
    first, second = order(db), order(db,"INV-2",owner=2,state="sync_failed")
    receipt(db,first,sync_status="failed",status="voided")
    receipt(db,second,"HK-2",sync_status="uncertain")
    assert document_anomalies.summary(db,SELF)["domains"]["receipt"]["count"] == 0
    overview = document_anomalies.summary(db,ADMIN)
    assert overview["domains"]["order"]["has_anomaly"] and overview["domains"]["receipt"]["has_anomaly"]
    rows = [{"id":first.id}]; document_anomalies.annotate(db,ADMIN,rows)
    assert rows[0]["anomalies"] == []


def test_worker_proven_retry_is_normal_but_uncertain_is_anomaly(db):
    invoice = order(db)
    task = OkkiOutboundTask(invoice_id=invoice.id,order_id=invoice.xiaoman_order_id,status="failed",attempts=1,
        last_error=json.dumps({"outcome":"pre_submit_failed","attempts":1,"max_attempts":3,"retry_delay_minutes":10}))
    db.add(task); db.flush()
    assert not document_anomalies.summary(db,ADMIN)["domains"]["outbound"]["has_anomaly"]
    task.status = "uncertain"; db.flush()
    assert document_anomalies.summary(db,ADMIN)["domains"]["outbound"]["has_anomaly"]


def outbound_event(db, identity, action="sync_failed"):
    from app.shipping_inspection.models import ShippingOperationEvent
    row = ShippingOperationEvent(scope="outbound-invoice-sync", request_id=identity,
        outbound_record_id=identity, source="pc", action=action, login_user_id=1,
        operator_user_id=1, operator_name="Test", login_name="Test", payload={"outbound_no": "OLD-"+identity})
    db.add(row); db.flush(); return row


def test_outbound_problem_list_pages_current_failures_without_logs(db):
    for n in range(3):
        invoice = order(db, f"I-{n}", owner=n+1)
        db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id,
            status="failed" if n == 0 else "uncertain", last_error="secret executor text"))
    db.flush()
    full = document_anomalies.outbound_problems(db, ADMIN)
    assert full["total"] == document_anomalies.summary(db, ADMIN)["domains"]["outbound"]["count"] == 3
    assert "secret executor text" not in json.dumps(full, default=str)
    assert {r["problem"] for r in full["items"]} == {"生成失败", "待核对"}
    pages = [document_anomalies.outbound_problems(db, ADMIN, page=p, page_size=2) for p in (1, 2)]
    assert [r["key"] for page in pages for r in page["items"]] == [r["key"] for r in full["items"]]


@pytest.mark.parametrize("renamed", [False, True])
def test_normal_current_document_hides_old_task_and_operation_history(db, renamed):
    from sqlalchemy import text, event
    from app.shipping_inspection import outbound_queue_service
    invoice = order(db)
    db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id, status="uncertain"))
    db.execute(text("INSERT INTO lsordertest.okki_outbound_records (id,outbound_no,company_id) VALUES ('CURRENT',:number,'101')"),
               {"number": "Renamed" if renamed else invoice.invoice_no})
    if renamed:
        db.execute(text("INSERT INTO lsordertest.okki_outbound_record_items (id,outbound_record_id,order_id) VALUES ('LINK','CURRENT',:order_id)"),
                   {"order_id": invoice.xiaoman_order_id})
    for identity, action in [("old-fail","sync_failed"),("old-uncertain","sync_uncertain"),("old-recheck","recheck_required")]:
        outbound_event(db, identity, action)
    shipment(db, invoice, state="review_required")
    db.flush()
    rows, _ = outbound_queue_service.list_outbound_records(db)
    assert all(row["outbound_state"] == "ready" for row in rows)
    statements = []
    def capture(_conn, _cursor, sql, *_args): statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert document_anomalies.outbound_problems(db, ADMIN)["total"] == 0
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert not any("ark_shipping_operation_events" in sql or "ark_shipment_settlements" in sql for sql in statements)
    assert document_anomalies.summary(db, ADMIN)["domains"]["outbound"] == {"state":"ready", "has_anomaly":False, "count":0}
    projected = [{"id":invoice.id}]
    document_anomalies.annotate(db, ADMIN, projected)
    assert "outbound" not in projected[0]["anomalies"]


def test_outbound_problem_list_excludes_normal_stock_wait_and_automatic_retry(db):
    for n, status in enumerate(["pending", "waiting_stock", "failed", "uncertain"]):
        invoice = order(db, f"I-{n}", owner=n+1)
        db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id, status=status, attempts=1,
            last_error=json.dumps({"outcome":"pre_submit_failed", "attempts":1,"max_attempts":3,"retry_delay_minutes":10})))
    db.flush()
    data = document_anomalies.outbound_problems(db, ADMIN)
    assert data["total"] == 1 and data["items"][0]["number"] == "I-3"
    assert data["items"][0]["target"] == {"order_id":"2004"}


def test_visible_current_outbound_replaces_old_task_for_scoped_user(db, monkeypatch):
    from sqlalchemy import text
    from app.auth.models import ArkUserExternalBinding
    from app.invoice.models import InvoiceSyncLog
    invoice = order(db)
    db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id, status="uncertain"))
    db.add(ArkUserExternalBinding(ark_user_id=1, provider="okki", external_account_id="901", binding_status="active"))
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="create", success=1))
    db.execute(text("INSERT INTO lsordertest.okki_outbound_records (id,outbound_no,company_id) VALUES ('OWN-CURRENT','RENAMED','101')"))
    db.execute(text("INSERT INTO lsordertest.okki_outbound_record_items (id,outbound_record_id,order_id) VALUES ('OWN-LINK','OWN-CURRENT',:order_id)"),
               {"order_id":invoice.xiaoman_order_id})
    db.flush()
    monkeypatch.setattr(detail_access, "outbound_scope", lambda *a: "901")
    user = {"sub":"1", "roles":[], "permissions":["shipping_inspection:read"]}
    assert document_anomalies.outbound_problems(db, user)["total"] == 0
    assert document_anomalies.summary(db, user)["domains"]["outbound"]["count"] == 0


def test_outbound_problem_list_scopes_current_tasks_without_order_permission(db, monkeypatch):
    from app.auth.models import ArkUserExternalBinding
    from app.shipping_inspection import outbound_service as records
    own, other = order(db, "OWN"), order(db, "PRIVATE", owner=2)
    for invoice in (own, other):
        db.add(OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id, status="uncertain"))
    db.add(ArkUserExternalBinding(ark_user_id=1, provider="okki", external_account_id="901", binding_status="active"))
    monkeypatch.setattr(detail_access, "outbound_scope", lambda *a: "901")
    reader = {"sub":"1", "roles":[], "permissions":["shipping_inspection:read"]}
    db.flush()
    data = document_anomalies.outbound_problems(db, reader)
    assert data["total"] == 1
    assert {r["number"] for r in data["items"]} == {"OWN"}
    assert "PRIVATE" not in json.dumps(data, default=str)
    with pytest.raises(HTTPException) as error:
        document_anomalies.outbound_problems(db, SELF)
    assert error.value.status_code == 403


def test_outbound_problem_read_failure_is_not_reported_as_empty(db, monkeypatch):
    def fail(*a, **kw): raise RuntimeError("backend unavailable")
    monkeypatch.setattr(document_anomalies, "_outbound_sources", fail)
    with pytest.raises(HTTPException) as error:
        detail_router.outbound_problems(1, 20, db, ADMIN)
    assert error.value.status_code == 503 and "不能据此判断问题已解决" in error.value.detail


def shipment(db, invoice, state="awaiting_payment", number="S1"):
    row = ShipmentSettlement(invoice_id=invoice.id,sequence=1,settlement_no=number,state=state,is_final=0,
        quote={},quote_hash=number,request_key=number,request_hash=number,created_by=1)
    db.add(row); db.flush(); return row


def test_freight_target_failure_does_not_override_current_receipt_status(db, monkeypatch):
    invoice = order(db,kind="presale")
    batch = shipment(db,invoice,state="cancelled")
    target = Receivable(invoice_id=invoice.id,settlement_id=batch.id,business_key="F1",kind="freight",amount=40,currency="USD",customer_id="101",remote_status="failed")
    db.add(target); db.flush()
    monkeypatch.setattr(remote,"order_snapshot",lambda *a:snapshot(invoice,[]))
    data = detail_receipts.read(db,invoice,ADMIN)
    assert Decimal(data["freight"]["total_amount"]) == 0
    assert not document_anomalies.summary(db,ADMIN)["domains"]["receipt"]["has_anomaly"]
    batch.state="paused"; db.flush()
    assert not document_anomalies.summary(db,ADMIN)["domains"]["receipt"]["has_anomaly"]
    data = detail_receipts.read(db,invoice,ADMIN)
    assert data["freight"]["state"] == "unverified" and data["freight"]["total_amount"] is None


def test_order_badge_only_uses_current_document_status(db):
    invoice = order(db)
    invoice.sync_status = "sync_failed"
    invoice.sync_error = "previous failure"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["order"]["count"] == 0
    invoice.status = "sync_uncertain"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["order"]["count"] == 1
    invoice.status = "synced"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["order"]["count"] == 0


def test_receipt_recovery_clears_badge_even_when_error_evidence_remains(db):
    invoice = order(db)
    row = receipt(db, invoice, sync_status="uncertain", last_error="old failure")
    assert document_anomalies.summary(db, ADMIN)["domains"]["receipt"]["count"] == 1
    row.sync_status = "synced"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["receipt"]["count"] == 0
    row.sync_status = "failed"
    row.status = "voided"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["receipt"]["count"] == 0
    row.status = "remote_deleted"
    db.flush()
    assert document_anomalies.summary(db, ADMIN)["domains"]["receipt"]["count"] == 0


def projection_order():
    return SimpleNamespace(order_type="stock",xiaoman_order_id="2001",items=[SimpleNamespace(id=i,quantity=10,product_name=f"Line {i}",
        xiaoman_unique_id=str(i),product_id=100,sku_id=101) for i in (1,2)])


def doc(identity="D1", status=2, first=6, second=2):
    return {"outbound_invoice_id":identity,"status":status,"inspection":{"state":"ready","status":"submitted" if status==2 else "draft"},"record_list":[
        {"order_id":"2001","order_record_id":str(i),"product_id":100,"sku_id":101,"outbound_count":n} for i,n in ((1,first),(2,second))]}


def test_inspection_outbound_uses_exact_lines_not_sku_totals():
    shipped=doc(); shipped["record_list"].append({"order_id":"9999","outbound_count":100})
    data, quantities=detail_outbounds.project(projection_order(),[shipped,doc("D2",1,4,8)])
    assert quantities == {"1":"6","2":"2"} and len(data[0]["items"]) == 2
    assert data[1]["state"] == "generated"


def test_presale_progress_uses_archived_actual_quantity_without_rewriting_original():
    invoice = projection_order()
    invoice.order_type = "presale"
    original = invoice.items[0]
    original.presale_archived = 1
    original.presale_shipped_quantity = 6
    invoice.items[1].quantity = 3
    data, quantities = detail_outbounds.project(invoice, [doc(first=6, second=2)])
    assert original.quantity == 10
    assert data[0]["items"][0]["ordered_quantity"] == 6
    assert quantities == {"1": "6", "2": "2"}


@pytest.mark.parametrize("mutate", [lambda d:d["inspection"].update(status="unknown"),lambda d:d["record_list"][0].update(outbound_count=11),lambda d:d["record_list"][0].update(order_record_id="unknown"),lambda d:d["record_list"].append(d["record_list"][0])])
def test_invalid_or_overfull_outbound_is_not_zero_progress(mutate):
    document=doc(); mutate(document)
    with pytest.raises(ValueError): detail_outbounds.project(projection_order(),[document])


def test_presale_remote_moved_line_rejected():
    document=doc(); frozen=SimpleNamespace(status="shipped",payload={"record_list":[dict(r) for r in document["record_list"]]})
    document["record_list"][1]["order_id"]="9999"
    with pytest.raises(ValueError): detail_outbounds.project(projection_order(),[document],presale_outbounds={"D1":frozen})


def test_presale_local_shipped_without_inspection_submission_is_not_complete():
    document=doc(status=1); frozen=SimpleNamespace(status="shipped",payload={"record_list":document["record_list"]})
    _, quantities = detail_outbounds.project(projection_order(),[document],presale_outbounds={"D1":frozen})
    assert quantities == {"1":"0","2":"0"}


def test_missing_and_duplicate_order_line_mapping_rejected():
    invoice=projection_order(); invoice.items[1].xiaoman_unique_id="1"
    with pytest.raises(ValueError): detail_outbounds.project(invoice,[])


@pytest.mark.parametrize("status", [None, 2, "unknown"])
def test_unknown_financial_state_hides_progress(db, monkeypatch, status):
    invoice = order(db)
    receipt(db, invoice, xiaoman_receipt_id="701")
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: snapshot(invoice, [rr(status=status)]))
    data = detail_receipts.read(db, invoice, ADMIN)
    assert data["state"] == "unverified" and data["summary"] is None
    assert len(data["items"]) == 1 and data["items"][0]["collect_status"] is None


def test_batch_review_does_not_override_outbound_document_state(db):
    invoice = order(db, kind="presale")
    shipment(db, invoice, state="review_required")
    assert not document_anomalies.summary(db, ADMIN)["domains"]["outbound"]["has_anomaly"]
    rows = [{"id": invoice.id}]
    document_anomalies.annotate(db, ADMIN, rows)
    assert "outbound" not in rows[0]["anomalies"]


def test_mixed_owner_receipt_batch_is_private_before_external_read(db):
    from app.invoice.settlement_models import ReceiptBatch
    first, second = order(db), order(db, "INV-2", owner=2)
    batch = ReceiptBatch(batch_no="B1", customer_id="101", currency="USD", gross_amount=100, bank_charge_total=0,
        collection_date=date(2026,10,8), payment_type="T/T", request_key="B1", request_hash="B1", created_by=1)
    db.add(batch); db.flush()
    receipt(db, first, batch_id=batch.id, sync_status="failed")
    receipt(db, second, "HK-2", batch_id=batch.id)
    with pytest.raises(HTTPException): detail_receipts.read(db, first, SELF)
    assert not document_anomalies.summary(db, SELF)["domains"]["receipt"]["has_anomaly"]
    assert document_anomalies.summary(db, ADMIN)["domains"]["receipt"]["has_anomaly"]


def test_presale_deposit_and_independent_freight_are_not_added_twice(db, monkeypatch):
    invoice = order(db, kind="presale")
    receipt(db, invoice, purpose="presale_deposit", amount=20, bank_charge=0, xiaoman_receipt_id="701", xiaoman_order_id=invoice.xiaoman_order_id)
    batch = shipment(db, invoice, state="shipped")
    target = Receivable(invoice_id=invoice.id, settlement_id=batch.id, business_key="F1", kind="freight",
        amount=40, currency="USD", customer_id="101", remote_order_id="F1", remote_status="synced")
    db.add(target); db.flush()
    receipt(db, invoice, "HK-F1", purpose="freight", receivable_id=target.id, amount=40,
        bank_charge=0, xiaoman_order_id="F1", xiaoman_receipt_id="702")
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: snapshot(invoice, [rr(amount="20")]))
    monkeypatch.setattr(remote, "target_snapshot", lambda *a: {"rows":[rr("702","40")],
        "target_binding":[target.id,target.remote_order_id,str(target.amount),target.currency,target.customer_id,target.version]})
    data = detail_receipts.read(db, invoice, ADMIN)
    assert data["state"] == "ready" and data["freight"]["state"] == "ready"
    assert Decimal(data["summary"]["effective_amount"]) == 20
    assert Decimal(data["freight"]["effective_amount"]) == 40
    assert len(data["items"]) == 2


def test_inspection_metadata_obeys_its_own_scope(db, monkeypatch):
    from app.shipping_inspection import router
    from app.shipping_inspection.models import ShippingInspection
    documents = [{"record_id":"R1"}]
    db.add(ShippingInspection(outbound_record_id="R1", status="submitted")); db.flush()
    monkeypatch.setattr(router, "_inspection_scope", lambda *a: "owner")
    monkeypatch.setattr(detail_outbounds.detail_outbound_mirror, "read", lambda *a: [])
    detail_outbounds.annotate_inspections(db, order(db), documents, ADMIN, None)
    assert documents[0]["inspection"] == {"state":"restricted", "status":None}
    monkeypatch.setattr(detail_outbounds.detail_outbound_mirror, "read", lambda *a: documents)
    detail_outbounds.annotate_inspections(db, db.query(Invoice).first(), documents, ADMIN, None)
    assert documents[0]["inspection"]["status"] == "submitted"


def test_batch_frozen_amounts_require_receipt_permission(db, monkeypatch):
    from app.invoice.settlement_models import SettlementItem
    invoice = order(db, kind="presale")
    item = InvoiceItem(invoice_id=invoice.id,product_id=100,sku_id=101,product_name="Current name",product_display="Current name",
        color="1",length="18",quantity=10,price_per_piece=10,total_price=100,xiaoman_unique_id="L1")
    db.add(item); db.flush()
    batch = shipment(db, invoice, state="review_required")
    batch.quote = {"freight_amount":"40", "goods_amount":"50"}
    db.add(SettlementItem(settlement_id=batch.id,invoice_item_id=item.id,quantity=5,line_amount=50,
        snapshot={"product_name":"Frozen name","sale_price":"10"})); db.flush()
    invoice.xiaoman_order_id = None
    user = {"sub":"1", "roles":[], "permissions":["invoice:read","shipping_inspection:read","shipment:read"]}
    data = detail_outbounds.read(db, invoice, user)
    assert data["batches"][0]["amounts"] is None
    assert data["batches"][0]["items"][0]["line_amount"] is None
    data = detail_outbounds.read(db, invoice, ADMIN)
    assert data["batches"][0]["amounts"]["freight_amount"] == "40"
    assert data["batches"][0]["items"][0]["product_name"] == "Frozen name"
