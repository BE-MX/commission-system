from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.invoice import export_service, product_service, service
from app.invoice.models import Invoice, InvoiceItem  # noqa: F401 - register metadata for test create_all
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


def _seed_products(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT,
            name TEXT,
            model TEXT,
            color TEXT,
            size TEXT,
            unit TEXT,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER,
            sku_id INTEGER,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
        (product_id, product_no, name, model, color, size, unit, disable_flag)
        VALUES
        (1, 'P001', 'Raw Hair/Body Wave', 'M1', 'Natural', '18', '100g', 0),
        (2, 'P002', 'Raw Hair/Straight', 'M1', 'Natural', '20', '100g', 0),
        (3, 'P003', 'Raw Hair/Body Wave', 'M2', 'Piano', '18', '120g', 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (1, 9001, 0), (2, 9002, 0), (3, 9003, 0)
    """))
    db.commit()


def test_product_filter_options_and_unique_match(db):
    _seed_products(db)

    options = product_service.get_filter_options(db, model="M1", color="Natural")
    assert options["models"] == ["M1"]
    assert options["colors"] == ["Natural"]
    assert options["sizes"] == ["18", "20"]
    assert options["units"] == ["100g"]

    match = product_service.match_product(db, model="M1", color="Natural", size="18", unit="100g")
    assert match["is_unique"] is True
    assert match["item"]["product_id"] == 1
    assert match["item"]["sku_id"] == 9001
    assert match["item"]["product_name"] == "Raw Hair/Body Wave"
    assert match["item"]["product_display"] == "Raw Hair"


def test_invoice_create_totals_and_validation(db):
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 2),
        items=[
            InvoiceItemPayload(
                product_id=1,
                sku_id=9001,
                product_name="Raw Hair/Body Wave",
                product_display="Raw Hair",
                net_weight_grams="100g",
                curl="Body Wave",
                model="M1",
                color="Natural",
                length="18",
                quantity=3,
                price_per_piece=Decimal("12.50"),
            )
        ],
    )

    invoice = service.create_invoice(db, payload, user_id=1)
    db.flush()

    assert invoice.total_amount == Decimal("37.50")
    assert invoice.status == "ready"
    assert service.validate_invoice(invoice) == []
    assert export_service.build_invoice_pdf(invoice).getvalue().startswith(b"%PDF-1.4")
