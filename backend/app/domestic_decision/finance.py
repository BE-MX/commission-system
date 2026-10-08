"""Read-only account bridges. Wallet credits are never added to order revenue."""

from collections import defaultdict
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from statistics import median

from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.domestic.models import DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision.metrics import decimal, number

ORDER_TYPES = ("order_charge", "order_adjustment", "order_refund")


def _stamp(value):
    return to_beijing_naive(value)


def ledger_evidence(row):
    return {"id": row.id, "customer_id": row.customer_id, "order_id": row.order_id,
            "transaction_type": row.transaction_type, "amount": number(row.amount),
            "balance_before": number(row.balance_before), "balance_after": number(row.balance_after),
            "created_at": _stamp(row.created_at).isoformat(), "operator_user_id": row.created_by}


def request_evidence(row):
    return {"id": row.id, "customer_id": row.customer_id, "request_type": row.request_type,
            "amount": number(row.amount), "status": row.status,
            "created_at": _stamp(row.created_at).isoformat(),
            "reviewed_at": _stamp(row.reviewed_at).isoformat() if row.reviewed_at else None}


def recharge_cohorts(ledger, commercial_orders, end_date, start_date=None):
    """Monthly customer-month anchors and period customer anchors stay separate."""
    anchors = {}
    customer_anchors = {}
    buying = defaultdict(set)
    for order in commercial_orders:
        buying[order.customer_id].add(order.order_date)
    for row in ledger:
        if row.transaction_type != "recharge" or decimal(row.amount) <= 0:
            continue
        day = _stamp(row.created_at).date()
        anchors.setdefault((row.customer_id, day.strftime("%Y-%m")), day)
        if start_date is None or start_date <= day <= end_date:
            customer_anchors.setdefault(row.customer_id, day)

    def observe(values, grain):
        result = []
        for days in (7, 30):
            mature = [(customer_id, day) for customer_id, day in values if (end_date - day).days >= days]
            converted = sum(any(day < purchase <= day + timedelta(days=days) for purchase in buying[customer_id]) for customer_id, day in mature)
            result.append({"window_days": days, "grain": grain, "mature_count": len(mature),
                           "purchase_count": converted, "rate": converted / len(mature) if mature else None,
                           "immature_count": len(values) - len(mature), "same_day_ordering": "unknown_excluded"})
        return result
    months = sorted({month for _, month in anchors if start_date is None or start_date.strftime("%Y-%m") <= month <= end_date.strftime("%Y-%m")})
    return {"monthly": [{"month": month, "observations": observe([(cid, day) for (cid, key), day in anchors.items() if key == month], "customer_month")} for month in months],
            "period_customers": observe(list(customer_anchors.items()), "customer"),
            "limitation": "同日订单只有日期，先后未知，未计入充值后购买"}


def purchase_waiting(recharges, commercial_orders):
    by_customer = defaultdict(list)
    for order in commercial_orders:
        by_customer[order.customer_id].append(order)
    result = []
    for row in recharges:
        day = _stamp(row.created_at).date()
        purchases = sorted([order for order in by_customer[row.customer_id] if order.order_date >= day], key=lambda order: (order.order_date, order.id))
        same_day = bool(purchases and purchases[0].order_date == day)
        next_order = purchases[0] if purchases and not same_day else None
        result.append({"ledger_id": row.id, "customer_id": row.customer_id, "next_order_id": next_order.id if next_order else None,
                       "first_purchase_wait_days": (next_order.order_date - day).days if next_order else None,
                       "status": "same_day_ordering_unknown" if same_day else "observed_next_buying_day" if next_order else "not_observed_yet",
                       "time_grain": "day", "evidence_refs": [{"type": "ledger", "id": row.id}] + ([{"type": "orders", "id": next_order.id}] if next_order else [])})
    return result


def review_metrics(requests, as_of):
    reviewed, pending = [], []
    for row in requests:
        if row.reviewed_at and _stamp(row.reviewed_at) <= as_of:
            seconds = (_stamp(row.reviewed_at) - _stamp(row.created_at)).total_seconds()
            if seconds >= 0:
                reviewed.append(seconds)
        elif row.status == "pending":
            pending.append({"request_id": row.id, "customer_id": row.customer_id, "wait_seconds": max(0, (as_of - _stamp(row.created_at)).total_seconds())})
    ordered = sorted(reviewed)
    return {"reviewed_count": len(ordered), "median_review_seconds": median(ordered) if ordered else None,
            "p90_review_seconds": ordered[max(0, int(len(ordered) * .9 + .999999) - 1)] if ordered else None,
            "pending": pending, "status_basis": "current_request_status_no_historical_replay"}


