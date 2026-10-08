"""Snapshot dimensions, unique-grain aggregation, and whitelisted evidence."""

from collections import defaultdict
from app.domestic_decision.metrics import decimal, number, change
from app.domestic_decision.schemas import PRODUCT_FIELDS, CUSTOMER_FIELDS, ORDER_FIELDS

UNKNOWN = "未知"
NOT_APPLICABLE = "不适用"


def item_attributes(item, mappings):
    snapshot = item.attrs_snapshot if isinstance(item.attrs_snapshot, dict) else {}
    product_type = snapshot.get("product_type")
    result, raw = {}, {}
    for field in PRODUCT_FIELDS:
        value = item.color if field == "color" else snapshot.get(field)
        value = str(value).strip() if value is not None else ""
        raw[field] = value
        if product_type == "piece" and field == "size":
            compound = str(snapshot.get("craft") or "").strip()
            raw[field] = compound
            result[field] = mappings.get(("size", "piece", compound)) or (f"待映射：{compound}" if compound else UNKNOWN)
        elif product_type == "piece" and field in ("net_color", "density", "hair_style_series"):
            result[field] = NOT_APPLICABLE
        elif field == "density" and product_type == "cap" and snapshot.get("length") != "15厘米":
            result[field] = NOT_APPLICABLE
        elif not value:
            result[field] = UNKNOWN
        else:
            mapped = mappings.get((field, product_type or "", value), mappings.get((field, "", value)))
            result[field] = mapped or (f"未归类：{value}" if field == "color" else value)
    return result, raw


def matches(values, filters):
    return all(not selected or str(values.get(field) or UNKNOWN) in selected for field, selected in filters.items())


def header_evidence(order, finance=False):
    result = {"id": order.id, "domestic_no": order.domestic_no, "customer_id": order.customer_id,
              "order_date": order.order_date.isoformat(), "order_kind": order.order_kind,
              "order_category": order.order_category, "order_type": order.order_type,
              "order_channel": order.order_channel, "status": order.status, "deleted_flag": order.deleted_flag,
              "total_amount": number(order.total_amount), "created_by": order.created_by,
              "updated_at": order.updated_at.isoformat() if order.updated_at else None}
    if finance:
        result["charged_amount"] = number(order.charged_amount)
    return result


def item_evidence(item, attrs, raw):
    return {"id": item.id, "order_id": item.order_id, "product_id": item.product_id,
            "line_no": item.line_no, "product_name": item.product_name,
            "attrs": attrs, "raw_attrs": raw, "order_qty": item.order_qty,
            "unit_price": number(item.unit_price), "amount": number(decimal(item.unit_price) * item.order_qty),
            "original_price": number(item.original_price), "labor_fee": number(item.labor_fee),
            "discount_amount": number(item.discount_amount), "membership_level_snapshot": item.membership_level_snapshot,
            "pricing_rule": item.pricing_rule, "pricing_version": item.pricing_version,
            "base_price_version_snapshot": item.base_price_version_snapshot,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None}


def aggregate_orders(orders, items, aftersales):
    amount = sum((decimal(r.total_amount) for r in orders), decimal(0))
    matched_amount = sum((decimal(r.unit_price) * r.order_qty for r in items), decimal(0))
    quantity = sum(r.order_qty for r in items)
    return {"amount": number(amount), "related_order_amount": number(amount), "matched_amount": number(matched_amount),
            "quantity": quantity, "order_count": len(orders), "customer_count": len({r.customer_id for r in orders}),
            "weighted_unit_price": number(matched_amount / quantity) if quantity else None,
            "average_order_amount": number(amount / len(orders)) if orders else None,
            "commercial_amount": number(sum((decimal(r.total_amount) for r in orders if decimal(r.total_amount) > 0 and r.order_type not in aftersales), decimal(0))),
            "commercial_order_count": sum(decimal(r.total_amount) > 0 and r.order_type not in aftersales for r in orders),
            "zero_order_count": sum(decimal(r.total_amount) == 0 for r in orders),
            "aftersales_order_count": sum(r.order_type in aftersales for r in orders)}


