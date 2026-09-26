"""Local contract simulations only; these tests never call OKKI."""
from copy import deepcopy
from decimal import Decimal

import pytest

from app.invoice.settlement_contract import build_freight_order_candidate, build_outbound_candidate
from app.invoice.settlement_pricing import quote_settlement, split_payment


def order():
    return {
        "order_id": 100, "company_id": 200, "currency": "USD",
        "users": [{"user_id": "300", "rate": 100}],
        "exchange_rate": 720, "exchange_rate_usd": 100,
        "product_list": [
            {"unique_id": 11, "product_id": 21, "sku_id": 31, "count": 10,
             "to_outbound_count": 0, "task_outbound_count": 0,
             "unit_price": "100.00", "unit": "", "product_name": "Hair"},
            {"unique_id": 12, "product_id": 22, "sku_id": 32, "count": 5,
             "to_outbound_count": 0, "task_outbound_count": 0,
             "unit_price": "20.00", "unit": "Piece", "product_name": "Accessory"},
        ],
    }


def items():
    return [{"quantity": 4, "snapshot": {"order_id": "100", "order_record_id": 11,
            "product_id": 21, "sku_id": 31, "sale_price": "100.00"}}]


def outbound(rows=None, remote=None, reserved=None):
    return build_outbound_candidate("PRE-1-01", "100", "200", "USD",
                                    rows if rows is not None else items(), remote or order(), 400,
                                    handler_id=300, reserved_quantities=reserved if reserved is not None else {11: 0})


def test_partial_outbound_uses_only_selected_remote_line_and_batch_number():
    payload = outbound()
    assert payload["serial_id"] == "PRE-1-01"
    assert payload["status"] == 1
    assert payload["invoice_warehouse_id"] == 400
    assert payload["record_list"] == [{
        "order_id": 100, "order_record_id": 11, "product_id": 21, "sku_id": 31,
        "outbound_count": 4, "sale_price": 100.0, "product_unit": "Piece",
        "product_name": "Hair",
    }]


@pytest.mark.parametrize("change", [
    lambda rows: rows[0]["snapshot"].update(order_record_id=12),
    lambda rows: rows[0]["snapshot"].update(order_id="101"),
    lambda rows: rows[0].update(quantity=11),
    lambda rows: rows.append(deepcopy(rows[0])),
])
def test_outbound_rejects_changed_identity_overquantity_and_duplicate_line(change):
    rows = items()
    change(rows)
    with pytest.raises(ValueError):
        outbound(rows=rows)


def test_outbound_rejects_prior_allocation_exceeding_remote_line():
    rows = items()
    rows[0]["quantity"] = 8
    with pytest.raises(ValueError, match="剩余"):
        outbound(rows=rows, reserved={11: 4})


def test_outbound_rejects_unaccounted_remote_allocation_and_price_drift():
    remote = order()
    remote["product_list"][0]["to_outbound_count"] = 4
    with pytest.raises(ValueError, match="远端已占"):
        outbound(remote=remote)
    remote["product_list"][0]["to_outbound_count"] = 0
    remote["product_list"][0]["unit_price"] = "101.00"
    with pytest.raises(ValueError, match="单价"):
        outbound(remote=remote)


def test_freight_candidate_is_separate_and_does_not_change_main_order():
    main = {"order_id": 100, "name": "PRE-1", "account_date": "2026-09-23", "currency": "USD",
            "company_id": 200, "status": 1, "handler": [300],
            "users": [{"user_id": 300, "rate": 100}], "departments": [{"department_id": 4, "rate": 100}],
            "product_list": [{"product_id": 21}], "cost_list": [{"cost_name": "Packaging", "cost": 10}]}
    original = deepcopy(main)
    candidate = build_freight_order_candidate(main, "PRE-1-01", "100", "200", "USD", "2026-09-24", "150.00")
    assert candidate["local_kind"] == "freight"
    assert candidate["sendable"] is False
    assert candidate["payload"]["name"] == "PRE-1-01-F"
    assert candidate["payload"]["account_date"] == "2026-09-24"
    assert candidate["payload"]["product_list"] == []
    assert candidate["payload"]["cost_list"] == [{
        "cost_name": "Shipping fee", "percent_type": 0,
        "percent_amount": 150.0, "cost": 150.0,
    }]
    assert main == original


@pytest.mark.parametrize("amount", ["0", "-1", "1.001", "NaN"])
def test_freight_candidate_rejects_invalid_amount(amount):
    with pytest.raises(ValueError):
        build_freight_order_candidate({"company_id": 200}, "PRE-1-01", "100", "200", "USD", "2026-09-24", amount)


def test_freight_candidate_rejects_wrong_main_order_and_customer():
    main = {"order_id": 101, "company_id": 201, "currency": "USD"}
    with pytest.raises(ValueError, match="来源订单"):
        build_freight_order_candidate(main, "PRE-1-01", "100", "200", "USD", "2026-09-24", "150")
    main["order_id"] = 100
    with pytest.raises(ValueError, match="客户"):
        build_freight_order_candidate(main, "PRE-1-01", "100", "200", "USD", "2026-09-24", "150")


def test_two_batches_keep_deposit_for_final_and_map_exact_outbound_quantities():
    first = quote_settlement([
        {"invoice_item_id": 1, "quantity": 10, "total_price": "10000",
         "shipped_quantity": 0, "requested_quantity": 4},
    ], "0", "0", "3000", "0", freight="200")
    last = quote_settlement([
        {"invoice_item_id": 1, "quantity": 10, "total_price": "10000",
         "shipped_quantity": 4, "requested_quantity": 6},
    ], "0", "0", "3000", "0", freight="150")
    assert (first["new_payment_due"], first["deposit_applied"]) == ("4200.00", "0.00")
    assert (last["new_payment_due"], last["deposit_applied"]) == ("3150.00", "3000.00")
    assert split_payment(first["new_payment_due"], first["goods_payment_due"],
                         first["freight_amount"], first["goods_payment_charge"])["freight_amount"] == 200
    assert split_payment(last["new_payment_due"], last["goods_payment_due"],
                         last["freight_amount"], last["goods_payment_charge"])["freight_amount"] == 150
    batch_one = outbound()
    batch_two_items = items()
    batch_two_items[0]["quantity"] = 6
    batch_two = build_outbound_candidate("PRE-1-02", "100", "200", "USD", batch_two_items, order(), 400,
                                         handler_id=300, reserved_quantities={11: 4})
    assert [batch_one["record_list"][0]["outbound_count"],
            batch_two["record_list"][0]["outbound_count"]] == [4, 6]
    assert sum(map(Decimal, ("3000", first["new_payment_due"], last["new_payment_due"]))) == Decimal("10350")
