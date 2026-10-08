"""Customer history uses commercial buying days, independent of current filters."""

from collections import defaultdict
from datetime import date, timedelta
from calendar import monthrange
import hashlib
from statistics import median

from fastapi import HTTPException
from app.auth.models import ArkUser
from app.core.time import beijing_today
from app.domestic_decision.metrics import decimal, number
from app.domestic_decision.scope import live_actor, require_customer, has_permission


def customer_rows(customers, period_orders, period_items, commercial_history, config, as_of):
    history_by_customer = defaultdict(list)
    period_by_customer = defaultdict(list)
    items_by_customer = defaultdict(list)
    order_customers = {r.id: r.customer_id for r in period_orders}
    for order in commercial_history:
        history_by_customer[order.customer_id].append(order)
    for order in period_orders:
        period_by_customer[order.customer_id].append(order)
    for item in period_items:
        items_by_customer[order_customers[item.order_id]].append(item)
    result = []
    for customer in customers:
        orders = sorted(history_by_customer[customer.id], key=lambda r: (r.order_date, r.id))
        dates = sorted({r.order_date for r in orders})
        annual_days = [d for d in dates if d >= as_of - timedelta(days=364)]
        intervals = [(b - a).days for a, b in zip(annual_days, annual_days[1:])]
        cycle = median(intervals[-6:]) if len(annual_days) >= 4 else None
        recency = (as_of - dates[-1]).days if dates else None
        half_year = [r for r in orders if r.order_date >= as_of - timedelta(days=179)]
        period = period_by_customer[customer.id]
        items = items_by_customer[customer.id]
        coverage_start = date.fromisoformat(config["coverage_start"]) if config["coverage_start"] else None
        recorded_amount = sum((decimal(r.total_amount) for r in orders), decimal(0))
        archival_precedes = bool(dates and customer.first_order_date and customer.first_order_date < dates[0])
        archival_exceeds = (customer.total_order_count is not None and customer.total_order_count > len(orders)) or (customer.total_sales_amount is not None and decimal(customer.total_sales_amount) > recorded_amount)
        history_complete = bool(coverage_start and coverage_start <= as_of - timedelta(days=364) and (not dates or coverage_start <= dates[0]) and not archival_precedes and not archival_exceeds)
        stage = "sample_accumulating"
        if cycle and recency is not None:
            stage = "demand_check" if recency > 2 * cycle else "delayed" if recency > 1.5 * cycle else "repurchase_window" if recency >= cycle else "active"
        history = {"purchase_days": len(dates), "purchase_dates": [d.isoformat() for d in dates],
                   "system_amount": number(sum((decimal(r.total_amount) for r in orders), decimal(0))),
                   "commercial_order_count": len(orders), "first_purchase_date": dates[0].isoformat() if dates else None,
                   "last_purchase_date": dates[-1].isoformat() if dates else None, "recency_days": recency,
                   "cycle_days": cycle, "cycle_status": stage, "cycle_min_purchase_days": 4,
                   "cycle_sample_days": len(annual_days), "history_complete": history_complete,
                   "annual_window_complete": bool(coverage_start and coverage_start <= as_of - timedelta(days=364)),
                   "first_purchase_status": "historical_customer_entered_system" if archival_precedes or archival_exceeds else "system_first_purchase_in_confirmed_coverage" if history_complete else "first_observed_purchase_not_verified_new",
                   "history_limitations": ([] if history_complete else ["完整覆盖未覆盖观察窗口，或历史档案提示系统记录前已有购买；系统首单不能视为真实新客"]),
                   "archival_amount": number(customer.total_sales_amount) if customer.total_sales_amount is not None else None,
                   "archival_order_count": customer.total_order_count,
                   "rfm": {"r": recency, "f": len({r.order_date for r in half_year}), "m": number(sum((decimal(r.total_amount) for r in half_year), decimal(0))), "window_days": 180, "scores": None, "peer_count": 0, "status": "insufficient_peer_sample"},
                   "windows": {str(days): {"amount": number(sum((decimal(r.total_amount) for r in orders if r.order_date >= as_of - timedelta(days=days - 1)), decimal(0))), "purchase_days": len({r.order_date for r in orders if r.order_date >= as_of - timedelta(days=days - 1)})} for days in (30, 90, 180, 365)},
                   "evidence_refs": [{"type": "orders", "id": r.id} for r in orders]}
        result.append({"customer_id": customer.id, "shop_name": customer.shop_name,
                       "owner_user_id": customer.owner_user_id, "province": customer.province,
                       "city": customer.city, "store_type": customer.store_type,
                       "customer_source": customer.customer_source, "settle_mode": customer.settle_mode,
                       "membership_level": customer.membership_level, "lifecycle_status": customer.lifecycle_status,
                       "status": customer.status,
                       "amount": number(sum((decimal(r.total_amount) for r in period), decimal(0))),
                       "matched_amount": number(sum((decimal(r.unit_price) * r.order_qty for r in items), decimal(0))),
                       "quantity": sum(r.order_qty for r in items), "order_count": len(period),
                       "history": history, "labels": [stage] if dates else ["no_system_purchase"]})
    peers = defaultdict(list)
    for row in result:
        if row["history"]["rfm"]["r"] is not None:
            peers[(row["settle_mode"], row["store_type"])].append(row)
    for group in peers.values():
        for row in group:
            rfm = row["history"]["rfm"]
            rfm["peer_count"] = len(group)
            rfm["cohort_fields"] = ["settle_mode", "store_type"]
            if len(group) < 30:
                continue
            rfm["scores"] = {key: min(5, 1 + int(5 * sum((other["history"]["rfm"][key] > rfm[key]) if key == "r" else (other["history"]["rfm"][key] < rfm[key]) for other in group) / len(group))) for key in ("r", "f", "m")}
            rfm["status"] = "available"
            rfm["method"] = "empirical_quintiles_strict_comparison_ties_same_score"
    return sorted(result, key=lambda r: (-r["amount"], r["customer_id"]))


