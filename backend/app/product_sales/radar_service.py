"""产品风向标：按 B1 / B3 / 50%幅度 三个大类分页，大类内按「规格 / 颜色 / 尺寸」任意组合看排行与涨跌。

口径见 docs/requirements/2026-11-18-product-sales-radar/README.md（第 8 节为 2026-11-24 调整）：
- 大类 = 型号前缀；规格 = 去掉前缀后的型号（如「天才发帘（帘宽12"）」）；SKU = 规格 × 颜色 × 尺寸。
- 排行与涨跌按 kg，同时给件数；涨跌 = 本期 vs 紧邻的上一个同长窗口。
- 组合里含颜色或尺寸时，只统计 exact/derived 且这两维可识别的行，被排除的件数单独返回；
  只看规格时历史估算行（只有型号）也计入。
- 公司级产品汇总对 ``product_sales:read`` 可见；「我的份额」默认是当前账号绑定的 OKKI 业务员，
  ``product_sales:read_all`` 可切换团队/个人。
- 两个对比窗口都达到可信阈值才算「可比」；否则涨跌只作参考。可信度按「三大类 + 识别不出型号的行」
  判断，不只看本大类：识别不出型号的历史行进不了任何大类，只看大类内会把估算期误判为可信；
  已知属于配件、费用等其他产品的行不参与，避免它们拖累三大类。
"""

from __future__ import annotations

import re
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

WINDOW_CHOICES = (30, 60, 90, 180)
TREND_MONTHS = 12
MOVER_LIMIT = 10
# 大类：(参数值, 展示名, 型号前缀)。前缀按顺序匹配，大小写不敏感。
GRADES = (("B1", "B1", "B1"), ("B3", "B3", "B3"), ("50", "50%幅度", "50%幅度"))
GRADE_LABELS = {code: label for code, label, _ in GRADES}
DIMENSIONS = {"spec": "规格", "color": "颜色", "size": "尺寸"}
DIMENSION_ORDER = ("spec", "color", "size")
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


COMPANY_SCOPE = ShareScope("none", None, None, False, "全公司")


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


_GRADE_PATTERNS = (
    ("B1", re.compile(r"^B1(?!\d)\s*", re.IGNORECASE)),
    ("B3", re.compile(r"^B3(?!\d)\s*", re.IGNORECASE)),
    ("50", re.compile(r"^50\s*[%\uff05]\s*幅度\s*")),
)
_SPEC_CHARS = str.maketrans({"\uff08": "(", "\uff09": ")", "\u201c": '"', "\u201d": '"', "\u2033": '"',
                             "\uff02": '"', "\u3000": " "})
_SPACES = re.compile(r"\s+")


def split_grade(model: object) -> tuple[str | None, str]:
    """型号 → (大类参数值, 规格)。不以三个前缀开头的型号（含 B10 这类）返回 (None, "")。

    规格统一全角括号/引号与空白，避免产品表型号与历史映射型号写法不同被拆成两项。
    """
    text = str(model or "").strip()
    for code, pattern in _GRADE_PATTERNS:
        match = pattern.match(text)
        if match:
            spec = _SPACES.sub(" ", text[match.end():].translate(_SPEC_CHARS)).strip(" -_·")
            return code, spec or metrics.UNKNOWN_LABEL
    return None, ""


def validate_grade(grade: str) -> str:
    if grade not in GRADE_LABELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"大类只支持 {list(GRADE_LABELS.values())}")
    return grade


def normalize_dims(dims: list[str] | None) -> tuple[str, ...]:
    chosen = set(dims or DIMENSION_ORDER)
    if not chosen or chosen - set(DIMENSIONS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "维度只支持规格、颜色、尺寸，至少选一个")
    return tuple(dim for dim in DIMENSION_ORDER if dim in chosen)


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
        for line in lines:
            line["grade"], line["spec"] = split_grade(line.get("model"))
        with _cache_lock:
            _lines_cache.clear()
            _lines_cache[key] = (monotonic(), lines)
        return lines


