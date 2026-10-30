from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.sales_return.policy import price
from app.sales_return.schemas import Draft


def snapshot(paid="1000"):
    return {"order_id": "o1", "order_no": "ORDER", "customer_id": "c1", "customer_name": "Synthetic",
            "owner_okki_user_id": "owner", "invoice_id": None, "sales_user_id": None, "currency": "USD",
            "goods_amount": "1000", "goods_amount_usd": "1000", "gmv_eligible": True,
            "order_role": "repeat", "departments": [{"department_id": 1, "rate": 100}],
            "lines": [{"source_key": "out:line", "outbound_id": "out", "outbound_line_id": "line",
                       "order_line_id": "original", "product_id": "p", "sku_id": "sku",
                       "product_name": "Hair", "specification": "Demo", "quantity": 10,
                       "net_amount": "1000", "net_amount_usd": "1000"}],
            "payments": [{"payment_id": "original-payment", "currency": "USD", "principal": paid,
                          "principal_usd": paid, "collection_date": "2025-01-01"}] if Decimal(paid) else []}


def draft(amount="200", quantity=2, refund=None, **extra):
    return Draft(order_id="o1", return_type="return_refund", reason_code="quality", reason="verified damage",
                 lines=[{"source_key": "out:line", "quantity": quantity, "reduction_amount": amount}],
                 refund_amount=refund, **extra)


@pytest.mark.parametrize("paid,credit,qty,refund,waived,receivable,received,outstanding", [
    ("1000", "200", 2, "200", "0", "800", "800", "0"),
    ("600", "1000", 10, "600", "400", "0", "0", "0"),
    ("600", "200", 2, "0", "200", "800", "600", "200"),
    ("0", "1000", 10, "0", "1000", "0", "0", "0"),
])
def test_goods_cash_waiver_are_distinct(paid, credit, qty, refund, waived, receivable, received, outstanding):
    quote = price(snapshot(paid), draft(credit, qty, refund))
    assert Decimal(quote["refund_amount"]) == Decimal(refund)
    assert Decimal(quote["waived_amount"]) == Decimal(waived)
    assert tuple(Decimal(quote["balance"][key]) for key in ("net_receivable", "net_received", "net_outstanding")) == tuple(map(Decimal, (receivable, received, outstanding)))


@pytest.mark.parametrize("paid,refund", [("1000", "200.00"), ("0", "0.00")])
def test_default_refund_and_explicit_value_have_same_quote_identity(paid, refund):
    implicit = price(snapshot(paid), draft())
    explicit = price(snapshot(paid), draft(refund=refund))
    assert implicit["quote_version"] == explicit["quote_version"]


def test_quantity_and_money_cumulative_limits_are_independent():
    history = {"quantities": {"out:line": 9}, "reductions": {"out:line": Decimal("900")},
               "reductions_usd": {"out:line": Decimal("900")}, "reduction_amount": Decimal("900"),
               "refunds": {"original-payment": Decimal("900")}, "refunds_usd": {"original-payment": Decimal("900")}}
    with pytest.raises(ValueError, match="数量"):
        price(snapshot(), draft(), history)
    assert price(snapshot(), draft("100", 1), history)["refund_amount"] == "100.00"
    with pytest.raises(ValueError, match="净货值"):
        price(snapshot(), draft("101", 1), history)


def test_refund_only_does_not_consume_physical_quantity():
    body = draft("100", 1)
    body.return_type = "refund_only"
    quote = price(snapshot(), body, {"quantities": {"out:line": 10}})
    assert quote["refund_amount"] == "100.00"


def test_fully_refunded_goods_may_be_physically_recovered_without_duplicate_cash():
    history = {"reductions": {"out:line": Decimal("1000")}, "reductions_usd": {"out:line": Decimal("1000")},
               "reduction_amount": Decimal("1000"), "refunds": {"original-payment": Decimal("1000")},
               "refunds_usd": {"original-payment": Decimal("1000")}}
    quote = price(snapshot(), draft("0", 10), history)
    assert Decimal(quote["refund_amount"]) == 0
    assert quote["allocations"] == []


