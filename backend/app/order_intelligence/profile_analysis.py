"""客户画像、画像级复购规律和基于画像基准的返单预警。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Iterable


AMPLITUDES = ("16", "18", "20", "22", "24")
MIN_PROFILE_FIRST_RETURN_CUSTOMERS = 3
MIN_PROFILE_REPEAT_CUSTOMERS = 3
MIN_PROFILE_REPEAT_INTERVALS = 5
MIN_CUSTOMER_REPEAT_INTERVALS = 3
_MODEL_FAMILY_PATTERN = {
    family: re.compile(rf"(^|[^A-Z0-9]){family}([^A-Z0-9]|$)")
    for family in ("B1", "B3")
}
NEW_SIGN_MODEL_REASON_LABELS = {
    "matched_b1_b3": "首张新签型号命中 B1/B3",
    "no_new_sign_order": "历史订单未标记新签",
    "no_order_items": "首张新签无商品明细",
    "missing_model": "首张新签型号缺失",
    "other_model": "首张新签为非 B1/B3 型号",
}


def normalize_customer_nature(raw: object) -> str:
    value = " ".join(str(raw or "").split()).strip()
    return "未知" if value in {"", "无"} else value


def _model_values(rows: Iterable[dict]) -> list[str]:
    values = []
    for row in rows:
        # 每条明细只取一个最高优先级来源，避免结构化 B1 与旧名称 B3
        # 被错误合并成 B1+B3；“未知”则继续向后回退。
        selected = ""
        for key in ("filter_model", "model", "product_model"):
            value = str(row.get(key) or "").strip()
            if value and value != "未知":
                selected = value
                break
        if not selected:
            selected = str(row.get("product_name") or "").split("/", 1)[0].strip()
        if selected and selected != "未知":
            values.append(selected)
    return values


def model_family(rows: Iterable[dict]) -> str:
    matched = set()
    for value in _model_values(rows):
        value = value.upper()
        for family, pattern in _MODEL_FAMILY_PATTERN.items():
            if pattern.search(value):
                matched.add(family)
    if matched == {"B1", "B3"}:
        return "B1+B3"
    if matched:
        return next(iter(matched))
    return "其他/未知"


def new_sign_model_classification(
    rows: Iterable[dict],
    has_new_sign_order: bool,
) -> tuple[str, str]:
    """返回画像型号族及可解释的归类原因码。"""
    product_rows = list(rows)
    if not has_new_sign_order:
        return "其他/未知", "no_new_sign_order"
    if not product_rows:
        return "其他/未知", "no_order_items"
    family = model_family(product_rows)
    if family != "其他/未知":
        return family, "matched_b1_b3"
    if not _model_values(product_rows):
        return family, "missing_model"
    return family, "other_model"


def amplitude(row: dict) -> str | None:
    value = str(row.get("size") or "").strip()
    match = re.search(r"(?<!\d)(16|18|20|22|24)(?!\d)", value)
    return match.group(1) if match else None


def _distribution(
    rows: Iterable[dict],
    key: str,
    limit: int = 5,
) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        name = str(row.get(key) or "未知").strip() or "未知"
        counts[name] += max(0, int(row.get("quantity") or 0))
    total = sum(counts.values())
    return [
        {
            "name": name,
            "quantity": quantity,
            "share": round(quantity / total * 100, 1) if total else 0,
        }
        for name, quantity in counts.most_common(limit)
    ]


def _model_family_distribution(rows: Iterable[dict]) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        value = model_family([row])
        counts[value] += max(0, int(row.get("quantity") or 0))
    total = sum(counts.values())
    ordered = ("B1", "B3", "其他/未知")
    return [
        {
            "name": value,
            "quantity": counts[value],
            "share": round(counts[value] / total * 100, 1) if total else 0,
        }
        for value in ordered
    ]


def _amplitude_distribution(rows: Iterable[dict]) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        value = amplitude(row)
        if value:
            counts[value] += max(0, int(row.get("quantity") or 0))
    total = sum(counts.values())
    return [
        {
            "name": value,
            "quantity": counts[value],
            "share": round(counts[value] / total * 100, 1) if total else 0,
        }
        for value in AMPLITUDES
    ]


def _profile_id(key: tuple[str, str, str, str]) -> str:
    return hashlib.sha1("\x1f".join(key).encode("utf-8")).hexdigest()[:12]


def _order_sort_key(row: dict) -> tuple[date, tuple[int, int | str]]:
    order_id = str(row.get("order_id") or "")
    sequence: tuple[int, int | str] = (
        (0, int(order_id)) if order_id.isdigit() else (1, order_id)
    )
    return row["account_date"], sequence


def _evidence(interval_count: int, customer_count: int) -> str:
    if interval_count >= 30 and customer_count >= 10:
        return "high"
    if interval_count >= 10 or customer_count >= 3:
        return "medium"
    return "low"


def _robust_cycle(
    values: Iterable[float | int],
    minimum_days: int = 1,
) -> int | None:
    samples = list(values)
    if not samples:
        return None
    return max(minimum_days, int(round(float(median(samples)))))


def _resolve_customer_cycle(stats: dict, benchmark: dict) -> tuple[int | None, str, str]:
    profile_cycle = benchmark["typical_repeat_cycle_days"]
    if profile_cycle is not None:
        return profile_cycle, "profile_robust", benchmark["evidence_level"]
    intervals = stats["intervals"]
    if len(intervals) >= MIN_CUSTOMER_REPEAT_INTERVALS:
        return _robust_cycle(intervals), "customer_robust", _evidence(len(intervals), 1)
    return None, "insufficient_data", "low"


def analyze_customer_profiles(
    history_orders: Iterable[dict],
    history_products: Iterable[dict],
    period_orders: Iterable[dict],
    period_products: Iterable[dict],
    as_of: date,
    source_labels: dict[str, str],
    alert_company_ids: set[str] | None = None,
    include_cycles: bool = True,
) -> dict:
    """画像基准使用截至 as_of 的完整历史；畅销分布只使用选定统计周期。"""
    history = list(history_orders)
    products = list(history_products)
    current_orders = list(period_orders)
    current_products = list(period_products)
    orders_by_company: dict[str, list[dict]] = defaultdict(list)
    products_by_company: dict[str, list[dict]] = defaultdict(list)
    for row in history:
        if row.get("company_id"):
            orders_by_company[row["company_id"]].append(row)
    for row in products:
        if row.get("company_id"):
            products_by_company[row["company_id"]].append(row)

    customer_nature_by_company: dict[str, str] = {}
    for company_id, rows in orders_by_company.items():
        known = [
            normalize_customer_nature(row.get("customer_nature"))
            for row in sorted(rows, key=_order_sort_key)
            if normalize_customer_nature(row.get("customer_nature")) != "未知"
        ]
        customer_nature_by_company[company_id] = known[-1] if known else "未知"

    company_profiles: dict[str, tuple[str, str, str, str]] = {}
    company_model_reasons: dict[str, str] = {}
    company_stats: dict[str, dict] = {}
    profile_companies: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for company_id, rows in orders_by_company.items():
        rows.sort(key=_order_sort_key)
        company_products = products_by_company[company_id]
        new_orders = [row for row in rows if row.get("new_deal") == "是"]
        first_new_order_id = str(new_orders[0]["order_id"]) if new_orders else None
        new_products = [
            row for row in company_products
            if first_new_order_id is not None and str(row.get("order_id")) == first_new_order_id
        ]
        acquisition_order = new_orders[0] if new_orders else rows[0]
        new_sign_family, model_reason = new_sign_model_classification(
            new_products,
            bool(new_orders),
        )
        key = (
            rows[-1].get("country") or "未知",
            acquisition_order.get("source_category") or "unknown",
            customer_nature_by_company[company_id],
            new_sign_family,
        )
        dates = sorted({row["account_date"] for row in rows if row["account_date"] <= as_of})
        intervals = [
            (right - left).days
            for left, right in zip(dates, dates[1:])
            if right > left
        ]
        first_return_cycle = None
        if new_orders:
            first_new_order = new_orders[0]
            first_new_index = rows.index(first_new_order)
            first_return_order = next(
                (
                    row for row in rows[first_new_index + 1:]
                    if row.get("first_return") == "是"
                ),
                None,
            )
            if first_return_order:
                # account_date 只有日粒度；同日后续首返保留为 0 天。
                first_return_cycle = (
                    first_return_order["account_date"] - first_new_order["account_date"]
                ).days
        company_profiles[company_id] = key
        company_model_reasons[company_id] = model_reason
        profile_companies[key].append(company_id)
        company_stats[company_id] = {
            "rows": rows,
            "dates": dates,
            "intervals": intervals,
            "first_return_cycle": first_return_cycle,
        }

    profile_benchmarks = {}
    for key, company_ids in profile_companies.items():
        intervals = [
            days for company_id in company_ids
            for days in company_stats[company_id]["intervals"]
        ]
        customer_typical_intervals = [
            median(company_stats[company_id]["intervals"])
            for company_id in company_ids
            if company_stats[company_id]["intervals"]
        ]
        first_returns = [
            company_stats[company_id]["first_return_cycle"]
            for company_id in company_ids
            if company_stats[company_id]["first_return_cycle"] is not None
        ]
        interval_customers = sum(bool(company_stats[company_id]["intervals"]) for company_id in company_ids)
        typical_cycle = (
            _robust_cycle(customer_typical_intervals)
            if (
                interval_customers >= MIN_PROFILE_REPEAT_CUSTOMERS
                and len(intervals) >= MIN_PROFILE_REPEAT_INTERVALS
            )
            else None
        )
        typical_first_return_cycle = (
            _robust_cycle(first_returns, minimum_days=0)
            if len(first_returns) >= MIN_PROFILE_FIRST_RETURN_CUSTOMERS
            else None
        )
        profile_benchmarks[key] = {
            # avg_repeat_cycle_days 保留兼容旧前端/API，语义已改为稳健典型周期。
            "avg_repeat_cycle_days": typical_cycle,
            "typical_repeat_cycle_days": typical_cycle,
            "repeat_cycle_method": (
                "median_of_customer_medians" if typical_cycle is not None
                else "insufficient_profile_sample"
            ),
            "repeat_interval_count": len(intervals),
            "repeat_customer_count": interval_customers,
            # avg_first_return_cycle_days 保留兼容旧前端/API，语义已改为稳健典型周期。
            "avg_first_return_cycle_days": typical_first_return_cycle,
            "typical_first_return_cycle_days": typical_first_return_cycle,
            "first_return_cycle_method": (
                "median" if typical_first_return_cycle is not None
                else "insufficient_profile_sample"
            ),
            "first_return_sample_count": len(first_returns),
            "evidence_level": _evidence(len(intervals), interval_customers),
        }

    period_company_ids = {
        row["company_id"] for row in current_orders if row.get("company_id") in company_profiles
    }
    period_orders_by_profile: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    period_products_by_profile: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in current_orders:
        key = company_profiles.get(row.get("company_id"))
        if key:
            period_orders_by_profile[key].append(row)
    for row in current_products:
        key = company_profiles.get(row.get("company_id"))
        if key:
            period_products_by_profile[key].append(row)

    items = []
    for key in sorted({company_profiles[company_id] for company_id in period_company_ids}):
        country, source_code, customer_nature, new_sign_family = key
        peer_ids = profile_companies[key]
        repeat_products = [
            row for company_id in peer_ids for row in products_by_company[company_id]
            if row.get("new_deal") == "否"
        ]
        profile_period_orders = period_orders_by_profile[key]
        profile_period_products = period_products_by_profile[key]
        active_ids = {row["company_id"] for row in profile_period_orders if row.get("company_id")}
        benchmark = profile_benchmarks[key]
        model_reason_counts = Counter(company_model_reasons[company_id] for company_id in peer_ids)
        model_reason_items = [
            {
                "code": code,
                "label": NEW_SIGN_MODEL_REASON_LABELS[code],
                "customer_count": count,
            }
            for code, count in model_reason_counts.most_common()
        ]
        items.append({
            "profile_id": _profile_id(key),
            "profile_label": " · ".join((country, source_labels.get(source_code, source_code), customer_nature, new_sign_family)),
            "country": country,
            "source_code": source_code,
            "source_label": source_labels.get(source_code, source_code),
            "customer_nature": customer_nature,
            "new_sign_model_family": new_sign_family,
            "new_sign_model_reason_counts": model_reason_items,
            "new_sign_model_reason_summary": "；".join(
                f"{item['label']} {item['customer_count']}"
                for item in model_reason_items
            ),
            "active_customer_count": len(active_ids),
            "peer_customer_count": len(peer_ids),
            "period_orders": len(profile_period_orders),
            "period_amount_usd": round(sum(float(row.get("amount_usd") or 0) for row in profile_period_orders), 2),
            **benchmark,
            "repeat_models": _distribution(repeat_products, "model"),
            "repeat_amplitudes": _amplitude_distribution(repeat_products),
            "period_best_sellers": _distribution(profile_period_products, "product_name"),
            "period_models": _model_family_distribution(profile_period_products),
            "period_colors": _distribution(profile_period_products, "color"),
            "period_amplitudes": _amplitude_distribution(profile_period_products),
        })
    items.sort(key=lambda item: (item["period_amount_usd"], item["period_orders"]), reverse=True)
    summary = {
        "active_customer_count": len(period_company_ids),
        "profile_count": len(items),
        "customer_nature_coverage": round(
            sum(company_profiles[company_id][2] != "未知" for company_id in period_company_ids)
            / len(period_company_ids) * 100,
            1,
        ) if period_company_ids else 0,
        "new_sign_b1_b3_coverage": round(
            sum(company_profiles[company_id][3] != "其他/未知" for company_id in period_company_ids)
            / len(period_company_ids) * 100,
            1,
        ) if period_company_ids else 0,
        "repeat_cycle_coverage": round(
            sum(
                _resolve_customer_cycle(
                    company_stats[company_id],
                    profile_benchmarks[company_profiles[company_id]],
                )[0] is not None
                for company_id in period_company_ids
            ) / len(period_company_ids) * 100,
            1,
        ) if period_company_ids else 0,
    }

    cycles = {}
    if not include_cycles:
        return {
            "items": items,
            "total": len(items),
            "summary": summary,
            "customer_cycles": cycles,
            "definitions": _definitions(),
        }
    for company_id in (alert_company_ids if alert_company_ids is not None else period_company_ids):
        if company_id not in company_stats:
            continue
        stats = company_stats[company_id]
        rows = stats["rows"]
        key = company_profiles[company_id]
        benchmark = profile_benchmarks[key]
        cycle_days, cycle_source, cycle_evidence = _resolve_customer_cycle(stats, benchmark)
        last_date = stats["dates"][-1]
        elapsed_days = max(0, (as_of - last_date).days)
        if cycle_days is None:
            risk = "insufficient_data"
            expected_date = None
            abnormal_date = None
        else:
            expected_date = last_date + timedelta(days=cycle_days)
            # 状态规则是严格超过 2 倍才异常，2 倍边界当天仍为 due。
            abnormal_date = last_date + timedelta(days=cycle_days * 2 + 1)
            if elapsed_days > cycle_days * 2:
                risk = "abnormal"
            elif elapsed_days >= cycle_days:
                risk = "due"
            else:
                risk = "healthy"
        cycles[company_id] = {
            "company_id": company_id,
            "company_name": rows[-1].get("company_name") or "",
            "country": rows[-1].get("country") or "未知",
            "customer_nature": customer_nature_by_company[company_id],
            "user_id": rows[-1].get("user_id") or "",
            "user_name": rows[-1].get("user_name") or "",
            "team": rows[-1].get("team") or "",
            "order_count": len(rows),
            "lifetime_amount_usd": round(sum(float(row.get("amount_usd") or 0) for row in rows), 2),
            "typical_cycle_days": cycle_days,
            "cycle_source": cycle_source,
            "cycle_evidence": cycle_evidence,
            "profile_id": _profile_id(key),
            "profile_label": " · ".join((key[0], source_labels.get(key[1], key[1]), key[2], key[3])),
            "new_sign_model_family": key[3],
            "profile_peer_customers": len(profile_companies[key]),
            "profile_repeat_interval_count": benchmark["repeat_interval_count"],
            "top_models": _distribution(products_by_company[company_id], "model", 2),
            "top_colors": _distribution(products_by_company[company_id], "color", 2),
            "last_order_date": last_date,
            "expected_order_date": expected_date,
            "abnormal_date": abnormal_date,
            "days_since_last_order": elapsed_days,
            "days_to_expected": (expected_date - as_of).days if expected_date else None,
            "overdue_days": max(0, (as_of - expected_date).days) if expected_date else 0,
            "risk_status": risk,
        }

    return {
        "items": items,
        "total": len(items),
        "summary": summary,
        "customer_cycles": cycles,
        "definitions": _definitions(),
    }


def _definitions() -> dict[str, str]:
    return {
        "profile": "最近国家 + 首张新签订单来源 + customer_info.trail_status_name + 新签订单 B1/B3 型号组合",
        "first_return_cycle": "首张新签订单至后续首张明确标记“首返=是”订单的天数，同日计 0 天；同画像至少 3 位首返客户后取中位数，降低异常长周期影响",
        "repeat_cycle": "先取每位客户连续有效下单间隔的中位数，再取同画像客户中位数；画像至少需 3 位复购客户且累计 5 个间隔",
        "alert": "达到稳健典型周期即提醒，严格超过 2 倍标记异常；画像样本不足时，仅对拥有至少 3 个历史间隔的客户使用其个人中位数，否则不强预警",
        "period_distribution": "畅销产品、型号、颜色及 16/18/20/22/24 幅度按统计期订单明细 quantity 汇总",
    }
