"""Verify the warehouse fact before any local receipt effect."""

from decimal import Decimal, InvalidOperation


class PurchaseReadbackError(ValueError):
    """The external response does not prove this specific completed receipt."""


def _id(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and len(value) <= 19 and value.isascii() and value.isdecimal() and not value.startswith("0"):
        return int(value)
    raise PurchaseReadbackError("小满入库身份缺失或无效")


def _amount(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise PurchaseReadbackError("小满入库数量或金额无效") from None
    if not amount.is_finite() or amount < 0:
        raise PurchaseReadbackError("小满入库数量或金额无效")
    return amount


def _purchase_link(row):
    order_id, item_id = row.get("purchase_order_id"), row.get("purchase_order_product_id")
    empty = (None, "", 0, "0")
    if order_id in empty and item_id in empty:
        return None
    return _id(order_id), _id(item_id)


def _details(rows, warehouse_id, *, readback):
    if not isinstance(rows, list) or not rows:
        raise PurchaseReadbackError("小满入库明细缺失")
    details = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PurchaseReadbackError("小满入库明细无效")
        pair = _id(row.get("product_id")), _id(row.get("sku_id"))
        quantity = _amount(row.get("inbound_count"))
        price = _amount(row.get("purchase_price"))
        if not 0 < quantity <= 2_147_483_647 or int(quantity) != quantity or pair in details:
            raise PurchaseReadbackError("小满入库明细重复或数量无效")
        if readback and _id(row.get("warehouse_id")) != warehouse_id:
            raise PurchaseReadbackError("小满入库明细仓库发生变化")
        details[pair] = (int(quantity), price, _purchase_link(row))
    links = [link for _, _, link in details.values() if link is not None]
    if links and (len(links) != len(details) or len({link[0] for link in links}) != 1
                  or len({link[1] for link in links}) != len(links)):
        raise PurchaseReadbackError("采购关联须覆盖整张入库单，并且只关联一张采购单的不同明细")
    return details


def _verify_purchase(request, response, *, inbound_id, serial_id, status):
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise PurchaseReadbackError("缺少小满完整入库回读")
    warehouse_id = _id(request.get("invoice_warehouse_id"))
    if response.get("status") not in (status, str(status)) or response.get("delete_flag") not in (0, "0"):
        expected_status = "已完成" if status == 2 else "草稿"
        raise PurchaseReadbackError(f"小满单据未证实为有效的{expected_status}状态")
    if response.get("type") not in (28, "28"):
        raise PurchaseReadbackError("小满单据类型不是采购入库")
    remote_id = _id(inbound_id)
    requested_serial = request.get("serial_id")
    if (not serial_id or (requested_serial is not None and requested_serial != serial_id)
            or response.get("serial_id") != serial_id or _id(response.get("inbound_invoice_id")) != remote_id):
        raise PurchaseReadbackError("小满入库单号或 ID 与批次不符")
    if _id(response.get("invoice_warehouse_id")) != warehouse_id or _id(response.get("supplier_id")) != _id(request.get("supplier_id")):
        raise PurchaseReadbackError("小满入库仓库或供应商与批次不符")
    if not request.get("remark") or response.get("remark") != request["remark"]:
        raise PurchaseReadbackError("小满入库备注缺少该批次的绑定证据")
    if response.get("currency") != request.get("currency") or not request.get("currency"):
        raise PurchaseReadbackError("小满入库币种与批次不符")
    expected = _details(request.get("record_list"), warehouse_id, readback=False)
    actual = _details(response.get("record_list"), warehouse_id, readback=True)
    if expected != actual:
        raise PurchaseReadbackError("小满入库产品、数量、采购单价或采购关联与批次不符")
    records = []
    for (product, sku), (quantity, price, link) in sorted(actual.items()):
        row = {"product_id": product, "sku_id": sku, "quantity": quantity, "purchase_price": str(price)}
        if link:
            row.update(purchase_order_id=link[0], purchase_order_product_id=link[1])
        records.append(row)
    return {
        "inbound_invoice_id": remote_id, "serial_id": serial_id, "warehouse_id": warehouse_id,
        "record_list": records,
    }


def verify_purchase_draft(request, response, *, inbound_id, serial_id):
    """Match an active draft and its purchase links against the frozen request."""
    return _verify_purchase(request, response, inbound_id=inbound_id, serial_id=serial_id, status=1)


def verify_completed_purchase(request, response, *, inbound_id, serial_id):
    """Return the verified completed receipt identity and lines for a frozen request."""
    return _verify_purchase(request, response, inbound_id=inbound_id, serial_id=serial_id, status=2)