def test_non_usd_cumulative_last_refund_absorbs_tail():
    source = snapshot("3")
    source.update(currency="EUR", goods_amount="3", goods_amount_usd="0.02")
    source["payments"][0].update(currency="EUR", principal_usd="0.02")
    source["lines"][0].update(quantity=3, net_amount="3", net_amount_usd="0.02")
    history = {"quantities": {"out:line": 2}, "reductions": {"out:line": Decimal("2")},
               "reductions_usd": {"out:line": Decimal("0.01")}, "reduction_amount": Decimal("2"),
               "refunds": {"original-payment": Decimal("2")}, "refunds_usd": {"original-payment": Decimal("0.01")}}
    quote = price(source, draft("1", 1), history)
    assert quote["reduction_usd"] == "0.01"
    assert quote["refund_usd"] == "0.01"


def test_last_physical_return_accepts_original_price_rounding_tail():
    source = snapshot("100")
    source.update(goods_amount="100", goods_amount_usd="100")
    source["lines"][0].update(quantity=3, net_amount="100", net_amount_usd="100")
    history = {"quantities": {"out:line": 2}, "physical_rounding": {"out:line": Decimal("100") * 2 / 3 - Decimal("66.66")},
               "reductions": {"out:line": Decimal("66.66")},
               "reductions_usd": {"out:line": Decimal("66.66")}, "reduction_amount": Decimal("66.66"),
               "refunds": {"original-payment": Decimal("66.66")}, "refunds_usd": {"original-payment": Decimal("66.66")}}
    quote = price(source, draft("33.34", 1), history)
    assert quote["refund_amount"] == "33.34"
    assert Decimal(quote["balance"]["net_outstanding"]) == 0


def test_prior_refund_only_does_not_consume_next_physical_piece_value():
    history = {"quantities": {}, "physical_reductions": {},
               "reductions": {"out:line": Decimal("500")}, "reductions_usd": {"out:line": Decimal("500")},
               "reduction_amount": Decimal("500"), "refunds": {"original-payment": Decimal("500")},
               "refunds_usd": {"original-payment": Decimal("500")}}
    assert price(snapshot(), draft("100", 1), history)["refund_amount"] == "100.00"


def test_presale_refund_cannot_use_batch_cash_beyond_its_selected_goods_value():
    source = snapshot()
    source["lines"] = [dict(source["lines"][0], net_amount="100", net_amount_usd="100", quantity=1),
                       dict(source["lines"][0], source_key="out2:line2", outbound_id="out2", outbound_line_id="line2",
                            order_line_id="original2", net_amount="900", net_amount_usd="900", quantity=9)]
    source["funding_batches"] = [{"settlement_id": 1, "outbound_id": "out"}, {"settlement_id": 2, "outbound_id": "out2"}]
    source["payments"][0].update(funding_limits=[{"settlement_id": 1, "amount": "1000"}], refundable_amount="1000")
    body = draft("100", 1)
    body.lines.append(type(body.lines[0])(source_key="out2:line2", quantity=9, reduction_amount="900"))
    with pytest.raises(ValueError, match="本金|资金"):
        price(source, body)


@pytest.mark.parametrize("value", [1.5, "1", True])
def test_quantity_must_be_integer_not_coerced(value):
    with pytest.raises(ValidationError):
        draft(quantity=value)


def test_prior_negotiated_discount_cannot_enlarge_next_piece_value():
    history = {"quantities": {"out:line": 1}, "physical_rounding": {},
               "reductions": {"out:line": Decimal("10")}, "reductions_usd": {"out:line": Decimal("10")},
               "reduction_amount": Decimal("10"), "refunds": {"original-payment": Decimal("10")},
               "refunds_usd": {"original-payment": Decimal("10")}}
    with pytest.raises(ValueError, match="净货值"):
        price(snapshot(), draft("190", 1), history)
    assert price(snapshot(), draft("100", 1), history)["refund_amount"] == "100.00"


@pytest.mark.parametrize("reason", ["  ", " a "])
def test_blank_or_short_reason_is_rejected_after_trimming(reason):
    body = draft().model_dump()
    body["reason"] = reason
    with pytest.raises(ValidationError):
        Draft(**body)
