"""Invoice V2: pricing engine, custom product sink, totals with fees."""

from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import text

from app.invoice import price_service, product_service, service
from app.invoice.models import (  # noqa: F401 - register metadata for create_all
    CustomerPriceRule,
    CustomProduct,
    Invoice,
    InvoiceItem,
    PriceColorType,
    StdPrice,
)
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


def _seed_okki(db, rows=()):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT, name TEXT, model TEXT,
            color TEXT, size TEXT, unit TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    for pid, name, model, color, size, unit, sku in rows:
        db.execute(text(
            "INSERT INTO lsordertest.okki_products (product_id, product_no, name, model, color, size, unit, disable_flag) "
            "VALUES (:pid, :pno, :name, :model, :color, :size, :unit, 0)"
        ), {"pid": pid, "pno": f"P{pid}", "name": name, "model": model, "color": color, "size": size, "unit": unit})
        db.execute(text(
            "INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag) VALUES (:pid, :sku, 0)"
        ), {"pid": pid, "sku": sku})
    db.commit()


def _seed_pricing(db):
    price_service.upsert_color_type(db, color_code="#P8/24", color_type="piano")
    price_service.upsert_std_price(
        db,
        series_grade="Super Double Drawn Genius Weft(20g 天才发帘）",
        length='16"',
        weight_unit="20g",
        color_type="piano",
        price=Decimal("20.1828"),
    )
    db.flush()


# ── normalization / match key ─────────────────────────────────

def test_normalize_and_match_key():
    assert price_service.normalize_length('16"') == "16"
    assert price_service.normalize_text("  Super   Double Drawn ") == "super double drawn"
    assert price_service.normalize_color("#P8/24") == "p8/24"
    key1 = price_service.make_match_key("Genius Weft", None, "#1B", '16"', "20g")
    key2 = price_service.make_match_key(" genius  weft ", "", "1B", "16", " 20G ")
    assert key1 == key2


def test_infer_color_type_heuristic(db):
    assert price_service.resolve_color_type(db, "#2TP2/8A") == ("balayage", "inferred")
    assert price_service.resolve_color_type(db, "#P4/18") == ("piano", "inferred")
    assert price_service.resolve_color_type(db, "#5AT60") == ("ombre", "inferred")
    assert price_service.resolve_color_type(db, "#1B") == ("solid", "inferred")


# ── rule application ──────────────────────────────────────────

def test_apply_rule_fixed_percent_and_floor():
    std = Decimal("20.0000")
    fixed = CustomerPriceRule(adjust_type="fixed", adjust_value=Decimal("2.5"))
    percent = CustomerPriceRule(adjust_type="percent", adjust_value=Decimal("-10"))
    crash = CustomerPriceRule(adjust_type="fixed", adjust_value=Decimal("-30"))
    assert price_service.apply_rule(std, fixed) == Decimal("22.5000")
    assert price_service.apply_rule(std, percent) == Decimal("18.0000")
    assert price_service.apply_rule(std, None) == Decimal("20.0000")
    assert price_service.apply_rule(std, crash) == Decimal("0.0000")


def test_resolve_price_with_rule_and_series_prefix(db):
    _seed_pricing(db)
    price_service.upsert_customer_rule(
        db, customer_id="CUST001", customer_name="客户A",
        adjust_type="percent", adjust_value=Decimal("5"),
    )
    db.flush()

    result = price_service.resolve_price(
        db, customer_id="CUST001",
        product_display="Super Double Drawn Genius Weft",
        length="16", unit="20g", color="#P8/24",
    )
    assert result["standard_price"] == Decimal("20.1828")
    assert result["customer_price"] == Decimal("21.1919")
    assert result["color_type"] == "piano"
    assert result["price_source"] == "customer_rule"


def test_resolve_price_missing_std(db):
    result = price_service.resolve_price(
        db, customer_id=None,
        product_display="Unknown Series", length="30", unit="999g", color="#1",
    )
    assert result["standard_price"] is None
    assert result["customer_price"] is None
    assert result["price_source"] == "missing_std"


# ── custom product sink ───────────────────────────────────────

def test_ensure_custom_product_reuse(db):
    _seed_okki(db)
    first = product_service.ensure_custom_product(
        db, product_display="Genius Weft", model=None,
        color="#1B", size='16"', unit="20g", user_id=1,
    )
    again = product_service.ensure_custom_product(
        db, product_display=" genius  weft ", model="",
        color="1B", size="16", unit=" 20G ", user_id=2,
    )
    assert first["source"] == "custom"
    assert again["custom_product_id"] == first["custom_product_id"]
    row = db.query(CustomProduct).filter(CustomProduct.id == first["custom_product_id"]).one()
    assert row.use_count == 2
    assert row.product_name == 'Genius Weft/16"/#1B/20g'

    other = product_service.ensure_custom_product(
        db, product_display="Genius Weft", model=None,
        color="#60", size="16", unit="20g", user_id=1,
    )
    assert other["custom_product_id"] != first["custom_product_id"]


def test_ensure_custom_product_links_unique_okki(db):
    _seed_okki(db, rows=[
        (11, "Standard Double Drawn Genius Weft/16/#1/20g", "B3天才发帘", "#1", "16", "20g", 9011),
    ])
    resolved = product_service.ensure_custom_product(
        db, product_display="Standard Double Drawn Genius Weft", model=None,
        color="#1", size="16", unit="20g", user_id=1,
    )
    assert resolved["source"] == "okki"
    assert resolved["product_id"] == 11
    assert resolved["sku_id"] == 9011
    assert db.query(CustomProduct).count() == 0


