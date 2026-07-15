"""订单发票 — 金额计算与校验回归测试

覆盖 app/invoice/service.py：
- _money: 两位小数 ROUND_HALF_UP
- 明细行 total_price = quantity × price_per_piece + 行级折扣
- 发票 total_amount = Σ 明细 total_price + 订单折扣 + 包装费 + 运费 + 手续费
- validate_invoice 对数量/单价的金额校验
- update_invoice 重算金额
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.invoice import service
from app.invoice.models import Invoice, InvoiceItem, StdPrice  # noqa: F401 - register metadata for create_all
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload, InvoiceUpdate


def _item(quantity: int, price, **overrides) -> InvoiceItemPayload:
    base = dict(
        product_id=1,
        sku_id=9001,
        product_name="Raw Hair/Body Wave",
        product_display="Raw Hair",
        net_weight_grams="100g",
        curl="Body Wave",
        model="M1",
        color="Natural",
        length="18",
        quantity=quantity,
        price_per_piece=price,
    )
    base.update(overrides)
    return InvoiceItemPayload(**base)


def _create(db, items, **header_overrides) -> Invoice:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY, name TEXT, model TEXT, color TEXT,
            size TEXT, unit TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_product_skus (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT OR IGNORE INTO lsordertest.okki_products
            (product_id, name, color, size, unit, disable_flag)
        VALUES (1, 'Raw Hair/Body Wave', 'Natural', '18', '100g', 0)
    """))
    exists = db.execute(text("""
        SELECT 1 FROM lsordertest.okki_inventory WHERE product_id = 1 AND sku_id = 9001
    """)).first()
    if not exists:
        db.execute(text("""
            INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
            VALUES (1, 9001, 0)
        """))
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 3),
        items=items,
        **header_overrides,
    )
    invoice = service.create_invoice(db, payload, user_id=1)
    db.flush()
    return invoice


