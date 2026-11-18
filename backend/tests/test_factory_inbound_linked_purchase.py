from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.factory_inbound.linked_purchase import (
    LinkedPurchaseBatch,
    LinkedPurchaseError,
    LinkedPurchaseLine,
    build_inbound_completion,
    build_inbound_draft,
    build_purchase_order,
)
from app.factory_inbound.purchase_readback import PurchaseReadbackError


@pytest.fixture
def batch():
    return LinkedPurchaseBatch(
        purchase_order_no="PO-123", inbound_serial_id="IN-123", supplier_id=901,
        warehouse_id=903, handler_id=905, purchasing_status_id=907, business_date=date(2026, 11, 18),
        remark="Factory batch 123",
        lines=(LinkedPurchaseLine(1, 101, 2, 5), LinkedPurchaseLine(2, 201, 3, 7),
               LinkedPurchaseLine(1, 101, 4, 5), LinkedPurchaseLine(1, 102, 1, 4)),
    )


@pytest.fixture
def detail():
    return {
        "purchase_order_id": 1001, "purchase_order_no": "PO-123", "supplier_info": {"supplier_id": 901},
        "currency": "USD", "status_info": {"id": "907"}, "remark": "Factory batch 123", "amount": 55,
        "product_list": [
            {"product_id": "2", "sku_id": 201, "count": "3.00", "unit_price": "7.0",
             "purchase_order_product_id": "1102", "to_inbound_count": "0"},
            {"product_id": "1", "sku_id": 102, "count": "1", "unit_price": "4",
             "purchase_order_product_id": "1103", "to_inbound_count": "1"},
            {"product_id": "1", "sku_id": 101, "count": "6", "unit_price": "5",
             "purchase_order_product_id": "1101", "to_inbound_count": "6"},
        ],
    }


def inbound_detail(draft):
    return {
        **draft, "inbound_invoice_id": 1500, "delete_flag": 0, "type": 28,
        "record_list": [{**row, "warehouse_id": draft["invoice_warehouse_id"]} for row in draft["record_list"]],
    }


def test_same_purchase_and_inbound_cover_all_products_and_bind_reordered_detail(batch, detail):
    purchase = build_purchase_order(batch)
    assert purchase["amount"] == purchase["product_total_amount"] == 55
    assert purchase["product_list"] == [
        {"product_id": 1, "sku_id": 101, "count": 6, "unit_price": 5, "cost_amount": 30},
        {"product_id": 2, "sku_id": 201, "count": 3, "unit_price": 7, "cost_amount": 21},
        {"product_id": 1, "sku_id": 102, "count": 1, "unit_price": 4, "cost_amount": 4},
    ]
    draft = build_inbound_draft(batch, detail, purchase_order_id=1001)
    assert draft["serial_id"] == "IN-123" and draft["status"] == 1
    assert draft["invoice_warehouse_id"] == 903 and draft["supplier_id"] == 901
    assert draft["record_list"] == [
        {"product_id": 1, "sku_id": 101, "inbound_count": 6, "purchase_price": 5,
         "purchase_order_id": 1001, "purchase_order_product_id": 1101},
        {"product_id": 2, "sku_id": 201, "inbound_count": 3, "purchase_price": 7,
         "purchase_order_id": 1001, "purchase_order_product_id": 1102},
        {"product_id": 1, "sku_id": 102, "inbound_count": 1, "purchase_price": 4,
         "purchase_order_id": 1001, "purchase_order_product_id": 1103},
    ]

    original = deepcopy(draft)
    completion = build_inbound_completion(draft, inbound_detail(draft), inbound_id=1500)
    assert completion == dict(original, status=2, inbound_id=1500)
    completion["record_list"][0]["inbound_count"] = 1
    assert draft == original


@pytest.mark.parametrize("line", [
    LinkedPurchaseLine(1, 101, 1, 6),
    LinkedPurchaseLine(0, 111, 1, 5),
    LinkedPurchaseLine(3, None, 1, 5),
    LinkedPurchaseLine(3, 301, True, 5),
    LinkedPurchaseLine(3, 301, 0, 5),
    LinkedPurchaseLine(3, 301, 1, 0),
    LinkedPurchaseLine(3, 301, 1, Decimal("5.25")),
])
def test_invalid_inputs_stop_entire_purchase_before_building_a_body(batch, line):
    with pytest.raises(LinkedPurchaseError):
        build_purchase_order(replace(batch, lines=(*batch.lines, line)))


@pytest.mark.parametrize(("field", "value"), [
    ("purchase_order_id", 1002), ("purchase_order_no", "PO-124"), ("remark", "Other batch"),
    ("supplier_info", {"supplier_id": 902}), ("status_info", {"id": "909"}), ("status_info", None),
    ("currency", "CNY"), ("amount", 54), ("amount", "NaN"), ("product_list", {}), ("product_list", []),
])
def test_wrong_purchase_detail_header_or_shape_never_creates_draft(batch, detail, field, value):
    detail[field] = value
    with pytest.raises(LinkedPurchaseError):
        build_inbound_draft(batch, detail, purchase_order_id=1001)


@pytest.mark.parametrize("override", [
    {"purchase_order_product_id": "1103"},  # Different SKU reuses a purchase line ID.
    {"product_id": "1", "sku_id": 102},  # Duplicate product and SKU, omitting another pair.
    {"product_id": "3"}, {"count": "2"}, {"unit_price": "7.01"}, {"unit_price": "NaN"},
    {"sku_id": True}, {"purchase_order_product_id": None}, {"cost_amount": "2"},
])
def test_wrong_or_duplicate_purchase_line_never_creates_draft(batch, detail, override):
    detail["product_list"][0].update(override)
    with pytest.raises(LinkedPurchaseError):
        build_inbound_draft(batch, detail, purchase_order_id=1001)


def test_completion_requires_existing_draft_id_and_cannot_resubmit_a_completion(batch, detail):
    draft = build_inbound_draft(batch, detail, purchase_order_id=1001)
    with pytest.raises(LinkedPurchaseError):
        build_inbound_completion(draft, inbound_detail(draft), inbound_id=0)
    with pytest.raises(LinkedPurchaseError):
        build_inbound_completion(dict(draft, record_list=[]), inbound_detail(draft), inbound_id=1500)
    completed = build_inbound_completion(draft, inbound_detail(draft), inbound_id=1500)
    with pytest.raises(LinkedPurchaseError):
        build_inbound_completion(completed, inbound_detail(draft), inbound_id=1500)


@pytest.mark.parametrize(("field", "value"), [
    ("inbound_invoice_id", 1501), ("serial_id", "IN-OTHER"), ("status", 2),
])
def test_completion_requires_matching_remote_draft(batch, detail, field, value):
    draft = build_inbound_draft(batch, detail, purchase_order_id=1001)
    remote = {**inbound_detail(draft), field: value}
    with pytest.raises(PurchaseReadbackError):
        build_inbound_completion(draft, remote, inbound_id=1500)


def test_completion_rejects_wrong_purchase_row_in_remote_draft(batch, detail):
    draft = build_inbound_draft(batch, detail, purchase_order_id=1001)
    remote = inbound_detail(draft)
    remote["record_list"][0]["purchase_order_product_id"] = 1104
    with pytest.raises(PurchaseReadbackError, match="采购关联"):
        build_inbound_completion(draft, remote, inbound_id=1500)