def apply_reference_cycles(rows, items, commercial_orders, attrs):
    """Sparse individuals may use 20 equally weighted valid peer cycles."""
    order_customer = {r.id: r.customer_id for r in commercial_orders}
    quantities = defaultdict(lambda: defaultdict(int))
    for item in items:
        if item.order_id in order_customer:
            product_type = attrs[item.id][0]["product_type"]
            if product_type in ("cap", "piece"):
                quantities[order_customer[item.order_id]][product_type] += item.order_qty
    cohorts = defaultdict(list)
    for row in rows:
        history = row["history"]
        values = quantities[row["customer_id"]]
        primary = max(values, key=lambda key: (values[key], key)) if values else None
        history["main_product_type"] = primary
        history["cycle_basis"] = "individual" if history["cycle_days"] else "insufficient_sample"
        history["cycle_peer_count"] = 0
        if history["cycle_days"] and primary:
            cohorts[(row["settle_mode"], row["store_type"], primary)].append(history["cycle_days"])
    for row in rows:
        history = row["history"]
        if history["cycle_days"] or history["recency_days"] is None or not history["main_product_type"]:
            continue
        peers = cohorts[(row["settle_mode"], row["store_type"], history["main_product_type"])]
        history["cycle_peer_count"] = len(peers)
        if len(peers) >= 20:
            history["cycle_days"] = median(peers)
            history["cycle_basis"] = "peer_reference"
            cycle, recency = history["cycle_days"], history["recency_days"]
            history["cycle_status"] = "demand_check" if recency > 2 * cycle else "delayed" if recency > 1.5 * cycle else "repurchase_window" if recency >= cycle else "active"
            row["labels"] = [history["cycle_status"]]


