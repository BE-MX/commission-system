"""Frozen analysis evidence with live authorization and source-version checks."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from app.core.time import beijing_now
from app.domestic_decision import analytics, scope
from app.domestic_decision.models import DecisionRun
from app.domestic_decision.schemas import AnalysisRequest
from app.domestic_decision.insight_service import enrich
from app.domestic_decision.schemas import PRODUCT_FIELDS
from app.domestic_decision.metrics import METRIC_VERSION

SORT_FIELDS = {
    "reports": {"id", "item_id", "order_id", "customer_id", "process_name", "reported_at", "report_qty", "amount"},
    "orders": {"id", "domestic_no", "order_date", "customer_id", "order_category", "order_type", "status", "total_amount"},
    "items": {"id", "order_id", "order_qty", "unit_price", "amount", *[f"attrs.{field}" for field in PRODUCT_FIELDS]},
    "customers": {"customer_id", "shop_name", "amount", "matched_amount", "history.cycle_status"},
    "ledger": {"id", "customer_id", "order_id", "transaction_type", "amount", "balance_before", "balance_after", "created_at"},
    "requests": {"id", "customer_id", "request_type", "amount", "status", "created_at"},
}


def has(actor, permission):
    return "super_admin" in actor.get("roles", []) or permission in actor.get("permissions", [])


def create_run(db, actor, query):
    result = enrich(analytics.build_analysis(db, actor, query))
    run_id = str(uuid4())
    result["meta"]["run_id"] = run_id
    row = DecisionRun(
        id=run_id, owner_user_id=actor["id"], query_json=query.model_dump(mode="json"),
        result_json=result, scope_customer_ids=result["meta"]["customer_ids"],
        includes_finance=int("finance" in result), data_version=result["meta"]["data_version"],
        created_at=beijing_now(), expires_at=beijing_now() + timedelta(days=1),
    )
    db.add(row)
    db.commit()
    return result


def require_run(db, actor, run_id, *, fresh=False, allow_expired=False):
    row = db.query(DecisionRun).filter(DecisionRun.id == run_id, DecisionRun.owner_user_id == actor["id"]).first()
    if row is None:
        raise HTTPException(404, "分析结果不存在")
    if row.result_json.get("meta", {}).get("metric_version") != METRIC_VERSION:
        raise HTTPException(409, "统计口径已更新，请重新分析")
    if not allow_expired and row.expires_at <= beijing_now():
        raise HTTPException(410, "分析已过期，请刷新")
    visible = {customer.id for customer in scope.customer_query(db, actor).all()}
    if not set(row.scope_customer_ids).issubset(visible):
        raise HTTPException(403, "客户归属或权限已变化，请重新分析")
    if row.includes_finance and not has(actor, "domestic_decision_finance:read"):
        raise HTTPException(403, "资金阅读权限已变化，请重新分析")
    if row.result_json.get("meta", {}).get("includes_unassigned_production") and not (has(actor, "domestic_decision:read_all") and has(actor, "domestic:read_all")):
        raise HTTPException(403, "生产订单阅读权限已变化，请重新分析")
    if fresh:
        latest = analytics.build_analysis(db, actor, AnalysisRequest.model_validate(row.query_json))
        if latest["meta"]["data_version"] != row.data_version:
            raise HTTPException(409, "源数据已变化，请刷新整组分析后下钻")
    return row


def rows(db, actor, run_id, *, kind="orders", page=1, page_size=50, customer_id=None, order_id=None, dimension=None, value=None, sort_field=None, sort_order=None):
    row = require_run(db, actor, run_id, fresh=True)
    if kind not in {"orders", "items", "customers", "ledger", "requests", "reports"}:
        raise HTTPException(422, "证据类型不支持")
    if (sort_field is not None and sort_field not in SORT_FIELDS[kind]) or sort_order not in {None, "asc", "desc"} or bool(sort_field) != bool(sort_order):
        raise HTTPException(422, "排序字段或方向不支持")
    if kind in {"ledger", "requests"} and not has(actor, "domestic_decision_finance:read"):
        raise HTTPException(403, "需要资金阅读权限")
    data = row.result_json.get("customers", []) if kind == "customers" else row.result_json["evidence"].get(kind, [])
    if customer_id is not None:
        scope.require_customer(db, actor, customer_id)
        data = [item for item in data if item.get("customer_id", item.get("id") if kind == "customers" else None) == customer_id]
    if order_id is not None:
        data = [item for item in data if item.get("order_id", item.get("id") if kind == "orders" else None) == order_id]
    if dimension:
        if kind == "reports":
            raise HTTPException(422, "报工证据请按客户、订单或事实引用下钻")
        if dimension not in row.result_json.get("dimensions", {}):
            raise HTTPException(422, "维度不支持")
        # Restrict whole-order evidence by matching item IDs, preserving the
        # explicit distinction between matching lines and related whole orders.
        headers = {item["id"]: item for item in row.result_json["evidence"].get("orders", [])}
        customers = {item["customer_id"]: item for item in row.result_json.get("customers", [])}
        def group_value(item):
            values = {**customers.get(item.get("customer_id"), {}), **headers.get(item["order_id"], {}), **item.get("attrs", {})}
            return str(values.get(dimension) or "未知")
        matched = [item for item in row.result_json["evidence"].get("items", []) if group_value(item) == value]
        ids = {item["id"] for item in matched}
        order_ids = {item["order_id"] for item in matched}
        customer_ids = {item["customer_id"] for item in matched}
        if kind == "items":
            data = [item for item in data if item["id"] in ids]
        elif kind == "orders":
            data = [item for item in data if item["id"] in order_ids]
        else:
            data = [item for item in data if item.get("customer_id", item.get("id")) in customer_ids]
    if sort_field:
        def get_value(item):
            current = item
            for key in sort_field.split("."):
                current = current.get(key) if isinstance(current, dict) else None
            return current
        present = [item for item in data if get_value(item) not in (None, "", "—")]
        missing = [item for item in data if get_value(item) in (None, "", "—")]
        def stable_id(item):
            return item.get("id", item.get("customer_id", 0))
        def value_key(item):
            value = get_value(item)
            return (0, value) if isinstance(value, (int, float)) else (1, str(value).casefold())
        # The complete frozen authorized result is sorted before slicing.
        present.sort(key=stable_id)
        present.sort(key=value_key, reverse=sort_order == "desc")
        data = present + sorted(missing, key=stable_id)
    start = (page - 1) * page_size
    return {"items": deepcopy(data[start:start + page_size]), "total": len(data), "page": page, "page_size": page_size, "meta": row.result_json["meta"]}
