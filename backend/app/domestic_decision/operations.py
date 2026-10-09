"""Report-date shipping and authorized production facts; never inferred inventory."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticReportLog
from app.production.models import Process
from app.domestic_decision.analytic_facts import item_attributes, matches, header_evidence, item_evidence
from app.domestic_decision.schemas import PRODUCT_FIELDS, ORDER_FIELDS, CUSTOMER_FIELDS
from app.domestic_decision.metrics import decimal, number
from app.domestic_decision.scope import has_permission

REPORT_PROCESSES = ("发货完成", "入库", "毛坯出库")


def unassigned_production_allowed(actor, payload):
    return (payload.scope == "all" and not payload.customer_ids and not payload.owner_ids
            and not any(key in CUSTOMER_FIELDS and values for key, values in payload.filters.items())
            and has_permission(actor, "domestic_decision:read_all") and has_permission(actor, "domestic:read_all"))


def report_evidence(log, item, order, process_name):
    return {"id": log.id, "item_id": item.id, "order_id": item.order_id,
            "customer_id": order.customer_id, "process_id": log.process_id, "process_name": process_name,
            "report_qty": log.report_qty, "reported_at": to_beijing_naive(log.reported_at).isoformat(),
            "revoked": log.revoked, "unit_price": number(item.unit_price),
            "amount": number(decimal(item.unit_price) * log.report_qty)}


def load_operations(db, actor, payload, orders, items, attrs, mappings):
    orders, items, attrs = list(orders), list(items), dict(attrs)
    includes_unassigned = unassigned_production_allowed(actor, payload)
    if includes_unassigned:
        extra_orders = db.query(DomesticOrder).filter(DomesticOrder.customer_id.is_(None), DomesticOrder.order_kind == "production", DomesticOrder.order_date <= min(payload.end_date, beijing_today())).populate_existing().order_by(DomesticOrder.id).all()
        extra_items = db.query(DomesticOrderItem).filter(DomesticOrderItem.order_id.in_([row.id for row in extra_orders])).populate_existing().order_by(DomesticOrderItem.id).all() if extra_orders else []
        orders.extend(extra_orders)
        items.extend(extra_items)
        attrs.update({item.id: item_attributes(item, mappings) for item in extra_items})
    order_map, item_map = {row.id: row for row in orders}, {row.id: row for row in items}
    end = min(datetime.combine(payload.end_date + timedelta(days=1), time.min), beijing_now())
    process_names = {row.id: row.name for row in db.query(Process).filter(Process.name.in_(REPORT_PROCESSES)).populate_existing().all()}
    logs = db.query(DomesticReportLog).filter(DomesticReportLog.item_id.in_(list(item_map)), DomesticReportLog.process_id.in_(list(process_names)), DomesticReportLog.reported_at < end).populate_existing().order_by(DomesticReportLog.reported_at, DomesticReportLog.id).all() if item_map and process_names else []
    source = [report_evidence(log, item_map[log.item_id], order_map[item_map[log.item_id].order_id], process_names[log.process_id]) for log in logs]
    eligible_items = {}
    for item in items:
        order = order_map[item.order_id]
        if order.deleted_flag or order.status not in (1, 2, 3):
            continue
        if order.order_kind == "business" and not matches({field: getattr(order, field) for field in ORDER_FIELDS}, {key: values for key, values in payload.filters.items() if key in ORDER_FIELDS}):
            continue
        # Production has no business channel/category nor final hairstyle.
        product_filters = {key: values for key, values in payload.filters.items() if key in PRODUCT_FIELDS and not (order.order_kind == "production" and key == "hair_style_series")}
        if all(not values or attrs[item.id][0][key] in values or attrs[item.id][1][key] in values for key, values in product_filters.items()):
            eligible_items[item.id] = item
    valid = [row for row in source if row["item_id"] in eligible_items and not row["revoked"] and row["report_qty"] > 0]
    shipping = [row for row in valid if row["process_name"] == "发货完成" and order_map[row["order_id"]].order_kind == "business"]
    supply = [row for row in valid if (row["process_name"] == "入库" and order_map[row["order_id"]].order_kind == "production") or (row["process_name"] == "毛坯出库" and order_map[row["order_id"]].order_kind == "business")]
    return {"orders": order_map, "items": eligible_items, "attrs": attrs, "shipping": shipping, "supply": supply,
            "source": {"reports": source, "extra_orders": [header_evidence(row) for row in orders if row.customer_id is None], "extra_items": [item_evidence(row, *attrs[row.id]) for row in items if order_map[row.order_id].customer_id is None], "process_names": process_names},
            "includes_unassigned_production": includes_unassigned}


def in_period(rows, start, end):
    return [row for row in rows if start.isoformat() <= row["reported_at"][:10] <= end.isoformat()]


def shipping_summary(rows):
    return {"shipped_amount": number(sum((decimal(row["unit_price"]) * row["report_qty"] for row in rows), decimal(0))), "shipped_quantity": sum(row["report_qty"] for row in rows)}


def shipping_by_day(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["reported_at"][:10]].append(row)
    return {day: shipping_summary(values) for day, values in grouped.items()}
