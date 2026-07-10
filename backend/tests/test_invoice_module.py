from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.invoice import export_service, product_service, service, xiaoman_service
from app.invoice.models import Invoice, InvoiceItem, XiaomanSettings  # noqa: F401 - register metadata for test create_all
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

# ── OKKI push settings ────────────────────────────────────────

def _base_settings_kwargs(**overrides):
    kwargs = dict(
        generic_product_no=None,
        generic_sku_id=None,
        default_order_status=None,
        default_currency="USD",
        access_token=None,
        token_expires_at=None,
        user_id=1,
    )
    kwargs.update(overrides)
    return kwargs


def test_xiaoman_settings_defaults_and_token_semantics(db):
    # 未初始化时返回默认结构，不隐式建行
    assert xiaoman_service.get_settings_row(db) is None
    default = xiaoman_service.serialize_settings(None)
    assert default["has_token"] is False
    assert default["default_currency"] == "USD"

    # 写入 token → 只回掩码；手动覆盖的过期时间不信表单残值，按刚签发 8h 计
    from datetime import timedelta

    expires = datetime(2026, 12, 31, 23, 59, 59)
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(
        access_token="tok_1234567890abcdef", token_expires_at=expires,
        default_order_status="待确认",
    ))
    db.commit()
    data = xiaoman_service.serialize_settings(row)
    assert data["has_token"] is True
    assert data["access_token_masked"] == "tok_****cdef"
    assert "tok_1234567890abcdef" not in str(data)
    assert row.token_expires_at > datetime.utcnow() + timedelta(hours=7)

    # access_token=None → 保持不变
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(
        access_token=None, token_expires_at=expires,
    ))
    db.commit()
    assert row.access_token == "tok_1234567890abcdef"

    # access_token="" → 清除，过期时间联动清空
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(
        access_token="", token_expires_at=expires,
    ))
    db.commit()
    assert row.access_token is None
    assert row.token_expires_at is None

    # 始终单行
    assert db.query(XiaomanSettings).count() == 1


def test_xiaoman_settings_generic_product_resolution(db):
    _seed_products(db)

    # 唯一 SKU 自动关联
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(generic_product_no="P001"))
    db.commit()
    assert row.generic_product_id == 1
    assert row.generic_sku_id == 9001

    # 不存在的产品编号拒绝保存
    with pytest.raises(ValueError):
        xiaoman_service.update_settings(db, **_base_settings_kwargs(generic_product_no="NOPE"))

    # SKU 不属于该产品拒绝保存
    with pytest.raises(ValueError):
        xiaoman_service.update_settings(db, **_base_settings_kwargs(
            generic_product_no="P001", generic_sku_id=9002,
        ))

    # 多 SKU 且未指定时不猜测
    db.execute(text("INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag) VALUES (1, 9010, 0)"))
    db.commit()
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(generic_product_no="P001"))
    db.commit()
    assert row.generic_sku_id is None
    resolved = xiaoman_service.resolve_generic_product(db, "P001")
    assert resolved["skus"] == [9001, 9010]

    # 指定合法 SKU 通过
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(
        generic_product_no="P001", generic_sku_id=9010,
    ))
    db.commit()
    assert row.generic_sku_id == 9010

    # 清空产品编号 → 关联 ID 全部清空
    row = xiaoman_service.update_settings(db, **_base_settings_kwargs(generic_product_no="  "))
    db.commit()
    assert row.generic_product_no is None
    assert row.generic_product_id is None
    assert row.generic_sku_id is None
