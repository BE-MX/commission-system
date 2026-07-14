"""Invoice clipboard import preview tests."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.invoice import import_service
from app.invoice.models import CustomProduct  # noqa: F401 - register table in test metadata


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