def dimension_rows(items, orders, customers, field, attrs, previous_items, previous_orders, metric):
    order_map = {r.id: r for r in orders + previous_orders}
    customer_map = {r.id: r for r in customers}
    def value(item):
        order = order_map[item.order_id]
        if field in PRODUCT_FIELDS:
            return attrs[item.id][0][field]
        source = customer_map[order.customer_id] if field in CUSTOMER_FIELDS else order
        return str(getattr(source, field) or UNKNOWN)
    def group(source):
        result = defaultdict(lambda: {"amount": decimal(0), "quantity": 0, "orders": set(), "customers": set(), "items": []})
        for item in source:
            row = result[value(item)]
            row["amount"] += decimal(item.unit_price) * item.order_qty
            row["quantity"] += item.order_qty
            row["orders"].add(item.order_id)
            row["customers"].add(order_map[item.order_id].customer_id)
            row["items"].append(item.id)
        return result
    current, previous = group(items), group(previous_items)
    total = sum(r["amount"] for r in current.values())
    previous_total = sum(r["amount"] for r in previous.values())
    rows = []
    for key in set(current) | set(previous):
        row, old = current[key], previous[key]
        values = {"amount": number(row["amount"]), "quantity": row["quantity"], "order_count": len(row["orders"]), "customer_count": len(row["customers"])}
        rows.append({"key": key, "label": key, **values, "value": values[metric],
                     "share": float(row["amount"] / total) if total > 0 else None,
                     "previous_share": float(old["amount"] / previous_total) if previous_total > 0 else None,
                     "share_change": float(row["amount"] / total - old["amount"] / previous_total) if total > 0 and previous_total > 0 else None,
                     "previous_customer_count": len(old["customers"]), "customer_count_change": len(row["customers"]) - len(old["customers"]),
                     "previous_amount": number(old["amount"]), "amount_change": change(number(row["amount"]), number(old["amount"])),
                     "evidence_refs": [{"type": "items", "id": identifier} for identifier in row["items"]]})
    return sorted(rows, key=lambda r: (-r[metric], r["key"]))


def amount_decomposition(current_summary, previous_summary):
    """Base-price quantity contribution plus current-quantity price contribution."""
    quantity_now = decimal(current_summary["quantity"])
    quantity_before = decimal(previous_summary["quantity"])
    amount_now = decimal(current_summary["matched_amount"])
    amount_before = decimal(previous_summary["matched_amount"])
    result = {"grain": "matched_order_items", "matched_amount_change": number(amount_now - amount_before),
              "method": "base_period_price_quantity_first",
              "header_item_difference_change": number((decimal(current_summary["amount"]) - amount_now) - (decimal(previous_summary["amount"]) - amount_before)),
              "quantity_contribution": None, "weighted_price_contribution": None,
              "limitation": "混合单价受产品结构变化影响，不等于同规格提价或利润变化"}
    if quantity_now <= 0 or quantity_before <= 0:
        result["status"] = "new_or_zero_base"
        return result
    price_now, price_before = amount_now / quantity_now, amount_before / quantity_before
    result.update({"status": "available", "quantity_contribution": number((quantity_now - quantity_before) * price_before),
                   "weighted_price_contribution": number(quantity_now * (price_now - price_before))})
    return result


