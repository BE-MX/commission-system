"""Invoice clipboard import preview tests."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.invoice import import_service, price_service, product_service, service
from app.invoice.models import CustomProduct  # noqa: F401 - register table in test metadata
from app.invoice.models import StdPrice
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


@contextmanager
def api_client(db, *, permissions):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": "5",
        "username": "invoice-import-test",
        "roles": [],
        "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def valid_row(**overrides):
    row = {
        "source_row": 2,
        "product": "Standard Double Drawn Genius Weft",
        "length": "18",
        "color": "#1B",
        "weight": "100g",
        "quantity": 2,
        "unit_price": "36.00",
    }
    row.update(overrides)
    return row


def test_normalize_import_row_accepts_historical_formats():
    row = import_service.normalize_row(valid_row(
        product="  Standard  Double Drawn Genius Weft ",
        length="18 inch",
        color=" #1b ",
        weight="0.1kg",
    ))

    assert row == {
        "source_row": 2,
        "product": "Standard Double Drawn Genius Weft",
        "length": "18",
        "color": "#1B",
        "weight": "100g",
        "quantity": 2,
        "unit_price": Decimal("36.00"),
    }


@pytest.mark.parametrize(("raw", "expected"), [
    ("37.5g", "37.5g"),
    ("37.50", "37.5g"),
    ("0.0375kg", "37.5g"),
    ("100.00g", "100g"),
    ("0.5g", "0.5g"),
])
def test_normalize_import_row_accepts_decimal_weight(raw, expected):
    row = import_service.normalize_row(valid_row(weight=raw))
    assert row["weight"] == expected


@pytest.mark.parametrize(("field", "value"), [
    ("quantity", 0),
    ("quantity", 1.5),
    ("quantity", True),
    ("unit_price", "0"),
    ("weight", "abc"),
])
def test_normalize_import_row_rejects_invalid_values(field, value):
    with pytest.raises(ValueError):
        import_service.normalize_row(valid_row(**{field: value}))


def test_normalize_rows_rejects_empty_and_over_limit_batches():
    with pytest.raises(ValueError, match="至少包含 1 行"):
        import_service.normalize_rows([])
    with pytest.raises(ValueError, match="最多导入 200 行"):
        import_service.normalize_rows([valid_row(source_row=index + 1) for index in range(201)])


def test_invoice_currency_is_normalized_and_rejects_non_three_letter_codes():
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 14),
        currency=" eur ",
    )
    assert payload.currency == "EUR"

    with pytest.raises(ValidationError):
        InvoiceCreate(
            customer_id="CUST001",
            customer_name="Customer A",
            invoice_date=date(2026, 7, 14),
            currency="USDD",
        )


def test_batch_fingerprint_is_stable_and_ignores_mapping_order():
    row = import_service.normalize_row(valid_row())
    reordered = dict(reversed(list(row.items())))

    assert import_service.make_batch_fingerprint([row]) == import_service.make_batch_fingerprint([reordered])


def seed_okki_products(db, rows):
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
    for product_id, name, color, size, unit, sku_id in rows:
        db.execute(text("""
            INSERT INTO lsordertest.okki_products
                (product_id, product_no, name, model, color, size, unit, disable_flag)
            VALUES (:product_id, :product_no, :name, '', :color, :size, :unit, 0)
        """), {
            "product_id": product_id,
            "product_no": f"P{product_id}",
            "name": name,
            "color": color,
            "size": size,
            "unit": unit,
        })
        if sku_id is not None:
            db.execute(text("""
                INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
                VALUES (:product_id, :sku_id, 0)
            """), {"product_id": product_id, "sku_id": sku_id})
    db.commit()


def test_preview_import_uniquely_matches_product_and_sku(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db)

    result = import_service.preview_import(
        db,
        customer_id="CUST001",
        order_type="stock",
        currency="USD",
        raw_rows=[valid_row()],
    )

    row = result["rows"][0]
    assert row["matched_product"]["product_id"] == 11
    assert row["matched_product"]["sku_id"] == 9011
    assert row["status"] == "passed"
    assert result["summary"] == {"total": 1, "passed": 1, "warning": 0, "blocked": 0}


def test_preview_import_blocks_ambiguous_products_with_candidates(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
        (12, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9012),
    ])

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["status"] == "blocked"
    assert row["matched_product"] is None
    assert [item["product_id"] for item in row["candidates"]] == [11, 12]
    assert "找到 2 个产品" in row["errors"][0]


def test_preview_import_blocks_multiple_skus_for_one_product(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (11, 9012, 0)
    """))
    db.commit()

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["status"] == "blocked"
    assert row["matched_product"] is None
    assert [(item["product_id"], item["sku_id"]) for item in row["candidates"]] == [
        (11, 9011), (11, 9012),
    ]


