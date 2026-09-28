"""Opt-in Ark-to-OKKI presale order probe. Never runs in the ordinary test suite."""
import hashlib
import io
import json
import os
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from PIL import Image

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.config import get_settings
from app.core.time import beijing_today
from app.invoice import okki_client, product_service, service, settlement_policy, xiaoman_service
from app.invoice.models import XiaomanSettings
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload
from app.receipt import attachments
from app.receipt.models import ReceiptAttachment
from app.receipt.schemas import ReceiptDraft


pytestmark = pytest.mark.skipif(
    os.getenv("ARK_PRESALE_LIVE_PROBE") != "1", reason="explicit live OKKI probe only",
)

API_USER = 55372793
PRODUCT = 105791567930963
SKU = 105791567931559


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
        finally:
            if order_id:
                detail = order_detail or _call(client, base, headers, "GET", "/v1/invoices/order/info",
                                               params={"order_id": order_id})
                if (str(detail.get("order_id")) == order_id
                        and detail.get("name") == marker + "-MAIN"
                        and str(detail.get("company_id")) == customer_id):
                    _record(root, "cleanup-order-intent.json", {"order_id": order_id,
                                                                 "order_no": detail.get("order_no")})
                    _call(client, base, headers, "POST", "/v1/invoices/order/remove",
                          params={"order_id": order_id, "order_no": detail.get("order_no")})
                    assert not _active_order(client, base, headers, order_id, detail["create_time"])
                    _record(root, "cleanup-order-verified.json", {"order_id": order_id, "active": False})
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
