"""Observed purchase combinations and service prompts, with bounded evidence."""

from collections import defaultdict
from datetime import timedelta
from itertools import combinations
import hashlib
import json

from app.domestic_decision.metrics import decimal, number


def customer_recommendations(rows, items, commercial_orders, attrs, as_of, quality_threshold, inactive_lifecycle_statuses=()):
    order_map = {order.id: order for order in commercial_orders}
    by_customer = defaultdict(list)
    per_order = defaultdict(set)
    combination_customers = defaultdict(set)
    combinations_meta = {}
    for item in items:
        order = order_map.get(item.order_id)
        if not order:
            continue
        values = attrs[item.id][0]
        identity = tuple(values[field] for field in ("product_type", "craft", "size", "length", "color"))
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:16]
        combinations_meta[key] = {"key": key, "attrs": {field: values[field] for field in ("product_type", "craft", "size", "length", "color")}, "label": " / ".join(identity)}
        by_customer[order.customer_id].append((item, order, key))
        if order.order_date >= as_of - timedelta(days=179):
            per_order[order.id].add(key)
            combination_customers[key].add(order.customer_id)
    pair_customers = defaultdict(set)
    for order_id, keys in per_order.items():
        for pair in combinations(sorted(keys), 2):
            pair_customers[pair].add(order_map[order_id].customer_id)
    peer_customer_count = len({order_map[order_id].customer_id for order_id in per_order})
    qualifying_pairs = {pair: customers for pair, customers in pair_customers.items() if peer_customer_count >= 20 and len(customers) >= 5}

    def group(entries):
        result = defaultdict(lambda: {"quantity": 0, "amount": decimal(0), "orders": set(), "days": set(), "items": []})
        for item, order, key in entries:
            row = result[key]
            row["quantity"] += item.order_qty
            row["amount"] += decimal(item.unit_price) * item.order_qty
            row["orders"].add(order.id)
            row["days"].add(order.order_date)
            row["items"].append(item.id)
        return sorted([{**combinations_meta[key], "quantity": value["quantity"], "amount": number(value["amount"]), "order_count": len(value["orders"]), "purchase_days": len(value["days"]), "last_purchase_date": max(value["days"]).isoformat(), "evidence_refs": [{"type": "items", "id": identifier} for identifier in value["items"]]} for key, value in result.items()], key=lambda row: (-row["quantity"], row["key"]))

    for customer in rows:
        entries = by_customer[customer["customer_id"]]
        recent = [entry for entry in entries if entry[1].order_date >= as_of - timedelta(days=179)]
        recent_groups, history_groups = group(recent), group(entries)
        known = [entry for entry in recent if all(attrs[entry[0].id][0][field] != "未知" and not attrs[entry[0].id][0][field].startswith(("未归类：", "待映射：")) for field in ("craft", "length", "color"))]
        coverage = len(known) / len(recent) if recent else None
        applicable_quantity = sum(max(entry[0].order_qty, 0) for entry in recent)
        known_quantity = sum(max(entry[0].order_qty, 0) for entry in known)
        quantity_coverage = known_quantity / applicable_quantity if applicable_quantity > 0 else None
        effective_coverage = min(coverage, quantity_coverage) if coverage is not None and quantity_coverage is not None else None
        purchasing_days = len({entry[1].order_date for entry in recent})
        strong = purchasing_days >= 3 and effective_coverage is not None and effective_coverage >= quality_threshold
        total_quantity = sum(row["quantity"] for row in recent_groups)
        for row in recent_groups:
            row["quantity_share"] = row["quantity"] / total_quantity if total_quantity else None
        recommendations = []
        if recent_groups:
            top = recent_groups[0]
            recommendations.append({"rule_key": "own_repeat_combination", "title": "核对常购组合复购需求" if strong else "核对已购组合需求", "explanation": f"近180天该组合购买 {top['quantity']} 件，涉及 {top['purchase_days']} 个购买日；" + ("主要属性覆盖达到门槛。" if strong else "购买日或结构化属性不足，当前只表示已购记录。"), "product": top["attrs"], "evidence_refs": top["evidence_refs"][-6:], "confidence": "medium" if strong else "limited", "next_step": "询问当前采购计划，核对库存和交期后推荐", "inventory_delivery": "unknown"})
        now_entries = [entry for entry in recent if entry[1].order_date >= as_of - timedelta(days=89)]
        previous_entries = [entry for entry in recent if entry[1].order_date < as_of - timedelta(days=89)]
        now_quantity = sum(entry[0].order_qty for entry in now_entries)
        previous_quantity = sum(entry[0].order_qty for entry in previous_entries)
        if now_quantity != previous_quantity and recent:
            recommendations.append({"rule_key": "own_half_year_change", "title": "核对近半年购买变化", "explanation": f"最近90天商业购买 {now_quantity} 件，前90天 {previous_quantity} 件；仅为已观察变化，不推断需求预测。", "current_quantity": now_quantity, "previous_quantity": previous_quantity, "evidence_refs": [{"type": "items", "id": entry[0].id} for entry in recent[-6:]], "confidence": "limited", "next_step": "询问门店计划与交付体验，验证变化原因", "inventory_delivery": "unknown"})
        own_keys = {entry[2] for entry in recent}
        co_purchase = []
        for pair, customers in qualifying_pairs.items():
            if not own_keys.intersection(pair):
                continue
            support = len(customers) / peer_customer_count
            lift = support / ((len(combination_customers[pair[0]]) / peer_customer_count) * (len(combination_customers[pair[1]]) / peer_customer_count))
            co_purchase.append({"products": [combinations_meta[key] for key in pair], "support_customer_count": len(customers), "peer_customer_count": peer_customer_count, "support": support, "lift": lift, "grain": "customers_with_same_order_combination", "inventory_delivery": "unknown", "limitation": "共购是相关观察，不证明因果或确定需求"})
        customer["preferences"] = {"recent_180_days": recent_groups, "history": history_groups, "purchase_days": purchasing_days, "dimension_coverage": coverage, "quantity_coverage": quantity_coverage, "effective_coverage": effective_coverage, "status": "preference" if strong else "observed_purchases", "co_purchase_status": "available" if qualifying_pairs else "insufficient_customer_or_support_sample", "co_purchase_min_customers": 20, "co_purchase_min_support_customers": 5, "co_purchase": co_purchase[:10]}
        contact_eligible = customer["status"] != 0 and customer["lifecycle_status"] not in inactive_lifecycle_statuses
        customer["recommendations"] = recommendations if contact_eligible else []
        customer["recommendation_status"] = "available" if contact_eligible else "suppressed_contact_policy"
    return {"peer_customer_count": peer_customer_count, "qualifying_pair_count": len(qualifying_pairs), "basis": "authorized_current_portfolio_last180day_commercial_history", "minimum_customers": 20, "minimum_support_customers": 5}
