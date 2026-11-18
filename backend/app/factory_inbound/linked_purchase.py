"""Build the paired OKKI documents for one confirmed factory inbound batch."""

import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.factory_inbound.purchase_readback import verify_purchase_draft


class LinkedPurchaseError(ValueError):
    """The batch or purchase readback cannot establish a complete document pair."""


@dataclass(frozen=True)
class LinkedPurchaseLine:
    """A product and SKU resolved by the caller against the OKKI catalog."""

    product_id: int
    sku_id: int
    quantity: int
    unit_price: int


@dataclass(frozen=True)
class LinkedPurchaseBatch:
    purchase_order_no: str
    inbound_serial_id: str
    supplier_id: int
    warehouse_id: int
    handler_id: int
    purchasing_status_id: int
    business_date: date
    remark: str
    lines: tuple[LinkedPurchaseLine, ...]


def _positive_int(value, label, *, limit=9_223_372_036_854_775_807):
    if type(value) is not int or not 0 < value <= limit:
        raise LinkedPurchaseError(f"{label}必须为有效的正整数")
    return value


def _read_id(value, label):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        value = int(value)
    return _positive_int(value, label)


def _decimal_matches(value, expected):
    if type(value) in (int, float):
        value = str(value)
    return (
        isinstance(value, str)
        and len(value) <= 64
        and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is not None
        and Decimal(value) == expected
    )


def _mapping(value, label):
    if not isinstance(value, dict):
        raise LinkedPurchaseError(f"{label}缺失或格式无效")
    return value


def _purchase_lines(lines: Iterable[LinkedPurchaseLine]):
    combined: dict[tuple[int, int], LinkedPurchaseLine] = {}
    for line in lines:
        if not isinstance(line, LinkedPurchaseLine):
            raise LinkedPurchaseError("批次包含未映射的小满产品或 SKU")
        key = (
            _positive_int(line.product_id, "小满产品 ID"),
            _positive_int(line.sku_id, "小满 SKU ID"),
        )
        qty = _positive_int(line.quantity, "采购数量", limit=2_147_483_647)
        price = _positive_int(line.unit_price, "USD 采购单价")
        if key in combined:
            previous = combined[key]
            if price != previous.unit_price:
                raise LinkedPurchaseError("同一产品和 SKU 的采购单价冲突")
            qty = _positive_int(qty + previous.quantity, "合并采购数量", limit=2_147_483_647)
        combined[key] = LinkedPurchaseLine(*key, qty, price)
    if not combined:
        raise LinkedPurchaseError("批次缺少已映射的小满产品")
    return combined


def build_purchase_order(batch: LinkedPurchaseBatch) -> dict:
    """Return one purchase order body after validating all batch inputs."""
    if not isinstance(batch, LinkedPurchaseBatch):
        raise LinkedPurchaseError("缺少已冻结的批次采购计划")
    for value, label in (
        (batch.purchase_order_no, "采购单号"),
        (batch.inbound_serial_id, "入库单号"),
        (batch.remark, "批次备注"),
    ):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise LinkedPurchaseError(f"{label}缺失或无效")
    if type(batch.business_date) is not date:
        raise LinkedPurchaseError("批次日期无效")
    supplier_id = _positive_int(batch.supplier_id, "供应商 ID")
    _positive_int(batch.warehouse_id, "仓库 ID")
    handler_id = _positive_int(batch.handler_id, "经办人 ID")
    status_id = _positive_int(batch.purchasing_status_id, "采购中状态 ID")
    if not isinstance(batch.lines, tuple):
        raise LinkedPurchaseError("批次采购明细必须为已冻结的行")
    lines = _purchase_lines(batch.lines)
    product_list = []
    for line in lines.values():
        product_list.append({
            "product_id": line.product_id, "sku_id": line.sku_id, "count": line.quantity,
            "unit_price": line.unit_price, "cost_amount": line.quantity * line.unit_price,
        })
    amount = _positive_int(sum(row["cost_amount"] for row in product_list), "采购总额")
    return {
        "purchase_order_no": batch.purchase_order_no, "supplier_id": supplier_id,
        "currency": "USD", "purchase_date": batch.business_date.isoformat(), "remark": batch.remark,
        "creator": handler_id, "handler": [handler_id], "status": status_id,
        "amount": amount, "product_total_amount": amount, "product_list": product_list,
    }


