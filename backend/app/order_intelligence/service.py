"""订单经营智能分析服务。

底层数字由确定性 SQL/Python 计算，AI 只负责综合解读。订单有效口径沿用采购节：
排除私人订单，计入已结束订单以及状态为已结清的终止订单。
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter, OrderedDict, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from app.core.time import beijing_today
from statistics import median
from threading import RLock
from time import monotonic
from typing import Iterable, Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.core.config import get_settings
from app.order_intelligence.filtering import (
    AnalysisFilters,
    color_expression,
    group_countries,
    model_expression,
    order_sql,
    product_sql,
)
from app.order_intelligence.profile_analysis import analyze_customer_profiles

logger = logging.getLogger("order_intelligence")

NEW_DEAL_FIELD = "22595163468"
FIRST_RETURN_FIELD = "20528142733548"
RESOURCE_SOURCE_FIELD = "45285192666116"

SOURCE_LABELS = {
    "alibaba_inquiry": "阿里询盘",
    "alibaba_ecosystem": "阿里生态",
    "social_owned": "社媒自主开发",
    "social_assigned": "社媒分配",
    "referral": "转介绍",
    "website": "官网询盘",
    "other": "其他",
    "unknown": "未知",
}

_PROFILE_CACHE_TTL_SECONDS = 300
_PROFILE_CACHE_MAX_ENTRIES = 8
_PROFILE_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_PROFILE_CACHE_LOCK = RLock()
_FILTER_CACHE_TTL_SECONDS = 300
_FILTER_CACHE_MAX_ENTRIES = 16
_FILTER_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_FILTER_CACHE_LOCK = RLock()

ORDER_STATUS_ENDED = "13972831656"
ORDER_STATUS_TERMINATED = "13972831654"
ORDER_STATUS_SETTLED_NAME = "已结清"

VALID_ORDER_SQL = f"""
    ({{a}}.status = '{ORDER_STATUS_ENDED}'
     OR ({{a}}.status = '{ORDER_STATUS_TERMINATED}' AND {{a}}.status_name = '{ORDER_STATUS_SETTLED_NAME}'))
    AND ({{a}}.trail IS NULL OR CAST({{a}}.trail AS CHAR) NOT LIKE '%个人%')