def price_report(items):
    """Only recorded positive standard prices support reference comparisons."""
    known = [r for r in items if decimal(r.original_price) > 0]
    known_qty = sum(r.order_qty for r in known)
    reference = sum(((decimal(r.original_price) + decimal(r.labor_fee)) * r.order_qty for r in known), decimal(0))
    paid = sum((decimal(r.unit_price) * r.order_qty for r in known), decimal(0))
    bands = defaultdict(lambda: {"quantity": 0, "amount": decimal(0), "item_count": 0})
    for item in items:
        price = decimal(item.unit_price)
        band = "0" if price == 0 else "0-500" if price <= 500 else "500-1000" if price <= 1000 else "1000-2000" if price <= 2000 else "2000+"
        bands[band]["quantity"] += item.order_qty
        bands[band]["amount"] += price * item.order_qty
        bands[band]["item_count"] += 1
    return {"known_standard_item_count": len(known), "unknown_standard_item_count": len(items) - len(known),
            "known_standard_quantity": known_qty, "reference_amount_including_labor": number(reference),
            "known_standard_paid_amount": number(paid), "recorded_discount_amount": number(reference - paid),
            "discount_rate": float((reference - paid) / reference) if reference > 0 else None,
            "labor_fee_amount": number(sum((decimal(r.labor_fee) * r.order_qty for r in items), decimal(0))),
            "price_bands": [{"band": key, "quantity": row["quantity"], "amount": number(row["amount"]), "item_count": row["item_count"]} for key, row in sorted(bands.items())],
            "limitation": "原价缺失的历史明细已排除原价比较；无成本数据，不计算利润"}


def quantity_report(orders, matched_items, all_items):
    """Disjoint line and whole-order quantity bins never share a denominator."""
    bands = ("无有效件数", "1", "2-3", "4-5", "6-10", "11+")
    def band(quantity):
        return "无有效件数" if quantity <= 0 else "1" if quantity == 1 else "2-3" if quantity <= 3 else "4-5" if quantity <= 5 else "6-10" if quantity <= 10 else "11+"
    item_groups = defaultdict(lambda: {"item_count": 0, "quantity": 0, "amount": decimal(0), "evidence_refs": []})
    full_quantities, matched_quantities = defaultdict(int), defaultdict(int)
    for item in all_items:
        full_quantities[item.order_id] += item.order_qty
    for item in matched_items:
        row = item_groups[band(item.order_qty)]
        row["item_count"] += 1
        row["quantity"] += item.order_qty
        row["amount"] += decimal(item.unit_price) * item.order_qty
        row["evidence_refs"].append({"type": "items", "id": item.id})
        matched_quantities[item.order_id] += item.order_qty
    order_groups = defaultdict(lambda: {"order_count": 0, "whole_quantity": 0, "matched_quantity": 0, "related_order_amount": decimal(0), "evidence_refs": []})
    for order in orders:
        row = order_groups[band(full_quantities[order.id])]
        row["order_count"] += 1
        row["whole_quantity"] += full_quantities[order.id]
        row["matched_quantity"] += matched_quantities[order.id]
        row["related_order_amount"] += decimal(order.total_amount)
        row["evidence_refs"].append({"type": "orders", "id": order.id})
    return {"item_bands": [{"band": name, **item_groups[name], "amount": number(item_groups[name]["amount"])} for name in bands if name in item_groups],
            "order_bands": [{"band": name, **order_groups[name], "related_order_amount": number(order_groups[name]["related_order_amount"])} for name in bands if name in order_groups],
            "limitation": "明细按匹配行件数分箱；关联整单按全部行总件数分箱，两类分母不同。"}


def matrix_rows(items, orders, customers, dimensions, attrs, metric):
    if len(dimensions) != 2:
        return []
    order_map, customer_map = {r.id: r for r in orders}, {r.id: r for r in customers}
    grouped = defaultdict(lambda: {"amount": decimal(0), "quantity": 0, "orders": set(), "customers": set(), "items": []})
    for item in items:
        order = order_map[item.order_id]
        values = []
        for field in dimensions:
            source = customer_map[order.customer_id] if field in CUSTOMER_FIELDS else order
            values.append(attrs[item.id][0][field] if field in PRODUCT_FIELDS else str(getattr(source, field) or UNKNOWN))
        row = grouped[tuple(values)]
        row["amount"] += decimal(item.unit_price) * item.order_qty
        row["quantity"] += item.order_qty
        row["orders"].add(order.id)
        row["customers"].add(order.customer_id)
        row["items"].append(item.id)
    rows = []
    for (x, y), row in grouped.items():
        values = {"amount": number(row["amount"]), "quantity": row["quantity"], "order_count": len(row["orders"]), "customer_count": len(row["customers"])}
        rows.append({"x": x, "y": y, **values, "value": values[metric], "evidence_refs": [{"type": "items", "id": identifier} for identifier in row["items"]]})
    return sorted(rows, key=lambda r: (-r[metric], r["x"], r["y"]))


