"""产品销量口径：每条有效订单明细 → 标准化维度 + 件数 + kg + 置信度。

口径（docs/requirements/2026-11-18-product-sales-radar/README.md 第 2、4 节）：
- 有效订单与战报 GMV 相同：``app.dingtalk.gmv_daily_service.VALID_ORDER_SQL``。
- 重量 = quantity × okki_products.unit（g）；产品表命中且 unit 可解析才算 ``exact``。
- 旧产品库时期（产品表找不到）的品名只能给出型号：经映射表取默认克重，置信度
  ``assumed``，颜色/发长固定「未知」。人工确认只代表采纳假设，不升级为确切值。
- 退货不按款冲减（销售退货单无可靠的款级克重），与 Codex 报告口径一致。
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dingtalk.gmv_daily_service import VALID_ORDER_SQL
from app.order_intelligence.filtering import name_color
from app.product_sales.models import MAPPING_CONFIRMED, MAPPING_SUGGESTED, ProductSalesNameMapping

EXACT = "exact"
DERIVED = "derived"
ASSUMED = "assumed"
UNKNOWN = "unknown"
CONFIDENCES = (EXACT, DERIVED, ASSUMED, UNKNOWN)
CREDIBLE = (EXACT, DERIVED)
CREDIBLE_MONTH_SHARE = Decimal("0.9")
UNKNOWN_LABEL = "未知"

_GRAMS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*g\s*$", re.IGNORECASE)
_QUOTES = str.maketrans({"“": '"', "”": '"', "″": '"', "＂": '"', "（": "(", "）": ")", "　": " "})
_SPACES = re.compile(r"\s+")


def parse_grams(value: object) -> Decimal | None:
    """'20g' / '2.5 G' → Decimal；其他格式（'Customized Order'、'#1'）→ None。"""
    match = _GRAMS.match(str(value or ""))
    if not match:
        return None
    grams = Decimal(match.group(1))
    return grams if grams > 0 else None


def normalize_name(name: object) -> str:
    return _SPACES.sub(" ", str(name or "").translate(_QUOTES)).strip().casefold()


def name_hash(name: object) -> str:
    return hashlib.sha256(normalize_name(name).encode("utf-8")).hexdigest()


def _segments(name: object) -> list[str]:
    return [part.strip() for part in str(name or "").split("/")]


def _clean(value: object) -> str:
    return str(value or "").strip()


def spec_key(model: object, size: object) -> str:
    return f"{normalize_name(model)}|{normalize_name(size)}"


def classify_line(row: dict, mappings: dict[str, ProductSalesNameMapping], known_specs: set[str]) -> dict:
    """单行归类。``row`` 需含 product_name、p_model/p_color/p_size/p_unit、quantity。"""
    name = row.get("product_name")
    parts = _segments(name)
    quantity = Decimal(str(row.get("quantity") or 0))
    line = {
        "order_id": str(row.get("order_id") or ""),
        "company_id": str(row.get("company_id") or ""),
        "user_id": str(row.get("user_id") or ""),
        "account_date": row.get("account_date"),
        "country": _clean(row.get("country")) or UNKNOWN_LABEL,
        "product_name": _clean(name),
        "quantity": quantity,
        "model": UNKNOWN_LABEL,
        "color": UNKNOWN_LABEL,
        "size": UNKNOWN_LABEL,
        "unit_grams": None,
        "kg": None,
        "confidence": UNKNOWN,
    }
    grams = parse_grams(row.get("p_unit"))
    mapping = mappings.get(name_hash(name)) if grams is None else None
    if grams is not None:
        line.update(
            model=_clean(row.get("p_model")) or parts[0] or UNKNOWN_LABEL,
            color=_clean(row.get("p_color")) or name_color(name) or UNKNOWN_LABEL,
            size=_clean(row.get("p_size")) or (parts[1] if len(parts) >= 2 else "") or UNKNOWN_LABEL,
            confidence=EXACT,
        )
    elif mapping is not None and mapping.status != MAPPING_SUGGESTED:
        # 人工结论优先于规则解析：confirmed 采纳克重假设（仍是 assumed），ignored 不计重量。
        line["model"] = _clean(mapping.model) or UNKNOWN_LABEL
        if mapping.status == MAPPING_CONFIRMED and mapping.unit_grams:
            grams = Decimal(str(mapping.unit_grams))
            line["confidence"] = ASSUMED
    elif len(parts) >= 3 and parse_grams(parts[-1]) is not None:
        grams = parse_grams(parts[-1])
        model, size = parts[0] or UNKNOWN_LABEL, parts[1] or UNKNOWN_LABEL
        line.update(
            model=model,
            color=name_color(name) or UNKNOWN_LABEL,
            size=size,
            confidence=DERIVED if spec_key(model, size) in known_specs else ASSUMED,
        )
    elif mapping is not None and mapping.unit_grams:
        grams = Decimal(str(mapping.unit_grams))
        line.update(model=_clean(mapping.model) or UNKNOWN_LABEL, confidence=ASSUMED)
    elif mapping is not None and mapping.model:
        line["model"] = _clean(mapping.model)
    if grams is not None:
        line["unit_grams"] = grams
        line["kg"] = quantity * grams / Decimal(1000)
    return line


def load_mappings(db: Session) -> dict[str, ProductSalesNameMapping]:
    return {row.name_hash: row for row in db.query(ProductSalesNameMapping).all()}


def load_known_specs(db: Session) -> set[str]:
    """当前产品表里克重可解析的「型号|规格」，用于判定结构化品名是否 derived。"""
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(text(
        f"SELECT DISTINCT model, size, unit FROM `{schema}`.okki_products WHERE model IS NOT NULL AND model <> ''"
    ))
    return {spec_key(model, size) for model, size, unit in rows if parse_grams(unit) is not None}


def load_raw_rows(db: Session, date_from: date, date_to: date) -> list[dict]:
    schema = get_settings().BUSINESS_DB_NAME
    sql = f"""
        SELECT o.order_id, o.company_id, o.user_id, o.account_date,
               COALESCE(NULLIF(NULLIF(TRIM(ci.country_name), ''), '0'), '未知') country,
               oi.product_name, oi.quantity,
               p.model p_model, p.color p_color, p.size p_size, p.unit p_unit
        FROM `{schema}`.okki_orders o
        JOIN `{schema}`.okki_order_items oi ON oi.order_id = o.order_id
        LEFT JOIN `{schema}`.customer_info ci ON ci.company_id = o.company_id
        LEFT JOIN `{schema}`.okki_products p ON p.product_id = oi.product_id
        WHERE {VALID_ORDER_SQL}
          AND o.account_date >= :date_from AND o.account_date <= :date_to
    """
    return [dict(row) for row in db.execute(text(sql), {"date_from": date_from, "date_to": date_to}).mappings()]


def load_lines(db: Session, date_from: date, date_to: date) -> list[dict]:
    """全公司口径明细。数据范围裁剪由调用方按 user_id 过滤（P1 接入）。"""
    mappings = load_mappings(db)
    known_specs = load_known_specs(db)
    return [classify_line(row, mappings, known_specs) for row in load_raw_rows(db, date_from, date_to)]


def monthly_coverage(lines: Iterable[dict]) -> list[dict]:
    """按月统计件数分档与 kg；``credible`` = exact+derived 件数占比 ≥ 90%。"""
    months: dict[str, dict] = defaultdict(lambda: {
        "quantity": Decimal(0), "kg": Decimal(0), "lines": 0,
        **{f"{level}_quantity": Decimal(0) for level in CONFIDENCES},
    })
    for line in lines:
        account_date = line.get("account_date")
        if account_date is None:
            continue
        bucket = months[f"{account_date:%Y-%m}"]
        bucket["lines"] += 1
        bucket["quantity"] += line["quantity"]
        bucket[f"{line['confidence']}_quantity"] += line["quantity"]
        if line["kg"] is not None:
            bucket["kg"] += line["kg"]
    result = []
    for month in sorted(months):
        bucket = months[month]
        total = bucket["quantity"]
        credible_qty = sum(bucket[f"{level}_quantity"] for level in CREDIBLE)
        share = (credible_qty / total) if total else Decimal(0)
        result.append({
            "month": month,
            "lines": bucket["lines"],
            "quantity": float(total),
            "kg": round(float(bucket["kg"]), 3),
            **{f"{level}_quantity": float(bucket[f"{level}_quantity"]) for level in CONFIDENCES},
            "credible_share": round(float(share), 4),
            "credible": share >= CREDIBLE_MONTH_SHARE,
        })
    return result
