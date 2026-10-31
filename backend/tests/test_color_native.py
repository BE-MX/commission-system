"""Local stock and color trends never read transaction mirrors."""
from datetime import date
from sqlalchemy import event
from app.catalog.models import CatalogProduct
from app.inventory.models import StockBalance
from app.inventory.service import post_document
from app.colorwork.service import compute_template_statuses
from app.color import local_sales_service
from app.color.models import ColorTrendData
from app.core.config import get_settings
from app.invoice.commerce_service import create_draft, confirm, cancel
from app.trade.projection_service import project_invoice
from tests.test_inventory_local import stock, command
from tests.test_invoice_commerce import buyer, draft, action


def test_native_available_stock_ignores_reserved_quarantine_and_inactive_warehouses(db, stock, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, (main, other) = stock
    db.get(CatalogProduct, sku.product_id).name = "Standard Double Drawn Genius Weft"
    sku.weight_grams, sku.color, sku.size = 20, "#1", '16.0"'
    post_document(db, command("main", "receipt", main, sku, 21), actor_id=None)
    post_document(db, command("quarantine", "receipt", main, sku, 100, quality="quarantine"), actor_id=None)
    post_document(db, command("other", "receipt", other, sku, 100), actor_id=None)
    other.active = False
    sellable = db.query(StockBalance).filter_by(warehouse_id=main.id, sku_id=sku.id, quality="sellable").one()
    sellable.reserved = 2
    db.flush()
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        result = compute_template_statuses(db, "20g-genius-weft-regular")
        assert result["statuses"] == {"#1|16": "low_stock"}
        assert result["source_synced_at"] and result["source"] == "local"
        sellable.reserved = 21
        db.flush()
        assert compute_template_statuses(db, "20g-genius-weft-regular")["statuses"] == {"#1|16": "restocking"}
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_color_aggregation_pending_and_cancelled_sales_clear_old_totals(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    monkeypatch.setattr(local_sales_service, "beijing_today", lambda: date(2026, 10, 3))
    sku, _ = stock
    customer, seller = buyer
    sku.color = "黑色"
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("color-confirm", 1), seller)
    assert local_sales_service.aggregate_sales(db)["status"] == "pending"
    project_invoice(db, invoice.id)
    result = local_sales_service.aggregate_sales(db)
    assert result["family_sales"]["black"] == float(invoice.items[0].quantity)
    cancel(db, invoice.id, action("color-cancel", 2), seller)
    assert local_sales_service.aggregate_sales(db)["status"] == "pending"
    project_invoice(db, invoice.id)
    assert local_sales_service.aggregate_sales(db)["family_sales"]["black"] == 0
    assert db.query(ColorTrendData).filter_by(color_family="black", data_source="sales").one().raw_value == 0


def test_industry_palette_aliases_and_conflicting_sources_do_not_silently_erase_sales(db, stock, buyer, monkeypatch):
    from app.color.models import ColorPalette
    monkeypatch.setattr(local_sales_service, "beijing_today", lambda: date(2026, 10, 3))
    sku, _ = stock
    customer, seller = buyer
    sku.color = "#1"
    palette = ColorPalette(industry_code="#1", display_name="Natural black", hex_code="#000000", rgb_r=0, rgb_g=0, rgb_b=0,
        color_family="black", source="industry")
    db.add(palette)
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("palette-confirm", 1), seller)
    project_invoice(db, invoice.id)
    assert local_sales_service.aggregate_sales(db)["family_sales"]["black"] == 3
    db.add(ColorPalette(industry_code="#1", display_name="Different source", hex_code="#ffffff", rgb_r=255, rgb_g=255, rgb_b=255,
        color_family="silver", source="other"))
    db.flush()
    result = local_sales_service.aggregate_sales(db)
    assert result["status"] == "needs_review" and result["unresolved_colors"] == {"#1": 3}
    assert db.query(ColorTrendData).filter_by(color_family="black", data_source="sales").one().raw_value == 3




def test_monday_job_includes_previous_week_and_repairs_late_cancellation(db, stock, buyer, monkeypatch):
    sku, _ = stock
    customer, seller = buyer
    sku.color = "黑色"
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("weekly-confirm", 1), seller)
    project_invoice(db, invoice.id)
    monkeypatch.setattr(local_sales_service, "beijing_today", lambda: date(2026, 10, 5))
    result = local_sales_service.refresh_sales_history(db)
    previous = db.query(ColorTrendData).filter_by(color_family="black", data_source="sales", period_date=date(2026, 9, 28)).one()
    assert previous.raw_value == 3
    assert {"week_start": "2026-09-28", "status": "success"} in result["periods"]
    cancel(db, invoice.id, action("weekly-cancel", 2), seller)
    project_invoice(db, invoice.id)
    monkeypatch.setattr(local_sales_service, "beijing_today", lambda: date(2026, 11, 2))
    local_sales_service.refresh_sales_history(db)
    db.refresh(previous)
    assert previous.raw_value == 0
