"""Repeated shipments and blank-spec supply signals with visible sample limits."""
from collections import defaultdict
from datetime import date
from statistics import median
import hashlib
import json
from app.core.time import beijing_today

from app.domestic_decision.schemas import PRODUCT_FIELDS
from app.domestic_decision.metrics import decimal, number, comparison_period
from app.domestic_decision.operations import in_period

BLANK_FIELDS = tuple(field for field in PRODUCT_FIELDS if field != "hair_style_series")


def _identity(attrs, fields):
    return tuple(attrs[field] for field in fields)


def _key(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:16]


def product_report(current_items, current_orders, operations, payload, config):
    attrs, all_items, all_orders = operations["attrs"], operations["items"], operations["orders"]
    shipping = in_period(operations["shipping"], payload.start_date, payload.end_date)
    comparison = comparison_period(payload)
    previous_shipping = in_period(operations["shipping"], *comparison) if comparison else []
    groups, shipments, history = defaultdict(list), defaultdict(list), defaultdict(list)
    order_map = {row.id: row for row in current_orders}
    for item in current_items:
        groups[_identity(attrs[item.id][0], PRODUCT_FIELDS)].append(item)
    for row in shipping:
        shipments[_identity(attrs[row["item_id"]][0], PRODUCT_FIELDS)].append(row)
    for row in previous_shipping:
        history[_identity(attrs[row["item_id"]][0], PRODUCT_FIELDS)].append(row)
    products = []
    for identity in groups.keys() | shipments.keys():
        lines, reports = groups[identity], shipments[identity]
        days = sorted({row["reported_at"][:10] for row in reports})
        weeks = {date.fromisoformat(day).isocalendar()[:2] for day in days}
        customers = {row["customer_id"] for row in reports}
        per_customer = defaultdict(set)
        for row in reports:
            per_customer[row["customer_id"]].add(row["reported_at"][:10])
        repeat = sum(len(values) >= 2 for values in per_customer.values())
        order_dates = {all_orders[row["order_id"]].order_date for row in reports}
        commercial_reports = [row for row in reports if decimal(row["unit_price"]) > 0 and decimal(all_orders[row["order_id"]].total_amount) > 0 and all_orders[row["order_id"]].order_type not in config["aftersales_order_types"]]
        commercial_days = {row["reported_at"][:10] for row in commercial_reports}
        commercial_weeks = {date.fromisoformat(day).isocalendar()[:2] for day in commercial_days}
        commercial_customers = {row["customer_id"] for row in commercial_reports}
        commercial_order_days = {all_orders[row["order_id"]].order_date for row in commercial_reports}
        status = "steady_seller" if len(commercial_days) >= 3 and len(commercial_weeks) >= 2 and len(commercial_customers) >= 2 and len(commercial_order_days) >= 2 else "occasional_shipping" if commercial_reports else "noncommercial_shipping" if reports else "ordered_not_shipped"
        total = sum(row["report_qty"] for row in reports)
        concentration = max((sum(row["report_qty"] for row in reports if row["customer_id"] == cid) for cid in customers), default=0) / total if total else None
        products.append({"key": _key(identity), "attrs": dict(zip(PRODUCT_FIELDS, identity)), "label": " / ".join(identity),
                         "amount": number(sum((decimal(item.unit_price) * item.order_qty for item in lines), decimal(0))),
                         "quantity": sum(item.order_qty for item in lines), "order_count": len({item.order_id for item in lines}),
                         "customer_count": len({order_map[item.order_id].customer_id for item in lines}),
                         "shipped_quantity": total, "shipped_amount": number(sum((decimal(row["unit_price"]) * row["report_qty"] for row in reports), decimal(0))),
                         "shipping_days": len(days), "shipping_weeks": len(weeks), "shipping_customer_count": len(customers), "repeat_shipping_customer_count": repeat,
                         "shipping_order_days": len(order_dates),
                         "commercial_shipping_days": len(commercial_days), "commercial_shipping_customer_count": len(commercial_customers),
                         "top_customer_quantity_share": concentration, "previous_shipping_quantity": sum(row["report_qty"] for row in history[identity]),
                         "demand_status": status, "gross_profit": None, "profit_status": "missing_cost", "inventory_quantity": None,
                         "evidence_refs": [{"type": "items", "id": item.id} for item in lines] + [{"type": "reports", "id": row["id"]} for row in reports]})
    supply_groups = defaultdict(lambda: {"production_items": [], "received": [], "issued": [], "shipped": []})
    for item in all_items.values():
        if all_orders[item.order_id].order_kind == "production":
            supply_groups[_identity(attrs[item.id][0], BLANK_FIELDS)]["production_items"].append(item)
    for row in operations["supply"]:
        key = "received" if row["process_name"] == "入库" else "issued"
        supply_groups[_identity(attrs[row["item_id"]][0], BLANK_FIELDS)][key].append(row)
    for row in shipping:
        supply_groups[_identity(attrs[row["item_id"]][0], BLANK_FIELDS)]["shipped"].append(row)
    supplies = []
    for identity, group in supply_groups.items():
        received = in_period(group["received"], payload.start_date, payload.end_date)
        issued = in_period(group["issued"], payload.start_date, payload.end_date)
        completed, cycles, wip, overdue, overreported = [], [], 0, 0, 0
        received_by_item = defaultdict(list)
        for row in group["received"]:
            received_by_item[row["item_id"]].append(row)
        for item in group["production_items"]:
            cumulative, completion_day = 0, None
            for row in received_by_item[item.id]:
                cumulative += row["report_qty"]
                if completion_day is None and cumulative >= item.order_qty > 0:
                    completion_day = date.fromisoformat(row["reported_at"][:10])
            wip += max(0, item.order_qty - cumulative)
            overreported += int(cumulative > item.order_qty)
            order = all_orders[item.order_id]
            if completion_day and payload.start_date <= completion_day <= payload.end_date:
                cycle = (completion_day - order.order_date).days
                if cycle >= 0:
                    cycles.append(cycle)
                    completed.append(item.id)
            if cumulative < item.order_qty and (min(payload.end_date, beijing_today()) - order.order_date).days >= 90:
                overdue += max(0, item.order_qty - cumulative)
        received_qty, issued_qty = sum(row["report_qty"] for row in received), sum(row["report_qty"] for row in issued)
        known_spec = not any(value == "未知" or value.startswith(("待映射：", "未归类：")) for value in identity)
        signal = "specification_unverified" if not known_spec else "aged_production" if overdue else "supply_build_up" if received_qty > issued_qty else "demand_supported" if issued_qty > 0 else "insufficient_sample"
        supplies.append({"key": _key(identity), "attrs": dict(zip(BLANK_FIELDS, identity)), "label": " / ".join(identity),
                         "production_received_quantity": received_qty, "blank_issued_quantity": issued_qty,
                         "shipped_quantity": sum(row["report_qty"] for row in group["shipped"]), "production_wip_quantity": wip,
                         "supply_excess_quantity": max(0, received_qty - issued_qty), "aged_wip_quantity": overdue,
                         "production_cycle_days": median(cycles) if cycles else None, "production_completed_item_count": len(completed),
                         "overreported_item_count": overreported, "inventory_signal": signal, "inventory_quantity": None,
                         "evidence_refs": [{"type": "reports", "id": row["id"]} for row in received + issued] + [{"type": "items", "id": item.id} for item in group["production_items"]]})
    baseline = median([row["production_cycle_days"] for row in supplies if row["production_completed_item_count"] >= 3]) if any(row["production_completed_item_count"] >= 3 for row in supplies) else None
    for row in supplies:
        row["replenishment_status"] = "insufficient_sample" if row["production_completed_item_count"] < 3 or baseline is None else "faster_replenishment" if row["production_cycle_days"] <= baseline else "slower_replenishment"
    return sorted(products, key=lambda row: (-row["shipped_quantity"], -row["amount"], row["key"])), {
        "rows": sorted(supplies, key=lambda row: (-row["aged_wip_quantity"], -row["supply_excess_quantity"], row["key"])), "cycle_baseline_days": baseline,
        "includes_unassigned_production": operations["includes_unassigned_production"],
        "scope_basis": "authorized_customers_and_unassigned_production" if operations["includes_unassigned_production"] else "authorized_customer_linked_production_only",
        "limitation": "毛坯规格去掉最终发型系列并去重。入库仅生产单，毛坯出库仅业务单；生产供给不应用业务渠道/类型/类别与最终发型筛选。入出库差是期间供需线索，不是库存余额。周期按整行数量实际入库完成日减下单日，至少3行样本才比较快慢；90天未入库在制量提示核查。缺成本、期初库存及销售批次消耗关联，利润与实际库存风险待核算。"}