@pytest.mark.parametrize("sku_id", [None])
def test_preview_import_blocks_stock_product_without_sku(db, sku_id):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", sku_id),
    ])

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["status"] == "blocked"
    assert "SKU" in row["errors"][0]


def test_preview_import_allows_explicit_custom_path_only_for_production(db):
    seed_okki_products(db, [])

    stock = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]
    production = import_service.preview_import(
        db, customer_id="CUST001", order_type="production", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert stock["status"] == "blocked"
    assert stock["can_create_custom"] is False
    assert production["status"] == "blocked"
    assert production["can_create_custom"] is True
    assert db.query(CustomProduct).count() == 0


def test_preview_import_returns_field_errors_without_aborting_valid_rows(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])

    result = import_service.preview_import(
        db,
        customer_id="CUST001",
        order_type="stock",
        currency="USD",
        raw_rows=[valid_row(), valid_row(source_row=3, quantity="half")],
    )

    assert result["rows"][0]["matched_product"]["sku_id"] == 9011
    assert result["rows"][1]["status"] == "blocked"
    assert result["rows"][1]["source_row"] == 3
    assert "quantity 必须是正整数" in result["rows"][1]["errors"][0]
    assert result["summary"] == {"total": 2, "passed": 0, "warning": 1, "blocked": 1}


def seed_standard_price(db, *, price="36.00", currency="USD"):
    db.add(StdPrice(
        series_grade="Standard Double Drawn Genius Weft",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal(price),
        currency=currency,
    ))
    db.commit()


def test_preview_import_keeps_excel_price_and_marks_customer_rule_when_equal(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db, price="36.00")

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["normalized"]["unit_price"] == Decimal("36.00")
    assert row["standard_price"] == Decimal("36.00")
    assert row["customer_price"] == Decimal("36.00")
    assert row["price_difference"] == Decimal("0.00")
    assert row["price_source"] == "customer_rule"
    assert row["status"] == "passed"


def test_preview_import_warns_but_preserves_different_excel_price(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db, price="36.00")

    row = import_service.preview_import(
        db,
        customer_id="CUST001",
        order_type="stock",
        currency="USD",
        raw_rows=[valid_row(unit_price="34.00")],
    )["rows"][0]

    assert row["normalized"]["unit_price"] == Decimal("34.00")
    assert row["customer_price"] == Decimal("36.00")
    assert row["price_difference"] == Decimal("-2.00")
    assert row["price_source"] == "manual"
    assert row["status"] == "warning"
    assert "保留 Excel 成交价" in row["warnings"][0]


def test_preview_import_marks_missing_standard_price_as_warning(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="USD", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["customer_price"] is None
    assert row["price_difference"] is None
    assert row["price_source"] == "missing_std"
    assert row["status"] == "warning"
    assert "没有可用的 USD 系统价格" in row["warnings"][0]


def test_preview_import_does_not_compare_cross_currency_prices(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db, price="36.00", currency="USD")

    row = import_service.preview_import(
        db, customer_id="CUST001", order_type="stock", currency="EUR", raw_rows=[valid_row()],
    )["rows"][0]

    assert row["standard_price"] is None
    assert row["customer_price"] is None
    assert row["price_difference"] is None
    assert row["price_source"] == "missing_std"
    assert row["status"] == "warning"
    assert "系统价格币种为 USD" in row["warnings"][0]
    assert "无法直接比较" in row["warnings"][0]


def test_save_does_not_compare_cross_currency_price(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db, price="36.00", currency="USD")
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        order_type="stock",
        invoice_date=date(2026, 7, 14),
        currency="EUR",
        items=[InvoiceItemPayload(
            item_type="stock",
            product_id=11,
            sku_id=9011,
            product_name="Standard Double Drawn Genius Weft/18/#1B/100g",
            product_display="Standard Double Drawn Genius Weft",
            net_weight_grams="100g",
            color="#1B",
            length="18",
            quantity=2,
            price_per_piece=Decimal("34.00"),
        )],
    )

    invoice = service.create_invoice(db, payload, user_id=1)
    item = invoice.items[0]

    assert item.price_per_piece == Decimal("34.00")
    assert item.standard_price is None
    assert item.customer_price is None
    assert item.price_source == "missing_std"


