"""SKU identity comes from the catalog, independently of warehouse inventory."""
import pytest
from sqlalchemy import text
from app.invoice import product_service, import_service, xiaoman_service

PID = 105767890099971
SID = 105767890100162

@pytest.fixture
def catalog(db):
    db.execute(text("CREATE TABLE lsordertest.okki_products (product_id INTEGER, product_no TEXT, name TEXT, model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER)"))
    db.execute(text("CREATE TABLE lsordertest.okki_product_skus (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER)"))
    db.execute(text("CREATE TABLE lsordertest.okki_inventory (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER, real_count NUMERIC)"))
    db.execute(text("INSERT INTO lsordertest.okki_products VALUES (:pid, '6583', 'Super Double Drawn Genius Weft/18/Cookies Cream/20g', 'M1', 'Cookies Cream', '18', '20g', 0)"), {"pid": PID})
    db.execute(text("INSERT INTO lsordertest.okki_product_skus VALUES (:pid, :sid, 0)"), {"pid": PID, "sid": SID})
    return db


def test_catalog_sku_without_inventory_matches_every_entry(catalog):
    db = catalog
    result = product_service.match_product(db, model="M1", color="Cookies Cream", size="18", unit="20g")
    assert result["is_unique"] is True
    assert result["item"]["sku_id"] == SID
    assert result["item"]["sku_count"] == 1
    matched = product_service.find_okki_by_attributes(db, product_display="Super Double Drawn Genius Weft", color="Cookies Cream", size="18", unit="20g")
    assert matched["sku_id"] == SID
    assert import_service._load_sku_map(db, {PID}) == {PID: [SID]}
    assert product_service.valid_okki_product_skus(db, {(PID, SID), (PID + 1, SID)}) == {(PID, SID)}
    assert xiaoman_service.resolve_generic_product(db, "6583")["skus"] == [SID]


@pytest.mark.parametrize("has_disabled_catalog_row", [False, True])
def test_inventory_cannot_make_missing_or_disabled_sku_valid(catalog, has_disabled_catalog_row):
    db = catalog
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (:pid, :sid, 0, 0)"), {"pid": PID, "sid": SID})
    db.execute(text("UPDATE lsordertest.okki_product_skus SET disable_flag=1" if has_disabled_catalog_row else "DELETE FROM lsordertest.okki_product_skus"))
    assert product_service.match_product(db, model="M1", color="Cookies Cream", size="18", unit="20g")["item"]["sku_id"] is None
    assert import_service._load_sku_map(db, {PID}) == {}
    assert product_service.valid_okki_product_skus(db, {(PID, SID)}) == set()
    assert xiaoman_service.resolve_generic_product(db, "6583")["skus"] == []


def test_disabled_product_is_rejected(catalog):
    catalog.execute(text("UPDATE lsordertest.okki_products SET disable_flag=1"))
    assert product_service.valid_okki_product_skus(catalog, {(PID, SID)}) == set()
    assert product_service.match_product(catalog, model="M1", color="Cookies Cream", size="18", unit="20g")["item"] is None
    assert xiaoman_service.resolve_generic_product(catalog, "6583") is None


@pytest.mark.parametrize("counts", [[], [0], [-1], [5, -5]])
def test_no_actual_inventory_only_warns_and_allows_import_and_save(catalog, counts):
    from app.invoice import service
    from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload
    from datetime import date
    db = catalog
    for count in counts:
        db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (:pid, :sid, 0, :count)"), {"pid": PID, "sid": SID, "count": count})
    matched = product_service.match_product(db, model="M1", color="Cookies Cream", size="18", unit="20g")["item"]
    assert "可继续下单" in matched["stock_warning"]
    preview = import_service.preview_import(db, customer_id="C1", order_type="stock", currency="USD", raw_rows=[{
        "source_row": 1, "product": "Super Double Drawn Genius Weft", "length": "18", "color": "Cookies Cream", "weight": "20g", "quantity": 2, "unit_price": 10,
    }])
    row = preview["rows"][0]
    assert row["status"] == "warning"
    assert row["errors"] == []
    assert row["matched_product"]["sku_id"] == SID
    assert any("可继续下单" in warning for warning in row["warnings"])
    invoice = service.create_invoice(db, InvoiceCreate(
        invoice_no="NO-STOCK-TEST", order_type="stock", customer_id="C1", customer_name="Test", invoice_date=date(2026, 9, 17),
        items=[InvoiceItemPayload(item_type="stock", product_id=PID, sku_id=SID, product_name="Super Double Drawn Genius Weft", product_display="Super Double Drawn Genius Weft", model="M1", color="Cookies Cream", length="18", net_weight_grams="20g", quantity=2, price_per_piece=10)],
    ))
    assert invoice.id is not None
    assert invoice.items[0].sku_id == SID


def test_positive_actual_inventory_needs_no_warning(catalog):
    catalog.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (:pid, :sid, 0, 5)"), {"pid": PID, "sid": SID})
    assert product_service.load_stock_warnings(catalog, {PID}) == {}