def cached_lines(db: Session, date_from: date, date_to: date, version: tuple) -> list[dict]:
    """全公司明细（所有用户共享），份额在内存里按 user_id 过滤。"""
    if (date_to - date_from).days > _SPAN_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "统计区间过长")
    return [line for line in _span_lines(db, date_to, version) if date_from <= line["account_date"] <= date_to]


def group_values(line: dict, dims: tuple[str, ...]) -> tuple[str, ...] | None:
    """行在所选维度组合下的取值；不可统计时返回 None（无 kg，或颜色/尺寸不可信、不可识别）。"""
    if line["kg"] is None:
        return None
    if ("color" in dims or "size" in dims) and line["confidence"] not in metrics.CREDIBLE:
        return None
    values = tuple(line.get(dim) or metrics.UNKNOWN_LABEL for dim in dims)
    if metrics.UNKNOWN_LABEL in values:
        return None
    return values


def _in(line: dict, window: tuple[date, date]) -> bool:
    return window[0] <= line["account_date"] <= window[1]


def _credibility_population(line: dict) -> bool:
    """可信度的分母：三大类的行 + 识别不出型号的行（可能属于任一大类）；已知属于其他产品的行不算。"""
    return bool(line.get("grade")) or line.get("model") in (None, "", metrics.UNKNOWN_LABEL)


def window_credibility(lines: list[dict], window: tuple[date, date]) -> dict:
    total = credible = Decimal(0)
    for line in lines:
        if _in(line, window) and _credibility_population(line):
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


def _ranks(rows: list[dict], field: str) -> dict[str, int]:
    ranked = sorted((row for row in rows if row[field] > 0), key=lambda row: (-row[field], row["key"]))
    return {row["key"]: index for index, row in enumerate(ranked, start=1)}


def aggregate(lines: list[dict], dims: tuple[str, ...], current: tuple, previous: tuple,
              share: ShareScope) -> tuple[list[dict], Decimal]:
    """按维度组合汇总本期/上期 kg 与件数；返回 (按本期 kg 排序的行, 本期被排除的件数)。"""
    buckets: dict[tuple, dict] = defaultdict(lambda: {
        "kg": Decimal(0), "prev_kg": Decimal(0), "quantity": Decimal(0), "prev_quantity": Decimal(0),
        "my_kg": Decimal(0),
    })
    excluded = Decimal(0)
    for line in lines:
        in_current = _in(line, current)
        if not in_current and not _in(line, previous):
            continue
        values = group_values(line, dims)
        if values is None:
            if in_current:
                excluded += line["quantity"]
            continue
        bucket = buckets[values]
        if in_current:
            bucket["kg"] += line["kg"]
            bucket["quantity"] += line["quantity"]
            if share.matches(line):
                bucket["my_kg"] += line["kg"]
        else:
            bucket["prev_kg"] += line["kg"]
            bucket["prev_quantity"] += line["quantity"]
    rows = []
    for values, bucket in buckets.items():
        rows.append({
            "key": " · ".join(values),
            "values": dict(zip(dims, values)),
            "kg": round(float(bucket["kg"]), 3),
            "prev_kg": round(float(bucket["prev_kg"]), 3),
            "delta_kg": round(float(bucket["kg"] - bucket["prev_kg"]), 3),
            "growth": _growth(bucket["kg"], bucket["prev_kg"]),
            "quantity": float(bucket["quantity"]),
            "prev_quantity": float(bucket["prev_quantity"]),
            "my_kg": round(float(bucket["my_kg"]), 3),
            "my_share": round(float(bucket["my_kg"] / bucket["kg"]), 4) if bucket["kg"] else None,
        })
    current_rank, previous_rank = _ranks(rows, "kg"), _ranks(rows, "prev_kg")
    for row in rows:
        row["rank"] = current_rank.get(row["key"])
        row["prev_rank"] = previous_rank.get(row["key"])
    rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0, -row["prev_kg"], row["key"]))
    return rows, excluded


