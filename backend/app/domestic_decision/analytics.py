"""Read-only decision facts under current customer ownership and permissions."""

from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json

from fastapi import HTTPException
from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer, DomesticOrder, DomesticOrderItem
from app.domestic_decision.models import DecisionMapping
from app.domestic_decision.scope import live_actor, customer_query, has_permission
from app.domestic_decision.schemas import PRODUCT_FIELDS, CUSTOMER_FIELDS, ORDER_FIELDS, DIMENSIONS
from app.domestic_decision.metrics import METRIC_VERSION, METRICS, config_values, decimal, number, comparison_period, change
from app.domestic_decision.analytic_facts import item_attributes, matches, header_evidence, item_evidence, aggregate_orders, dimension_rows, matrix_rows, quality_report, amount_decomposition, price_report, quantity_report, UNKNOWN
from app.domestic_decision.analytic_rules import build_insights
from app.domestic_decision.profiles import customer_rows, buying_cohorts, apply_reference_cycles
from app.domestic_decision.finance import build_finance
from app.domestic_decision.recommendations import customer_recommendations
from app.domestic_decision.operations import load_operations, in_period, shipping_summary, shipping_by_day
from app.domestic_decision.customer_operations import retention_report, recharge_segments
from app.domestic_decision.product_operations import product_report


def _selected_customers(db, actor, payload):
    all_allowed = customer_query(db, actor).populate_existing().order_by(DomesticCustomer.id).all()
    allowed_ids = {r.id for r in all_allowed}
    if payload.scope == "all" and not has_permission(actor, "domestic_decision:read_all"):
        raise HTTPException(403, "缺少全量经营范围权限")
    if not set(payload.customer_ids).issubset(allowed_ids):
        raise HTTPException(404, "客户不存在或不在当前范围")
    if payload.owner_ids and not has_permission(actor, "domestic_decision:read_all") and set(payload.owner_ids) != {actor["id"]}:
        raise HTTPException(404, "业务员不存在或不在当前范围")
    selected = [r for r in all_allowed if payload.scope == "all" or r.owner_user_id == actor["id"]]
    if payload.customer_ids:
        selected = [r for r in selected if r.id in payload.customer_ids]
    if payload.owner_ids:
        selected = [r for r in selected if r.owner_user_id in payload.owner_ids]
    customer_filters = {key: value for key, value in payload.filters.items() if key in CUSTOMER_FIELDS}
    return [r for r in selected if matches({field: getattr(r, field) for field in CUSTOMER_FIELDS}, customer_filters)]


def _facts(db, customers, end_date):
    ids = [r.id for r in customers]
    orders = db.query(DomesticOrder).filter(DomesticOrder.customer_id.in_(ids), DomesticOrder.order_date <= end_date).populate_existing().order_by(DomesticOrder.id).all() if ids else []
    items = db.query(DomesticOrderItem).filter(DomesticOrderItem.order_id.in_([r.id for r in orders])).populate_existing().order_by(DomesticOrderItem.id).all() if orders else []
    return orders, items


def _period_facts(orders, items, attrs, payload, start, end):
    order_filters = {key: value for key, value in payload.filters.items() if key in ORDER_FIELDS}
    product_filters = {key: value for key, value in payload.filters.items() if key in PRODUCT_FIELDS}
    headers = [r for r in orders if start <= r.order_date <= end and r.order_kind == "business" and r.deleted_flag == 0 and r.status in (1, 2, 3) and matches({field: getattr(r, field) for field in ORDER_FIELDS}, order_filters)]
    ids = {r.id for r in headers}
    lines = [r for r in items if r.order_id in ids and all(not selected or attrs[r.id][0][field] in selected or attrs[r.id][1][field] in selected for field, selected in product_filters.items())]
    if product_filters:
        matching_order_ids = {r.order_id for r in lines}
        headers = [r for r in headers if r.id in matching_order_ids]
    return headers, lines