def coverage_metrics(customer, history, commercial_orders, closing, reliable, as_of, config):
    if customer.settle_mode != "prepay":
        return {"coverage_days": None, "coverage_status": "not_applicable_credit", "coverage_gross_deduction_90d": None, "coverage_purchase_days_90d": None}
    window_start = as_of - timedelta(days=89)
    orders = {order.id: order for order in commercial_orders if order.customer_id == customer.id and order.order_date >= window_start}
    commercial_ids = {order.id for order in commercial_orders if order.customer_id == customer.id}
    purchase_days = len({order.order_date for order in orders.values()})
    account_entries = [entry for entry in history if _stamp(entry.created_at).date() >= window_start and entry.transaction_type in ORDER_TYPES]
    deduction_entries = [entry for entry in account_entries if entry.order_id in commercial_ids]
    gross = -sum((decimal(entry.amount) for entry in deduction_entries if entry.transaction_type in ("order_charge", "order_adjustment") and decimal(entry.amount) < 0), decimal(0))
    # Termination removes orders from demand history but never erases wallet
    # refunds. Inspect every customer return before allowing a consumption rate.
    returns = sum((decimal(entry.amount) for entry in account_entries if entry.transaction_type in ("order_refund", "order_adjustment") and decimal(entry.amount) > 0), decimal(0))
    unclassified_deductions = [entry for entry in account_entries if entry.order_id not in commercial_ids and entry.transaction_type in ("order_charge", "order_adjustment") and decimal(entry.amount) < 0]
    known_window = bool((history and _stamp(history[0].created_at).date() <= window_start) or (config and config.get("coverage_start") and date.fromisoformat(config["coverage_start"]) <= window_start))
    status = "available"
    if not reliable or closing is None or closing < 0:
        status = "account_unverified"
    elif purchase_days < 3:
        status = "insufficient_buying_days"
    elif not known_window:
        status = "incomplete_90day_history"
    elif gross <= 0:
        status = "no_valid_consumption_speed"
    elif returns / gross > decimal((config or {}).get("coverage_refund_ratio_limit", .2)):
        status = "refund_adjustment_variation"
    elif unclassified_deductions:
        status = "unverifiable_commercial_deduction_history"
    return {"coverage_days": number(max(closing, decimal(0)) * 90 / gross) if status == "available" else None,
            "coverage_status": status, "coverage_gross_deduction_90d": number(gross), "coverage_returns_90d": number(returns),
            "coverage_purchase_days_90d": purchase_days, "coverage_window_days": 90,
            "coverage_unclassified_deduction_count_90d": len(unclassified_deductions),
            "coverage_returns_basis": "all_customer_order_refunds_and_positive_order_adjustments",
            "coverage_limitation": "按有效商业订单实际扣款毛额估算；账户全部退款/正向订单调整参与异常检查，未知或非商业订单扣款暂停预测"}


def completed_month_balances(history, as_of):
    """Only recorded month-end ledger states, never today's customer balance."""
    month_start = as_of.replace(day=1)
    last_day = as_of.replace(day=monthrange(as_of.year, as_of.month)[1])
    if as_of < last_day or as_of >= beijing_today():
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    months = []
    for _ in range(3):
        next_month = date(month_start.year + 1, 1, 1) if month_start.month == 12 else date(month_start.year, month_start.month + 1, 1)
        entries = [entry for entry in history if _stamp(entry.created_at).date() < next_month]
        entry = entries[-1] if entries else None
        balance = decimal(entry.balance_after) if entry else None
        months.append({"month": month_start.strftime("%Y-%m"), "closing_balance": number(balance) if balance is not None else None,
                       "debt": number(max(-balance, decimal(0))) if balance is not None else None, "ledger_id": entry.id if entry else None})
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    return list(reversed(months))


