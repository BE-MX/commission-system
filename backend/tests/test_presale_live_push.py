"""Opt-in Ark-to-OKKI presale order probe. Never runs in the ordinary test suite."""
import hashlib
import io
import json
import os
from time import perf_counter
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from PIL import Image

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.config import get_settings
from app.core.time import beijing_today
from app.invoice import (freight_delivery, linked_outbound_service, okki_client, product_service, service,
                         settlement_policy, settlement_service, shipment_delivery, xiaoman_service)
from app.invoice.models import XiaomanSettings
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload
from app.invoice.settlement_models import Receivable, ShipmentOutbound
from app.invoice.settlement_schemas import ShipmentCreate, ShipmentQuote
from app.receipt import attachments, fees, invoice_link, remote, sync_service
from app.receipt.models import Receipt, ReceiptAttachment
from app.receipt.schemas import ReceiptDraft, ReceiptFields


pytestmark = pytest.mark.skipif(
    os.getenv("ARK_PRESALE_LIVE_PROBE") != "1", reason="explicit live OKKI probe only",
)

API_USER = 55372793
PRODUCT = 105791567930963
SKU = 105791567931559
WAREHOUSE = 8193514242746


@pytest.fixture
def live_settings(monkeypatch):
    for key, value in dotenv_values(os.environ["ARK_PRESALE_LIVE_ENV_FILE"]).items():
        if value is not None:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def _record(root: Path, name: str, value: dict):
    with (root / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _call(client, base, headers, method, path, **kwargs):
    response = client.request(method, base + path, headers=headers, timeout=60, **kwargs)
    body = response.json()
    if response.status_code != 200 or body.get("code") != 200:
        raise AssertionError(f"OKKI {method} {path}: HTTP {response.status_code}, code={body.get('code')}")
    return body.get("data") or {}


def _active_order(client, base, headers, order_id, create_time):
    day = create_time[:10]
    data = _call(client, base, headers, "GET", "/v1/invoices/order/list", params={
        "start_time": day + " 00:00:00", "end_time": day + " 23:59:59",
        "time_type": 2, "start_index": 1, "count": 100, "removed": 0,
    })
    rows, count = data.get("list"), data.get("count")
    if not isinstance(rows, list) or not str(count).isdigit() or int(count) > 100 or len(rows) != int(count):
        raise AssertionError("OKKI active order list is incomplete")
    return any(str(row.get("order_id")) == str(order_id) for row in rows)


def _active_outbound(client, base, headers, outbound_id, create_time):
    day = create_time[:10]
    data = _call(client, base, headers, "GET", "/v1/invoices/outbound/list", params={
        "start_time": day + " 00:00:00", "end_time": day + " 23:59:59",
        "time_type": 2, "start_index": 1, "count": 100, "removed": 0,
    })
    rows, count = data.get("list"), data.get("count")
    if not isinstance(rows, list) or not str(count).isdigit() or int(count) > 100 or len(rows) != int(count):
        raise AssertionError("OKKI active outbound list is incomplete")
    return any(str(row.get("outbound_invoice_id")) == str(outbound_id) for row in rows)


def _remove_test_order(client, base, headers, root, slug, name, order_id, customer_id):
    detail = _call(client, base, headers, "GET", "/v1/invoices/order/info",
                   params={"order_id": order_id})
    assert str(detail.get("order_id")) == str(order_id)
    assert detail.get("name") == name and str(detail.get("company_id")) == customer_id
    assert _active_order(client, base, headers, order_id, detail["create_time"])
    if str(detail.get("status")) == "13972831656":
        _record(root, f"cleanup-{slug}-draft-intent.json", {"id": order_id, "status": "13972831654"})
        _call(client, base, headers, "POST", "/v1/invoices/order/push", json={
            "order_id": int(order_id), "currency": "USD", "status": 13972831654,
        })
        detail = _call(client, base, headers, "GET", "/v1/invoices/order/info",
                       params={"order_id": order_id})
        assert str(detail.get("status")) == "13972831654"
        assert detail.get("name") == name and str(detail.get("company_id")) == customer_id
        _record(root, f"cleanup-{slug}-draft-verified.json", {"id": order_id, "status": detail["status"]})
    _record(root, f"cleanup-{slug}-intent.json", {"id": order_id, "order_no": detail.get("order_no")})
    _call(client, base, headers, "POST", "/v1/invoices/order/remove", params={
        "order_id": order_id, "order_no": detail.get("order_no"),
    })
    assert not _active_order(client, base, headers, order_id, detail["create_time"])
    _record(root, f"cleanup-{slug}-verified.json", {"id": order_id, "active": False})


def _run_dispatch_probe(db, monkeypatch, root, marker, invoice, order_detail, flow):
    """Probe Ark's freight/outbound senders, optionally with real receipts."""
    assert invoice.xiaoman_order_id and invoice.items[0].xiaoman_unique_id
    settings = get_settings()
    monkeypatch.setattr(settings, "OKKI_PRESALE_WAREHOUSE_ID", WAREHOUSE)
    monkeypatch.setattr(settlement_service, "require_enabled", lambda: None)
    monkeypatch.setattr(freight_delivery, "require_delivery", lambda: None)
    monkeypatch.setattr(shipment_delivery, "require_delivery", lambda: None)

    intent = invoice_link.get_intent(db, invoice.id)
    assert intent and intent.status == "draft"
    intent.status = "ready"  # Router success callback, omitted by the direct service call above.
    db.commit()
    monkeypatch.setattr(fees, "allocate", lambda *_args, **_kwargs: Decimal("0"))
    sync_service.generate_ready(db)
    deposit = db.query(Receipt).filter_by(invoice_id=invoice.id, purpose="presale_deposit").one()
    if flow["real_funding"]:
        _record(root, "flow-deposit-intent.json", {"receipt_id": deposit.id,
            "receipt_no": deposit.receipt_no, "order_id": invoice.xiaoman_order_id})
        sync_service.deliver(db, deposit.id)
        db.refresh(deposit)
        _record(root, "flow-deposit-result.json", {"id": deposit.xiaoman_receipt_id,
            "status": deposit.sync_status, "collect_status": deposit.collect_status,
            "error": deposit.last_error})
        if deposit.xiaoman_receipt_id:
            flow["receipt_ids"].append(deposit.xiaoman_receipt_id)
        assert deposit.sync_status == "synced" and deposit.collect_status == 1
    else:
        deposit.xiaoman_receipt_id = "999000000000001"  # Isolated SQLite fixture; never POSTed to OKKI.
        deposit.sync_status = "synced"
        deposit.collect_status = 1
        db.commit()
        evidence = {"receipt": {"rows": [{"cash_collection_id": deposit.xiaoman_receipt_id,
            "amount": "0.01", "currency": "USD", "collect_status": 1}]},
            "order": order_detail, "outbounds": [], "freight": {}}
        monkeypatch.setattr(settlement_service, "fetch_evidence", lambda *_: evidence)
    draft = ShipmentQuote(items=[{"invoice_item_id": invoice.items[0].id, "quantity": 1}],
                          freight_amount="0.01")
    quoted = settlement_service.quote(db, invoice.id, draft, {"sub": "1", "roles": ["super_admin"]})
    assert quoted["is_final"] and quoted["deposit_applied"] == "0.01"
    payment = (ReceiptFields(amount="0.01", collection_date=beijing_today(),
                            payment_type="T/T", attachment_ids=["b" * 32])
               if flow["real_funding"] else None)
    settlement = settlement_service.create(db, invoice.id, ShipmentCreate(
        **draft.model_dump(), quote_hash=quoted["quote_hash"],
        request_key=marker + "-SHIPMENT", payment=payment), {"sub": "1", "roles": ["super_admin"]})
    db.commit()
    target = db.query(Receivable).filter_by(settlement_id=settlement.id, kind="freight").one()
    flow["freight_attempted"] = True
    _record(root, "flow-freight-intent.json", {"target_id": target.id,
        "name": target.remote_order_name, "amount": str(target.amount)})
    freight_delivery.deliver(db, target.id)
    db.refresh(target)
    flow["freight_id"] = target.remote_order_id
    _record(root, "flow-freight-result.json", {"id": target.remote_order_id,
        "status": target.remote_status, "error": target.last_error})
    assert target.remote_status == "bound" and target.remote_order_id

    if flow["real_funding"]:
        sync_service.release_targets(db)
        freight_receipt = db.query(Receipt).filter_by(invoice_id=invoice.id, purpose="freight").one()
        db.refresh(freight_receipt)
        assert freight_receipt.sync_status == "pending"
        _record(root, "flow-freight-receipt-intent.json", {"receipt_id": freight_receipt.id,
            "receipt_no": freight_receipt.receipt_no, "order_id": target.remote_order_id})
        sync_service.deliver(db, freight_receipt.id)
        db.refresh(freight_receipt)
        _record(root, "flow-freight-receipt-result.json", {"id": freight_receipt.xiaoman_receipt_id,
            "status": freight_receipt.sync_status, "collect_status": freight_receipt.collect_status,
            "error": freight_receipt.last_error})
        if freight_receipt.xiaoman_receipt_id:
            flow["receipt_ids"].append(freight_receipt.xiaoman_receipt_id)
        assert freight_receipt.sync_status == "synced" and freight_receipt.collect_status == 1
    else:
        freight_receipt = Receipt(invoice_id=invoice.id, receivable_id=target.id,
            receipt_no=marker + "-FUNDING-FIXTURE", source="manual", purpose="freight",
            request_key=marker + "-FUNDING", request_hash="f" * 64,
            amount=Decimal("0.01"), bank_charge=Decimal("0"), currency="USD", collection_date=beijing_today(),
            payment_type="T/T", customer_id=invoice.customer_id,
            xiaoman_order_id=target.remote_order_id, xiaoman_receipt_id="999000000000002",
            collect_status=1, sync_status="synced", created_by=1, attachment_ids=[])
        db.add(freight_receipt)
        db.flush()
        settlement_service.application(db, settlement, freight_receipt, "freight", freight_receipt.amount, 0)
        db.commit()
        monkeypatch.setattr(shipment_delivery, "_refresh_funding", lambda *_: True)
        monkeypatch.setattr(shipment_delivery, "_live_funding", lambda session, *_:
            remote.read(session, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id}))
    outbound_id = shipment_delivery.queue_ready(db, settlement.id)
    assert outbound_id
    task = db.get(ShipmentOutbound, outbound_id)
    assert task.status == "pending" and task.payload["serial_id"] == settlement.settlement_no
    flow["outbound_attempted"] = True
    _record(root, "flow-outbound-intent.json", {"task_id": outbound_id,
        "serial": task.outbound_no, "payload_hash": task.payload_hash})
    shipment_delivery.deliver(db, outbound_id)
    db.refresh(task)
    flow["outbound_id"] = task.remote_id
    _record(root, "flow-outbound-result.json", {"id": task.remote_id,
        "status": task.status, "error": task.last_error})
    assert task.status == "pending_remote" and task.remote_id and task.remote_line_snapshot
    db.refresh(settlement)
    _record(root, "flow-confirm-intent.json", {"task_id": outbound_id,
        "remote_id": task.remote_id, "version": settlement.version})
    result = shipment_delivery.confirm(db, outbound_id, settlement.version, 1,
                                       "Dedicated API probe; no physical shipment")
    db.refresh(task)
    _record(root, "flow-confirm-result.json", {"id": task.remote_id,
        "status": result, "error": task.last_error})
    assert result == "shipped" and task.status == "shipped"


