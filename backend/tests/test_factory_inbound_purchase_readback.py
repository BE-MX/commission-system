from copy import deepcopy

import pytest

from app.factory_inbound.purchase_readback import PurchaseReadbackError, verify_completed_purchase


@pytest.fixture
def purchase():
    request = {
        "invoice_warehouse_id": 52, "supplier_id": 88, "currency": "USD", "remark": "FI-test-1",
        "record_list": [{"product_id": 67, "sku_id": 99, "inbound_count": 3, "purchase_price": 2}],
    }
    response = {
        **request, "inbound_invoice_id": 123, "serial_id": "CGRK-123", "status": 2,
        "delete_flag": 0, "type": 28,
        "record_list": [{**request["record_list"][0], "warehouse_id": 52, "inbound_count": "3.000"}],
    }
    return request, response


def validate(request, response):
    return verify_completed_purchase(request, response, inbound_id=123, serial_id="CGRK-123")


def test_readback_compares_identity_and_exact_numeric_lines(purchase):
    request, response = purchase
    assert validate(request, response) == {
        "inbound_invoice_id": 123, "serial_id": "CGRK-123", "warehouse_id": 52,
        "record_list": [{"product_id": 67, "sku_id": 99, "quantity": 3, "purchase_price": "2"}],
    }


@pytest.mark.parametrize(("field", "value"), [
    ("status", 1), ("status", None), ("type", 29), ("inbound_invoice_id", 124),
    ("serial_id", "CGRK-124"), ("delete_flag", 1), ("remark", "another batch"),
    ("invoice_warehouse_id", 53), ("supplier_id", 89), ("currency", "RMB"),
])
def test_draft_or_other_warehouse_document_is_not_completion(purchase, field, value):
    request, response = purchase
    with pytest.raises(PurchaseReadbackError):
        validate(request, {**response, field: value})


@pytest.mark.parametrize(("field", "value"), [
    ("sku_id", 100), ("product_id", 66), ("warehouse_id", 6), ("inbound_count", 4),
    ("inbound_count", "3.1"), ("purchase_price", "2.01"), ("purchase_price", "nan"),
])
def test_wrong_detail_cannot_release_writeback(purchase, field, value):
    request, response = purchase
    modified = deepcopy(response)
    modified["record_list"][0][field] = value
    with pytest.raises(PurchaseReadbackError):
        validate(request, modified)


def test_linked_receipt_requires_the_frozen_purchase_order_and_line(purchase):
    request, response = purchase
    request["record_list"][0].update(purchase_order_id=88, purchase_order_product_id=98)
    receipt_line = response["record_list"][0]
    receipt_line.update(purchase_order_id="88", purchase_order_product_id="98")
    proof = validate(request, response)
    assert proof["record_list"][0]["purchase_order_id"] == 88
    assert proof["record_list"][0]["purchase_order_product_id"] == 98
    receipt_line["purchase_order_product_id"] = "97"
    with pytest.raises(PurchaseReadbackError, match="采购关联"):
        validate(request, response)
    receipt_line.pop("purchase_order_product_id")
    with pytest.raises(PurchaseReadbackError, match="身份缺失"):
        validate(request, response)


def test_receipt_number_must_match_the_frozen_request(purchase):
    request, response = purchase
    request["serial_id"] = "CGRK-OTHER"
    with pytest.raises(PurchaseReadbackError, match="单号或 ID"):
        validate(request, response)


@pytest.mark.parametrize(("purchase_id", "line_id"), [(89, 99), (88, 98), (None, None)])
def test_linked_batch_requires_one_purchase_order_and_distinct_purchase_rows(purchase, purchase_id, line_id):
    request, response = purchase
    request["record_list"][0].update(purchase_order_id=88, purchase_order_product_id=98)
    second = {**request["record_list"][0], "product_id": 68, "sku_id": 100,
              "purchase_order_id": purchase_id, "purchase_order_product_id": line_id}
    request["record_list"].append(second)
    response["record_list"] = [{**line, "warehouse_id": 52} for line in request["record_list"]]
    with pytest.raises(PurchaseReadbackError, match="采购关联须覆盖"):
        validate(request, response)