def build_finance(db, customers, payload, commercial_orders, config=None):
    start = datetime.combine(payload.start_date, time.min)
    end = min(datetime.combine(payload.end_date + timedelta(days=1), time.min), beijing_now())
    customer_ids = [c.id for c in customers]
    ledger = db.query(DomesticCustomerLedger).filter(DomesticCustomerLedger.customer_id.in_(customer_ids), DomesticCustomerLedger.created_at < end).order_by(DomesticCustomerLedger.created_at, DomesticCustomerLedger.id).all() if customer_ids else []
    requests = db.query(DomesticCustomerRequest).filter(DomesticCustomerRequest.customer_id.in_(customer_ids), DomesticCustomerRequest.created_at < end).order_by(DomesticCustomerRequest.id).all() if customer_ids else []
    grouped = defaultdict(list)
    pending = defaultdict(list)
    for row in ledger:
        grouped[row.customer_id].append(row)
    for row in requests:
        if row.request_type == "recharge" and row.status == "pending":
            pending[row.customer_id].append(row)
    rows, period_entries, anomalies = [], [], []
    for customer in customers:
        history = grouped[customer.id]
        before = [r for r in history if _stamp(r.created_at) < start]
        during = [r for r in history if start <= _stamp(r.created_at) < end]
        period_entries.extend(during)
        opening = decimal(before[-1].balance_after) if before else (decimal(during[0].balance_before) if during else None)
        closing = decimal(history[-1].balance_after) if history else None
        reasons = []
        for index, entry in enumerate(history):
            if decimal(entry.balance_before) + decimal(entry.amount) != decimal(entry.balance_after):
                reasons.append({"type": "entry_arithmetic", "ledger_id": entry.id})
            if index and decimal(history[index - 1].balance_after) != decimal(entry.balance_before):
                reasons.append({"type": "continuity", "ledger_id": entry.id, "previous_ledger_id": history[index - 1].id})
        if opening is None:
            reasons.append({"type": "opening_unknown"})
        movement = sum((decimal(r.amount) for r in during), decimal(0))
        bridge_difference = opening + movement - closing if opening is not None and closing is not None else None
        if bridge_difference is not None and bridge_difference != 0:
            reasons.append({"type": "bridge_difference", "difference": number(bridge_difference)})
        current_difference = None
        if payload.end_date == beijing_today() and closing is not None:
            current_difference = decimal(customer.balance) - closing
            if current_difference:
                reasons.append({"type": "current_balance_difference", "difference": number(current_difference)})
        recharges = [r for r in during if r.transaction_type == "recharge" and decimal(r.amount) > 0]
        all_recharges = [r for r in history if r.transaction_type == "recharge" and decimal(r.amount) > 0]
        recharge_days = sorted({_stamp(r.created_at).date() for r in all_recharges})
        intervals = [(b - a).days for a, b in zip(recharge_days, recharge_days[1:])]
        components = {kind: number(sum((decimal(r.amount) for r in during if r.transaction_type == kind), decimal(0))) for kind in sorted({r.transaction_type for r in during})}
        net_deduction = -sum((decimal(r.amount) for r in during if r.transaction_type in ORDER_TYPES), decimal(0))
        row = {"customer_id": customer.id, "shop_name": customer.shop_name, "settle_mode": customer.settle_mode,
               "opening_balance": number(opening) if opening is not None else None,
               "closing_balance": number(closing) if closing is not None else None,
               "movement": number(movement), "components": components,
               "bridge_components": {"recharge": number(sum((decimal(r.amount) for r in recharges), decimal(0))),
                                     "order_charge": number(-sum((decimal(r.amount) for r in during if r.transaction_type == "order_charge" and decimal(r.amount) < 0), decimal(0))),
                                     "order_adjustment_positive": number(sum((decimal(r.amount) for r in during if r.transaction_type == "order_adjustment" and decimal(r.amount) > 0), decimal(0))),
                                     "order_adjustment_negative": number(-sum((decimal(r.amount) for r in during if r.transaction_type == "order_adjustment" and decimal(r.amount) < 0), decimal(0))),
                                     "order_refund": components.get("order_refund", 0), "init": components.get("init", 0), "adjust": components.get("adjust", 0), "level_adjust": components.get("level_adjust", 0)},
               "positive_balance": number(max(closing, decimal(0))) if closing is not None else None,
               "debt": number(max(-closing, decimal(0))) if closing is not None else None,
               "recharge_amount": number(sum((decimal(r.amount) for r in recharges), decimal(0))),
               "recharge_count": len(recharges), "net_order_deduction": number(net_deduction),
               "debt_improvement": number(sum((min(decimal(r.amount), max(-decimal(r.balance_before), decimal(0))) for r in recharges), decimal(0))),
               "pending_recharge_amount": number(sum((decimal(r.amount) for r in pending[customer.id]), decimal(0))),
               "pending_recharge_count": len(pending[customer.id]), "recharge_cycle_days": median(intervals[-6:]) if len(recharge_days) >= 3 else None,
               "first_recharge_date": recharge_days[0].isoformat() if recharge_days else None,
               "last_recharge_date": recharge_days[-1].isoformat() if recharge_days else None,
               "recharge_recency_days": (min(payload.end_date, beijing_today()) - recharge_days[-1]).days if recharge_days else None,
               "manual_adjustment_count_30d": sum(r.transaction_type == "adjust" and _stamp(r.created_at).date() >= min(payload.end_date, beijing_today()) - timedelta(days=29) for r in history),
               "monthly_balances": completed_month_balances(history, min(payload.end_date, beijing_today())),
               "reliable": not reasons, "anomalies": reasons,
               "bridge_difference": number(bridge_difference) if bridge_difference is not None else None,
               "current_reconciliation_difference": number(current_difference) if current_difference is not None else None,
               "evidence_refs": [{"type": "ledger", "id": r.id} for r in during]}
        row.update(coverage_metrics(customer, history, commercial_orders, closing, not reasons, min(payload.end_date, beijing_today()), config))
        rows.append(row)
        anomalies.extend({"customer_id": customer.id, **reason} for reason in reasons)
    recharges = [r for r in period_entries if r.transaction_type == "recharge" and decimal(r.amount) > 0]
    trend = defaultdict(lambda: {"amount": decimal(0), "customers": set(), "count": 0})
    for row in recharges:
        point = trend[_stamp(row.created_at).date().isoformat()]
        point["amount"] += decimal(row.amount)
        point["customers"].add(row.customer_id)
        point["count"] += 1
    summary = {"recharge_amount": number(sum((decimal(r.amount) for r in recharges), decimal(0))),
               "recharge_count": len(recharges), "recharge_customer_count": len({r.customer_id for r in recharges}),
               "net_order_deduction": number(sum((decimal(r["net_order_deduction"]) for r in rows), decimal(0))),
               "positive_balance": number(sum((decimal(r["positive_balance"]) for r in rows), decimal(0))),
               "debt": number(sum((decimal(r["debt"]) for r in rows), decimal(0))),
               "unknown_balance_customer_count": sum(r["closing_balance"] is None for r in rows),
               "pending_recharge_amount": number(sum((decimal(r["pending_recharge_amount"]) for r in rows), decimal(0))),
               "pending_recharge_count": sum(r["pending_recharge_count"] for r in rows), "anomaly_count": len(anomalies)}
    summary["net_balance"] = number(decimal(summary["positive_balance"]) - decimal(summary["debt"]))
    summary["balance_scope"] = "known_balances_only" if summary["unknown_balance_customer_count"] else "all_selected_customers"
    summary["opening_balance"] = number(sum((decimal(r["opening_balance"]) for r in rows), decimal(0))) if rows and all(r["opening_balance"] is not None for r in rows) else None
    summary["closing_balance"] = number(sum((decimal(r["closing_balance"]) for r in rows), decimal(0))) if rows and all(r["closing_balance"] is not None for r in rows) else None
    summary["bridge_components"] = {key: number(sum((decimal(r["bridge_components"][key]) for r in rows), decimal(0))) for key in ("recharge", "order_charge", "order_adjustment_positive", "order_adjustment_negative", "order_refund", "init", "adjust", "level_adjust")}
    summary["funds_use_ratio"] = summary["net_order_deduction"] / summary["recharge_amount"] if summary["recharge_amount"] > 0 else None
    return {"summary": summary, "customers": rows, "trend": [{"date": day, "recharge_amount": number(point["amount"]), "recharge_count": point["count"], "customer_count": len(point["customers"])} for day, point in sorted(trend.items())],
            "ledger": [ledger_evidence(r) for r in period_entries], "requests": [request_evidence(r) for r in requests if _stamp(r.created_at) >= start or r.status == "pending"],
            "history_ledger": [ledger_evidence(r) for r in ledger if _stamp(r.created_at) < start],
            "anomalies": anomalies, "cohorts": recharge_cohorts(ledger, commercial_orders, min(payload.end_date, beijing_today()), payload.start_date),
            "recharge_purchase_waiting": purchase_waiting(recharges, commercial_orders), "review_metrics": review_metrics(requests, end),
            "scope_semantics": "related_customers" if payload.finance_related_customers else "customer_scope_product_filters_ignored",
            "historical_request_status": "current_status_no_historical_replay", "as_of": end.isoformat(),
            "version_evidence": [ledger_evidence(r) for r in ledger] + [request_evidence(r) for r in requests]}