def test_ark_created_presale_is_accepted_and_read_back_by_okki(db, monkeypatch, tmp_path, live_settings):
    root = Path(os.environ["ARK_PRESALE_LIVE_RECORD_DIR"])
    marker = os.environ["ARK_PRESALE_LIVE_MARKER"]
    assert marker.startswith("ARK-PRESALE-ARKPUSH-") and len(marker) <= 45
    root.mkdir(parents=True, exist_ok=False)
    base = live_settings.OKKI_API_BASE.rstrip("/")
    assert base == "https://api-sandbox.xiaoman.cn"
    token, _ = okki_client.fetch_token()
    headers = {"Authorization": f"Bearer {token}"}
    today = beijing_today().isoformat()
    customer_id = order_id = None
    order_attempted = False
    order_detail = None
    flow = {"enabled": os.getenv("ARK_PRESALE_LIVE_DISPATCH") == "1",
            "real_funding": os.getenv("ARK_PRESALE_LIVE_FUNDING") == "1",
            "freight_attempted": False, "outbound_attempted": False, "receipt_ids": []}
    assert not flow["real_funding"] or flow["enabled"]

    with httpx.Client() as client:
        listing = _call(client, base, headers, "GET", "/v1/company/list", params={
            "count": 100, "start_index": 1, "removed": 0, "all": 1,
            "start_time": today + " 00:00:00", "end_time": today + " 23:59:59",
            "time_type": 2,
        })
        rows, total = listing.get("list"), listing.get("totalItem")
        assert isinstance(rows, list) and str(total).isdigit() and int(total) <= 100
        assert len(rows) == int(total) and all(row.get("name") != marker for row in rows)
        customer_payload = {
            "name": marker, "short_name": "Ark Presale Test", "is_public": 1,
            "country": "CN", "origin_list": ["20527643031709"],
            "trail_status": 14364928550, "pool_id": 0, "group_id": 22118077307645,
            "remark": "Dedicated Ark order-push TEST; no real customer or payment.",
            "customers": [{"name": "Ark Presale Test Contact",
                           "email": "ark-presale-test@example.invalid", "main_customer_flag": 1}],
            "4432264586798": ["A1"], "1937147522317": "Genius Weft",
        }
        _record(root, "customer-intent.json", {"marker": marker, "payload": customer_payload})
        try:
            created = _call(client, base, headers, "POST", "/v1/company/pushCompanyAndCustomers",
                            json=customer_payload)
            customer_id = str(created["company_id"])
            _record(root, "customer-result.json", {"id": customer_id})
            customer = _call(client, base, headers, "GET", "/v1/company/info",
                             params={"company_id": customer_id})
            assert str(customer.get("company_id")) == customer_id and customer.get("name") == marker
            _record(root, "customer-verified.json", {"id": customer_id, "name": marker})

            db.add(XiaomanSettings(id=1, generic_product_no="TEST", generic_product_id=PRODUCT,
                                   generic_sku_id=SKU, default_order_status="13972831654",
                                   default_currency="USD"))
            db.add(ArkUser(id=1, username="ark-test", password_hash="x", real_name="Ark Test",
                           okki_department_id=0, okki_department_name="我的企业"))
            db.add(ArkUserExternalBinding(ark_user_id=1, provider="okki",
                                          external_account_id=str(API_USER), binding_status="active"))
            db.flush()
            monkeypatch.setattr(settlement_policy, "require_enabled", lambda: None)
            monkeypatch.setattr(product_service, "valid_okki_product_skus", lambda _db, pairs: pairs)
            monkeypatch.setattr(product_service, "reconcile_custom_products", lambda _db: {})
            monkeypatch.setattr(attachments, "path_for", lambda row: tmp_path / row.storage_key)
            image = io.BytesIO()
            Image.new("RGB", (8, 8), "white").save(image, format="PNG")
            proof = image.getvalue()
            (tmp_path / "proof.png").write_bytes(proof)
            db.add(ReceiptAttachment(id="a" * 32, filename="proof.png", storage_key="proof.png",
                                     content_type="image/png", size=len(proof),
                                     sha256=hashlib.sha256(proof).hexdigest(), created_by=1))
            if flow["real_funding"]:
                (tmp_path / "freight-proof.png").write_bytes(proof)
                db.add(ReceiptAttachment(id="b" * 32, filename="freight-proof.png",
                                         storage_key="freight-proof.png", content_type="image/png",
                                         size=len(proof), sha256=hashlib.sha256(proof).hexdigest(), created_by=1))
            db.flush()
            invoice = service.create_invoice(db, InvoiceCreate(
                invoice_no=marker + "-MAIN", order_type="presale", customer_id=customer_id,
                customer_name=marker, invoice_date=beijing_today(), currency="USD",
                shipping_fee="0", okki_new_deal=0, okki_free_shipping=1, okki_first_return=0,
                receipt_draft=ReceiptDraft(amount="0.01", collection_date=beijing_today(),
                                           payment_type="T/T", attachment_ids=["a" * 32]),
                items=[InvoiceItemPayload(product_id=PRODUCT, sku_id=SKU,
                                          product_name="Other Items", product_display="Other Items",
                                          net_weight_grams="100g", color="Black", length="18",
                                          quantity=1, price_per_piece="0.01")],
            ), user_id=1)
            db.flush()
            _record(root, "order-intent.json", {"invoice_id": invoice.id,
                                                 "invoice_no": invoice.invoice_no,
                                                 "customer_id": customer_id,
                                                 "amount": "0.01", "product_id": PRODUCT, "sku_id": SKU})
            order_attempted = True
            result = xiaoman_service.sync_invoice(db, invoice, operator_id=1)
            order_id = str(invoice.xiaoman_order_id or "") or None
            _record(root, "order-result.json", {"ok": result["ok"], "order_id": order_id,
                                                 "sync_status": invoice.sync_status,
                                                 "message": result["message"]})
            assert result["ok"] is True and order_id
            assert invoice.items[0].xiaoman_unique_id and not invoice.outbound_auto_requested
            order_detail = _call(client, base, headers, "GET", "/v1/invoices/order/info",
                                 params={"order_id": order_id})
            products = order_detail.get("product_list") or []
            assert str(order_detail.get("order_id")) == order_id
            assert order_detail.get("name") == invoice.invoice_no
            assert str(order_detail.get("company_id")) == customer_id
            assert order_detail.get("currency") == "USD" and str(order_detail.get("amount")) in {"0.01", "0.0100"}
            assert len(products) == 1 and str(products[0].get("product_id")) == str(PRODUCT)
            assert str(products[0].get("sku_id")) == str(SKU)
            assert int(products[0].get("count")) == 1
            assert str(products[0].get("unique_id")) == invoice.items[0].xiaoman_unique_id
            _record(root, "order-verified.json", {"order_id": order_id, "customer_id": customer_id,
                                                   "amount": str(order_detail["amount"]),
                                                   "line_id": invoice.items[0].xiaoman_unique_id})
            if flow["enabled"]:
                _run_dispatch_probe(db, monkeypatch, root, marker, invoice, order_detail, flow)
        finally:
            if flow["real_funding"]:
                _record(root, "manual-receipt-cleanup-required.json", {
                    "marker": marker, "customer_id": customer_id, "order_id": order_id,
                    "freight_order_id": flow.get("freight_id"),
                    "outbound_id": flow.get("outbound_id"), "receipt_ids": flow["receipt_ids"],
                    "reason": "Delete real test receipts in OKKI before removing their target orders"})
            else:
                flow_cleared = True
                if flow["outbound_attempted"]:
                    outbound_id = flow.get("outbound_id")
                    flow_cleared = bool(outbound_id)
                    if outbound_id:
                        detail = _call(client, base, headers, "GET", "/v1/invoices/outbound/info",
                                       params={"outbound_invoice_id": outbound_id})
                        assert str(detail.get("outbound_invoice_id")) == outbound_id
                        assert detail.get("serial_id") == marker + "-MAIN-01"
                        assert all(str(row.get("order_id")) == order_id
                                   for row in detail.get("record_list") or [])
                        _record(root, "cleanup-outbound-intent.json", {"id": outbound_id,
                            "serial": detail["serial_id"], "status": detail.get("status")})
                        _call(client, base, headers, "POST", "/v1/invoices/outbound/remove", params={
                            "outbound_invoice_id": outbound_id, "serial_id": detail["serial_id"],
                        })
                        assert not _active_outbound(client, base, headers, outbound_id, detail["create_time"])
                        _record(root, "cleanup-outbound-verified.json", {"id": outbound_id, "active": False})
                if flow["freight_attempted"]:
                    freight_id = flow.get("freight_id")
                    flow_cleared = flow_cleared and bool(freight_id)
                    if flow_cleared:
                        _remove_test_order(client, base, headers, root, "freight-order",
                                           marker + "-MAIN-01-F", freight_id, customer_id)
                if order_id and flow_cleared:
                    _remove_test_order(client, base, headers, root, "order",
                                       marker + "-MAIN", order_id, customer_id)
                if customer_id and (not order_attempted or (root / "cleanup-order-verified.json").exists()):
                    customer = _call(client, base, headers, "GET", "/v1/company/info",
                                     params={"company_id": customer_id})
                    if customer.get("name") == marker:
                        phones = customer.get("tel") or ["", ""]
                        body = {"company_id": int(customer_id), "serial_id": customer.get("serial_id"),
                                "name": marker, "tel_area_code": customer.get("tel_area_code") or "",
                                "tel": phones[1] if isinstance(phones, list) and len(phones) > 1 else phones}
                        _record(root, "cleanup-customer-intent.json", {"id": customer_id, "name": marker})
                        _call(client, base, headers, "POST", "/v1/company/moveToPublic", json=body)
                        _call(client, base, headers, "POST", "/v1/company/removeCompanyAndCustomers",
                              data={"company_id": customer_id})
                        response = client.get(base + "/v1/company/info", headers=headers,
                                              params={"company_id": customer_id}, timeout=60)
                        assert response.status_code == 200 and response.json().get("code") == 404
                        _record(root, "cleanup-customer-verified.json", {"id": customer_id, "detail_code": 404})