def movers(rows: list[dict], limit: int = MOVER_LIMIT) -> dict:
    risers = sorted((r for r in rows if r["delta_kg"] > 0), key=lambda r: (-r["delta_kg"], r["key"]))[:limit]
    fallers = sorted((r for r in rows if r["delta_kg"] < 0), key=lambda r: (r["delta_kg"], r["key"]))[:limit]
    return {"risers": risers, "fallers": fallers}


def _sum(lines: list[dict], window: tuple, field: str = "kg", predicate=None) -> Decimal:
    return sum(
        (line[field] for line in lines
         if line[field] is not None and _in(line, window) and (predicate is None or predicate(line))),
        Decimal(0),
    )


def _window_payload(window_days: int, current: tuple, previous: tuple) -> dict:
    return {"days": window_days, "current": [d.isoformat() for d in current],
            "previous": [d.isoformat() for d in previous]}


def grade_tabs(lines: list[dict], current: tuple, previous: tuple) -> dict:
    tabs = []
    for code, label, _prefix in GRADES:
        scoped = [line for line in lines if line.get("grade") == code]
        tabs.append({"grade": code, "label": label, "kg": round(float(_sum(scoped, current)), 3),
                     "prev_kg": round(float(_sum(scoped, previous)), 3)})
    other = [line for line in lines if not line.get("grade")]
    return {"tabs": tabs, "unclassified": {
        "kg": round(float(_sum(other, current)), 3),
        "quantity": float(_sum(other, current, "quantity")),
    }}


def get_radar(db: Session, share: ShareScope, grade: str, dims: list[str] | None, window_days: int,
              version: tuple, today: date | None = None) -> dict:
    grade = validate_grade(grade)
    dim_tuple = normalize_dims(dims)
    current, previous = windows(window_days, today)
    lines = cached_lines(db, previous[0], current[1], version)
    scoped = [line for line in lines if line.get("grade") == grade]
    rows, excluded = aggregate(scoped, dim_tuple, current, previous, share)
    total_kg = _sum(scoped, current)
    my_kg = _sum(scoped, current, predicate=share.matches)
    cred_cur, cred_prev = window_credibility(lines, current), window_credibility(lines, previous)
    return {
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "dims": list(dim_tuple),
        "dim_labels": {dim: DIMENSIONS[dim] for dim in dim_tuple},
        "window": _window_payload(window_days, current, previous),
        "credibility": {"current": cred_cur, "previous": cred_prev,
                        "comparable": cred_cur["credible"] and cred_prev["credible"],
                        "threshold": float(metrics.CREDIBLE_MONTH_SHARE)},
        "summary": {
            "kg": round(float(total_kg), 3),
            "prev_kg": round(float(_sum(scoped, previous)), 3),
            "quantity": float(_sum(scoped, current, "quantity")),
            "my_kg": round(float(my_kg), 3) if share.mode != "none" else None,
            "my_share": round(float(my_kg / total_kg), 4) if total_kg and share.mode != "none" else None,
            "excluded_quantity": float(excluded),
            "group_count": sum(1 for row in rows if row["kg"] > 0),
        },
        "share_scope": {"mode": share.mode, "label": share.label, "can_read_all": share.can_read_all},
        **grade_tabs(lines, current, previous),
        "rows": rows,
        "movers": movers(rows),
    }


def _month_starts(end: date, months: int) -> list[date]:
    first = end.replace(day=1)
    result = []
    for _ in range(months):
        result.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    return list(reversed(result))


