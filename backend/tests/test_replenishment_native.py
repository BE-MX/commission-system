"""Replenishment combines native SKU demand, sellable stock and open production."""
from datetime import date
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.catalog.models import CatalogProduct
from app.core.config import get_settings
from app.inventory.models import StockBalance
from app.inventory.service import post_document
from app.invoice.commerce_service import create_draft, confirm, cancel
from app.production.local_schemas import ProductionCreate, ProductionLine
from app.production.local_service import create
from app.production.local_service import complete, link_supply
from app.production.local_schemas import QuantityCommand, SupplyCreate
from app.stock.models import ProductionOrderItem
from app.stock import overview_service, safety_service, sku_query
from app.stock.models import SafetyStock
from app.trade.projection_service import project_invoice
from tests.test_inventory_local import stock, command
from tests.test_invoice_commerce import buyer, draft, action


@pytest.mark.asyncio
async def test_native_replenishment_scope_versions_and_pending(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    monkeypatch.setattr("app.stock.local_query_service.beijing_today", lambda: date(2026, 10, 3))
    sku, (warehouse, other) = stock
    customer, user = buyer
    product = db.get(CatalogProduct, sku.product_id)
    product.model, sku.color, sku.size, sku.weight_grams = "Native", "#1", "18", Decimal("20")
    post_document(db, command("initial", "receipt", warehouse, sku, 10), actor_id=None)
    post_document(db, command("isolated", "receipt", warehouse, sku, 100, quality="quarantine"), actor_id=None)
    post_document(db, command("disabled", "receipt", other, sku, 200), actor_id=None)
    other.active = False
    invoice = create_draft(db, draft(customer, user, sku), user)
    confirm(db, invoice.id, action("confirm", 1, warehouse.id), user)
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_products" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        with pytest.raises(HTTPException) as pending:
            overview_service.query_stock_overview(db)
        assert pending.value.status_code == 409
        project_invoice(db, invoice.id)
        identity = f"ark:sku:{sku.id}"
        result = safety_service.save_safety_stock(db, [{"product_id": identity, "safety_stock": 12,
            "expected_version": 0}], 30, 1.5, "manual", int(user["sub"]))
        assert result["saved"] == [identity]
        stale = safety_service.save_safety_stock(db, [{"product_id": identity, "safety_stock": 100,
            "expected_version": 0}], 30, 1.5, "manual", int(user["sub"]))
        assert len(stale["failed"]) == 1
        production = create(db, ProductionCreate(request_key="replenish", batch_no="NATIVE",
            items=[ProductionLine(local_sku_id=sku.id, quantity=4)]), user)
        result = overview_service.query_stock_overview(db, color="#1", weight="20g")
        assert result["total"] == 1 and result["summary"]["shortage_count"] == 1
        row = result["items"][0]
        assert row["sales_30d"] == 3 and row["sales_90d"] == 3
        assert row["enable_count"] == 7 and row["real_count"] == 10
        assert row["production_in_transit"] == 4 and row["effective_enable_count"] == 11
        assert row["suggested_qty"] == 13 and row["stock_items"][0]["batch_no"] == "NATIVE"
        assert safety_service.query_safety_stock_list(db, has_in_transit=True)["total"] == 1
        assert overview_service.query_stock_overview(db, page=2, page_size=1)["items"] == []
        assert sku_query.get_sku_sales(db, identity, 30) == 3
        suggestions = await safety_service.batch_generate_suggestions(db, [identity], 30, 1.5, 30)
        assert suggestions["tft_available"] is False and suggestions["items"][0]["source"] == "formula"
        cancel(db, invoice.id, action("cancel", 2), user)
        project_invoice(db, invoice.id)
        assert sku_query.query_all_sku_status(db)[0]["sales_30d"] == 0
        assert db.query(SafetyStock).filter_by(local_sku_id=sku.id).one().safety_stock == 12
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_finished_goods_waiting_receipt_and_customer_supply_are_distinct(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    customer, user = buyer
    invoice = create_draft(db, draft(customer, user, sku, order_type="production", shipping_fee=0), user)
    confirm(db, invoice.id, action("confirm", 1), user)
    project_invoice(db, invoice.id)
    production = create(db, ProductionCreate(request_key="replenishment", batch_no="AWAITING-RECEIPT",
        items=[ProductionLine(local_sku_id=sku.id, quantity=4)]), user)
    item = db.query(ProductionOrderItem).filter_by(order_id=production.id).one()
    complete(db, item.id, QuantityCommand(request_key="finish", expected_version=1, quantity=4, reason="done"), user)
    row = overview_service.query_stock_overview(db)["items"][0]
    assert row["production_in_transit"] == 4 and row["effective_enable_count"] == 4
    link_supply(db, item.id, SupplyCreate(request_key="customer-supply", expected_version=2,
        quantity=3, invoice_item_id=invoice.items[0].id, reason="planned"), user)
    row = overview_service.query_stock_overview(db)["items"][0]
    assert row["production_in_transit"] == 4 and row["available_production_in_transit"] == 1
    assert row["effective_enable_count"] == 1
    item.is_urgent = 1
    db.flush()
    assert safety_service.query_safety_stock_list(db, stock_status="stocking")["total"] == 0
    assert safety_service.query_safety_stock_list(db, stock_status="urgent")["total"] == 1
    assert "piece" in overview_service.get_filter_options(db)["weights"]
    assert overview_service.query_stock_overview(db, weight="piece")["total"] == 1
