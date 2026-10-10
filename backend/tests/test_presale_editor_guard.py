"""Presale editor guidance must distinguish document writes from new cash."""
from datetime import date

import pytest

from app.invoice import service
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement


@pytest.fixture
def order(db):
    row = Invoice(invoice_no="2026.Veronika赊销", order_type="presale", customer_id="C1",
        customer_name="Veronika", invoice_date=date(2026, 10, 10), currency="USD",
        product_amount=627, total_amount=627, status="draft", sync_status="synced")
    db.add(row)
    db.flush()
    return row


def settlement(db, order, state, version=2):
    row = ShipmentSettlement(invoice_id=order.id, settlement_no="Veronika-01", sequence=1,
        request_key="editor_guard_shipment_01", request_hash="a" * 64, quote_hash="b" * 64,
        state=state, quote={"funding_version": version}, is_final=0, created_by=1)
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("state", ["awaiting_payment", "ready", "outbound_pending", "paused", "uncertain"])
def test_active_v2_batch_explains_independent_receipt_entry_and_keeps_write_fence(db, order, state):
    settlement(db, order, state)
    detail = service.serialize_detail(order, db)
    reason = detail.get("presale_edit_blocked_reason")
    assert reason and "登记预售收款" in reason and "无需保存主单" in reason
    with pytest.raises(ValueError, match="未完成的发货结算"):
        ensure_mutable(db, order)


@pytest.mark.parametrize("state", ["shipped", "cancelled"])
def test_terminal_batch_does_not_lock_editor(db, order, state):
    settlement(db, order, state)
    assert service.serialize_detail(order, db).get("presale_edit_blocked_reason") is None


def test_legacy_batch_guidance_does_not_offer_pool_registration(db, order):
    settlement(db, order, "awaiting_payment", version=1)
    reason = service.serialize_detail(order, db).get("presale_edit_blocked_reason")
    assert reason and "原批次" in reason and "登记预售收款" not in reason


def test_ordinary_order_is_not_locked_by_presale_guidance(db, order):
    order.order_type = "stock"
    assert service.serialize_detail(order, db).get("presale_edit_blocked_reason") is None