def test_save_rejects_custom_lines_on_stock_invoice(db):
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        order_type="stock",
        invoice_date=date(2026, 7, 14),
        items=[InvoiceItemPayload(
            item_type="custom",
            product_display="Custom Weft",
            net_weight_grams="100g",
            color="#1B",
            length="18",
            quantity=1,
            price_per_piece=Decimal("34.00"),
        )],
    )

    with pytest.raises(ValueError, match="库存单不能包含定制产品"):
        service.create_invoice(db, payload, user_id=1)


def test_save_rejects_mismatched_product_sku_pair(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        order_type="stock",
        invoice_date=date(2026, 7, 14),
        items=[InvoiceItemPayload(
            item_type="stock",
            product_id=11,
            sku_id=9999,
            product_name="Standard Double Drawn Genius Weft/18/#1B/100g",
            product_display="Standard Double Drawn Genius Weft",
            net_weight_grams="100g",
            color="#1B",
            length="18",
            quantity=1,
            price_per_piece=Decimal("34.00"),
        )],
    )

    with pytest.raises(ValueError, match="产品与 SKU 不匹配"):
        service.create_invoice(db, payload, user_id=1)


def test_production_custom_save_loads_full_okki_projection(db, monkeypatch):
    captured = {}

    def fake_load(_db, *, limit=10000):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(product_service, "load_okki_rows", fake_load)
    monkeypatch.setattr(product_service, "ensure_custom_product", lambda *_args, **_kwargs: {
        "custom_product_id": None,
        "product_id": None,
        "sku_id": None,
        "product_name": "",
        "source": "custom",
    })
    monkeypatch.setattr(price_service, "resolve_price", lambda *_args, **_kwargs: {
        "standard_price": None,
        "customer_price": None,
        "currency": "USD",
        "color_type_source": "",
    })
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        order_type="production",
        invoice_date=date(2026, 7, 14),
        items=[InvoiceItemPayload(
            item_type="custom",
            product_display="Custom Weft",
            net_weight_grams="100g",
            color="#1B",
            length="18",
            quantity=1,
            price_per_piece=Decimal("34.00"),
        )],
    )

    service.create_invoice(db, payload, user_id=1)

    assert captured["limit"] is None


def test_import_preview_endpoint_requires_write_permission(db):
    seed_okki_products(db, [])
    body = {
        "customer_id": "CUST001",
        "order_type": "production",
        "currency": "USD",
        "rows": [valid_row()],
    }

    with api_client(db, permissions=["invoice:read"]) as client:
        assert client.post("/api/invoice/import/preview", json=body).status_code == 403


def test_import_preview_endpoint_returns_unified_envelope(db):
    seed_okki_products(db, [
        (11, "Standard Double Drawn Genius Weft/18/#1B/100g", "#1B", "18", "100g", 9011),
    ])
    seed_standard_price(db)
    body = {
        "customer_id": "CUST001",
        "order_type": "stock",
        "currency": "USD",
        "rows": [valid_row()],
    }

    with api_client(db, permissions=["invoice:write"]) as client:
        response = client.post("/api/invoice/import/preview", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["summary"]["passed"] == 1
    assert payload["data"]["rows"][0]["matched_product"]["product_id"] == 11


def test_import_preview_endpoint_returns_invalid_row_as_blocked(db):
    body = {
        "customer_id": "CUST001",
        "order_type": "stock",
        "currency": "USD",
        "rows": [valid_row(quantity="half")],
    }

    with api_client(db, permissions=["invoice:write"]) as client:
        response = client.post("/api/invoice/import/preview", json=body)

    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["status"] == "blocked"


def test_import_preview_endpoint_rejects_more_than_200_rows(db):
    body = {
        "customer_id": "CUST001",
        "order_type": "stock",
        "currency": "USD",
        "rows": [valid_row(source_row=index + 1) for index in range(201)],
    }

    with api_client(db, permissions=["invoice:write"]) as client:
        response = client.post("/api/invoice/import/preview", json=body)

    assert response.status_code == 422