def monthly_trend(lines: list[dict], end: date, match, share: ShareScope | None = None) -> list[dict]:
    """近 12 个月匹配行的 kg；``lines`` 须是全公司明细，credible 按该月全部明细判断，与可信度规则一致。"""
    starts = _month_starts(end, TREND_MONTHS)
    monthly = {start.strftime("%Y-%m"): {"kg": Decimal(0), "my_kg": Decimal(0)} for start in starts}
    month_lines = [line for line in lines if line["account_date"].strftime("%Y-%m") in monthly]
    for line in month_lines:
        if line["kg"] is None or not match(line):
            continue
        bucket = monthly[line["account_date"].strftime("%Y-%m")]
        bucket["kg"] += line["kg"]
        if share is not None and share.matches(line):
            bucket["my_kg"] += line["kg"]
    coverage = {row["month"]: row for row in metrics.monthly_coverage(
        [line for line in month_lines if _credibility_population(line)]
    )}
    current_month = end.strftime("%Y-%m")
    return [
        {"month": month, "kg": round(float(value["kg"]), 3), "my_kg": round(float(value["my_kg"]), 3),
         "credible": bool(coverage.get(month, {}).get("credible")),
         # 截止日所在月份只有部分天数，不能和完整月比较涨跌
         "partial": month == current_month, "days_covered": end.day if month == current_month else None}
        for month, value in monthly.items()
    ]


def _top(values: dict[str, Decimal], limit: int = 6) -> list[dict]:
    total = sum(values.values(), Decimal(0))
    ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"name": name, "kg": round(float(kg), 3),
             "share": round(float(kg / total), 4) if total else None} for name, kg in ranked]


def _safe_countries(countries: dict[str, Decimal], customers: dict[str, set]) -> dict[str, Decimal]:
    """只到产品级：买过的客户少于 3 个的国家并入「其他」，避免从国家分布反推单个客户的采购量。"""
    safe: dict[str, Decimal] = defaultdict(Decimal)
    other_customers: set = set()
    for name, value in countries.items():
        if len(customers[name]) >= MIN_COUNTRY_CUSTOMERS:
            safe[name] += value
        else:
            safe["其他"] += value
            other_customers |= customers[name]
    if len(other_customers) < MIN_COUNTRY_CUSTOMERS:
        safe.pop("其他", None)  # 「其他」本身也可能只代表一两个客户，此时不展示
    return safe


def get_item_detail(db: Session, share: ShareScope, grade: str, values: dict[str, str], window_days: int,
                    version: tuple, today: date | None = None) -> dict:
    """单个组合（如 B1 · 颜色 #1B，或某个 SKU）的 12 个月走势与其余维度、国家分布。"""
    grade = validate_grade(grade)
    picked = {dim: str(value).strip() for dim, value in values.items() if value is not None and str(value).strip()}
    dims = normalize_dims(list(picked)) if picked else None
    if not dims:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请指定规格、颜色或尺寸")
    target = tuple(picked[dim] for dim in dims)
    current, previous = windows(window_days, today)
    end = current[1]
    starts = _month_starts(end, TREND_MONTHS)
    lines = cached_lines(db, min(starts[0], previous[0]), end, version)
    scoped = [line for line in lines if line.get("grade") == grade]

    def match(line: dict) -> bool:
        return line.get("grade") == grade and group_values(line, dims) == target

    breakdown: dict[str, dict[str, Decimal]] = {dim: defaultdict(Decimal) for dim in DIMENSION_ORDER if dim not in dims}
    countries: dict[str, Decimal] = defaultdict(Decimal)
    country_customers: dict[str, set] = defaultdict(set)
    models: set[str] = set()
    matched = False
    for line in scoped:
        if not match(line):
            continue
        matched = True
        if _in(line, previous) or _in(line, current):
            models.add(line["model"])  # 只在上期有销量的行（跌榜）也要能深链，型号取两个窗口
        if not _in(line, current):
            continue
        for dim, bucket in breakdown.items():
            value = line.get(dim) or metrics.UNKNOWN_LABEL
            # 颜色/尺寸分布只用确切行，和排行口径一致；规格任何有 kg 的行都计入
            if value != metrics.UNKNOWN_LABEL and (dim == "spec" or line["confidence"] in metrics.CREDIBLE):
                bucket[value] += line["kg"]
        countries[line["country"]] += line["kg"]
        if line.get("company_id"):  # 缺客户 ID 的行不计入客户数，宁可多并入「其他」
            country_customers[line["country"]].add(line["company_id"])
    if not matched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该组合在所选时间内没有可统计的销量")

    rows, _ = aggregate(scoped, dims, current, previous, share)
    summary = next((row for row in rows if tuple(row["values"][dim] for dim in dims) == target), None)
    return {
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "values": dict(zip(dims, target)),
        "dim_labels": {dim: DIMENSIONS[dim] for dim in dims},
        "key": " · ".join(target),
        "summary": summary,
        "monthly": monthly_trend(lines, end, match, share),
        "breakdowns": [{"dim": dim, "label": DIMENSIONS[dim], "rows": _top(bucket)} for dim, bucket in breakdown.items()],
        "top_countries": _top(_safe_countries(countries, country_customers)),
        "models": sorted(models),
        "window": _window_payload(window_days, current, previous),
        "credibility": {"current": window_credibility(lines, current),
                        "previous": window_credibility(lines, previous)},
        "share_scope": {"mode": share.mode, "label": share.label},
    }


