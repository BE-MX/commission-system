"""Public/MCP catalogs read native identities without exposing stock counts."""
import json
from sqlalchemy import event
from app.catalog.models import CatalogProduct, CatalogSku
from app.core.config import get_settings
from app.inventory.models import StockBalance
from app.inventory.service import post_document
from app.invoice import product_service, catalog_specs
from app.mcp.price_tools import _find_product
from app.stock.public_service import query_public_inventory
from tests.test_inventory_local import stock, command


def test_native_catalog_dimensions_public_stock_and_agent_privacy(db, stock, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, (main, other) = stock
    product = db.get(CatalogProduct, sku.product_id)
    product.model, sku.weight_grams = "Native Weft", 20
    sku.color, sku.size = "#1", '18 inch'
    post_document(db, command("public-main", "receipt", main, sku, 3), actor_id=None)
    post_document(db, command("public-other", "receipt", other, sku, 10), actor_id=None)
    post_document(db, command("public-quarantine", "receipt", main, sku, 50, quality="quarantine"), actor_id=None)
    other.active = False
    balance = db.query(StockBalance).filter_by(sku_id=sku.id, warehouse_id=main.id, quality="sellable").one()
    balance.reserved = 3
    db.flush()
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_products" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        result = query_public_inventory(db)
        assert result["items"] == [{"product_id": f"ark:sku:{sku.id}", "type": "Hair", "color": "#1", "size": "18 inch",
            "weight": "20g", "in_stock": False, "source": "local"}]
        assert query_public_inventory(db, in_stock_only=True)["total"] == 0
        values = dict(model="Native Weft", color="#1", size="18", unit="20g")
        matched = product_service.match_product(db, **values)
        assert matched["is_unique"] and matched["item"]["local_sku_id"] == sku.id
        assert matched["item"]["available_stock"] == 0
        assert product_service.get_filter_options(db, model="Native Weft")["units"] == ["20g"]
        assert product_service.get_entry_options(db)["models"] == ["Native Weft"]
        identity = {"permissions": ["invoice_price:read"]}
        agent = json.loads(_find_product(db, identity, **values))
        assert agent["item"]["local_sku_id"] == sku.id and "available_stock" not in agent["item"]
        assert "stock_warning" not in agent["matches"][0]
        specs = catalog_specs.lookup_specs(db, identity, ["Weft"], length='18"')
        assert specs["matches"] == [{"model": "Native Weft", "size": "18 inch", "unit": "20g"}]
        assert catalog_specs.lookup_specs(db, {}, ["Weft"])["status"] == "permission_denied"
        sku.active = False
        db.flush()
        assert not product_service.match_product(db, **values)["matches"]
        assert query_public_inventory(db)["total"] == 0
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)
