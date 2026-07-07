"""订单发票 — 金额计算与校验回归测试

覆盖 app/invoice/service.py：
- _money: 两位小数 ROUND_HALF_UP
- 明细行 total_price = quantity × price_per_piece
- 发票 total_amount = Σ 明细 total_price
- validate_invoice 对数量/单价的金额校验
- update_invoice 重算金额
"""

from datetime import date
from decimal import Decimal

from app.invoice import service
from app.invoice.models import Invoice, InvoiceItem  # noqa: F401 - register metadata for create_all
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


def _create(db, items) -> Invoice:
    payload = InvoiceCreate(
        customer_id="CUST001",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 3),
        items=items,
    )
    invoice = service.create_invoice(db, payload, user_id=1)
    db.flush()
    return invoice


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