def _version(customers, orders, items, attrs, mappings, config, finance, operations, segments):
    customer_fields = ("id", "shop_name", "owner_user_id", "province", "city", "customer_source", "store_type", "settle_mode", "membership_level", "lifecycle_status", "status", "total_order_count", "total_sales_amount", "first_order_date", "last_order_date", "updated_at")
    customer_values = [{field: str(getattr(r, field)) if getattr(r, field) is not None else None for field in customer_fields} for r in customers]
    if finance:
        for row, customer in zip(customer_values, customers):
            row["balance"] = str(customer.balance)
    sources = {"customers": customer_values, "orders": [header_evidence(r, bool(finance)) for r in orders],
               "items": [item_evidence(r, *attrs[r.id]) for r in items],
               "mappings": [{"id": r.id, "property": r.property, "product_type": r.product_type, "raw_value": r.raw_value, "standard_value": r.standard_value, "version": r.version} for r in mappings],
               "config": config, "finance": finance.get("version_evidence") if finance else None,
               "operations": operations["source"], "customer_segments": segments.get("source") if segments else None,
               "metric_version": METRIC_VERSION}
    return hashlib.sha256(json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def build_analysis(db, actor, payload):
    actor = live_actor(db, actor)
    finance_allowed = has_permission(actor, "domestic_decision_finance:read")
    if payload.finance_related_customers and not finance_allowed:
        raise HTTPException(403, "缺少资金阅读权限")
    if not finance_allowed and ({"settle_mode", "membership_level"} & (set(payload.filters) | set(payload.dimensions))):
        raise HTTPException(403, "资金筛选与分组需要资金阅读权限")
    config = config_values(db)
    customers = _selected_customers(db, actor, payload)
    comparison = comparison_period(payload)
    source_orders, all_items = _facts(db, customers, min(payload.end_date, beijing_today()))
    mapping_rows = db.query(DecisionMapping).order_by(DecisionMapping.id).all()
    mappings = {(r.property, r.product_type or "", r.raw_value): r.standard_value for r in mapping_rows}
    attrs = {r.id: item_attributes(r, mappings) for r in all_items}
    operations = load_operations(db, actor, payload, source_orders, all_items, attrs, mappings)
    shipping = in_period(operations["shipping"], payload.start_date, payload.end_date)
    current_orders, current_items = _period_facts(source_orders, all_items, attrs, payload, payload.start_date, payload.end_date)
    previous_orders, previous_items = _period_facts(source_orders, all_items, attrs, payload, *comparison) if comparison else ([], [])
    aftersales = config["aftersales_order_types"]
    summary = aggregate_orders(current_orders, current_items, aftersales)
    previous_summary = aggregate_orders(previous_orders, previous_items, aftersales)
    summary.update(business_order_amount=summary["amount"], recharge_amount=None, **shipping_summary(shipping))
    previous_summary.update(business_order_amount=previous_summary["amount"], recharge_amount=None,
                            **shipping_summary(in_period(operations["shipping"], *comparison) if comparison else []))
    history = [r for r in source_orders if r.order_kind == "business" and r.deleted_flag == 0 and r.status in (1, 2, 3) and decimal(r.total_amount) > 0 and r.order_type not in aftersales]
    selected_customer_rows = customer_rows(customers, current_orders, current_items, history, config, min(payload.end_date, beijing_today()))
    apply_reference_cycles(selected_customer_rows, all_items, history, attrs)
    recommendation_meta = customer_recommendations(selected_customer_rows, all_items, history, attrs, min(payload.end_date, beijing_today()), config["quality_threshold"], config["inactive_lifecycle_statuses"])
    product_filters = {key: values for key, values in payload.filters.items() if key in PRODUCT_FIELDS}
    history_order_map = {order.id: order for order in history}
    risk_customer_ids = {order.customer_id for order in history}
    if product_filters:
        risk_customer_ids = {history_order_map[item.order_id].customer_id for item in all_items if item.order_id in history_order_map and all(not selected or attrs[item.id][0][field] in selected or attrs[item.id][1][field] in selected for field, selected in product_filters.items())}
        visible_customer_ids = risk_customer_ids | {order.customer_id for order in current_orders}
        selected_customer_rows = [row for row in selected_customer_rows if row["customer_id"] in visible_customer_ids]
    for row in selected_customer_rows:
        row["risk_candidate"] = row["customer_id"] in risk_customer_ids
    retention = retention_report(selected_customer_rows, config, payload)
    segments = recharge_segments(db, customers, selected_customer_rows, current_orders, current_items, payload, comparison) if finance_allowed else None
    requested_dimensions = [field for field in DIMENSIONS if finance_allowed or field not in {"settle_mode", "membership_level"}]
    dimensions = {field: dimension_rows(current_items, current_orders, customers, field, attrs, previous_items, previous_orders, payload.metric) for field in requested_dimensions}
    quality = quality_report(current_orders, all_items, current_items, attrs, requested_dimensions, config, [r for r in source_orders if payload.start_date <= r.order_date <= payload.end_date], payload.metric)
    finance_customers = customers
    if payload.finance_related_customers:
        related_ids = {r.customer_id for r in current_orders}
        finance_customers = [r for r in customers if r.id in related_ids]
    finance = build_finance(db, finance_customers, payload, history, config) if finance_allowed else None
    if finance:
        quality["ledger_anomaly_count"] = finance["summary"]["anomaly_count"]
        summary["recharge_amount"] = finance["summary"]["recharge_amount"]
        if comparison:
            related_ids = {r.customer_id for r in previous_orders} if payload.finance_related_customers else {r.id for r in customers}
            previous_summary["recharge_amount"] = number(sum((decimal(entry["amount"]) for entry in segments["source"] if "created_at" in entry and entry["customer_id"] in related_ids and comparison[0].isoformat() <= entry["created_at"][:10] <= comparison[1].isoformat()), decimal(0)))
    trend = []
    coverage_start = date.fromisoformat(config["coverage_start"]) if config["coverage_start"] else None
    config["trend_comparison_complete"] = bool(comparison and coverage_start and coverage_start <= comparison[0])
    daily_shipping = shipping_by_day(shipping)
    daily_recharge = {row["date"]: row["recharge_amount"] for row in finance["trend"]} if finance else {}
    day = payload.start_date
    while day <= payload.end_date:
        point_orders = [r for r in current_orders if r.order_date == day]
        ids = {r.id for r in point_orders}
        point_items = [r for r in current_items if r.order_id in ids]
        covered = bool(coverage_start and coverage_start <= day <= beijing_today())
        if point_orders or covered or day.isoformat() in daily_shipping or day.isoformat() in daily_recharge:
            trend.append({"date": day.isoformat(), "coverage": "confirmed" if covered else "observed", **aggregate_orders(point_orders, point_items, aftersales)})
        else:
            trend.append({"date": day.isoformat(), "coverage": "unconfirmed", "amount": None, "matched_amount": None, "quantity": None, "order_count": None, "customer_count": None})
        trend[-1].update(business_order_amount=trend[-1]["amount"],
                         **daily_shipping.get(day.isoformat(), {"shipped_amount": 0 if covered else None, "shipped_quantity": 0 if covered else None}),
                         recharge_amount=daily_recharge.get(day.isoformat(), 0) if finance else None)
        day += timedelta(days=1)
    current_order_map = {r.id: r for r in current_orders}
    products, production_operations = product_report(current_items, current_orders, operations, payload, config)
    owner_ids = {r.owner_user_id for r in customers if r.owner_user_id is not None}
    users = {r.id: r.real_name for r in db.query(ArkUser).filter(ArkUser.id.in_(owner_ids)).all()} if owner_ids else {}
    salespeople = []
    for owner_id in sorted({r.owner_user_id for r in customers}, key=lambda v: (v is None, v or 0)):
        portfolio = [r for r in selected_customer_rows if r["owner_user_id"] == owner_id]
        salespeople.append({"user_id": owner_id, "name": users.get(owner_id, "未分配"), "attribution_mode": "current_owner",
                           "portfolio_customer_count": len(portfolio), "active_customer_count": sum(r["order_count"] > 0 for r in portfolio),
                           "amount": number(sum((decimal(r["amount"]) for r in portfolio), decimal(0))),
                           "quantity": sum(r["quantity"] for r in portfolio), "order_count": sum(r["order_count"] for r in portfolio),
                           "historical_performance": "unknown_without_owner_snapshot"})
    warnings = ["仅为本公司内贸成交需求样本，不代表全行业市场", "历史订单按当前有效状态重算；未重建当时版本", "业务员归因采用当前客户负责人，历史业绩归属未知"]
    if not coverage_start:
        warnings.append("完整历史覆盖起点未确认；无记录日期不补零，新客和留存仅为系统观察口径")
    if comparison and payload.comparison_mode == "year" and (not coverage_start or coverage_start > comparison[0]):
        warnings.append("同比历史覆盖不完整，不生成强同比趋势结论")
    if quality["order_reconciliation_count"]:
        warnings.append("订单主表额与明细金额存在差异，已分别展示")
    if finance and any(field in PRODUCT_FIELDS for field in payload.filters) and not payload.finance_related_customers:
        warnings.append("资金分析未应用产品筛选；需明确开启按相关客户分析资金")
    data_version = _version(customers, source_orders, all_items, attrs, mapping_rows, config, finance, operations, segments)
    comparison_keys = ["amount", "matched_amount", "quantity", "order_count", "customer_count", "business_order_amount", "shipped_amount"] + (["recharge_amount"] if finance else [])
    result = {"meta": {"customer_ids": [r.id for r in customers], "data_version": data_version,
                       "period": {"start_date": payload.start_date.isoformat(), "end_date": payload.end_date.isoformat()},
                       "comparison_period": {"start_date": comparison[0].isoformat(), "end_date": comparison[1].isoformat()} if comparison else None,
                       "time_basis": "Asia/Shanghai", "attribution_mode": "current_owner", "scope_summary": {"mode": payload.scope, "customer_count": len(customers), "actor_id": actor["id"]},
                       "data_as_of": beijing_now().isoformat(), "coverage_start": config["coverage_start"],
                       "metric_version": METRIC_VERSION, "mapping_version": {str(r.id): r.version for r in mapping_rows}, "rule_version": config["rule_version"],
                       "includes_unassigned_production": operations["includes_unassigned_production"],
                       "config_version": config["config_version"], "sample_size": {"orders": len(current_orders), "items": len(current_items), "customers": len(customers)}, "warnings": warnings},
              "summary": summary, "comparison": {"summary": previous_summary if comparison else None, "changes": {key: change(summary[key], previous_summary[key]) for key in comparison_keys} if comparison else {}},
              "trend": trend, "dimensions": dimensions, "matrix": matrix_rows(current_items, current_orders, customers, payload.dimensions, attrs, payload.metric),
              "price_structure": price_report(current_items), "quantity_structure": quantity_report(current_orders, current_items, all_items), "amount_decomposition": amount_decomposition(summary, previous_summary) if comparison else None,
              "products": products, "production_operations": production_operations, "retention": retention, "customers": selected_customer_rows, "salespeople": salespeople,
              "cohorts": buying_cohorts(selected_customer_rows, min(payload.end_date, beijing_today()), config["coverage_start"]),
              "recommendation_meta": recommendation_meta,
              "quality": quality, "insights": build_insights(selected_customer_rows, dimensions, quality, config, finance),
              "evidence": {"orders": [header_evidence(r, finance_allowed) for r in current_orders], "items": [item_evidence(r, *attrs[r.id]) for r in current_items],
                           "reports": shipping + in_period(operations["supply"], payload.start_date, payload.end_date)}, "metric_registry": METRICS}
    if segments:
        segments.pop("source", None)
        result["customer_segments"] = segments
    if finance:
        finance.pop("version_evidence", None)
        result["finance"] = finance
        result["evidence"]["ledger"] = finance["ledger"]
        result["evidence"]["history_ledger"] = finance["history_ledger"]
        result["evidence"]["requests"] = finance["requests"]
    for item in result["evidence"]["items"]:
        item["customer_id"] = current_order_map[item["order_id"]].customer_id
        if not finance_allowed:
            item.pop("membership_level_snapshot", None)
    result["meta"]["risk_customer_ids"] = sorted(risk_customer_ids)
    result["meta"]["risk_scope_basis"] = "historical_matching_products_full_customer_buying_history" if product_filters else "full_customer_commercial_history"
    result["meta"]["coverage_method"] = quality["coverage_method"]
    result["evidence"]["history_orders"] = [header_evidence(order, finance_allowed) for order in history if order.id not in current_order_map]
    current_item_ids = {item.id for item in current_items}
    result["evidence"]["history_items"] = [{**item_evidence(item, *attrs[item.id]), "customer_id": history_order_map[item.order_id].customer_id} for item in all_items if item.order_id in history_order_map and item.id not in current_item_ids]
    if not finance_allowed:
        for item in result["evidence"]["history_items"]:
            item.pop("membership_level_snapshot", None)
        for customer in result["customers"]:
            customer.pop("settle_mode", None)
            customer.pop("membership_level", None)
    return result


def filter_options(db, actor):
    from app.system.models import SysDict
    actor = live_actor(db, actor)
    customers = customer_query(db, actor).order_by(DomesticCustomer.id).all()
    orders, items = _facts(db, customers, beijing_today())
    mapping_rows = db.query(DecisionMapping).all()
    mappings = {(r.property, r.product_type or "", r.raw_value): r.standard_value for r in mapping_rows}
    values = {field: set() for field in DIMENSIONS}
    finance_allowed = has_permission(actor, "domestic_decision_finance:read")
    for item in items:
        attrs, _ = item_attributes(item, mappings)
        for field in PRODUCT_FIELDS:
            values[field].add(attrs[field])
    for customer in customers:
        for field in CUSTOMER_FIELDS:
            values[field].add(str(getattr(customer, field) or UNKNOWN))
    for order in orders:
        for field in ORDER_FIELDS:
            values[field].add(str(getattr(order, field) or UNKNOWN))
    dictionaries = defaultdict(list)
    for row in db.query(SysDict).filter(SysDict.type.like("domestic_%")).order_by(SysDict.type, SysDict.sort, SysDict.id).all():
        if not finance_allowed and any(part in row.type for part in ("membership", "settle", "recharge")):
            continue
        dictionaries[row.type].append({"value": row.code, "label": row.label, "active": row.is_active})
    owner_ids = {r.owner_user_id for r in customers if r.owner_user_id is not None}
    owners = [{"value": r.id, "label": r.real_name} for r in db.query(ArkUser).filter(ArkUser.id.in_(owner_ids)).order_by(ArkUser.id).all()] if owner_ids else []
    if not finance_allowed:
        values.pop("settle_mode", None)
        values.pop("membership_level", None)
    return {"customers": [{"value": r.id, "label": r.shop_name} for r in customers], "owners": owners,
            "dimensions": {field: [{"value": value, "label": value} for value in sorted(options)] for field, options in values.items()},
            "dictionaries": dict(dictionaries), "metrics": METRICS,
            "permissions": {"finance": has_permission(actor, "domestic_decision_finance:read"), "all": has_permission(actor, "domestic_decision:read_all"), "action": has_permission(actor, "domestic_decision_action:write"), "report": has_permission(actor, "domestic_decision_report:write"), "admin": has_permission(actor, "domestic_decision:admin")}}