@pytest.mark.skipif(os.getenv("ARK_PRESALE_LIVE_SCAN") != "1", reason="explicit read-only scan only")
def test_live_related_outbound_scan_reads_all_details(db, live_settings):
    order_id = os.environ["ARK_PRESALE_LIVE_ORDER_ID"]
    outbound_id = os.getenv("ARK_PRESALE_LIVE_OUTBOUND_ID")
    order = remote.read(db, "/v1/invoices/order/info", {"order_id": order_id})
    assert str(order.get("order_id")) == order_id
    started = perf_counter()
    related = linked_outbound_service.find_related(db, order)
    if outbound_id:
        assert outbound_id in {str(row["outbound_invoice_id"]) for row in related}
    else:
        assert related == []
    print(f"presale outbound complete scan seconds={perf_counter() - started:.2f}", flush=True)


@pytest.mark.skipif(os.getenv("ARK_PRESALE_LIVE_CLEANUP") != "1", reason="explicit test-document cleanup only")
def test_cleanup_real_funding_probe_after_receipts_deleted(live_settings):
    root = Path(os.environ["ARK_PRESALE_LIVE_RECORD_DIR"])
    plan = json.loads((root / "manual-receipt-cleanup-required.json").read_text(encoding="utf-8"))
    marker = plan["marker"]
    assert marker == os.environ["ARK_PRESALE_LIVE_MARKER"]
    assert marker.startswith("ARK-PRESALE-ARKPUSH-")
    assert len(plan["receipt_ids"]) == 2
    assert all(str(value).isdigit() for value in [plan["customer_id"], plan["order_id"],
        plan["freight_order_id"], plan["outbound_id"], *plan["receipt_ids"]])
    base = live_settings.OKKI_API_BASE.rstrip("/")
    token, _ = okki_client.fetch_token()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client() as client:
        today = beijing_today().isoformat()
        active = _call(client, base, headers, "GET", "/v1/invoices/receipt/list", params={
            "start_time": today + " 00:00:00", "end_time": today + " 23:59:59",
            "start_index": 1, "count": 100, "removed": 0})
        rows, total = active.get("list"), active.get("totalItem")
        assert isinstance(rows, list) and str(total).isdigit() and int(total) <= 100
        assert len(rows) == int(total)
        active_ids = {str(row.get("cash_collection_id")) for row in rows}
        assert not active_ids.intersection(plan["receipt_ids"]), "测试回款仍在小满有效列表，停止清理"
        _record(root, "cleanup-receipts-verified.json", {
            "ids": plan["receipt_ids"], "active": False, "window": today})

        outbound_id = plan["outbound_id"]
        detail = _call(client, base, headers, "GET", "/v1/invoices/outbound/info",
                       params={"outbound_invoice_id": outbound_id})
        assert str(detail.get("outbound_invoice_id")) == outbound_id
        assert detail.get("serial_id") == marker + "-MAIN-01"
        assert all(str(row.get("order_id")) == plan["order_id"] for row in detail.get("record_list") or [])
        if _active_outbound(client, base, headers, outbound_id, detail["create_time"]):
            _record(root, "cleanup-outbound-intent.json", {"id": outbound_id, "serial": detail["serial_id"]})
            _call(client, base, headers, "POST", "/v1/invoices/outbound/remove", params={
                "outbound_invoice_id": outbound_id, "serial_id": detail["serial_id"]})
        assert not _active_outbound(client, base, headers, outbound_id, detail["create_time"])
        _record(root, "cleanup-outbound-verified.json", {"id": outbound_id, "active": False})

        _remove_test_order(client, base, headers, root, "freight-order",
                           marker + "-MAIN-01-F", plan["freight_order_id"], plan["customer_id"])
        _remove_test_order(client, base, headers, root, "order",
                           marker + "-MAIN", plan["order_id"], plan["customer_id"])
        customer = _call(client, base, headers, "GET", "/v1/company/info",
                         params={"company_id": plan["customer_id"]})
        assert customer.get("name") == marker
        phones = customer.get("tel") or ["", ""]
        body = {"company_id": int(plan["customer_id"]), "serial_id": customer.get("serial_id"),
                "name": marker, "tel_area_code": customer.get("tel_area_code") or "",
                "tel": phones[1] if isinstance(phones, list) and len(phones) > 1 else phones}
        _record(root, "cleanup-customer-intent.json", {"id": plan["customer_id"], "name": marker})
        _call(client, base, headers, "POST", "/v1/company/moveToPublic", json=body)
        _call(client, base, headers, "POST", "/v1/company/removeCompanyAndCustomers",
              data={"company_id": plan["customer_id"]})
        response = client.get(base + "/v1/company/info", headers=headers,
                              params={"company_id": plan["customer_id"]}, timeout=60)
        assert response.status_code == 200 and response.json().get("code") == 404
        _record(root, "cleanup-customer-verified.json", {"id": plan["customer_id"], "detail_code": 404})
