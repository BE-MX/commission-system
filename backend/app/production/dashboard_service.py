"""生产看板数据聚合 service — 批量查询版，零 N+1"""

from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.production.models import (
    Process, OrderProductProcessProgress,
)
from app.stock.models import ProductionOrderItem, ProductionOrder

_BJ_TZ = timezone(timedelta(hours=8))


def _bj_now():
    return datetime.now(_BJ_TZ)


_STATUS_MAP = {0: "pending", 1: "terminated", 2: "completed"}


def get_dashboard_data(db: Session) -> dict:
    """生产看板数据：3 条批量 SQL + 内存聚合，无 N+1"""
    today = _bj_now().date()

    # ── SQL 1: 活跃订单 + 明细 ────────────────────────────────────
    active_orders = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.deleted_flag == 0, ProductionOrder.status == 0)
        .order_by(ProductionOrder.created_at.desc())
        .all()
    )
    if not active_orders:
        return _empty()

    order_ids = [o.id for o in active_orders]
    order_map = {o.id: o for o in active_orders}

    items = (
        db.query(ProductionOrderItem)
        .filter(
            ProductionOrderItem.order_id.in_(order_ids),
            ProductionOrderItem.status != 1,
        )
        .all()
    )

    # ── SQL 2: 工序进度（按 order_product_id 批量查）────────────────
    item_ids = [i.id for i in items]
    progress_rows = []
    if item_ids:
        progress_rows = (
            db.query(
                OrderProductProcessProgress.order_product_id,
                OrderProductProcessProgress.step_order,
                OrderProductProcessProgress.status,
                Process.name.label("process_name"),
            )
            .join(Process, Process.id == OrderProductProcessProgress.process_id)
            .filter(OrderProductProcessProgress.order_product_id.in_(item_ids))
            .order_by(OrderProductProcessProgress.order_product_id, OrderProductProcessProgress.step_order)
            .all()
        )

    # 按 item_id 分组
    progress_by_item = defaultdict(list)
    for row in progress_rows:
        progress_by_item[row.order_product_id].append(row)

    # ── 组装 products ──────────────────────────────────────────────
    items_by_order = defaultdict(list)
    all_products = []

    for item in items:
        steps = progress_by_item.get(item.id, [])
        done_steps = sum(1 for s in steps if s.status == 1)
        total_steps = len(steps)

        current_process = ""
        for s in steps:
            if s.status == 0:
                current_process = s.process_name
                break
        if done_steps == total_steps and total_steps > 0:
            current_process = "完成"

        product = {
            "id": item.id,
            "order_id": order_map[item.order_id].order_no,
            "model": item.model or "",
            "spec_info": item.spec_info or "",
            "order_qty": item.order_qty,
            "received_qty": item.received_qty,
            "status": _STATUS_MAP.get(item.status, "pending"),
            "is_urgent": item.is_urgent,
            "expected_delivery_date": (
                item.expected_delivery_date.isoformat()
                if item.expected_delivery_date else None
            ),
            "current_process": current_process,
            "done_steps": done_steps,
            "process_steps": total_steps,
        }
        items_by_order[item.order_id].append(product)
        all_products.append(product)

    orders_out = []
    for o in active_orders:
        prods = items_by_order.get(o.id, [])
        if prods:
            orders_out.append({"id": o.id, "order_id": o.order_no, "products": prods})

    # ── KPI（内存聚合）─────────────────────────────────────────────
    in_transit = [p for p in all_products if p["status"] != "completed"]
    urgent = [p for p in in_transit if p["is_urgent"] == 1]

    urgent_critical_count = 0
    expiring_7d_count = 0
    for p in in_transit:
        if not p["expected_delivery_date"]:
            continue
        dl = (datetime.strptime(p["expected_delivery_date"], "%Y-%m-%d").date() - today).days
        if p["is_urgent"] == 1 and 0 <= dl <= 3:
            urgent_critical_count += 1
        if 0 <= dl <= 7:
            expiring_7d_count += 1

    wip_models = set(
        p["model"] for p in all_products
        if p["status"] == "pending" and p["process_steps"] > 0 and p["model"]
    )

    # ── SQL 3: 今日完工 ───────────────────────────────────────────
    today_completed = (
        db.query(ProductionOrderItem)
        .filter(
            ProductionOrderItem.status == 2,
            func.date(func.convert_tz(ProductionOrderItem.updated_at, "+00:00", "+08:00")) == today,
        )
        .all()
    )

    # 批量查 order_no
    today_order_ids = list({i.order_id for i in today_completed})
    today_order_map = {}
    if today_order_ids:
        for o in db.query(ProductionOrder).filter(ProductionOrder.id.in_(today_order_ids)).all():
            today_order_map[o.id] = o.order_no

    today_completions = []
    for item in today_completed:
        at = item.updated_at
        time_str = (
            at.replace(tzinfo=timezone.utc).astimezone(_BJ_TZ).strftime("%H:%M")
            if at else ""
        )
        today_completions.append({
            "model": item.model or "",
            "qty": item.received_qty,
            "time": time_str,
            "operator": "",
            "order_id": today_order_map.get(item.order_id, ""),
        })

    # ── SQL 4: 工序完成统计 ───────────────────────────────────────
    process_stats_q = (
        db.query(Process.name, func.count(OrderProductProcessProgress.id))
        .join(Process, Process.id == OrderProductProcessProgress.process_id)
        .filter(OrderProductProcessProgress.status == 1)
        .group_by(Process.id, Process.name)
        .order_by(Process.sort_order)
        .all()
    )

    return {
        "orders": orders_out,
        "kpi": {
            "transit_count": len(in_transit),
            "transit_qty": sum(p["order_qty"] for p in in_transit),
            "urgent_count": len(urgent),
            "urgent_critical_count": urgent_critical_count,
            "today_completed_count": len(today_completed),
            "today_completed_qty": sum(i.received_qty for i in today_completed),
            "expiring_7d_count": expiring_7d_count,
            "wip_model_count": len(wip_models),
        },
        "process_stats": [{"process": n, "count": c} for n, c in process_stats_q],
        "today_completions": today_completions,
    }


def _empty():
    return {
        "orders": [],
        "kpi": {
            "transit_count": 0, "transit_qty": 0,
            "urgent_count": 0, "urgent_critical_count": 0,
            "today_completed_count": 0, "today_completed_qty": 0,
            "expiring_7d_count": 0, "wip_model_count": 0,
        },
        "process_stats": [],
        "today_completions": [],
    }