def _seed_accessory_for_amounts(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY, name TEXT, model TEXT, color TEXT,
            size TEXT, unit TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_product_skus (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
            (product_id, name, model, color, size, unit, disable_flag)
        VALUES (2, 'Hair Gripper', 'Magic Tape', 'Black', NULL, NULL, 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (2, 9002, 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_product_skus (product_id, sku_id, disable_flag)
        VALUES (2, 9002, 0)
    """))
    db.add(StdPrice(
        product_kind="accessory",
        product_id=2,
        sku_id=9002,
        accessory_name="Hair Gripper",
        accessory_model="Magic Tape",
        accessory_color="Black",
        price=Decimal("15.0000"),
        currency="USD",
    ))
    db.flush()


class TestMoneyRounding:
    def test_half_up_at_third_decimal(self):
        assert service._money(Decimal("1.005")) == Decimal("1.01")
        assert service._money(Decimal("2.675")) == Decimal("2.68")

    def test_round_down(self):
        assert service._money(Decimal("1.004")) == Decimal("1.00")

    def test_two_decimal_normalization(self):
        assert str(service._money(Decimal("5"))) == "5.00"


class TestLineAndInvoiceTotals:
    def test_line_total_is_quantity_times_price(self, db):
        invoice = _create(db, [_item(3, Decimal("12.50"))])
        assert invoice.items[0].total_price == Decimal("37.50")
        assert invoice.total_amount == Decimal("37.50")

    def test_multi_line_sum(self, db):
        invoice = _create(db, [
            _item(2, Decimal("9.99")),
            _item(1, Decimal("0.01")),
        ])
        assert invoice.items[0].total_price == Decimal("19.98")
        assert invoice.items[1].total_price == Decimal("0.01")
        assert invoice.total_amount == Decimal("19.99")

    def test_line_total_rounded_half_up(self, db):
        # 3 × 1.335 = 4.005 → 4.01（逐行取整后再汇总）
        invoice = _create(db, [_item(3, Decimal("1.335"))])
        assert invoice.items[0].total_price == Decimal("4.01")
        assert invoice.total_amount == Decimal("4.01")

    def test_missing_price_counts_as_zero_and_blocks_ready(self, db):
        invoice = _create(db, [_item(5, None)])
        assert invoice.items[0].total_price == Decimal("0.00")
        assert invoice.total_amount == Decimal("0.00")
        # 单价缺失 → 校验不通过 → 状态停留 draft
        assert invoice.status == "draft"
        issues = service.validate_invoice(invoice)
        assert any("Price/Piece" in i["message"] for i in issues)

    def test_valid_invoice_becomes_ready(self, db):
        invoice = _create(db, [_item(1, Decimal("10.00"))])
        assert invoice.status == "ready"
        assert service.validate_invoice(invoice) == []

    def test_update_recalculates_totals(self, db):
        invoice = _create(db, [_item(3, Decimal("12.50"))])
        assert invoice.total_amount == Decimal("37.50")

        update = InvoiceUpdate(
            customer_id="CUST001",
            customer_name="Customer A",
            invoice_date=date(2026, 7, 3),
            items=[_item(10, Decimal("2.00"))],
        )
        service.update_invoice(db, invoice, update, user_id=1)
        db.flush()
        assert len(invoice.items) == 1
        assert invoice.total_amount == Decimal("20.00")

    def test_line_discount_is_normalized_negative_and_reduces_total(self, db):
        invoice = _create(db, [_item(2, Decimal("10.00"), discount_amount=Decimal("5.00"))])

        assert invoice.items[0].discount_amount == Decimal("-5.00")
        assert invoice.items[0].total_price == Decimal("15.00")
        assert invoice.product_amount == Decimal("15.00")
        assert invoice.total_amount == Decimal("15.00")

    def test_invoice_total_uses_line_discount_once_and_persists_packaging_quantity(self, db):
        invoice = _create(
            db,
            [_item(2, Decimal("50.00"), discount_amount=Decimal("-10.00"))],
            internal_discount=Decimal("5.00"),
            internal_accessory=Decimal("3.00"),
            packaging_quantity=4,
            shipping_fee=Decimal("7.00"),
            surcharge_amount=Decimal("2.00"),
            internal_received=Decimal("20.00"),
            internal_balance=Decimal("82.00"),
        )

        assert invoice.product_amount == Decimal("90.00")
        assert invoice.internal_discount == Decimal("-10.00")
        assert invoice.packaging_quantity == 4
        assert invoice.total_amount == Decimal("102.00")
        assert invoice.internal_balance == Decimal("82.00")

    def test_mixed_hair_accessory_totals_roundtrip_and_balance_refresh(self, db):
        _seed_accessory_for_amounts(db)
        hair = _item(1, Decimal("100.00"), discount_amount=Decimal("-10.00"))
        accessory = _item(
            2,
            Decimal("15.00"),
            product_kind="accessory",
            product_id=2,
            sku_id=9002,
            product_name="Hair Gripper",
            product_display="Hair Gripper",
            model="Magic Tape",
            color="Black",
            length=None,
            net_weight_grams=None,
            curl=None,
            discount_amount=Decimal("-2.00"),
        )
        invoice = _create(
            db,
            [hair, accessory],
            internal_accessory=Decimal("3.00"),
            packaging_quantity=4,
            shipping_fee=Decimal("7.00"),
            surcharge_amount=Decimal("2.00"),
            internal_received=Decimal("20.00"),
            internal_balance=Decimal("0.00"),
        )

        assert service.summarize_items(invoice) == {
            "hair_amount": Decimal("100.00"),
            "hair_discount": Decimal("-10.00"),
            "accessory_amount": Decimal("30.00"),
            "accessory_discount": Decimal("-2.00"),
        }
        assert invoice.product_amount == Decimal("118.00")
        assert invoice.total_amount == Decimal("130.00")
        assert invoice.internal_discount == Decimal("-10.00")
        assert invoice.internal_balance == Decimal("110.00")
        detail = service.serialize_detail(invoice)
        assert detail["hair_amount"] == Decimal("100.00")
        assert detail["hair_discount"] == Decimal("-10.00")
        assert detail["accessory_amount"] == Decimal("30.00")
        assert detail["accessory_discount"] == Decimal("-2.00")
        assert [item["product_kind"] for item in detail["items"]] == ["hair", "accessory"]

        updated_accessory = accessory.model_copy(update={
            "quantity": 2,
            "price_per_piece": Decimal("20.00"),
            "discount_amount": Decimal("-5.00"),
        })
        service.update_invoice(
            db,
            invoice,
            InvoiceUpdate(
                customer_id="CUST001",
                customer_name="Customer A",
                invoice_date=date(2026, 7, 3),
                internal_accessory=Decimal("3.00"),
                packaging_quantity=4,
                shipping_fee=Decimal("7.00"),
                surcharge_amount=Decimal("2.00"),
                internal_received=Decimal("20.00"),
                internal_balance=Decimal("110.00"),
                items=[hair, updated_accessory],
            ),
            user_id=1,
        )

        assert invoice.product_amount == Decimal("125.00")
        assert invoice.total_amount == Decimal("137.00")
        assert invoice.internal_discount == Decimal("-10.00")
        assert invoice.internal_balance == Decimal("117.00")

    def test_four_decimal_unit_price_uses_extended_line_rounding_for_saved_settlement(self, db):
        _seed_accessory_for_amounts(db)
        hair = _item(1, Decimal("10.0050"))
        accessory = _item(
            10,
            Decimal("2.7550"),
            product_kind="accessory",
            product_id=2,
            sku_id=9002,
            product_name="Hair Gripper",
            product_display="Hair Gripper",
            model="Magic Tape",
            color="Black",
            length=None,
            net_weight_grams=None,
            curl=None,
            discount_amount=Decimal("-1.00"),
        )

        invoice = _create(
            db,
            [hair, accessory],
            internal_received=Decimal("20.01"),
            internal_balance=Decimal("0.00"),
        )

        assert service.summarize_items(invoice) == {
            "hair_amount": Decimal("10.01"),
            "hair_discount": Decimal("0.00"),
            "accessory_amount": Decimal("27.55"),
            "accessory_discount": Decimal("-1.00"),
        }
        assert invoice.items[1].total_price == Decimal("26.55")
        assert invoice.product_amount == Decimal("36.56")
        assert invoice.total_amount == Decimal("36.56")
        assert invoice.internal_received == Decimal("20.01")
        assert invoice.internal_balance == Decimal("16.55")

    def test_line_discount_cannot_exceed_gross_line_amount(self, db):
        import pytest

        with pytest.raises(ValueError, match="产品行折扣不能超过该行金额"):
            _create(db, [_item(1, Decimal("10.00"), discount_amount=Decimal("-10.01"))])


class TestInternalSettlement:
    def test_prepayment_and_balance_must_equal_grand_total(self, db):
        invoice = _create(
            db,
            [_item(1, Decimal("90.00"))],
            shipping_fee=Decimal("8.00"),
            surcharge_amount=Decimal("2.00"),
            internal_received=Decimal("30.00"),
            internal_balance=Decimal("70.00"),
        )
        assert invoice.total_amount == Decimal("100.00")
        assert invoice.internal_received == Decimal("30.00")
        assert invoice.internal_balance == Decimal("70.00")

    def test_stale_balance_is_recalculated_from_prepayment(self, db):
        invoice = _create(
            db,
            [_item(1, Decimal("100.00"))],
            internal_received=Decimal("30.00"),
            internal_balance=Decimal("60.00"),
        )
        assert invoice.internal_balance == Decimal("70.00")

    def test_balance_is_derived_when_only_prepayment_is_entered(self, db):
        invoice = _create(
            db,
            [_item(1, Decimal("100.00"))],
            internal_received=Decimal("30.00"),
        )
        assert invoice.internal_balance == Decimal("70.00")

    def test_excessive_prepayment_is_rejected_by_schema(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InvoiceCreate(
                customer_id="CUST001",
                customer_name="Customer A",
                invoice_date=date(2026, 7, 3),
                internal_received=Decimal("-0.01"),
                items=[_item(1, Decimal("100.00"))],
            )


class TestValidateAmounts:
    """validate_invoice 直接作用于 ORM 对象，可绕过 Pydantic gt=0 约束测边界"""

    def _orm_invoice(self, quantity, price) -> Invoice:
        invoice = Invoice(
            customer_id="CUST001",
            customer_name="Customer A",
            invoice_date=date(2026, 7, 3),
        )
        invoice.items.append(InvoiceItem(
            sort_order=1,
            product_id=1,
            sku_id=9001,
            product_name="Raw Hair/Body Wave",
            product_display="Raw Hair",
            net_weight_grams="100g",
            model="M1",
            color="Natural",
            length="18",
            quantity=quantity,
            price_per_piece=price,
            total_price=Decimal("0.00"),
        ))
        return invoice

    def test_zero_quantity_rejected(self):
        issues = service.validate_invoice(self._orm_invoice(0, Decimal("1.00")))
        assert any("Quantity" in i["message"] for i in issues)

    def test_negative_quantity_rejected(self):
        issues = service.validate_invoice(self._orm_invoice(-1, Decimal("1.00")))
        assert any("Quantity" in i["message"] for i in issues)

    def test_zero_price_rejected(self):
        issues = service.validate_invoice(self._orm_invoice(1, Decimal("0")))
        assert any("Price/Piece" in i["message"] for i in issues)

    def test_valid_amounts_pass(self):
        assert service.validate_invoice(self._orm_invoice(1, Decimal("0.01"))) == []

    def test_empty_items_rejected(self):
        invoice = Invoice(
            customer_id="CUST001",
            customer_name="Customer A",
            invoice_date=date(2026, 7, 3),
        )
        issues = service.validate_invoice(invoice)
        assert any(i["field"] == "items" for i in issues)
