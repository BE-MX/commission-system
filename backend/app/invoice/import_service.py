"""Side-effect-free preview helpers for pasted invoice lines."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.invoice import price_service
from app.invoice import product_service

MAX_IMPORT_ROWS = 200


def normalize_row(raw: Mapping[str, object]) -> dict:
    source_row = _positive_int(raw.get("source_row"), "source_row")
    product = _display_text(raw.get("product"))
    length = price_service.normalize_length(_display_text(raw.get("length")))
    color = _normalize_color_display(raw.get("color"))
    weight = _normalize_weight(raw.get("weight"))
    quantity = _positive_int(raw.get("quantity"), "quantity")
    unit_price = _positive_money(raw.get("unit_price"))
    if not all((product, length, color)):
        raise ValueError("Product、Length、Color 必填")
    return {
        "source_row": source_row,
        "product": product,
        "length": length,
        "color": color,
        "weight": weight,
        "quantity": quantity,
        "unit_price": unit_price,
    }


def normalize_rows(raw_rows: Sequence[Mapping[str, object]]) -> list[dict]:
    if not raw_rows:
        raise ValueError("导入数据至少包含 1 行")
    if len(raw_rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"单次最多导入 {MAX_IMPORT_ROWS} 行")
    return [normalize_row(row) for row in raw_rows]


def make_batch_fingerprint(rows: Sequence[Mapping[str, object]]) -> str:
    stable = [
        {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}
        for row in rows
    ]
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview_import(
    db: Session,
    *,
    customer_id: str,
    order_type: str,
    currency: str,
    raw_rows: list[dict],
) -> dict:
    if order_type not in {"stock", "production"}:
        raise ValueError("order_type 必须是 stock 或 production")
    if not str(customer_id or "").strip():
        raise ValueError("customer_id 必填")
    if not str(currency or "").strip():
        raise ValueError("currency 必填")

    rows = normalize_rows(raw_rows)
    product_index = _load_product_index(db)
    hits_by_row = [product_index.get(_product_key(row), []) for row in rows]
    product_ids = {int(hit["product_id"]) for hits in hits_by_row for hit in hits}
    sku_map = _load_sku_map(db, product_ids)
    results = [
        _build_match_result(row, hits, sku_map, order_type)
        for row, hits in zip(rows, hits_by_row, strict=True)
    ]
    summary = {"total": len(results), "passed": 0, "warning": 0, "blocked": 0}
    for row in results:
        summary[row["status"]] += 1
    return {
        "batch_fingerprint": make_batch_fingerprint(rows),
        "context": {
            "customer_id": str(customer_id),
            "order_type": order_type,
            "currency": str(currency).upper(),
        },
        "summary": summary,
        "rows": results,
    }


def _load_product_index(db: Session) -> dict[tuple[str, str, str, str], list[dict]]:
    index: dict[tuple[str, str, str, str], list[dict]] = {}
    for row in product_service.load_okki_rows(db):
        product_name = str(row["product_name"] or "")
        product_display = product_name.split("/", 1)[0].strip()
        item = {
            "product_id": int(row["product_id"]),
            "product_name": product_name,
            "product_display": product_display,
            "color": str(row["color"] or ""),
            "length": str(row["size"] or ""),
            "net_weight_grams": str(row["unit"] or ""),
        }
        key = (
            price_service.normalize_text(product_display),
            price_service.normalize_color(item["color"]),
            price_service.normalize_length(item["length"]),
            price_service.normalize_text(item["net_weight_grams"]),
        )
        index.setdefault(key, []).append(item)
    return index


def _load_sku_map(db: Session, product_ids: set[int]) -> dict[int, dict]:
    if not product_ids:
        return {}
    columns = product_service._table_columns(db, "okki_inventory")
    if not {"product_id", "sku_id"}.issubset(columns):
        return {}
    schema = product_service._schema()
    active = product_service._disable_filter("okki_inventory", columns)
    statement = text(f"""
        SELECT product_id, MIN(sku_id) AS sku_id, COUNT(DISTINCT sku_id) AS sku_count
        FROM `{schema}`.okki_inventory
        WHERE product_id IN :product_ids AND {active}
        GROUP BY product_id
    """).bindparams(bindparam("product_ids", expanding=True))
    rows = db.execute(statement, {"product_ids": sorted(product_ids)}).mappings().all()
    return {
        int(row["product_id"]): {
            "sku_id": int(row["sku_id"]) if row["sku_id"] is not None else None,
            "sku_count": int(row["sku_count"] or 0),
        }
        for row in rows
    }


def _product_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        price_service.normalize_text(str(row["product"])),
        price_service.normalize_color(str(row["color"])),
        price_service.normalize_length(str(row["length"])),
        price_service.normalize_text(str(row["weight"])),
    )


def _build_match_result(row: dict, hits: list[dict], sku_map: dict[int, dict], order_type: str) -> dict:
    candidates = []
    for hit in sorted(hits, key=lambda item: item["product_id"]):
        candidate = {**hit, **sku_map.get(hit["product_id"], {"sku_id": None, "sku_count": 0})}
        candidates.append(candidate)

    matched = candidates[0] if len(candidates) == 1 else None
    errors: list[str] = []
    can_create_custom = False
    if len(candidates) > 1:
        errors.append(f"第 {row['source_row']} 行找到 {len(candidates)} 个产品，请选择正确的 SKU")
    elif matched is None:
        can_create_custom = order_type == "production"
        errors.append(
            f"第 {row['source_row']} 行未匹配到产品，"
            + ("可确认作为定制产品" if can_create_custom else "请选择已有产品")
        )
    elif matched["sku_id"] is None:
        can_create_custom = order_type == "production"
        errors.append(f"第 {row['source_row']} 行匹配产品没有可用 SKU")

    return {
        "source_row": row["source_row"],
        "normalized": row,
        "matched_product": matched,
        "candidates": candidates if len(candidates) != 1 else [],
        "can_create_custom": can_create_custom,
        "customer_price": None,
        "standard_price": None,
        "price_difference": None,
        "price_source": "missing_std",
        "status": "blocked" if errors else "passed",
        "errors": errors,
        "warnings": [],
    }


def _display_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_color_display(value: object) -> str:
    color = _display_text(value)
    if not color:
        return ""
    if color.startswith("#"):
        return f"#{color[1:].upper()}"
    return color


def _normalize_weight(value: object) -> str:
    text = _display_text(value).lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(kg|g)?", text)
    if not match:
        raise ValueError("Weight 必须是克或千克，例如 100g")
    amount = Decimal(match.group(1))
    grams = amount * (Decimal("1000") if match.group(2) == "kg" else Decimal("1"))
    if grams <= 0 or grams != grams.to_integral_value():
        raise ValueError("Weight 必须能换算为正整数克")
    return f"{int(grams)}g"


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是正整数")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是正整数") from exc
    if parsed <= 0 or parsed != parsed.to_integral_value():
        raise ValueError(f"{field} 必须是正整数")
    return int(parsed)


def _positive_money(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Unit Price 必须是大于 0 的数字") from exc
    if parsed <= 0:
        raise ValueError("Unit Price 必须是大于 0 的数字")
    return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