def get_grade_evidence(db: Session, grade: str, window_days: int, version: tuple, today: date | None = None,
                       top_n: int = 10) -> dict:
    """大类 AI 分析的结构化证据：公司口径（不含个人份额），每个单维度 + SKU 的排行与涨跌、月度走势。"""
    grade = validate_grade(grade)
    current, previous = windows(window_days, today)
    end = current[1]
    starts = _month_starts(end, TREND_MONTHS)
    lines = cached_lines(db, min(starts[0], previous[0]), end, version)
    scoped = [line for line in lines if line.get("grade") == grade]
    in_window = [line for line in scoped if _in(line, previous) or _in(line, current)]

    def compact(row: dict) -> dict:
        return {key: row[key] for key in ("key", "kg", "prev_kg", "delta_kg", "growth", "quantity", "rank", "prev_rank")}

    dimensions = []
    for dims in (("color",), ("size",), ("spec",), DIMENSION_ORDER):
        rows, excluded = aggregate(in_window, dims, current, previous, COMPANY_SCOPE)
        moving = movers(rows, 5)
        dimensions.append({
            "dimension": " × ".join(DIMENSIONS[dim] for dim in dims) if len(dims) > 1 else DIMENSIONS[dims[0]],
            "group_count": sum(1 for row in rows if row["kg"] > 0),
            "excluded_quantity": float(excluded),
            "top": [compact(row) for row in rows[:top_n] if row["kg"] > 0],
            "risers": [compact(row) for row in moving["risers"]],
            "fallers": [compact(row) for row in moving["fallers"]],
        })
    cred_cur, cred_prev = window_credibility(lines, current), window_credibility(lines, previous)
    return {
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "window": _window_payload(window_days, current, previous),
        "comparable": bool(cred_cur["credible"] and cred_prev["credible"]),
        "credibility": {"current": cred_cur, "previous": cred_prev, "threshold": float(metrics.CREDIBLE_MONTH_SHARE)},
        "summary": {"kg": round(float(_sum(scoped, current)), 3), "prev_kg": round(float(_sum(scoped, previous)), 3),
                    "quantity": float(_sum(scoped, current, "quantity")),
                    "prev_quantity": float(_sum(scoped, previous, "quantity"))},
        "monthly": [{key: row[key] for key in ("month", "kg", "credible", "partial", "days_covered")}
                    for row in monthly_trend(lines, end, lambda line: line.get("grade") == grade)],
        "dimensions": dimensions,
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