def quality_report(orders, all_items, matched_items, attrs, dimensions, config, source_orders, metric="amount"):
    by_order = defaultdict(lambda: decimal(0))
    for item in all_items:
        by_order[item.order_id] += decimal(item.unit_price) * item.order_qty
    reconciliation = [{"order_id": r.id, "header_amount": number(r.total_amount), "item_amount": number(by_order[r.id]), "difference": number(decimal(r.total_amount) - by_order[r.id])} for r in orders if decimal(r.total_amount) != by_order[r.id]]
    coverage = {}
    order_customer = {order.id: order.customer_id for order in orders}
    for field in PRODUCT_FIELDS:
        applicable = [r for r in matched_items if attrs[r.id][0][field] != NOT_APPLICABLE]
        known = [r for r in applicable if attrs[r.id][0][field] != UNKNOWN and not attrs[r.id][0][field].startswith(("未归类：", "待映射："))]
        record_rate = len(known) / len(applicable) if applicable else None
        applicable_quantity = sum(max(item.order_qty, 0) for item in applicable)
        known_quantity = sum(max(item.order_qty, 0) for item in known)
        applicable_amount = sum((max(decimal(item.unit_price) * item.order_qty, decimal(0)) for item in applicable), decimal(0))
        known_amount = sum((max(decimal(item.unit_price) * item.order_qty, decimal(0)) for item in known), decimal(0))
        applicable_orders = {item.order_id for item in applicable}
        known_orders = {item.order_id for item in known}
        applicable_customers = {order_customer[item.order_id] for item in applicable}
        known_customers = {order_customer[item.order_id] for item in known}
        weighted_rates = {"amount": float(known_amount / applicable_amount) if applicable_amount > 0 else None,
                          "quantity": known_quantity / applicable_quantity if applicable_quantity > 0 else None,
                          "order_count": len(known_orders) / len(applicable_orders) if applicable_orders else None,
                          "customer_count": len(known_customers) / len(applicable_customers) if applicable_customers else None}
        weighted_rate = weighted_rates[metric]
        effective_rate = min(record_rate, weighted_rate) if record_rate is not None and weighted_rate is not None else None
        coverage[field] = {"applicable_count": len(applicable), "known_count": len(known), "unknown_count": len(applicable) - len(known), "not_applicable_count": len(matched_items) - len(applicable), "rate": record_rate,
                           "record_coverage": record_rate, "quantity_coverage": weighted_rates["quantity"], "amount_coverage": weighted_rates["amount"],
                           "order_count_coverage": weighted_rates["order_count"], "customer_count_coverage": weighted_rates["customer_count"],
                           "applicable_quantity": applicable_quantity, "known_quantity": known_quantity,
                           "applicable_positive_amount": number(applicable_amount), "known_positive_amount": number(known_amount),
                           "display_metric": metric, "effective_coverage": effective_rate,
                           "strong_advice_enabled": effective_rate is not None and effective_rate >= config["quality_threshold"]}
    exclusions = defaultdict(int)
    for order in source_orders:
        if order.deleted_flag:
            exclusions["deleted"] += 1
        elif order.order_kind != "business":
            exclusions["production"] += 1
        elif order.status not in (1, 2, 3):
            exclusions[f"status_{order.status}"] += 1
    return {"order_reconciliation": reconciliation, "order_reconciliation_count": len(reconciliation),
            "dimension_coverage": coverage, "excluded_order_counts": dict(exclusions),
            "quality_threshold": config["quality_threshold"], "coverage_start": config["coverage_start"],
            "coverage_method": "minimum_of_record_and_display_metric_weighted_coverage",
            "historical_replay": "current_source_recalculation_no_prior_state_reconstruction",
            "group_counts_additive": False}
