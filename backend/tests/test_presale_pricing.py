from decimal import Decimal

import pytest

from app.invoice.settlement_pricing import quote_settlement, split_payment


def line(q=10, total="10000", shipped=0, requested=4):
    return dict(invoice_item_id=1, quantity=q, total_price=total,
                shipped_quantity=shipped, requested_quantity=requested)


def quote(lines=None, **kw):
    return quote_settlement(lines=lines or [line()], packaging="0", handling=kw.pop("handling", "0"),
                            deposit=kw.pop("deposit", "3000"), deposit_charge=kw.pop("deposit_charge", "0"), **kw)


def test_v2_two_deliveries():
    first = quote(freight="200")
    final = quote([line(shipped=4, requested=6)], freight="150")
    assert first["new_payment_due"] == "4200.00"
    assert first["deposit_applied"] == "0.00"
    assert final["new_payment_due"] == "3150.00"
    assert final["is_final"] is True


def test_v2_handling_and_frozen_deposit_charge():
    first = quote(handling="500", deposit="3150", deposit_charge="150", freight="200")
    final = quote([line(shipped=4, requested=6)], handling="500", deposit="3150", deposit_charge="150",
                  prior_handling=first["handling_amount"], freight="150")
    assert first["new_payment_due"] == "4400.00"
    assert first["goods_payment_charge"] == "200.00"
    assert final["new_payment_due"] == "3300.00"
    assert final["goods_payment_charge"] == "150.00"


def test_cumulative_line_rounding():
    parts = [quote([line(3, "10", shipped=k, requested=1)], deposit="0.01")["goods_amount"] for k in range(3)]
    assert parts == ["3.33", "3.34", "3.33"]


def test_zero_final_payment():
    result = quote([line(shipped=7, requested=3)])
    assert result["new_payment_due"] == "0.00"


def test_reserve_and_overquantity():
    with pytest.raises(ValueError, match="deposit"):
        quote([line(requested=8)])
    with pytest.raises(ValueError, match="quantity"):
        quote([line(requested=11)])


@pytest.mark.parametrize("bad", ["NaN", "Infinity", True, "-1", "0.001"])
def test_invalid_money(bad):
    with pytest.raises(ValueError):
        quote(freight=bad)


@pytest.mark.parametrize("bad", [True, "1.5", -1, 1.0])
def test_invalid_quantity(bad):
    with pytest.raises(ValueError):
        quote([line(requested=bad)])


def test_packaging_cumulative_and_fee_reserve():
    first = quote_settlement([line(3, "10", requested=1)], packaging="1", handling="1", deposit="1", deposit_charge="0.8")
    assert first["packaging_amount"] == "0.33"
    assert first["handling_amount"] == "0.20"
    final = quote_settlement([line(3, "10", shipped=1, requested=2)], packaging="1", handling="1", deposit="1", deposit_charge="0.8",
                             prior_packaging="0.33", prior_handling="0.20")
    assert final["packaging_amount"] == "0.67"
    assert final["handling_amount"] == "0.80"


def test_payment_largest_remainder_and_final_fee():
    first = split_payment("0.01", "0.01", "0.01", "0.01")
    assert first == dict(goods_amount=Decimal("0.01"), freight_amount=Decimal("0.00"), charge_amount=Decimal("0.01"))
    assert split_payment("10", "9", "1", "0.13")["charge_amount"] == Decimal("0.13")


def test_payment_overpay_and_fee_bounds():
    with pytest.raises(ValueError):
        split_payment("11", "9", "1", "0")
    with pytest.raises(ValueError):
        split_payment("1", "1", "1", "2")


def test_unrequested_line_prevents_final_and_discount_is_frozen():
    second = dict(line(q=1, total="10", requested=0), invoice_item_id=2)
    result = quote([line(q=1, total="7", requested=1), second], deposit="5")
    assert result["goods_amount"] == "7.00"
    assert result["is_final"] is False
    assert result["items"] == [dict(invoice_item_id=1, quantity=1, line_amount="7.00")]


def test_prior_allocations_and_duplicate_lines_rejected():
    with pytest.raises(ValueError, match="Prior"):
        quote(prior_packaging="1")
    with pytest.raises(ValueError, match="Duplicate"):
        quote([line(), line()])
    with pytest.raises(ValueError, match="positive"):
        quote([line(requested=0)])


def test_repeated_small_payments_conserve_all_components():
    goods, freight, fee = Decimal("1.17"), Decimal("0.23"), Decimal("0.19")
    allocated_goods = allocated_freight = allocated_fee = Decimal("0")
    while goods + freight:
        parts = split_payment(min(Decimal("0.07"), goods + freight), goods, freight, fee)
        assert Decimal("0") <= parts["charge_amount"] <= parts["goods_amount"]
        goods -= parts["goods_amount"]
        freight -= parts["freight_amount"]
        fee -= parts["charge_amount"]
        allocated_goods += parts["goods_amount"]
        allocated_freight += parts["freight_amount"]
        allocated_fee += parts["charge_amount"]
    assert (allocated_goods, allocated_freight, allocated_fee) == (Decimal("1.17"), Decimal("0.23"), Decimal("0.19"))
    assert fee == 0
