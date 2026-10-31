"""Local stock facts must survive retries and cannot manufacture availability."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockBalance, StockDocument, StockLedger, Warehouse
from app.inventory.schemas import DocumentCreate, MovementLine
from app.inventory.service import post_document, reverse_document


@pytest.fixture
def stock(db):
    from app.commerce_transition.models import PlatformPolicy
    from app.commerce_transition import service as transition
    current = db.get(PlatformPolicy, 1)
    if current.phase == 'legacy_only':
        transition.set_writer_receipt(db, 'isolated-native-fixture', 1, 'compatible', {'enforced': True})
        transition.set_policy(db, phase='local_only', expected_version=current.version,
                              inventory_evidence={'all_writers': ['isolated-native-fixture']})
    product = CatalogProduct(code="P1", name="Hair", kind="hair", display_name="Hair")
    db.add(product)
    db.flush()
    sku = CatalogSku(product_id=product.id, code="S1", color="black", size="18", unit="piece")
    warehouses = [Warehouse(code=code, name=code) for code in ("MAIN", "OTHER")]
    db.add_all([sku, *warehouses])
    db.flush()
    return sku, warehouses


def command(key, kind, warehouse, sku, quantity, **kwargs):
    return DocumentCreate(idempotency_key=key, kind=kind, reason="test", lines=[
        MovementLine(warehouse_id=warehouse.id, sku_id=sku.id, quantity=quantity, **kwargs)
    ])


def balance(db, warehouse, sku):
    return db.scalar(select(StockBalance).where(
        StockBalance.warehouse_id == warehouse.id, StockBalance.sku_id == sku.id,
        StockBalance.quality == "sellable",
    ))


def test_receipt_retry_and_key_collision(db, stock):
    sku, (wh, _) = stock
    body = command("receive-1", "receipt", wh, sku, 10)
    first = post_document(db, body, actor_id=None)
    assert post_document(db, body, actor_id=None).id == first.id
    assert balance(db, wh, sku).on_hand == 10
    with pytest.raises(ValueError, match="幂等"):
        post_document(db, command("receive-1", "receipt", wh, sku, 11), actor_id=None)
    assert balance(db, wh, sku).on_hand == 10
    assert len(db.scalars(select(StockLedger)).all()) == 1


def test_atomic_multi_line_and_insufficient_stock(db, stock):
    sku, (wh, other) = stock
    post_document(db, command("opening", "opening", wh, sku, 10), actor_id=None)
    body = DocumentCreate(idempotency_key="adjust", kind="adjustment", reason="count variance", lines=[
        MovementLine(warehouse_id=other.id, sku_id=sku.id, quantity=5),
        MovementLine(warehouse_id=wh.id, sku_id=sku.id, quantity=-11),
    ])
    with pytest.raises(ValueError, match="库存"):
        post_document(db, body, actor_id=None)
    assert balance(db, wh, sku).on_hand == 10
    assert balance(db, other, sku) is None
    assert db.scalar(select(StockDocument).where(StockDocument.idempotency_key == "adjust")) is None


def test_transfer_conserves_stock_and_reversal_is_once(db, stock):
    sku, (wh, other) = stock
    post_document(db, command("opening", "opening", wh, sku, 10), actor_id=None)
    transfer = post_document(db, command("transfer", "transfer", wh, sku, 6,
                                         destination_warehouse_id=other.id), actor_id=None)
    assert balance(db, wh, sku).on_hand == 4
    assert balance(db, other, sku).on_hand == 6
    reversed_doc = reverse_document(db, transfer.id, "reverse-1", "wrong warehouse", None)
    assert reverse_document(db, transfer.id, "reverse-1", "wrong warehouse", None).id == reversed_doc.id
    with pytest.raises(ValueError, match="冲销"):
        reverse_document(db, transfer.id, "reverse-2", "again", None)
    assert balance(db, wh, sku).on_hand == 10
    assert balance(db, other, sku).on_hand == 0
    for warehouse in (wh, other):
        facts = db.scalars(select(StockLedger).where(StockLedger.warehouse_id == warehouse.id)).all()
        assert sum(row.on_hand_delta for row in facts) == balance(db, warehouse, sku).on_hand


def test_reversal_cannot_erase_consumed_receipt(db, stock):
    sku, (wh, _) = stock
    receipt = post_document(db, command("receive", "receipt", wh, sku, 10), actor_id=None)
    post_document(db, command("issue", "adjustment", wh, sku, -4), actor_id=None)
    with pytest.raises(ValueError, match="库存"):
        reverse_document(db, receipt.id, "undo", "correction", None)
    assert balance(db, wh, sku).on_hand == 6
    assert receipt.reversed_by_id is None


def test_inactive_and_fractional_quantity_rejected(db, stock):
    sku, (wh, _) = stock
    with pytest.raises(ValueError):
        command("fraction", "receipt", wh, sku, Decimal("1.5"))
    with pytest.raises(ValueError):
        command("boolean", "receipt", wh, sku, True)
    wh.active = False
    db.flush()
    with pytest.raises(ValueError, match="停用"):
        post_document(db, command("inactive", "receipt", wh, sku, 1), actor_id=None)


def test_count_uses_expected_version_and_quality_is_not_sellable(db, stock):
    sku, (wh, _) = stock
    post_document(db, command("receive", "receipt", wh, sku, 10), actor_id=None)
    with pytest.raises(ValueError, match="版本"):
        post_document(db, command("stale-count", "count", wh, sku, 8, expected_version=0), actor_id=None)
    post_document(db, command("count", "count", wh, sku, 8, expected_version=1), actor_id=None)
    post_document(db, command("quarantine", "receipt", wh, sku, 4, quality="quarantine"), actor_id=None)
    assert balance(db, wh, sku).on_hand == 8


def test_transfer_overflow_restores_source_and_documents(db, stock):
    sku, (wh, other) = stock
    post_document(db, command("opening1", "opening", wh, sku, 10), actor_id=None)
    post_document(db, command("opening2", "opening", other, sku, 2147483647), actor_id=None)
    with pytest.raises(ValueError, match="范围"):
        post_document(db, command("overflow", "transfer", wh, sku, 1,
                                  destination_warehouse_id=other.id), actor_id=None)
    assert balance(db, wh, sku).on_hand == 10
    assert balance(db, other, sku).on_hand == 2147483647
    assert len(db.scalars(select(StockLedger)).all()) == 2


def test_reversal_multi_line_failure_restores_all_balances(db, stock):
    sku, (wh, other) = stock
    doc = post_document(db, DocumentCreate(idempotency_key="two-receipts", kind="receipt", reason="test", lines=[
        MovementLine(warehouse_id=wh.id, sku_id=sku.id, quantity=10),
        MovementLine(warehouse_id=other.id, sku_id=sku.id, quantity=10),
    ]), actor_id=None)
    post_document(db, command("consume-first", "adjustment", wh, sku, -4), actor_id=None)
    with pytest.raises(ValueError, match="库存"):
        reverse_document(db, doc.id, "undo-both", "wrong receipt", None)
    assert balance(db, wh, sku).on_hand == 6
    assert balance(db, other, sku).on_hand == 10
    assert len(db.scalars(select(StockLedger)).all()) == 3


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-02T15:59:59+00:00", "2026-10-02T23:59:59"),
    ("2026-10-02T16:00:00+00:00", "2026-10-03T00:00:00"),
])
def test_stock_audit_dates_use_beijing_on_non_beijing_server(db, stock, monkeypatch, instant, expected):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.core import time as business_time

    fixed = datetime.fromisoformat(instant)
    class ServerDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz or ZoneInfo("America/New_York"))
    monkeypatch.setattr(business_time, "datetime", ServerDateTime)
    sku, (wh, _) = stock
    doc = post_document(db, command("midnight", "receipt", wh, sku, 1), actor_id=None)
    assert doc.created_at.isoformat() == expected
    assert balance(db, wh, sku).updated_at.isoformat() == expected
    assert db.scalar(select(StockLedger.created_at)).isoformat() == expected
