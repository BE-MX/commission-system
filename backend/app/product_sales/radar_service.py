"""产品风向标 P1：颜色×发长 / 品类 / 小款的 kg 风向，以及单个款的走势与分布。

口径见 docs/requirements/2026-11-18-product-sales-radar/README.md：
- 公司级产品汇总对 ``product_sales:read`` 可见（只到产品级 kg/件数，不含客户和业务员明细）。
- 「我的份额」默认是当前账号绑定的 OKKI 业务员；``product_sales:read_all`` 可切换团队/个人。
- 颜色×发长只统计能解析出两个维度的行（exact/derived），被排除的件数单独返回。
- 两个对比窗口都达到可信阈值才给出「可比」结论；否则变化只作参考。
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from time import monotonic

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.core.time import beijing_today
from app.product_sales import metrics
from app.report.category_service import OTHER_CATEGORY_INDEX, OTHER_LABEL, classify

WINDOW_CHOICES = (30, 90, 180)
TREND_MONTHS = 12
SMALL_ITEM_TOP_N = 20
SMALL_ITEM_MIN_GROWTH = 0.5
MIN_RISER_KG = Decimal("1")
LIST_LIMIT = 30
DIMENSIONS = {
    "color_size": "颜色×发长",
    "category": "品类",
    "item": "款（型号×颜色×发长）",
}
_CACHE_TTL_SECONDS = 300
_SPAN_DAYS = 2 * max(WINDOW_CHOICES) + 31 * TREND_MONTHS  # 覆盖最大对比窗口与 12 个月走势
MIN_COUNTRY_CUSTOMERS = 3
_lines_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_load_lock = threading.Lock()


@dataclass(frozen=True)
class ShareScope:
    """「我的份额」的口径。user_id/team 都为空表示不计算份额（如未绑定 OKKI）。"""

    mode: str  # self / user / team / none
    user_id: str | None
    team: str | None
    can_read_all: bool
    label: str

    @property
    def key(self) -> str:
        return f"{self.mode}:{self.user_id or ''}:{self.team or ''}"

    def matches(self, line: dict) -> bool:
        if self.mode in ("self", "user"):
            return line["user_id"] == self.user_id
        if self.mode == "team":
            return line.get("team") == self.team
        return False


def resolve_share_scope(db: Session, user: dict, user_id: str | None, team: str | None) -> ShareScope:
    permissions = set(user.get("permissions") or [])
    can_read_all = "product_sales:read_all" in permissions or "super_admin" in set(user.get("roles") or [])
    if user_id or team:
        if not can_read_all:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看其他业务员的销量份额")
        if user_id:
            return ShareScope("user", str(user_id), None, True, "所选业务员")
        return ShareScope("team", None, str(team), True, f"{team} 团队")
    try:
        ark_user_id = int(user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
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
        return ShareScope("none", None, None, can_read_all, "未绑定 OKKI 业务员")
    return ShareScope("self", okki_user_id, None, can_read_all, "我")


def windows(window_days: int, today: date | None = None) -> tuple[tuple[date, date], tuple[date, date]]:
    if window_days not in WINDOW_CHOICES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"对比窗口只支持 {WINDOW_CHOICES} 天")
    end = today or beijing_today()
    current = (end - timedelta(days=window_days - 1), end)
    previous = (current[0] - timedelta(days=window_days), current[0] - timedelta(days=1))
    return current, previous


def _span_lines(db: Session, end: date, version: tuple) -> list[dict]:
    """每个进程只缓存一份「截止日往前约 2 年」的全公司明细（5 分钟），各窗口在内存里切片。

    未命中时用加载锁做 single-flight，避免并发请求同时扫全公司明细。
    """
    key = (end, version)

    def fresh():
        cached = _lines_cache.get(key)
        return cached[1] if cached and monotonic() - cached[0] < _CACHE_TTL_SECONDS else None

    with _cache_lock:
        hit = fresh()
    if hit is not None:
        return hit
    with _load_lock:
        with _cache_lock:
            hit = fresh()
        if hit is not None:
            return hit
        lines = metrics.load_lines(db, end - timedelta(days=_SPAN_DAYS), end)
        with _cache_lock:
            _lines_cache.clear()
            _lines_cache[key] = (monotonic(), lines)
        return lines


def cached_lines(db: Session, date_from: date, date_to: date, version: tuple) -> list[dict]:
    """全公司明细（所有用户共享），份额在内存里按 user_id 过滤。"""
    if (date_to - date_from).days > _SPAN_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "统计区间过长")
    return [line for line in _span_lines(db, date_to, version) if date_from <= line["account_date"] <= date_to]


def category_of(line: dict) -> str:
    grams = line.get("unit_grams")
    unit = f"{grams.normalize():f}g" if isinstance(grams, Decimal) else ""
    index, label = classify(line.get("model") or "", unit)
    return OTHER_LABEL if index == OTHER_CATEGORY_INDEX else label.split("\n")[0].strip()


def item_key(line: dict, dimension: str) -> str | None:
    if line["kg"] is None:
        return None
    if dimension == "category":
        return category_of(line)
    if line["confidence"] not in metrics.CREDIBLE:
        return None
    color, size = line["color"], line["size"]
    if metrics.UNKNOWN_LABEL in (color, size):
        return None
    if dimension == "color_size":
        return f"{color} · {size}"
    if dimension == "item":
        return f"{line['model']} · {color} · {size}"
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "维度无效")


def _in(line: dict, window: tuple[date, date]) -> bool:
    return window[0] <= line["account_date"] <= window[1]


def window_credibility(lines: list[dict], window: tuple[date, date]) -> dict:
    total = credible = Decimal(0)
    for line in lines:
        if _in(line, window):
            total += line["quantity"]
            if line["confidence"] in metrics.CREDIBLE:
                credible += line["quantity"]
    share = credible / total if total else Decimal(0)
    return {"quantity": float(total), "credible_share": round(float(share), 4),
            "credible": bool(total) and share >= metrics.CREDIBLE_MONTH_SHARE}


def _growth(current: Decimal, previous: Decimal) -> float | None:
    if previous <= 0:
        return None
    return round(float((current - previous) / previous), 4)


def aggregate(lines: list[dict], dimension: str, current: tuple, previous: tuple, share: ShareScope,
              models: set[str] | None = None) -> tuple[list[dict], Decimal]:
    buckets: dict[str, dict] = defaultdict(lambda: {
        "kg": Decimal(0), "prev_kg": Decimal(0), "quantity": Decimal(0), "my_kg": Decimal(0),
    })
    excluded = Decimal(0)
    for line in lines:
        in_current = _in(line, current)
        if not in_current and not _in(line, previous):
            continue
        if models and line["model"] not in models:
            continue
        key = item_key(line, dimension)
        if key is None:
            if in_current:
                excluded += line["quantity"]
            continue
        bucket = buckets[key]
        if in_current:
            bucket["kg"] += line["kg"]
            bucket["quantity"] += line["quantity"]
            if share.matches(line):
                bucket["my_kg"] += line["kg"]
        else:
            bucket["prev_kg"] += line["kg"]
    rows = []
    for key, bucket in buckets.items():
        rows.append({
            "key": key,
            "kg": round(float(bucket["kg"]), 3),
            "prev_kg": round(float(bucket["prev_kg"]), 3),
            "delta_kg": round(float(bucket["kg"] - bucket["prev_kg"]), 3),
            "growth": _growth(bucket["kg"], bucket["prev_kg"]),
            "quantity": float(bucket["quantity"]),
            "my_kg": round(float(bucket["my_kg"]), 3),
            "my_share": round(float(bucket["my_kg"] / bucket["kg"]), 4) if bucket["kg"] else None,
        })
    rows.sort(key=lambda row: (-row["kg"], row["key"]))
    return rows, excluded


def small_risers(rows: list[dict]) -> list[dict]:
    """小款冒头：上期不在前 20 的款里，本期 ≥ 1 kg 且增长 ≥ 50%（或新出现），按增量排序。

    款按「型号×颜色×发长」切得很细，单款占比普遍很低，所以用上期排名而不是占比来界定「小款」。
    """
    top_prev = {row["key"] for row in sorted(rows, key=lambda r: -r["prev_kg"])[:SMALL_ITEM_TOP_N] if row["prev_kg"] > 0}
    picked = [
        row for row in rows
        if row["key"] not in top_prev and row["delta_kg"] > 0 and Decimal(str(row["kg"])) >= MIN_RISER_KG
        and (row["growth"] is None or row["growth"] >= SMALL_ITEM_MIN_GROWTH)
    ]
    return sorted(picked, key=lambda row: -row["delta_kg"])[:10]


def movers(rows: list[dict]) -> dict:
    risers = sorted((r for r in rows if r["delta_kg"] > 0), key=lambda r: -r["delta_kg"])[:8]
    fallers = sorted((r for r in rows if r["delta_kg"] < 0), key=lambda r: r["delta_kg"])[:8]
    return {"risers": risers, "fallers": fallers}


def _sum_kg(lines: list[dict], window: tuple, predicate=None) -> Decimal:
    return sum(
        (line["kg"] for line in lines if line["kg"] is not None and _in(line, window) and (predicate is None or predicate(line))),
        Decimal(0),
    )


def get_radar(db: Session, share: ShareScope, window_days: int, models: list[str] | None,
              version: tuple, today: date | None = None) -> dict:
    current, previous = windows(window_days, today)
    lines = cached_lines(db, previous[0], current[1], version)
    model_set = set(models or []) or None
    color_size, excluded = aggregate(lines, "color_size", current, previous, share, model_set)
    categories, _ = aggregate(lines, "category", current, previous, share, model_set)
    items, _ = aggregate(lines, "item", current, previous, share, model_set)
    scoped = (lambda line: line["model"] in model_set) if model_set else None
    total_kg = _sum_kg(lines, current, scoped)
    my_kg = _sum_kg(lines, current, lambda line: share.matches(line) and (scoped is None or scoped(line)))
    cred_cur, cred_prev = window_credibility(lines, current), window_credibility(lines, previous)
    model_options = sorted({line["model"] for line in lines if line["model"] != metrics.UNKNOWN_LABEL})
    return {
        "window": {"days": window_days, "current": [d.isoformat() for d in current],
                   "previous": [d.isoformat() for d in previous]},
        "credibility": {"current": cred_cur, "previous": cred_prev,
                        "comparable": cred_cur["credible"] and cred_prev["credible"],
                        "threshold": float(metrics.CREDIBLE_MONTH_SHARE)},
        "summary": {
            "kg": round(float(total_kg), 3),
            "prev_kg": round(float(_sum_kg(lines, previous, scoped)), 3),
            "my_kg": round(float(my_kg), 3) if share.mode != "none" else None,
            "my_share": round(float(my_kg / total_kg), 4) if total_kg and share.mode != "none" else None,
            "color_size_excluded_quantity": float(excluded),
        },
        "share_scope": {"mode": share.mode, "label": share.label, "can_read_all": share.can_read_all},
        "color_size": {**movers(color_size), "top": color_size[:LIST_LIMIT]},
        "categories": categories,
        "small_risers": small_risers(items),
        "model_options": model_options,
    }


def _month_starts(end: date, months: int) -> list[date]:
    first = end.replace(day=1)
    result = []
    for _ in range(months):
        result.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    return list(reversed(result))


def get_item_detail(db: Session, share: ShareScope, dimension: str, key: str, window_days: int,
                    version: tuple, today: date | None = None) -> dict:
    if dimension not in DIMENSIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "维度无效")
    current, previous = windows(window_days, today)
    end = current[1]
    starts = _month_starts(end, TREND_MONTHS)
    lines = cached_lines(db, min(starts[0], previous[0]), end, version)
    monthly = {start.strftime("%Y-%m"): {"kg": Decimal(0), "my_kg": Decimal(0)} for start in starts}
    month_lines: dict[str, list[dict]] = defaultdict(list)
    models: dict[str, Decimal] = defaultdict(Decimal)
    countries: dict[str, Decimal] = defaultdict(Decimal)
    country_customers: dict[str, set] = defaultdict(set)
    matched = False
    for line in lines:
        month = line["account_date"].strftime("%Y-%m")
        if month in monthly:
            month_lines[month].append(line)
        if item_key(line, dimension) != key:
            continue
        matched = True
        if month in monthly:
            monthly[month]["kg"] += line["kg"]
            if share.matches(line):
                monthly[month]["my_kg"] += line["kg"]
        if _in(line, current):
            models[line["model"]] += line["kg"]
            countries[line["country"]] += line["kg"]
            if line.get("company_id"):  # 缺客户 ID 的行不计入客户数，宁可多并入「其他」
                country_customers[line["country"]].add(line["company_id"])
    if not matched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该款在所选时间内没有可统计的销量")
    coverage = {row["month"]: row for row in metrics.monthly_coverage(
        [line for rows in month_lines.values() for line in rows]
    )}

    def top(values: dict[str, Decimal]) -> list[dict]:
        total = sum(values.values(), Decimal(0))
        ranked = sorted(values.items(), key=lambda item: -item[1])[:6]
        return [{"name": name, "kg": round(float(kg), 3),
                 "share": round(float(kg / total), 4) if total else None} for name, kg in ranked]

    # 只到产品级：买过这款的客户少于 3 个的国家并入「其他」，避免从国家分布反推单个客户的采购量
    safe_countries: dict[str, Decimal] = defaultdict(Decimal)
    other_customers: set = set()
    for name, value in countries.items():
        if len(country_customers[name]) >= MIN_COUNTRY_CUSTOMERS:
            safe_countries[name] += value
        else:
            safe_countries["其他"] += value
            other_customers |= country_customers[name]
    if len(other_customers) < MIN_COUNTRY_CUSTOMERS:
        safe_countries.pop("其他", None)  # 「其他」本身也可能只代表一两个客户，此时不展示
    countries = safe_countries

    rows, _ = aggregate(lines, dimension, current, previous, share)
    summary = next((row for row in rows if row["key"] == key), None)
    return {
        "dimension": dimension,
        "dimension_label": DIMENSIONS[dimension],
        "key": key,
        "summary": summary,
        "monthly": [
            {"month": month, "kg": round(float(value["kg"]), 3), "my_kg": round(float(value["my_kg"]), 3),
             "credible": bool(coverage.get(month, {}).get("credible"))}
            for month, value in monthly.items()
        ],
        "top_models": top(models),
        "top_countries": top(countries),
        "window": {"days": window_days, "current": [d.isoformat() for d in current],
                   "previous": [d.isoformat() for d in previous]},
        "credibility": {"current": window_credibility(lines, current),
                        "previous": window_credibility(lines, previous)},
        "share_scope": {"mode": share.mode, "label": share.label},
    }


def get_scopes(db: Session, share: ShareScope, window_days: int, version: tuple, today: date | None = None) -> dict:
    """read_all 的份额切换选项：所选窗口内有销量的团队与业务员。"""
    if not share.can_read_all:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权切换其他业务员的销量份额")
    current, previous = windows(window_days, today)
    users: dict[str, dict] = {}
    for line in cached_lines(db, previous[0], current[1], version):
        if line["user_id"] and line["user_id"] not in users:
            users[line["user_id"]] = {"user_id": line["user_id"], "name": line.get("user_name") or line["user_id"],
                                      "team": line.get("team") or ""}
    teams = sorted({user["team"] for user in users.values() if user["team"]})
    return {"teams": teams, "users": sorted(users.values(), key=lambda user: (user["team"], user["name"]))}
