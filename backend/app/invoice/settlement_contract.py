"""Offline OKKI payload candidates for presale contract validation.

These builders perform no I/O and are intentionally not wired to a sender.
An isolated tenant must confirm the remote behavior and freight classification
before any candidate can be sent.
"""
from copy import deepcopy
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation


def _id(value, label):
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f"{label}缺失或无效")
    return int(text)


def _quantity(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("出库数量无效") from exc
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        raise ValueError("出库数量必须是正整数")
    return int(number)


def _nonnegative_quantity(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("已占用出库数量无效") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError("已占用出库数量无效")
    return int(number)


def _number(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label}无效") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label}无效")
    return number


def build_outbound_candidate(settlement_no, order_id, customer_id, currency, items, remote_order,
                             warehouse_id, *, handler_id, reserved_quantities):
    """Map only selected lines after checking their stable OKKI identities."""
    serial = str(settlement_no or "").strip()
    if not serial or len(serial) > 96:
        raise ValueError("分批出库编号无效")
    expected_order = _id(order_id, "订单 ID")
    if _id(remote_order.get("order_id"), "远端订单 ID") != expected_order:
        raise ValueError("远端订单身份已变化")
    customer = _id(customer_id, "客户 ID")
    if _id(remote_order.get("company_id"), "远端客户 ID") != customer:
        raise ValueError("远端客户身份已变化")
    if remote_order.get("currency") != currency:
        raise ValueError("远端订单币种已变化")
    handler = _id(handler_id, "绑定业务员 OKKI ID")
    users = remote_order.get("users") or []
    if not isinstance(users, list) or handler not in {
        _id(value.get("user_id"), "远端业务员 ID") for value in users if isinstance(value, dict)
    }:
        raise ValueError("绑定业务员不属于远端订单")
    warehouse = _id(warehouse_id, "出库仓库")
    if not isinstance(reserved_quantities, Mapping):
        raise ValueError("缺少已核对的出库占用快照")
    reserved = {}
    for identity, quantity in reserved_quantities.items():
        normalized = _id(identity, "已占用订单明细 ID")
        if normalized in reserved:
            raise ValueError("已占用订单明细 ID 重复")
        reserved[normalized] = _nonnegative_quantity(quantity)
    remote_lines = {}
    product_list = remote_order.get("product_list")
    if not isinstance(product_list, list):
        raise ValueError("远端订单明细列表缺失")
    for line in product_list:
        if not isinstance(line, dict):
            raise ValueError("远端订单明细无效")
        identity = _id(line.get("unique_id"), "远端订单明细 ID")
        if identity in remote_lines:
            raise ValueError("远端订单明细 ID 重复")
        remote_lines[identity] = line
    if not items:
        raise ValueError("本批没有出库明细")
    selected = set()
    record_list = []
    for item in items:
        snapshot = item.get("snapshot") or {}
        identity = _id(snapshot.get("order_record_id"), "结算明细 ID")
        if identity in selected:
            raise ValueError("本批订单明细重复")
        selected.add(identity)
        if _id(snapshot.get("order_id"), "结算订单 ID") != expected_order:
            raise ValueError("结算明细关联订单已变化")
        remote = remote_lines.get(identity)
        if remote is None:
            raise ValueError("远端订单明细已消失")
        product_id = _id(snapshot.get("product_id"), "结算产品 ID")
        sku_id = _id(snapshot.get("sku_id"), "结算 SKU ID")
        if product_id != _id(remote.get("product_id"), "远端产品 ID") or sku_id != _id(remote.get("sku_id"), "远端 SKU ID"):
            raise ValueError("远端产品身份已变化")
        quantity = _quantity(item.get("quantity"))
        if identity not in reserved:
            raise ValueError("缺少本行已核对的出库占用量")
        occupied = reserved[identity]
        remote_occupied = max(_nonnegative_quantity(remote.get("to_outbound_count")),
                              _nonnegative_quantity(remote.get("task_outbound_count")))
        if occupied < remote_occupied:
            raise ValueError("远端已占用出库数量未纳入快照")
        if occupied + quantity > _quantity(remote.get("count")):
            raise ValueError("本批数量超过远端订单明细剩余数量")
        price = _number(remote.get("unit_price"), "远端销售单价")
        if price != _number(snapshot.get("sale_price"), "冻结销售单价"):
            raise ValueError("远端销售单价已变化")
        unit = remote.get("unit") or "Piece"
        if not isinstance(unit, str):
            raise ValueError("远端产品单位无效")
        record_list.append({
            "order_id": expected_order, "order_record_id": identity,
            "product_id": product_id, "sku_id": sku_id,
            "outbound_count": quantity,
            "sale_price": float(price),
            "product_unit": unit,
            "product_name": remote.get("product_name") or snapshot.get("product_name") or "",
        })
    for field in ("exchange_rate", "exchange_rate_usd"):
        if _number(remote_order.get(field), f"远端 {field}") <= 0:
            raise ValueError(f"远端 {field} 无效")
    return {
        "serial_id": serial, "status": 1, "source_type": 2,
        "currency": currency, "exchange_rate": remote_order.get("exchange_rate"),
        "exchange_rate_usd": remote_order.get("exchange_rate_usd"),
        "invoice_warehouse_id": warehouse, "company_id": customer,
        "handler": [handler], "record_list": record_list,
    }


def build_freight_order_candidate(main_order_payload, settlement_no, order_id, customer_id,
                                  currency, account_date, amount):
    """Preview a separate freight target; remote classification is unverified."""
    freight = _number(amount, "运费金额")
    if freight <= 0 or freight != freight.quantize(Decimal("0.01")):
        raise ValueError("运费金额必须为正数且精确到分")
    source_order_id = _id(order_id, "来源订单 ID")
    if _id(main_order_payload.get("order_id"), "主单来源订单 ID") != source_order_id:
        raise ValueError("运费目标来源订单不匹配")
    if _id(main_order_payload.get("company_id"), "主单客户 ID") != _id(customer_id, "客户 ID"):
        raise ValueError("运费目标客户不匹配")
    if main_order_payload.get("currency") != currency:
        raise ValueError("运费目标币种不匹配")
    try:
        date.fromisoformat(account_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("运费发生日期无效") from exc
    serial = str(settlement_no or "").strip()
    if not serial or len(serial) > 94:
        raise ValueError("运费目标编号无效")
    for field in ("company_id", "status", "currency", "handler", "users", "departments"):
        if not main_order_payload.get(field):
            raise ValueError(f"主单 {field} 缺失，无法准备运费目标")
    payload = deepcopy(main_order_payload)
    payload.pop("order_id", None)
    payload.pop("order_no", None)
    payload["name"] = f"{serial}-F"
    payload["account_date"] = account_date
    payload["product_list"] = []
    payload["cost_list"] = [{
        "cost_name": "Shipping fee", "percent_type": 0,
        "percent_amount": float(freight), "cost": float(freight),
    }]
    payload["remark"] = f"Freight for OKKI order {source_order_id}; Ark settlement {serial}"
    return {"local_kind": "freight", "source_order_id": source_order_id,
            "sendable": False, "payload": payload}