def buying_cohorts(rows, as_of, coverage_start):
    groups = defaultdict(list)
    for row in rows:
        dates = row["history"]["purchase_dates"]
        if dates:
            groups[dates[0][:7]].append(row)
    result = []
    for month, customers in sorted(groups.items()):
        mature = [r for r in customers if (as_of - date.fromisoformat(r["history"]["first_purchase_date"])).days >= 30]
        retained = sum(any(0 < (date.fromisoformat(d) - date.fromisoformat(r["history"]["first_purchase_date"])).days <= 30 for d in r["history"]["purchase_dates"][1:]) for r in mature)
        observations = []
        for window in (30, 60, 90):
            eligible = [r for r in customers if (as_of - date.fromisoformat(r["history"]["first_purchase_date"])).days >= window]
            repeated = sum(any(0 < (date.fromisoformat(d) - date.fromisoformat(r["history"]["first_purchase_date"])).days <= window for d in r["history"]["purchase_dates"][1:]) for r in eligible)
            observations.append({"window_days": window, "mature_count": len(eligible), "second_purchase_count": repeated, "rate": repeated / len(eligible) if eligible else None, "immature_count": len(customers) - len(eligible)})
        first_month = date.fromisoformat(month + "-01")
        next_month_start = date(first_month.year + 1, 1, 1) if first_month.month == 12 else date(first_month.year, first_month.month + 1, 1)
        next_month_end = next_month_start.replace(day=monthrange(next_month_start.year, next_month_start.month)[1])
        next_month_mature = as_of >= next_month_end
        next_month_repeated = sum(any(next_month_start <= date.fromisoformat(d) <= next_month_end for d in r["history"]["purchase_dates"]) for r in customers) if next_month_mature else 0
        result.append({"month": month, "observed_first_customers": len(customers), "mature_30d_count": len(mature), "second_purchase_30d_count": retained, "second_purchase_30d_rate": retained / len(mature) if mature else None, "immature_count": len(customers) - len(mature), "observations": observations,
                       "historical_customer_count": sum(r["history"]["first_purchase_status"] == "historical_customer_entered_system" for r in customers),
                       "verified_new_customer_count": 0, "basis": "system_first_observed_purchase", "history_complete": all(r["history"]["history_complete"] for r in customers),
                       "next_month": {"month": next_month_start.strftime("%Y-%m"), "mature_count": len(customers) if next_month_mature else 0, "purchase_count": next_month_repeated, "rate": next_month_repeated / len(customers) if next_month_mature and customers else None},
                       "limitation": "仅统计系统首次观察后的复购；历史客户首次入系统单列，不作为真实新客留存。缺少可回放的首次购买事件，真实新客留存禁用。"})
    return result


def customer_profile(db, actor, customer_id, payload):
    from app.domestic_decision.analytics import build_analysis
    actor = live_actor(db, actor)
    require_customer(db, actor, customer_id)
    request = payload.model_copy(update={"customer_ids": [customer_id], "owner_ids": [], "filters": {}, "scope": "all" if has_permission(actor, "domestic_decision:read_all") else "mine"})
    result = build_analysis(db, actor, request)
    benchmark_request = request.model_copy(update={"customer_ids": []})
    benchmark = build_analysis(db, actor, benchmark_request)
    target = next(row for row in result["customers"] if row["customer_id"] == customer_id)
    benchmark_customer = next(row for row in benchmark["customers"] if row["customer_id"] == customer_id)
    target["history"]["rfm"] = benchmark_customer["history"]["rfm"]
    for field in ("cycle_days", "cycle_basis", "cycle_peer_count", "cycle_status"):
        target["history"][field] = benchmark_customer["history"][field]
    target["labels"] = benchmark_customer["labels"]
    target["preferences"] = benchmark_customer["preferences"]
    target["recommendations"] = benchmark_customer["recommendations"]
    result["meta"]["data_version"] = hashlib.sha256((result["meta"]["data_version"] + benchmark["meta"]["data_version"]).encode()).hexdigest()
    result["meta"]["benchmark_basis"] = "full_authorized_current_portfolio_same_cohort"
    result["insights"] = [insight for insight in benchmark["insights"] if insight["customer_id"] == customer_id] + [insight for insight in result["insights"] if insight["customer_id"] is None]
    return {"customer": next(row for row in result["customers"] if row["customer_id"] == customer_id), "meta": result["meta"], "preferences": result["dimensions"], "trend": result["trend"], "insights": result["insights"], "quality": result["quality"], "evidence": result["evidence"], **({"finance": result["finance"]} if "finance" in result else {})}


def salesperson_profile(db, actor, user_id, payload):
    from app.domestic_decision.analytics import build_analysis
    actor = live_actor(db, actor)
    if user_id != actor["id"] and not has_permission(actor, "domestic_decision:read_all"):
        raise HTTPException(404, "业务员不存在或不在当前范围")
    user = db.query(ArkUser).filter(ArkUser.id == user_id, ArkUser.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(404, "业务员不存在或不在当前范围")
    request = payload.model_copy(update={"owner_ids": [user_id], "customer_ids": [], "scope": "all" if has_permission(actor, "domestic_decision:read_all") else "mine"})
    result = build_analysis(db, actor, request)
    return {"user_id": user_id, "name": user.real_name, "attribution_mode": "current_owner", "historical_performance": "unavailable_without_owner_events", "meta": result["meta"], "summary": result["summary"], "customers": result["customers"], "products": result["products"], "trend": result["trend"], "insights": result["insights"], "evidence": result["evidence"], **({"finance": result["finance"]} if "finance" in result else {})}