def build_inbound_draft(batch: LinkedPurchaseBatch, purchase_detail: dict, *, purchase_order_id: int) -> dict:
    """Bind each inbound row to the matching verified purchase row, in batch order."""
    purchase = build_purchase_order(batch)
    detail = _mapping(purchase_detail, "小满采购单回读")
    order_id = _positive_int(purchase_order_id, "已创建采购单 ID")
    supplier = _mapping(detail.get("supplier_info"), "小满采购供应商")
    status = _mapping(detail.get("status_info"), "小满采购状态")
    if (
        _read_id(detail.get("purchase_order_id"), "回读采购单 ID") != order_id
        or detail.get("purchase_order_no") != purchase["purchase_order_no"]
        or _read_id(supplier.get("supplier_id"), "回读供应商 ID") != purchase["supplier_id"]
        or _read_id(status.get("id"), "回读采购状态 ID") != purchase["status"]
        or detail.get("currency") != purchase["currency"]
        or detail.get("remark") != purchase["remark"]
        or not _decimal_matches(detail.get("amount"), purchase["amount"])
    ):
        raise LinkedPurchaseError("小满采购单头与批次不符")

    expected = {(row["product_id"], row["sku_id"]): row for row in purchase["product_list"]}
    rows = detail.get("product_list")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise LinkedPurchaseError("小满采购明细数量与批次不符")
    verified = {}
    line_ids = set()
    for row in rows:
        row = _mapping(row, "小满采购明细")
        pair = (
            _read_id(row.get("product_id"), "回读产品 ID"),
            _read_id(row.get("sku_id"), "回读 SKU ID"),
        )
        line_id = _read_id(row.get("purchase_order_product_id"), "采购单产品 ID")
        match = expected.get(pair)
        if (
            match is None or pair in verified or line_id in line_ids
            or not _decimal_matches(row.get("count"), match["count"])
            or not _decimal_matches(row.get("unit_price"), match["unit_price"])
            or ("cost_amount" in row and not _decimal_matches(row["cost_amount"], match["cost_amount"]))
        ):
            raise LinkedPurchaseError("小满采购明细的产品、数量、单价或采购行 ID 与批次不符")
        verified[pair] = line_id
        line_ids.add(line_id)
    return {
        "supplier_id": batch.supplier_id, "currency": purchase["currency"],
        "serial_id": batch.inbound_serial_id, "warehouse_invoice_time": batch.business_date.isoformat(),
        "remark": batch.remark, "invoice_warehouse_id": batch.warehouse_id, "status": 1,
        "handler": [batch.handler_id],
        "record_list": [
            {
                "product_id": pair[0], "sku_id": pair[1], "inbound_count": row["count"],
                "purchase_price": row["unit_price"], "purchase_order_id": order_id,
                "purchase_order_product_id": verified[pair],
            }
            for pair, row in expected.items()
        ],
    }


def build_inbound_completion(draft: dict, draft_detail: dict, *, inbound_id: int) -> dict:
    """Verify the existing linked draft before requesting completion."""
    draft = _mapping(draft, "已冻结入库草稿")
    rows = draft.get("record_list")
    if (
        type(draft.get("status")) is not int or draft["status"] != 1 or "inbound_id" in draft
        or not isinstance(rows, list) or not rows
    ):
        raise LinkedPurchaseError("只能提交已冻结的入库草稿")
    draft_id = _positive_int(inbound_id, "已存在入库草稿 ID")
    verified = verify_purchase_draft(draft, draft_detail, inbound_id=draft_id, serial_id=draft.get("serial_id"))
    if any("purchase_order_id" not in row for row in verified["record_list"]):
        raise LinkedPurchaseError("入库草稿缺少采购单和采购行关联")
    body = deepcopy(draft)
    body.update(status=2, inbound_id=draft_id)
    return body