"""


def is_valid_business_order(status, status_name, trail) -> bool:
    """Apply the same effective-order rule used by ``VALID_ORDER_SQL``."""
    if not isinstance(status, str) or not status:
        return False
    if trail is not None and "个人" in str(trail):
        return False
    return status == ORDER_STATUS_ENDED or (
        status == ORDER_STATUS_TERMINATED
        and isinstance(status_name, str)
        and status_name == ORDER_STATUS_SETTLED_NAME
    )


@dataclass(frozen=True)
class AnalysisScope:
    mode: Literal["self", "all", "filtered"]
    user_id: str | None
    team: str | None
    can_read_all: bool


def classify_source(raw: str | None) -> str:
    """把 OKKI 多选来源归一为互斥经营渠道；自主开发优先于平台归因。"""
    value = (raw or "").strip().casefold()
    if not value:
        return "unknown"
    if any(mark in value for mark in ("熟人介绍", "转介绍", "referral")):
        return "referral"
    if any(mark in value for mark in ("ins开发", "社媒开发", "社交平台", "facebook", "tiktok")):
        return "social_owned"
    if any(mark in value for mark in ("ins分配", "社媒分配")):
        return "social_assigned"
    if any(mark in value for mark in ("官网询盘", "website")):
        return "website"
    if any(mark in value for mark in ("阿里询盘", "tm咨询", "国际站名片", "rfq")):
        return "alibaba_inquiry"
    if any(mark in value for mark in ("阿里巴巴", "alibaba", "信保订单")):
        return "alibaba_ecosystem"
    return "other"


def _decorate_order(row: dict) -> dict:
    source_raw = str(row.get("source_raw") or row.get("origin_name") or "")
    row["new_deal"] = str(row.get("new_deal") or "").strip()
    row["first_return"] = str(row.get("first_return") or "").strip()
    row["source_raw"] = source_raw
    row["source_category"] = classify_source(source_raw)
    row["country"] = (row.get("country_name") or "").strip()
    if row["country"] in {"", "0"}:
        row["country"] = "未知"
    row["amount_usd"] = float(row.get("amount_usd") or 0)
    row["company_id"] = str(row.get("company_id") or "")
    row["user_id"] = str(row.get("user_id") or "")
    return row


def resolve_scope(
    db: Session,
    current_user: dict,
    requested_user_id: str | None = None,
    requested_team: str | None = None,
) -> AnalysisScope:
    permissions = set(current_user.get("permissions") or [])
    roles = set(current_user.get("roles") or [])
    can_read_all = "order_intelligence:read_all" in permissions or "super_admin" in roles
    if can_read_all:
        return AnalysisScope(
            "filtered" if requested_user_id or requested_team else "all",
            requested_user_id or None,
            requested_team or None,
            True,
        )

    try:
        ark_user_id = int(current_user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(422, "当前登录账号无法识别，请重新登录") from None
    binding = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id)
        .first()
    )
    okki_user_id = str(binding.external_account_id).strip() if binding else ""
    if not okki_user_id:
        raise HTTPException(422, "当前账号尚未绑定 OKKI 业务员，请联系管理员配置")
    if requested_user_id and str(requested_user_id) != okki_user_id:
        raise HTTPException(403, "无权查看其他业务员的订单分析")
    return AnalysisScope("self", okki_user_id, None, False)


def normalize_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or beijing_today()
    start = date_from or (end - timedelta(days=364))
    if start > end:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    if (end - start).days > 1095:
        raise HTTPException(422, "单次分析区间不能超过 3 年")
    return start, end


def _scope_sql(scope: AnalysisScope, alias: str = "o") -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if scope.user_id:
        clauses.append(f"{alias}.user_id = :scope_user_id")
        params["scope_user_id"] = scope.user_id
    if scope.team:
        clauses.append("rt.Team = :scope_team")
        params["scope_team"] = scope.team
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def _load_orders(
    db: Session,
    scope: AnalysisScope,
    date_from: date | None = None,
    date_to: date | None = None,
    filters: AnalysisFilters | None = None,
) -> list[dict]:
    schema = get_settings().BUSINESS_DB_NAME
    filters = filters or AnalysisFilters()
    scope_clause, params = _scope_sql(scope)
    date_clause = ""
    if date_from is not None:
        date_clause += " AND o.account_date >= :date_from"
        params["date_from"] = date_from
    if date_to is not None:
        date_clause += " AND o.account_date <= :date_to"
        params["date_to"] = date_to
    filter_clause = order_sql(filters, params, schema)
    new_deal_expression = (
        f"JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, '$.\\\"{NEW_DEAL_FIELD}\\\"'))"
    )
    first_return_expression = (
        f"JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, '$.\\\"{FIRST_RETURN_FIELD}\\\"'))"
    )
    source_expression = (
        f"COALESCE(NULLIF(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, "
        f"'$.\\\"{RESOURCE_SOURCE_FIELD}\\\"')), ''), 'null'), ci.origin_name, '')"
    )
    sql = f"""
        SELECT o.order_id, o.order_no, o.account_date, o.amount_usd, o.company_id,
               o.user_id, {new_deal_expression} new_deal,
               {first_return_expression} first_return,
               {source_expression} source_raw,
               ci.company_name, ci.country_name,
               ci.origin_name, ci.trail_status_name customer_nature,
               COALESCE(rt.Name, ub.full_name, o.user_id) user_name,
               COALESCE(rt.Team, '') team, COALESCE(rt.Camp, '') camp
        FROM `{schema}`.okki_orders o
        LEFT JOIN `{schema}`.customer_info ci ON ci.company_id = o.company_id
        LEFT JOIN `{schema}`.user_rel_team rt ON rt.user_id = o.user_id
        LEFT JOIN `{schema}`.user_basic ub ON ub.user_id = o.user_id
        WHERE {VALID_ORDER_SQL.format(a='o')}
          {date_clause} {scope_clause} {filter_clause}
        ORDER BY o.account_date, o.order_id
    """
    rows = [_decorate_order(dict(row)) for row in db.execute(text(sql), params).mappings()]
    if filters.sources:
        allowed_sources = set(filters.sources)
        rows = [row for row in rows if row["source_category"] in allowed_sources]
    return rows


def _load_product_rows(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    filters: AnalysisFilters | None = None,
) -> list[dict]:
    schema = get_settings().BUSINESS_DB_NAME
    filters = filters or AnalysisFilters()
    scope_clause, params = _scope_sql(scope)
    params.update({"date_from": date_from, "date_to": date_to})
    order_filter_clause = order_sql(filters, params, schema)
    product_filter_clause = product_sql(filters, params)
    new_deal_expression = (
        f"JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, '$.\\\"{NEW_DEAL_FIELD}\\\"'))"
    )
    source_expression = (
        f"COALESCE(NULLIF(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, "
        f"'$.\\\"{RESOURCE_SOURCE_FIELD}\\\"')), ''), 'null'), ci.origin_name, '')"
    )
    sql = f"""
        SELECT o.order_id, o.company_id, o.user_id, o.account_date,
               COALESCE(NULLIF(ci.country_name, ''), '未知') country,
               oi.product_name, oi.product_model,
               {model_expression('oi', 'p')} model,
               {model_expression('oi', 'p', False)} filter_model,
               {color_expression('oi', 'p')} color,
               p.size, oi.quantity,
               {new_deal_expression} new_deal,
               {source_expression} source_raw
        FROM `{schema}`.okki_orders o
        JOIN `{schema}`.okki_order_items oi ON oi.order_id = o.order_id
        LEFT JOIN `{schema}`.customer_info ci ON ci.company_id = o.company_id
        LEFT JOIN `{schema}`.user_rel_team rt ON rt.user_id = o.user_id
        LEFT JOIN `{schema}`.okki_products p ON p.product_id = oi.product_id
        WHERE {VALID_ORDER_SQL.format(a='o')}
          AND o.account_date >= :date_from AND o.account_date <= :date_to
          {scope_clause} {order_filter_clause} {product_filter_clause}
    """
    rows = []
    for source in db.execute(text(sql), params).mappings():
        row = dict(source)
        parts = [part.strip() for part in str(row.get("product_name") or "").split("/")]
        row["model"] = (row.get("model") or (parts[0] if parts else "") or "未知").strip()
        row["color"] = (row.get("color") or (parts[-2] if len(parts) >= 3 else "") or "未知").strip()
        row["size"] = (row.get("size") or (parts[1] if len(parts) >= 2 else "") or "未知").strip()
        row["quantity"] = int(row.get("quantity") or 0)
        row["company_id"] = str(row.get("company_id") or "")
        row["user_id"] = str(row.get("user_id") or "")
        row["new_deal"] = str(row.get("new_deal") or "").strip()
        row["source_category"] = classify_source(str(row.get("source_raw") or ""))
        if row["country"] in {"", "0"}:
            row["country"] = "未知"
        if not filters.sources or row["source_category"] in filters.sources:
            rows.append(row)
    return rows


def _percent_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _aggregate(orders: Iterable[dict]) -> dict:
    rows = list(orders)
    positive = [r["amount_usd"] for r in rows if r["amount_usd"] > 0]
    customers = {r["company_id"] for r in rows if r["company_id"]}
    new_customers = {r["company_id"] for r in rows if r["new_deal"] == "是" and r["company_id"]}
    repeat_rows = [r for r in rows if r["new_deal"] == "否"]
    repeat_customers = {r["company_id"] for r in repeat_rows if r["company_id"]}
    first_return_customers = {
        r["company_id"] for r in rows if r["first_return"] == "是" and r["company_id"]
    }
    return {
        "orders": len(rows),
        "customers": len(customers),
        "new_sign_customers": len(new_customers),
        "repeat_customers": len(repeat_customers),
        "repeat_orders": len(repeat_rows),
        "first_return_customers": len(first_return_customers),
        "repurchase_rate": (
            round(len(first_return_customers) / len(new_customers) * 100, 1)
            if new_customers else 0
        ),
        "repeat_customer_rate": round(len(repeat_customers) / len(customers) * 100, 1) if customers else 0,
        "amount_usd": round(sum(r["amount_usd"] for r in rows), 2),
        "repeat_amount_usd": round(sum(r["amount_usd"] for r in repeat_rows), 2),
        "avg_order_amount_usd": round(sum(positive) / len(positive), 2) if positive else 0,
        "median_order_amount_usd": round(float(median(positive)), 2) if positive else 0,
        "non_positive_orders": sum(r["amount_usd"] <= 0 for r in rows),
    }


def _month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def _monthly_trend(
    orders: Iterable[dict],
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in orders:
        grouped[_month_key(row["account_date"])].append(row)
    if date_from is not None and date_to is not None:
        month = date_from.replace(day=1)
        last_month = date_to.replace(day=1)
        while month <= last_month:
            grouped.setdefault(_month_key(month), [])
            month = (
                month.replace(year=month.year + 1, month=1)
                if month.month == 12
                else month.replace(month=month.month + 1)
            )
    return [{"month": month, **_aggregate(rows)} for month, rows in sorted(grouped.items())]


def _source_mix(
    orders: Iterable[dict],
    previous_orders: Iterable[dict] | None = None,
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in orders:
        grouped[row["source_category"]].append(row)
    total = sum(len(rows) for rows in grouped.values())
    previous_counts: Counter = Counter()
    previous_total = 0
    if previous_orders is not None:
        previous_counts.update(row["source_category"] for row in previous_orders)
        previous_total = sum(previous_counts.values())
    result = []
    for code, rows in grouped.items():
        stat = _aggregate(rows)
        item = {
            "code": code,
            "label": SOURCE_LABELS[code],
            "orders": stat["orders"],
            "customers": stat["customers"],
            "new_sign_customers": stat["new_sign_customers"],
            "amount_usd": stat["amount_usd"],
            "order_share": round(stat["orders"] / total * 100, 1) if total else 0,
        }
        if previous_orders is not None:
            previous_share = round(previous_counts[code] / previous_total * 100, 1) if previous_total else 0
            item.update({
                "previous_order_share": previous_share,
                "share_change_pp": round(item["order_share"] - previous_share, 1),
            })
        result.append(item)
    return sorted(result, key=lambda item: (item["new_sign_customers"], item["amount_usd"]), reverse=True)


def _amount_distribution(orders: Iterable[dict]) -> list[dict]:
    buckets = [
        ("0–500", 0, 500), ("500–2K", 500, 2_000), ("2K–5K", 2_000, 5_000),
        ("5K–10K", 5_000, 10_000), ("10K–50K", 10_000, 50_000),
        ("50K+", 50_000, math.inf),
    ]
    result = []
    positive = [r for r in orders if r["amount_usd"] > 0]
    for label, low, high in buckets:
        selected = [r for r in positive if low < r["amount_usd"] <= high]
        result.append({
            "label": label,
            "orders": len(selected),
            "amount_usd": round(sum(r["amount_usd"] for r in selected), 2),
            "share": round(len(selected) / len(positive) * 100, 1) if positive else 0,
        })
    return result


def _amount_distribution_with_change(current: Iterable[dict], previous: Iterable[dict]) -> list[dict]:
    result = _amount_distribution(current)
    previous_distribution = {item["label"]: item for item in _amount_distribution(previous)}
    for item in result:
        previous_item = previous_distribution[item["label"]]
        item["previous_share"] = previous_item["share"]
        item["share_change_pp"] = round(item["share"] - previous_item["share"], 1)
    return result


def _top_attributes(
    rows: Iterable[dict],
    key: str,
    limit: int = 3,
    previous_rows: Iterable[dict] | None = None,
) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        value = str(row.get(key) or "未知").strip() or "未知"
        counts[value] += max(0, int(row.get("quantity") or 0))
    previous_counts: Counter = Counter()
    if previous_rows is not None:
        for row in previous_rows:
            value = str(row.get(key) or "未知").strip() or "未知"
            previous_counts[value] += max(0, int(row.get("quantity") or 0))
    result = []
    for name, qty in counts.most_common(limit):
        item = {"name": name, "quantity": qty}
        if previous_rows is not None:
            previous_qty = previous_counts[name]
            item.update({
                "previous_quantity": previous_qty,
                "quantity_growth": _percent_change(qty, previous_qty),
            })
        result.append(item)
    return result


def _profile_analysis(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    analysis_filters: AnalysisFilters,
    period_orders: list[dict] | None = None,
    period_products: list[dict] | None = None,
    alert_company_ids: set[str] | None = None,
    include_cycles: bool = True,
) -> dict:
    """画像历史限定到截至期末，统计期筛选只决定本期入选客户和商品分布。"""
    cache_key = (
        scope.mode,
        scope.user_id,
        scope.team,
        scope.can_read_all,
        date_from.isoformat(),
        date_to.isoformat(),
        tuple(analysis_filters.countries),
        tuple(analysis_filters.models),
        tuple(analysis_filters.colors),
        tuple(analysis_filters.sources),
        tuple(sorted(alert_company_ids)) if alert_company_ids is not None else None,
        include_cycles,
    )
    now = monotonic()
    with _PROFILE_CACHE_LOCK:
        cached = _PROFILE_CACHE.get(cache_key)
        if cached and cached[0] > now:
            _PROFILE_CACHE.move_to_end(cache_key)
            return deepcopy(cached[1])
        if cached:
            _PROFILE_CACHE.pop(cache_key, None)

    history_orders = _load_orders(db, scope, None, date_to)
    history_products = _load_product_rows(
        db,
        scope,
        min((row["account_date"] for row in history_orders), default=date_to),
        date_to,
    )
    if include_cycles and alert_company_ids is None:
        alert_orders = (
            history_orders
            if analysis_filters.is_empty()
            else _load_orders(db, scope, None, date_to, analysis_filters)
        )
        alert_company_ids = {
            row["company_id"] for row in alert_orders if row.get("company_id")
        }
    result = analyze_customer_profiles(
        history_orders,
        history_products,
        (
            period_orders
            if period_orders is not None
            else _load_orders(db, scope, date_from, date_to, analysis_filters)
        ),
        (
            period_products
            if period_products is not None
            else _load_product_rows(db, scope, date_from, date_to, analysis_filters)
        ),
        date_to,
        SOURCE_LABELS,
        alert_company_ids,
        include_cycles,
    )
    with _PROFILE_CACHE_LOCK:
        _PROFILE_CACHE[cache_key] = (monotonic() + _PROFILE_CACHE_TTL_SECONDS, deepcopy(result))
        _PROFILE_CACHE.move_to_end(cache_key)
        while len(_PROFILE_CACHE) > _PROFILE_CACHE_MAX_ENTRIES:
            _PROFILE_CACHE.popitem(last=False)
    return result


def _clear_profile_cache() -> None:
    """清空进程内画像缓存，供测试和订单同步链路显式失效使用。"""
    with _PROFILE_CACHE_LOCK:
        _PROFILE_CACHE.clear()


def _forecast_next_month(rows: list[dict]) -> tuple[float | None, str]:
    monthly = _monthly_trend(rows)
    amounts = [float(item["amount_usd"]) for item in monthly]
    if len(amounts) < 3:
        return None, "insufficient_data"
    recent = amounts[-3:]
    weighted = (recent[0] + recent[1] * 2 + recent[2] * 3) / 6
    growth = (recent[-1] - recent[0]) / max(abs(recent[0]), 1) / 2
    growth = max(-0.3, min(0.5, growth))
    return round(max(0, weighted * (1 + growth)), 2), "weighted_3m_trend"


def _minmax(values: list[float], value: float) -> float:
    if not values or max(values) == min(values):
        return 50.0
    return (value - min(values)) / (max(values) - min(values)) * 100


def _marketing_advice(row: dict) -> dict:
    source = row.get("top_source_code")
    models = "、".join(item["name"] for item in row.get("top_models", [])[:2]) or "已有优势产品"
    colors = "、".join(item["name"] for item in row.get("top_colors", [])[:2]) or "当地高频色"
    if row["customers"] < 5:
        return {
            "channel": "small_test",
            "title": "小预算验证，不宜放大",
            "action": f"样本仅 {row['customers']} 个成交客户，先用 {models} × {colors} 做窄受众测试并补齐询盘归因。",
        }
    if source in {"social_owned", "social_assigned"}:
        channel = "social"
        title = "优先社媒定向扩量"
        action = f"围绕 {models} 与 {colors} 建立本地化素材组，复用成交受众做相似人群测试。"
    elif source in {"alibaba_inquiry", "alibaba_ecosystem"}:
        channel = "alibaba"
        title = "优先强化阿里定向承接"
        action = f"围绕 {models} 与 {colors} 优化关键词、主图和询盘首响，按复购金额而非仅询盘量评估。"
    else:
        channel = "mixed_test"
        title = "阿里与社媒双通道对照测试"
        action = f"用同一组 {models} × {colors} 素材做双通道小预算测试，以有效询盘→新签→90天复购闭环判胜。"
    return {"channel": channel, "title": title, "action": action}


def get_filter_options(
    db: Session,
    scope: AnalysisScope,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    cache_key = (
        scope.mode,
        scope.user_id,
        scope.team,
        scope.can_read_all,
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    now = monotonic()
    with _FILTER_CACHE_LOCK:
        cached = _FILTER_CACHE.get(cache_key)
        if cached and cached[0] > now:
            _FILTER_CACHE.move_to_end(cache_key)
            return deepcopy(cached[1])
        if cached:
            _FILTER_CACHE.pop(cache_key, None)

    history = _load_orders(db, scope, date_from, date_to)
    if history:
        products = _load_product_rows(
            db,
            scope,
            min(row["account_date"] for row in history),
            max(row["account_date"] for row in history),
        )
    else:
        products = []
    users_by_id = {}
    for row in history:
        if row["user_id"]:
            users_by_id[row["user_id"]] = {
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "team": row["team"],
            }
    countries = sorted({r["country"] for r in history})
    result = {
        "can_read_all": scope.can_read_all,
        "scope": scope.mode,
        "teams": sorted({r["team"] for r in history if r["team"]}),
        "users": sorted(
            users_by_id.values(),
            key=lambda item: (item["team"], item["user_name"]),
        ),
        "countries": countries,
        "country_tree": group_countries(countries),
        # 筛选值只使用明确的产品型号字段，避免把 product_name 片段误作型号。
        "models": sorted({r["filter_model"] for r in products}),
        "colors": sorted({r["color"] for r in products}),
        "source_categories": [{"code": code, "label": label} for code, label in SOURCE_LABELS.items()],
    }
    with _FILTER_CACHE_LOCK:
        _FILTER_CACHE[cache_key] = (monotonic() + _FILTER_CACHE_TTL_SECONDS, deepcopy(result))
        _FILTER_CACHE.move_to_end(cache_key)
        while len(_FILTER_CACHE) > _FILTER_CACHE_MAX_ENTRIES:
            _FILTER_CACHE.popitem(last=False)
    return result


def _clear_filter_cache() -> None:
    """清空进程内筛选项缓存，供测试和订单同步链路显式失效使用。"""
    with _FILTER_CACHE_LOCK:
        _FILTER_CACHE.clear()


def get_customer_profile_analysis(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    analysis_filters: AnalysisFilters | None = None,
) -> dict:
    result = _profile_analysis(
        db,
        scope,
        date_from,
        date_to,
        analysis_filters or AnalysisFilters(),
        # 与总览/国家/人员分析共用同一缓存键，对外仍不返回客户明细。
        include_cycles=True,
    )
    result.pop("customer_cycles", None)
    return result


def get_customer_order_timeline(
    db: Session,
    scope: AnalysisScope,
    company_id: str,
    date_from: date,
    date_to: date,
    *,
    limit: int = 50,
) -> dict:
    """Return a scoped, deterministic order timeline for one OKKI company."""
    target = str(company_id or "").strip()
    if not target:
        raise ValueError("company_id 不能为空")
    rows = [
        row for row in _load_orders(db, scope, date_from, date_to)
        if row["company_id"] == target
    ]
    rows.sort(key=lambda item: (item["account_date"], item["order_id"]), reverse=True)
    visible = rows[:max(1, min(limit, 100))]
    return {
        "company_id": target,
        "customer_name": rows[0]["company_name"] if rows else None,
        "window": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "summary": {
            "orders": len(rows),
            "amount_usd": round(sum(item["amount_usd"] for item in rows), 2),
            "first_order_date": rows[-1]["account_date"].isoformat() if rows else None,
            "last_order_date": rows[0]["account_date"].isoformat() if rows else None,
        },
        "items": [{
            "order_id": item["order_id"],
            "order_no": item["order_no"],
            "account_date": item["account_date"].isoformat(),
            "amount_usd": item["amount_usd"],
            "new_deal": item["new_deal"],
            "first_return": item["first_return"],
            "source_category": item["source_category"],
            "country": item["country"],
        } for item in visible],
        "truncated": len(rows) > len(visible),
        "definition": "仅含当前账号数据范围内的有效 OKKI 订单；排除私人订单和非有效状态订单",
    }


def get_customer_repurchase_analysis(
    db: Session,
    scope: AnalysisScope,
    company_id: str,
    date_from: date,
    date_to: date,
) -> dict:
    """Return the existing deterministic customer-cycle result for one company."""
    target = str(company_id or "").strip()
    if not target:
        raise ValueError("company_id 不能为空")
    result = _profile_analysis(db, scope, date_from, date_to, AnalysisFilters())
    cycle = result["customer_cycles"].get(target)
    if cycle is None:
        return {
            "company_id": target,
            "found": False,
            "window": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "reason": "当前数据范围和分析窗口内没有足够的有效订单证据",
            "definitions": result["definitions"],
        }
    item = deepcopy(cycle)
    for key in ("last_order_date", "expected_order_date", "abnormal_date"):
        if item.get(key) is not None:
            item[key] = item[key].isoformat()
    return {
        "company_id": target,
        "found": True,
        "window": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "analysis": item,
        "definitions": result["definitions"],
    }


def get_overview(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    analysis_filters: AnalysisFilters | None = None,
    profile_result: dict | None = None,
) -> dict:
    analysis_filters = analysis_filters or AnalysisFilters()
    orders = _load_orders(db, scope, date_from, date_to, analysis_filters)
    days = (date_to - date_from).days + 1
    previous_to = date_from - timedelta(days=1)
    previous_from = previous_to - timedelta(days=days - 1)
    previous = _load_orders(db, scope, previous_from, previous_to, analysis_filters)
    current_stats = _aggregate(orders)
    previous_stats = _aggregate(previous)
    products = _load_product_rows(db, scope, date_from, date_to, analysis_filters)
    previous_products = _load_product_rows(db, scope, previous_from, previous_to, analysis_filters)
    profile_analysis = profile_result or _profile_analysis(
        db, scope, date_from, date_to, analysis_filters, orders, products, None,
    )
    cycles = profile_analysis["customer_cycles"]
    actionable = [
        item for item in cycles.values()
        if item["risk_status"] in {"due", "abnormal"}
    ]
    forecast, forecast_method = _forecast_next_month(orders)
    current_stats["changes"] = {
        "amount_usd": _percent_change(current_stats["amount_usd"], previous_stats["amount_usd"]),
        "new_sign_customers": _percent_change(current_stats["new_sign_customers"], previous_stats["new_sign_customers"]),
        "first_return_customers": _percent_change(current_stats["first_return_customers"], previous_stats["first_return_customers"]),
        "repurchase_rate": _percent_change(current_stats["repurchase_rate"], previous_stats["repurchase_rate"]),
        "repeat_amount_usd": _percent_change(current_stats["repeat_amount_usd"], previous_stats["repeat_amount_usd"]),
        "repeat_customer_rate": _percent_change(current_stats["repeat_customer_rate"], previous_stats["repeat_customer_rate"]),
    }
    country_known = sum(r["country"] != "未知" for r in orders)
    source_known = sum(r["source_category"] != "unknown" for r in orders)
    model_known = sum(r["model"] != "未知" for r in products)
    color_known = sum(r["color"] != "未知" for r in products)
    return {
        "window": {"date_from": date_from, "date_to": date_to, "previous_from": previous_from, "previous_to": previous_to},
        "scope": {"mode": scope.mode, "can_read_all": scope.can_read_all, "user_id": scope.user_id, "team": scope.team},
        "filters": analysis_filters.to_dict(),
        "metrics": current_stats,
        "forecast": {"next_30d_amount_usd": forecast, "method": forecast_method, "confidence": "medium" if len(_monthly_trend(orders)) >= 6 else "low"},
        "monthly_trend": _monthly_trend(orders, date_from, date_to),
        "source_mix": _source_mix(orders, previous),
        "amount_distribution": _amount_distribution_with_change(orders, previous),
        "top_models": _top_attributes(products, "model", 8, previous_products),
        "top_colors": _top_attributes(products, "color", 8, previous_products),
        "customer_risk": {
            "due": sum(item["risk_status"] == "due" for item in actionable),
            "abnormal": sum(item["risk_status"] == "abnormal" for item in actionable),
            "insufficient_data": sum(
                item["risk_status"] == "insufficient_data" for item in cycles.values()
            ),
        },
        "data_quality": {
            "country_coverage": round(country_known / len(orders) * 100, 1) if orders else 0,
            "source_coverage": round(source_known / len(orders) * 100, 1) if orders else 0,
            "product_model_coverage": round(model_known / len(products) * 100, 1) if products else 0,
            "product_color_coverage": round(color_known / len(products) * 100, 1) if products else 0,
            "non_positive_order_count": current_stats["non_positive_orders"],
        },
        "definitions": {
            "new_sign": f"OKKI 订单自定义字段 {NEW_DEAL_FIELD}=是，按客户去重",
            "repeat": f"OKKI 订单自定义字段 {NEW_DEAL_FIELD}=否；复购订单数按订单计数，复购金额按 amount_usd 求和",
            "first_return": f"OKKI 订单自定义字段 {FIRST_RETURN_FIELD}=是，按客户去重",
            "repurchase_rate": "统计期首返客户数 ÷ 统计期新签客户数 × 100%；按客户去重，分母为 0 时记 0%",
            "gmv": "有效订单 amount_usd；产品趋势使用明细 quantity，不与订单 GMV 混算",
            "forecast": "最近 3 个自然月加权均值叠加截断趋势（-30%~+50%），少于 3 个月不预测",
            **profile_analysis["definitions"],
        },
    }


def get_country_analysis(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    analysis_filters: AnalysisFilters | None = None,
    profile_result: dict | None = None,
) -> dict:
    analysis_filters = analysis_filters or AnalysisFilters()
    orders = _load_orders(db, scope, date_from, date_to, analysis_filters)
    days = (date_to - date_from).days + 1
    previous = _load_orders(db, scope, date_from - timedelta(days=days), date_from - timedelta(days=1), analysis_filters)
    products = _load_product_rows(db, scope, date_from, date_to, analysis_filters)
    previous_products = _load_product_rows(
        db, scope, date_from - timedelta(days=days), date_from - timedelta(days=1), analysis_filters,
    )
    profile_analysis = profile_result or _profile_analysis(
        db, scope, date_from, date_to, analysis_filters, orders, products,
    )
    cycles = profile_analysis["customer_cycles"]
    by_country: dict[str, list[dict]] = defaultdict(list)
    previous_by_country: dict[str, list[dict]] = defaultdict(list)
    products_by_country: dict[str, list[dict]] = defaultdict(list)
    previous_products_by_country: dict[str, list[dict]] = defaultdict(list)
    for row in orders:
        by_country[row["country"]].append(row)
    for row in previous:
        previous_by_country[row["country"]].append(row)
    for row in products:
        products_by_country[row["country"]].append(row)
    for row in previous_products:
        previous_products_by_country[row["country"]].append(row)

    rows = []
    for country, country_orders in by_country.items():
        stat = _aggregate(country_orders)
        prev = _aggregate(previous_by_country[country])
        previous_orders = previous_by_country[country]
        source_mix = _source_mix(country_orders, previous_orders)
        country_cycles = [item for item in cycles.values() if item["country"] == country]
        intervals = [
            item["typical_cycle_days"] for item in country_cycles
            if item["typical_cycle_days"] is not None
        ]
        forecast, method = _forecast_next_month(country_orders)
        item = {
            "country": country,
            **stat,
            "amount_growth": _percent_change(stat["amount_usd"], prev["amount_usd"]),
            "order_frequency_growth": _percent_change(stat["orders"], prev["orders"]),
            "new_sign_growth": _percent_change(stat["new_sign_customers"], prev["new_sign_customers"]),
            "median_cycle_days": int(round(float(median(intervals)))) if intervals else None,
            "at_risk_customers": sum(c["risk_status"] in {"due", "abnormal"} for c in country_cycles),
            "next_30d_amount_forecast": forecast,
            "forecast_method": method,
            "top_source_code": source_mix[0]["code"] if source_mix else "unknown",
            "top_source_label": source_mix[0]["label"] if source_mix else "未知",
            "source_mix": source_mix[:5],
            "amount_distribution": _amount_distribution_with_change(country_orders, previous_orders),
            "top_models": _top_attributes(
                products_by_country[country], "model", previous_rows=previous_products_by_country[country],
            ),
            "top_colors": _top_attributes(
                products_by_country[country], "color", previous_rows=previous_products_by_country[country],
            ),
        }
        rows.append(item)

    amount_values = [float(row["amount_usd"]) for row in rows]
    new_values = [float(row["new_sign_customers"]) for row in rows]
    repeat_values = [float(row["repeat_customer_rate"]) for row in rows]
    for row in rows:
        growth_score = 50 if row["amount_growth"] is None else max(0, min(100, 50 + row["amount_growth"]))
        row["opportunity_score"] = round(
            _minmax(amount_values, row["amount_usd"]) * 0.30
            + _minmax(new_values, row["new_sign_customers"]) * 0.25
            + _minmax(repeat_values, row["repeat_customer_rate"]) * 0.25
            + growth_score * 0.20,
            1,
        )
        row["evidence_level"] = "high" if row["customers"] >= 30 else ("medium" if row["customers"] >= 10 else "low")
        row["marketing_advice"] = _marketing_advice(row)
    rows.sort(key=lambda item: (item["opportunity_score"], item["amount_usd"]), reverse=True)
    return {"items": rows, "total": len(rows), "score_definition": "GMV 30% + 新签 25% + 复购率 25% + 同比趋势 20%；分数只用于内部排序"}


def _capability_labels(row: dict, medians: dict) -> list[str]:
    labels = []
    if (row["new_sign_customers"] > 0
            and row["new_sign_customers"] >= medians["new"]
            and row["new_avg_amount"] <= medians["new_avg"]):
        labels.append("新客小单破冰")
    if row["top_country_share"] >= 50 and row["customers"] >= 5:
        labels.append(f"{row['top_country']}定向开发")
    if row["first_return_customers"] >= max(2, medians["first_return"]):
        labels.append("老客激活")
    if row["repeat_customer_rate"] >= medians["repeat_rate"] and row["repeat_amount_usd"] >= medians["repeat_amount"]:
        labels.append("推动复购")
    if row["avg_order_amount_usd"] >= medians["avg_amount"] and row["orders"] >= 3:
        labels.append("高客单经营")
    return labels[:3] or ["样本积累中"]


def get_people_analysis(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    dimension: str,
    analysis_filters: AnalysisFilters | None = None,
    profile_result: dict | None = None,
) -> dict:
    analysis_filters = analysis_filters or AnalysisFilters()
    orders = _load_orders(db, scope, date_from, date_to, analysis_filters)
    days = (date_to - date_from).days + 1
    previous = _load_orders(db, scope, date_from - timedelta(days=days), date_from - timedelta(days=1), analysis_filters)
    products = _load_product_rows(db, scope, date_from, date_to, analysis_filters)
    previous_products = _load_product_rows(
        db, scope, date_from - timedelta(days=days), date_from - timedelta(days=1), analysis_filters,
    )
    profile_analysis = profile_result or _profile_analysis(
        db, scope, date_from, date_to, analysis_filters, orders, products,
    )
    cycles = profile_analysis["customer_cycles"]
    key = "team" if dimension == "team" else "user_id"
    grouped: dict[str, list[dict]] = defaultdict(list)
    prev_grouped: dict[str, list[dict]] = defaultdict(list)
    product_grouped: dict[str, list[dict]] = defaultdict(list)
    previous_product_grouped: dict[str, list[dict]] = defaultdict(list)
    cycle_grouped: dict[str, list[dict]] = defaultdict(list)
    team_by_user = {
        row["user_id"]: row["team"] for row in [*previous, *orders] if row["user_id"]
    }
    for row in orders:
        if row[key]:
            grouped[row[key]].append(row)
    for row in previous:
        if row[key]:
            prev_grouped[row[key]].append(row)
    for row in products:
        product_key = row["user_id"]
        if dimension == "team":
            product_key = team_by_user.get(row["user_id"], "")
        if product_key:
            product_grouped[product_key].append(row)
    for row in previous_products:
        product_key = row["user_id"]
        if dimension == "team":
            product_key = team_by_user.get(row["user_id"], "")
        if product_key:
            previous_product_grouped[product_key].append(row)
    for cycle in cycles.values():
        cycle_key = cycle["team"] if dimension == "team" else cycle["user_id"]
        if cycle_key:
            cycle_grouped[cycle_key].append(cycle)
    rows = []
    for group_id, group_orders in grouped.items():
        stat = _aggregate(group_orders)
        prev = _aggregate(prev_grouped[group_id])
        countries = Counter(r["country"] for r in group_orders if r["country"] != "未知")
        top_country, top_count = countries.most_common(1)[0] if countries else ("未知", 0)
        new_amounts = [r["amount_usd"] for r in group_orders if r["new_deal"] == "是" and r["amount_usd"] > 0]
        group_cycles = cycle_grouped[group_id]
        cycle_days = [
            item["typical_cycle_days"] for item in group_cycles
            if item["typical_cycle_days"] is not None
        ]
        row = {
            "id": group_id,
            "name": group_orders[-1]["team"] if dimension == "team" else group_orders[-1]["user_name"],
            "team": group_orders[-1]["team"],
            **stat,
            "new_avg_amount": round(sum(new_amounts) / len(new_amounts), 2) if new_amounts else 0,
            "country_count": len(countries),
            "top_country": top_country,
            "top_country_share": round(top_count / stat["customers"] * 100, 1) if stat["customers"] else 0,
            "amount_growth": _percent_change(stat["amount_usd"], prev["amount_usd"]),
            "order_frequency_growth": _percent_change(stat["orders"], prev["orders"]),
            "new_sign_growth": _percent_change(stat["new_sign_customers"], prev["new_sign_customers"]),
            "repeat_amount_growth": _percent_change(stat["repeat_amount_usd"], prev["repeat_amount_usd"]),
            "source_mix": _source_mix(group_orders, prev_grouped[group_id]),
            "amount_distribution": _amount_distribution_with_change(group_orders, prev_grouped[group_id]),
            "median_cycle_days": int(round(float(median(cycle_days)))) if cycle_days else None,
            "at_risk_customers": sum(item["risk_status"] in {"due", "abnormal"} for item in group_cycles),
            "top_models": _top_attributes(
                product_grouped[group_id], "model", 2, previous_product_grouped[group_id],
            ),
            "top_colors": _top_attributes(
                product_grouped[group_id], "color", 2, previous_product_grouped[group_id],
            ),
        }
        row["top_source"] = (row["source_mix"] or [{"label": "未知"}])[0]["label"]
        rows.append(row)
    if rows:
        medians = {
            "new": float(median([r["new_sign_customers"] for r in rows])),
            "new_avg": float(median([r["new_avg_amount"] for r in rows])),
            "first_return": float(median([r["first_return_customers"] for r in rows])),
            "repeat_rate": float(median([r["repeat_customer_rate"] for r in rows])),
            "repeat_amount": float(median([r["repeat_amount_usd"] for r in rows])),
            "avg_amount": float(median([r["avg_order_amount_usd"] for r in rows])),
        }
        for row in rows:
            row["capability_labels"] = _capability_labels(row, medians)
            row["evidence_level"] = "high" if row["orders"] >= 30 else ("medium" if row["orders"] >= 10 else "low")
    rows.sort(key=lambda item: item["amount_usd"], reverse=True)
    return {
        "dimension": dimension,
        "items": rows,
        "total": len(rows),
        "evaluation_note": "能力标签是同周期同层级的相对画像，不替代询盘量、跟进质量和客户分配难度等管理判断。",
    }


def get_customer_actions(
    db: Session,
    scope: AnalysisScope,
    as_of: date,
    page: int,
    page_size: int,
    risk_status: str | None = None,
    country: str | None = None,
    analysis_filters: AnalysisFilters | None = None,
    date_from: date | None = None,
) -> dict:
    analysis_filters = analysis_filters or AnalysisFilters()
    window_start = date_from or (as_of - timedelta(days=364))
    matching_orders = _load_orders(db, scope, window_start, as_of, analysis_filters)
    matching_products = _load_product_rows(
        db, scope, window_start, as_of, analysis_filters,
    )
    profile_analysis = _profile_analysis(
        db,
        scope,
        window_start,
        as_of,
        analysis_filters,
        matching_orders,
        matching_products,
    )
    cycles = profile_analysis["customer_cycles"]
    matching_company_ids = set(cycles)
    items = []
    for customer in cycles.values():
        if customer["company_id"] not in matching_company_ids:
            continue
        if risk_status and customer["risk_status"] != risk_status:
            continue
        if country and customer["country"] != country:
            continue
        if not risk_status and customer["risk_status"] not in {"due", "abnormal"}:
            continue
        top_models = customer["top_models"]
        top_colors = customer["top_colors"]
        if customer["risk_status"] == "due":
            action = "已达到稳健典型返单周期，本周确认库存、销量与下一批需求"
        elif customer["risk_status"] == "abnormal":
            action = "已超过稳健典型返单周期 2 倍，立即核实流失原因并制定激活方案"
        else:
            action = "同画像复购样本不足，先补充客户性质与新签型号信息"
        customer.update({
            "last_order_date": customer["last_order_date"].isoformat(),
            "expected_order_date": (
                customer["expected_order_date"].isoformat()
                if customer["expected_order_date"] else None
            ),
            "abnormal_date": (
                customer["abnormal_date"].isoformat()
                if customer["abnormal_date"] else None
            ),
            "top_models": top_models,
            "top_colors": top_colors,
            "recommended_action": action,
        })
        items.append(customer)
    priority = {"abnormal": 0, "due": 1, "insufficient_data": 2, "healthy": 3}
    items.sort(key=lambda item: (priority[item["risk_status"]], -item["lifetime_amount_usd"]))
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "analysis_window": {"date_from": window_start.isoformat(), "date_to": as_of.isoformat()},
        "risk_definition": "使用抗异常值的典型复购周期：画像满足最小样本时取客户中位数的中位数；画像样本不足但客户至少有 3 个历史间隔时取个人中位数。达到周期提醒，严格超过 2 倍异常。",
    }


def build_ai_brief(
    db: Session,
    scope: AnalysisScope,
    date_from: date,
    date_to: date,
    focus: str,
    caller_user_id: int | None,
    analysis_filters: AnalysisFilters | None = None,
) -> dict:
    analysis_filters = analysis_filters or AnalysisFilters()
    profile_result = _profile_analysis(db, scope, date_from, date_to, analysis_filters)
    overview = get_overview(
        db, scope, date_from, date_to, analysis_filters, profile_result,
    )
    countries = get_country_analysis(
        db, scope, date_from, date_to, analysis_filters, profile_result,
    )["items"][:8]
    people = get_people_analysis(
        db, scope, date_from, date_to, "user", analysis_filters, profile_result,
    )["items"][:8]
    profiles = profile_result["items"][:8]
    payload = {
        "focus": focus,
        "window": overview["window"],
        "metrics": overview["metrics"],
        "forecast": overview["forecast"],
        "data_quality": overview["data_quality"],
        "source_mix": overview["source_mix"],
        "top_countries": countries,
        "top_people": people,
        "top_customer_profiles": profiles,
        "definitions": overview["definitions"],
    }
    try:
        from app.ai.service import chat
        result = chat(
            db=db,
            preset_name="order_intelligence_brief",
            messages=[{
                "role": "user",
                "content": (
                    "以下 JSON 是系统实时计算的订单经营证据。请只使用其中的指标与值域，"
                    "输出中文经营简报；每条结论必须带数字证据，并区分事实、预测、建议。"
                    "禁止把订单来源表现表述为广告 ROI，禁止推断未提供的询盘数、广告费、CAC、ROAS或市场份额。\n"
                    + json.dumps(payload, ensure_ascii=False, default=str)
                ),
            }],
            caller_module="order_intelligence",
            caller_user_id=caller_user_id,
        )
        content = (result.get("content") or "").strip()
        if content:
            return {"content": content, "source": "ai", "evidence": payload}
    except Exception as exc:
        logger.warning("order intelligence AI brief failed: %s", exc)
        print(f"order intelligence AI brief failed: {exc}", flush=True)
    metrics = overview["metrics"]
    lead = countries[0] if countries else None
    fallback = (
        f"本期有效订单 {metrics['orders']} 单，GMV ${metrics['amount_usd']:,.0f}；"
        f"新签 {metrics['new_sign_customers']} 个，复购客户 {metrics['repeat_customers']} 个。"
    )
    if lead:
        fallback += f" {lead['country']}机会评分最高（{lead['opportunity_score']}），建议：{lead['marketing_advice']['action']}"
    return {"content": fallback, "source": "rules", "evidence": payload}
