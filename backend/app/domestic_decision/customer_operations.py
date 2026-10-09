"""Behavior observations are explicit and never treated as customer intent."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from app.core.time import beijing_now, to_beijing_naive
from app.domestic.models import DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision.metrics import decimal, number


def retention_report(customers, config, payload):
    for row in customers:
        history = row["history"]
        days, recency, cycle = history["purchase_days"], history["recency_days"], history["cycle_days"]
        dates = history["purchase_dates"]
        end_month = payload.end_date.year * 12 + payload.end_date.month
        recent_months = {day[:7] for day in dates if 0 <= end_month - (int(day[:4]) * 12 + int(day[5:7])) <= 2}
        if row["status"] != 1 or row["lifecycle_status"] in config["inactive_lifecycle_statuses"]:
            status = "inactive_store"
        elif not days:
            status = "no_system_purchase"
        elif recency >= config["dormant_days"]:
            status = "dormant"
        elif cycle and recency > 1.5 * cycle:
            status = "losing_rhythm"
        elif len(recent_months) == 3 and any(payload.start_date.isoformat() <= day <= payload.end_date.isoformat() for day in dates):
            status = "sustained_repeat"
        elif days >= 2:
            status = "repeat_observed"
        else:
            status = "sample_accumulating"
        row["retention_status"] = status
        row["retention_evidence_refs"] = history["evidence_refs"]
    counts = Counter(row["retention_status"] for row in customers)
    return {"summary": {key: counts[key] for key in ("sustained_repeat", "losing_rhythm", "dormant", "repeat_observed", "sample_accumulating", "no_system_purchase", "inactive_store")},
            "dormant_days": config["dormant_days"], "basis": "full_commercial_history_distinct_purchase_days",
            "limitation": "持续复购需近三个自然月均有商业购买且本期商业下单；周期延后超过参考周期1.5倍，长期未购按配置天数。均为观察信号，不代表已确认流失。"}


def recharge_segments(db, customers, rows, orders, items, payload, comparison):
    ids = [row.id for row in customers]
    end = min(datetime.combine(payload.end_date + timedelta(days=1), time.min), beijing_now())
    entries = db.query(DomesticCustomerLedger).filter(DomesticCustomerLedger.customer_id.in_(ids), DomesticCustomerLedger.transaction_type == "recharge", DomesticCustomerLedger.amount > 0, DomesticCustomerLedger.created_at < end).populate_existing().order_by(DomesticCustomerLedger.created_at, DomesticCustomerLedger.id).all() if ids else []
    pending = db.query(DomesticCustomerRequest).filter(DomesticCustomerRequest.customer_id.in_(ids), DomesticCustomerRequest.request_type == "recharge", DomesticCustomerRequest.status == "pending", DomesticCustomerRequest.created_at < end).populate_existing().order_by(DomesticCustomerRequest.id).all() if ids else []
    recharged = {row.customer_id for row in entries}
    order_map = {row.id: row for row in orders}
    item_groups = defaultdict(list)
    for item in items:
        item_groups[order_map[item.order_id].customer_id].append(item)
    groups = []
    for key, label, member in (("recharged", "充值客户", True), ("non_recharged", "非充值客户", False)):
        selected_orders = [order for order in orders if (order.customer_id in recharged) == member]
        customer_ids = {order.customer_id for order in selected_orders}
        lines = [item for item in items if order_map[item.order_id].customer_id in customer_ids]
        groups.append({"key": key, "label": label, "customer_count": len(customer_ids), "order_count": len(selected_orders),
                       "amount": number(sum((decimal(order.total_amount) for order in selected_orders), decimal(0))),
                       "discount_amount": number(sum((decimal(item.discount_amount) * item.order_qty for item in lines), decimal(0))),
                       "evidence_refs": [{"type": "orders", "id": order.id} for order in selected_orders] + [{"type": "items", "id": item.id} for item in lines]})
    pending_ids = {row.customer_id for row in pending}
    for row in rows:
        cid = row["customer_id"]
        lines = item_groups[cid]
        discounted = any(decimal(item.discount_amount) > 0 for item in lines)
        known_full_price = bool(lines) and all(decimal(item.original_price) > 0 and decimal(item.unit_price) == decimal(item.original_price) + decimal(item.labor_fee) and decimal(item.discount_amount) == 0 for item in lines)
        row["recharge_group"] = "recharged" if cid in recharged else "non_recharged"
        row["discount_amount"] = number(sum((decimal(item.discount_amount) * item.order_qty for item in lines), decimal(0)))
        row["recharge_behavior"] = ("pending_recharge" if cid in pending_ids else "recharge_and_discount" if cid in recharged and discounted else "recharged_without_discount" if cid in recharged else "full_price_without_recharge" if known_full_price else "discount_without_recharge" if discounted else "no_behavior_sample")
        row["recharge_intent"] = "unconfirmed"
        row["recharge_behavior_refs"] = [{"type": "ledger", "id": entry.id} for entry in entries if entry.customer_id == cid] + [{"type": "requests", "id": request.id} for request in pending if request.customer_id == cid] + [{"type": "items", "id": item.id} for item in lines]
    def total(start, finish):
        return number(sum((decimal(entry.amount) for entry in entries if start <= to_beijing_naive(entry.created_at).date() <= finish), decimal(0)))
    return {"groups": groups, "basis": "positive_posted_recharge_through_period_end",
            "recharge_amount": total(payload.start_date, payload.end_date),
            "previous_recharge_amount": total(*comparison) if comparison else None,
            "limitation": "按期末前实际充值入账分组，不使用当前会员等级；未充值记录不等于明确拒绝充值。行为信号用于询问意向，不证明折扣或充值造成购买。",
            "source": [{"id": entry.id, "customer_id": entry.customer_id, "amount": str(entry.amount), "created_at": to_beijing_naive(entry.created_at).isoformat()} for entry in entries] + [{"request_id": row.id, "customer_id": row.customer_id, "status": row.status, "amount": str(row.amount)} for row in pending]}
