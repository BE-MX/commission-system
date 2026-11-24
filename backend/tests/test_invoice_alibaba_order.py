"""9610 invoice boundaries and read-only shipment hints in isolated SQLite."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from pydantic import TypeAdapter
from app.core.config import get_settings
settings = get_settings()
from app.invoice import service, commerce_service
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate
from app.invoice.commerce_schemas import LocalInvoiceDraft
from app.commerce_migration.order_schemas import HistoricalOrder
from app.invoice.shipping_policy import validate_alibaba_order
from app.shipping_inspection.shipment_link_service import _cross_border_prefill
# The inventory gate queries these models; register them before SQLite create_all.
from app.factory_inbound import models as _factory_models, batch_models as _factory_batch_models

METHOD = "新莱莎信保（便捷发货）"
NUMBER = "00123456789012345"

@pytest.mark.parametrize("schema", [InvoiceCreate, LocalInvoiceDraft, HistoricalOrder])
def test_all_entry_schemas_normalize_and_validate(schema):
    adapter = TypeAdapter(schema.model_fields['alibaba_order_no'].rebuild_annotation())
    assert adapter.validate_python(" 00123 456789012345 ") == NUMBER
    assert adapter.validate_python(None) is None
    for invalid in [123456789012345, [], {}, True, "123", "１２３４５６７８９０１２３４５", "12345678901234A", "1" * 21]:
        with pytest.raises(ValueError):
            adapter.validate_python(invalid)

@pytest.mark.parametrize("entry", ["classic_create", "classic_update", "local_apply"])
def test_missing_order_rejected_before_any_write(entry):
    body = InvoiceCreate(invoice_date=date(2026,11,23), customer_id="101", customer_name="Test",
                         internal_payment_method=METHOD, express_channel="DHL9610", inspection_requirement="single", items=[])
    db = Mock()
    with pytest.raises(ValueError, match="阿里信保订单号"):
        if entry == "classic_create":
            service.create_invoice(db, body, 1)
        elif entry == "classic_update":
            service.update_invoice(db, Invoice(id=1, internal_payment_method="TT"), InvoiceUpdate(**body.model_dump()), 1)
        else:
            commerce_service._apply_draft(db, Invoice(), body, {"sub":"1"})
    assert db.mock_calls == []

@pytest.mark.parametrize("start", [None, date(2026, 11, 23)])
@pytest.mark.parametrize("entry", ["classic", "local"])
def test_saving_an_existing_convenient_invoice_requires_number(db, monkeypatch, entry, start):
    monkeypatch.setattr(settings, "CROSS_BORDER_GO_LIVE_DATE", start)
    invoice = Invoice(id=1, created_at=datetime(2025, 1, 1), internal_payment_method=METHOD)
    body = InvoiceUpdate(invoice_date=date(2026, 11, 23), customer_id="101", customer_name="Test",
                         internal_payment_method=METHOD, express_channel="FEDEX9610",
                         alibaba_order_no="  ", inspection_requirement="single", items=[])
    with pytest.raises(ValueError, match="便捷发货必须填写阿里信保订单号"):
        if entry == "classic":
            service.update_invoice(db, invoice, body, 1)
        else:
            commerce_service._apply_draft(db, invoice, body, {"sub": "1"})
    assert not db.new and not db.dirty


def test_number_optional_for_other_payment_methods():
    validate_alibaba_order("PayPal", None)
    validate_alibaba_order("大莱莎信保（报关）", None)
    validate_alibaba_order(METHOD, NUMBER)


def test_prefill_lists_all_convenient_invoices_and_missing_ids(db):
    for no, method, number, order in [("a", METHOD, NUMBER, "O1"), ("b", "小莱莎信保（便捷发货）", None, "O2"), ("c", "TT", None, "O3"), ("d", METHOD, NUMBER, "other")]:
        db.add(Invoice(invoice_no=no, customer_id="C", customer_name="Test", invoice_date=date(2026,11,23),
                       xiaoman_order_id=order, internal_payment_method=method, alibaba_order_no=number))
    db.add(Invoice(invoice_no="fedex", customer_id="C", customer_name="Test", invoice_date=date(2026,11,23),
                   xiaoman_order_id="O4", internal_payment_method=METHOD, express_channel="FEDEX9610", alibaba_order_no=NUMBER))
    db.add(Invoice(invoice_no="other", customer_id="C", customer_name="Test", invoice_date=date(2026,11,23),
                   xiaoman_order_id="O5", internal_payment_method=METHOD, express_channel="其他快递", alibaba_order_no=NUMBER))
    db.flush()
    result = _cross_border_prefill(db, SimpleNamespace(local_outbound_id=None), ["O1","O2","O3","O4","O5"])
    assert result['is_9610']
    assert [r['invoice_no'] for r in result['invoices']] == ['a','b']
    assert result['invoices'][1]['alibaba_order_no'] is None
    assert result['invoices'][1]['shop'] == "小莱莎"


def test_historical_manifest_omits_new_null_field():
    row = HistoricalOrder.model_construct(alibaba_order_no=None)
    assert 'alibaba_order_no' not in row.model_dump(exclude_unset=True)


def test_local_prefill_uses_outbound_invoice_not_mirror_order(db):
    from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement
    invoice = Invoice(invoice_no="local-f2", customer_id="C", customer_name="Test", invoice_date=date(2026,11,23),
                      internal_payment_method=METHOD, alibaba_order_no=NUMBER)
    db.add(invoice)
    db.flush()
    settlement = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="local-f2", is_final=1, quote={}, quote_hash="x",
                                    request_key="f2", request_hash="x", created_by=1)
    db.add(settlement)
    db.flush()
    outbound = ShipmentOutbound(invoice_id=invoice.id, settlement_id=settlement.id, outbound_no="local-f2",
                                payload={}, payload_hash="x")
    db.add(outbound)
    db.flush()
    result = _cross_border_prefill(db, SimpleNamespace(local_outbound_id=outbound.id), [])
    assert result['invoices'][0]['alibaba_order_no'] == NUMBER
    assert result['invoices'][0]['invoice_id'] == invoice.id


def test_linked_sync_old_command_hash_and_changed_identifier():
    import hashlib
    from pydantic import BaseModel
    from app.invoice.linked_sync_service import replay
    class Command(BaseModel):
        request_key: str
        invoice: InvoiceUpdate
    body = Command(request_key="old", invoice=InvoiceUpdate(invoice_date=date(2026,11,23),
        customer_id="C", customer_name="Test", inspection_requirement="single", items=[]))
    digest = hashlib.sha256(body.model_dump_json(exclude={"invoice": {"alibaba_order_no"}}).encode()).hexdigest()
    row = SimpleNamespace(request_hash=digest, invoice_id=1, created_by=1, after={"inspection_requirement":"single"})
    db = Mock()
    db.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = row
    assert replay(db, SimpleNamespace(id=1), body, 1) == (row, digest)
    body.invoice.alibaba_order_no = NUMBER
    with pytest.raises(ValueError, match="提交标识"):
        replay(db, SimpleNamespace(id=1), body, 1)


def test_waybill_9610_flag_excludes_non_dhl_channels():
    from app.shipping_inspection.waybill_scope_service import is_9610
    flag = lambda channel: is_9610(SimpleNamespace(internal_payment_method=METHOD, express_channel=channel))
    assert flag("DHL9610") and flag(None)
    assert not flag("FEDEX9610") and not flag("其他快递")
