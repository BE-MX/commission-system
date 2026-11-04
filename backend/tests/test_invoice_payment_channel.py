"""Payment/channel save contract; all persistence uses isolated SQLite."""
from unittest.mock import Mock

import pytest

from app.invoice import product_service, service
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate


def payload(method=None, channel=None):
    return InvoiceCreate(invoice_no="CHANNEL-TEST", order_type="stock", customer_id="101",
        customer_name="Test", invoice_date="2026-11-04", internal_payment_method=method,
        express_channel=channel, inspection_requirement="single", items=[])


@pytest.mark.parametrize("method,channel,message", [
    ("大莱莎信保（便捷发货）", "DHL普货", "快递渠道必须包含“9610”"),
    ("小莱莎信保（便捷发货）", "FEDEX", "快递渠道必须包含“9610”"),
    ("新莱莎信保（便捷发货）", None, "快递渠道必须包含“9610”"),
    ("PayPal", "DHL9610", "付款方式必须包含“便捷发货”"),
    (None, "FEDEX9610", "付款方式必须包含“便捷发货”"),
    ("大莱莎信保（报关）", "FEDEX9610", "付款方式必须包含“便捷发货”"),
])
@pytest.mark.parametrize("operation", ["create", "update", "local_create", "local_update"])
def test_mismatch_rejected_before_database_or_route_writes(method, channel, message, operation):
    db = Mock()
    body = payload(method, channel)
    if operation.startswith("local"):
        body.transaction_route = "local"
    with pytest.raises(ValueError, match=message):
        if operation.endswith("create"):
            service.create_invoice(db, body, 1)
        else:
            invoice = Invoice(id=1, transaction_mode="local" if operation.startswith("local") else "legacy")
            service.update_invoice(db, invoice, InvoiceUpdate(**body.model_dump()), 1)
    assert db.mock_calls == []


@pytest.mark.parametrize("method,channel", [
    ("大莱莎信保（便捷发货）", "DHL9610"),
    ("小莱莎信保（便捷发货）", "FEDEX9610"),
    ("新莱莎信保（便捷发货）", "DHL9610"),
    ("自定义便捷发货方式", "自定义9610渠道"),
    ("PayPal", "DHL普货"), ("TT", "FEDEX普货"),
    (None, None), ("现金", "顺丰"), ("大莱莎信保（报关）", "其他快递"),
    ("TT", "DHL"), ("PayPal", "FEDEX"),
])
def test_matching_pair_can_create_and_edit(db, monkeypatch, method, channel):
    monkeypatch.setattr(product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    body = payload(method, channel)
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    # Exercise update to a different valid pair as well as create.
    update = InvoiceUpdate(**body.model_dump())
    update.internal_payment_method = "小莱莎信保（便捷发货）"
    update.express_channel = "FEDEX9610"
    service.update_invoice(db, invoice, update, 1)
    db.commit()
    db.refresh(invoice)
    assert invoice.express_channel == "FEDEX9610"
    assert "便捷发货" in invoice.internal_payment_method


def test_invalid_edit_preserves_saved_order(db, monkeypatch):
    monkeypatch.setattr(product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    body = payload("TT", "DHL普货")
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    update = InvoiceUpdate(**body.model_dump())
    update.express_channel = "DHL9610"
    with pytest.raises(ValueError, match="付款方式必须"):
        service.update_invoice(db, invoice, update, 1)
    db.rollback()
    db.refresh(invoice)
    assert (invoice.internal_payment_method, invoice.express_channel) == ("TT", "DHL普货")


@pytest.mark.parametrize("method,channel", [("TT", "DHL9610"), ("便捷发货", "FEDEX普货")])
def test_save_api_returns_actionable_400_without_creating_order(db, method, channel):
    from fastapi import HTTPException
    from app.invoice.router import _write_invoice_or_400
    with pytest.raises(HTTPException) as error:
        _write_invoice_or_400(db, lambda: service.create_invoice(db, payload(method, channel), 1))
    assert error.value.status_code == 400
    assert "必须包含" in error.value.detail
    assert db.query(Invoice).count() == 0