def test_reconcile_backfills_okki_id(db):
    _seed_okki(db)
    created = product_service.ensure_custom_product(
        db, product_display="Standard Double Drawn Genius Weft", model=None,
        color="#4", size="18", unit="20g", user_id=1,
    )
    assert created["source"] == "custom"

    db.execute(text(
        "INSERT INTO lsordertest.okki_products (product_id, product_no, name, model, color, size, unit, disable_flag) "
        "VALUES (21, 'P21', 'Standard Double Drawn Genius Weft/18/#4/20g', 'B3', '#4', '18', '20g', 0)"
    ))
    db.execute(text("INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag) VALUES (21, 9021, 0)"))

    result = product_service.reconcile_custom_products(db)
    assert result == {"checked": 1, "linked": 1}
    row = db.query(CustomProduct).filter(CustomProduct.id == created["custom_product_id"]).one()
    assert row.okki_product_id == 21
    assert row.okki_sku_id == 9021


# ── invoice totals with pricing ───────────────────────────────

def _custom_item(**overrides):
    payload = dict(
        item_type="custom",
        product_display="Super Double Drawn Genius Weft",
        net_weight_grams="20g",
        color="#P8/24",
        length="16",
        quantity=5,
        price_per_piece=None,
    )
    payload.update(overrides)
    return InvoiceItemPayload(**payload)


def test_create_production_invoice_prices_and_totals(db):
    _seed_okki(db)
    _seed_pricing(db)
    price_service.upsert_customer_rule(
        db, customer_id="CUST001", customer_name="客户A",
        adjust_type="percent", adjust_value=Decimal("5"),
    )
    db.flush()

    body = InvoiceCreate(
        customer_id="CUST001",
        customer_name="客户A",
        order_type="production",
        invoice_date=date(2026, 7, 7),
        shipping_fee=Decimal("43"),
        surcharge_name="Paypal Surcharge",
        surcharge_amount=Decimal("10"),
        items=[_custom_item()],
    )
    invoice = service.create_invoice(db, body, user_id=1)
    db.flush()

    item = invoice.items[0]
    assert item.item_type == "custom"
    assert item.custom_product_id is not None
    assert item.standard_price == Decimal("20.1828")
    assert item.customer_price == Decimal("21.1919")
    assert item.price_per_piece == Decimal("21.1919")
    assert item.price_source == "customer_rule"
    assert invoice.product_amount == Decimal("105.96")
    assert invoice.total_amount == Decimal("158.96")


def test_manual_price_override_is_flagged(db):
    _seed_okki(db)
    _seed_pricing(db)
    body = InvoiceCreate(
        customer_id="CUST002",
        customer_name="客户B",
        order_type="production",
        invoice_date=date(2026, 7, 7),
        items=[_custom_item(price_per_piece=Decimal("30"))],
    )
    invoice = service.create_invoice(db, body, user_id=1)
    db.flush()

    item = invoice.items[0]
    assert item.customer_price == Decimal("20.1828")  # no rule -> std
    assert item.price_per_piece == Decimal("30")
    assert item.price_source == "manual"
    assert invoice.total_amount == Decimal("150.00")


def test_missing_std_price_is_flagged_not_blocking(db):
    _seed_okki(db)
    body = InvoiceCreate(
        customer_id="CUST003",
        customer_name="客户C",
        order_type="production",
        invoice_date=date(2026, 7, 7),
        items=[_custom_item(color="Cookies Cream", price_per_piece=Decimal("50"))],
    )
    invoice = service.create_invoice(db, body, user_id=1)
    db.flush()

    item = invoice.items[0]
    assert item.standard_price is None
    assert item.price_source == "missing_std"
    assert invoice.total_amount == Decimal("250.00")
    assert service.validate_invoice(invoice) == []  # D3: not blocking


# ── workbook import ───────────────────────────────────────────

def test_import_price_workbook(db):
    wb = Workbook()
    ws = wb.active
    ws.title = "价格表"
    ws.append(["Price List----Genius", None, None, None, None, None])
    ws.append(["Standard Double Drawn", None, None, None, None, None])
    ws.append(["Length", "Weight", "Solid Color", "Piano color", "Ombre rooted color", "Balayage color"])
    ws.append(['16"', "20g", 17.2155, 17.8455, 18.8955, 19.5255])
    ws.append(['18"', "20g", 23.799, 24.429, 25.479, 26.109])

    ws2 = wb.create_sheet("颜色对照表")
    ws2.append(["Solid colors", "Piano color", "Ombre rooted color", "Balayage color"])
    ws2.append(["#1", "#P2/8", "#4T60", "#2TP2/6"])
    ws2.append(["#1B", None, None, "Cookies Cream"])

    stream = BytesIO()
    wb.save(stream)

    result = price_service.import_price_workbook(db, stream.getvalue())
    db.flush()
    assert result["prices_imported"] == 8
    assert result["colors_imported"] == 6
    assert result["skipped"] == []

    resolved = price_service.resolve_price(
        db, customer_id=None,
        product_display="Standard Double Drawn Genius Weft",
        length="18", unit="20g", color="Cookies Cream",
    )
    # display 'Standard Double Drawn Genius Weft' vs series 'Standard Double Drawn Genius':
    # series is a prefix of the display, so the matrix row is found
    assert resolved["standard_price"] == Decimal("26.109")
    assert resolved["color_type"] == "balayage"
