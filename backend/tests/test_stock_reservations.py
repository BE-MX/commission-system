"""Reservations belong to invoice lines and may never exceed unshipped demand."""

from datetime import date

import pytest
from sqlalchemy import select

from app.invoice.models import Invoice, InvoiceItem
from app.inventory.models import StockBalance, StockDocument, StockReservation
from app.inventory.reservation_service import reserve_line, release_line, consume_line
from tests.test_inventory_local import stock, command, balance
from app.inventory.service import post_document


@pytest.fixture
def order_line(db, stock):
    sku, (wh, other) = stock
    invoice = Invoice(invoice_no="LOCAL-1", customer_id="legacy-1", customer_name="Buyer",
                      invoice_date=date(2026, 10, 3), transaction_mode="local", commerce_status="confirmed")
    db.add(invoice)
    db.flush()
    line = InvoiceItem(invoice_id=invoice.id, local_sku_id=sku.id, product_name="Hair",
                       product_display="Hair", color="Black", quantity=10)
    db.add(line)
    db.flush()
    for warehouse in (wh, other):
        post_document(db, command("receive-" + warehouse.code, "receipt", warehouse, sku, 20), actor_id=None)
    return invoice, line, sku, wh, other


def test_reserve_retry_partial_release_and_consume(db, order_line):
    invoice, line, sku, wh, _ = order_line
    doc = reserve_line(db, line.id, wh.id, 8, "reserve", None)
    assert reserve_line(db, line.id, wh.id, 8, "reserve", None).id == doc.id
    with pytest.raises(ValueError, match="幂等"):
        reserve_line(db, line.id, wh.id, 7, "reserve", None)
    assert (balance(db, wh, sku).on_hand, balance(db, wh, sku).reserved) == (20, 8)
    release_line(db, line.id, wh.id, 3, "release", "change", None)
    consume_line(db, line.id, wh.id, 4, "ship", "shipment-1", None)
    assert (balance(db, wh, sku).on_hand, balance(db, wh, sku).reserved) == (16, 1)
    reserve_line(db, line.id, wh.id, 5, "reserve-again", None)
    with pytest.raises(ValueError, match="订单数量"):
        reserve_line(db, line.id, wh.id, 1, "too-many", None)
    assert balance(db, wh, sku).reserved == 6
    rows = db.scalars(select(StockReservation).where(StockReservation.invoice_item_id == line.id)).all()
    assert line.stock_reserved_quantity == sum(row.reserved for row in rows) == 6
    assert line.stock_shipped_quantity == sum(row.shipped for row in rows) == 4


def test_cross_warehouse_demand_limit_and_release_identity(db, order_line):
    _, line, sku, wh, other = order_line
    reserve_line(db, line.id, wh.id, 7, "reserve", None)
    with pytest.raises(ValueError, match="订单数量"):
        reserve_line(db, line.id, other.id, 4, "too-many", None)
    with pytest.raises(ValueError, match="预占"):
        release_line(db, line.id, other.id, 1, "wrong-warehouse", "cancel", None)
    assert balance(db, wh, sku).reserved == 7
    assert balance(db, other, sku).reserved == 0
    assert db.scalar(select(StockDocument).where(StockDocument.idempotency_key == "too-many")) is None


def test_release_allowed_after_deactivation_but_new_reserve_is_not(db, order_line):
    _, line, sku, wh, _ = order_line
    reserve_line(db, line.id, wh.id, 7, "reserve", None)
    wh.active = False
    sku.active = False
    db.flush()
    release_line(db, line.id, wh.id, 7, "release", "cancel", None)
    assert balance(db, wh, sku).reserved == 0
    with pytest.raises(ValueError, match="停用"):
        reserve_line(db, line.id, wh.id, 1, "inactive", None)


def test_bad_quantity_and_legacy_order_cannot_reserve(db, order_line):
    invoice, line, _, wh, _ = order_line
    for qty in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            reserve_line(db, line.id, wh.id, qty, "invalid", None)
    invoice.transaction_mode = "legacy"
    db.flush()
    with pytest.raises(ValueError, match="本地"):
        reserve_line(db, line.id, wh.id, 1, "legacy", None)


def test_consume_cannot_take_another_lines_reservation(db, order_line):
    _, line, sku, wh, _ = order_line
    reserve_line(db, line.id, wh.id, 2, "reserve", None)
    with pytest.raises(ValueError, match="预占"):
        consume_line(db, line.id, wh.id, 3, "ship-too-many", "shipment-1", None)
    reservation = db.scalar(select(StockReservation))
    assert (reservation.reserved, reservation.shipped) == (2, 0)
    assert balance(db, wh, sku).on_hand == 20


def test_order_reduction_cannot_allow_excess_issue(db, order_line):
    _, line, sku, wh, _ = order_line
    reserve_line(db, line.id, wh.id, 10, "reserve", None)
    line.quantity = 5
    db.flush()
    with pytest.raises(ValueError, match="订单数量"):
        consume_line(db, line.id, wh.id, 10, "issue", "shipment-1", None)
    assert balance(db, wh, sku).on_hand == 20
    release_line(db, line.id, wh.id, 5, "reduce-reserved", "order reduced", None)
    consume_line(db, line.id, wh.id, 5, "issue-corrected", "shipment-2", None)
    assert balance(db, wh, sku).on_hand == 15
