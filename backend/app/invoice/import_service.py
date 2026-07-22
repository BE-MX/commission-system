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
from app.invoice.models import CustomerPriceRule, PriceColorType, StdPrice

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

    if not raw_rows:
        raise ValueError("导入数据至少包含 1 行")
    if len(raw_rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"单次最多导入 {MAX_IMPORT_ROWS} 行")

    parsed_rows: list[dict] = []
    valid_rows: list[dict] = []
    for raw in raw_rows:
        try:
            normalized = normalize_row(raw)
        except ValueError as exc:
            parsed_rows.append(_invalid_result(raw, str(exc)))
        else:
            parsed_rows.append({"normalized": normalized})
            valid_rows.append(normalized)

    product_index = _load_product_index(db)
    hits_by_row = [product_index.get(_product_key(row), []) for row in valid_rows]
    product_ids = {int(hit["product_id"]) for hits in hits_by_row for hit in hits}
    sku_map = _load_sku_map(db, product_ids)
    pricing_context = _load_pricing_context(db, customer_id=str(customer_id))
    valid_results = iter([
        _apply_pricing(
            _build_match_result(row, hits, sku_map, order_type),
            pricing_context,
            str(currency).upper(),
        )
        for row, hits in zip(valid_rows, hits_by_row, strict=True)
    ])
    results = [
        parsed if "status" in parsed else next(valid_results)
        for parsed in parsed_rows
    ]
    summary = {"total": len(results), "passed": 0, "warning": 0, "blocked": 0}
    for row in results:
        summary[row["status"]] += 1
    return {
        "batch_fingerprint": make_batch_fingerprint([
            parsed["normalized"] for parsed in parsed_rows
        ]),
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
    for row in product_service.load_okki_rows(db, limit=None):
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


def _invalid_result(raw: Mapping[str, object], error: str) -> dict:
    source_row = int(raw.get("source_row") or 1)
    normalized = {
        "source_row": source_row,
        "product": _display_text(raw.get("product")),
        "length": _display_text(raw.get("length")),
        "color": _display_text(raw.get("color")),
        "weight": _display_text(raw.get("weight")),
        "quantity": raw.get("quantity"),
        "unit_price": raw.get("unit_price"),
    }
    return {
        "source_row": source_row,
        "normalized": normalized,
        "matched_product": None,
        "candidates": [],
        "can_create_custom": False,
        "customer_price": None,
        "standard_price": None,
        "price_difference": None,
        "price_source": "missing_std",
        "status": "blocked",
        "errors": [f"第 {source_row} 行{error}，请回到 Excel 修正后重新校验"],
        "warnings": [],
    }


def _load_sku_map(db: Session, product_ids: set[int]) -> dict[int, list[int]]:
    if not product_ids:
        return {}
    columns = product_service._table_columns(db, "okki_inventory")
    if not {"product_id", "sku_id"}.issubset(columns):
        return {}
    schema = product_service._schema()
    active = product_service._disable_filter("okki_inventory", columns)
    statement = text(f"""
        SELECT DISTINCT product_id, sku_id
        FROM `{schema}`.okki_inventory
        WHERE product_id IN :product_ids AND {active}
        ORDER BY product_id, sku_id
    """).bindparams(bindparam("product_ids", expanding=True))
    rows = db.execute(statement, {"product_ids": sorted(product_ids)}).mappings().all()
    result: dict[int, list[int]] = {}
    for row in rows:
        if row["sku_id"] is not None:
            result.setdefault(int(row["product_id"]), []).append(int(row["sku_id"]))
    return result


def _product_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        price_service.normalize_text(str(row["product"])),
        price_service.normalize_color(str(row["color"])),
        price_service.normalize_length(str(row["length"])),
        price_service.normalize_text(str(row["weight"])),
    )


def _build_match_result(row: dict, hits: list[dict], sku_map: dict[int, list[int]], order_type: str) -> dict:
    candidates = []
    for hit in sorted(hits, key=lambda item: item["product_id"]):
        sku_ids = sku_map.get(hit["product_id"], [])
        candidates.extend({**hit, "sku_id": sku_id} for sku_id in sku_ids)
        if not sku_ids:
            candidates.append({**hit, "sku_id": None})

    matched = candidates[0] if len(candidates) == 1 else None
    errors: list[str] = []
    can_create_custom = False
    if len(candidates) > 1:
        product_count = len({candidate["product_id"] for candidate in candidates})
        subject = f"{product_count} 个产品" if product_count > 1 else f"{len(candidates)} 个 SKU"
        errors.append(f"第 {row['source_row']} 行找到 {subject}，请选择正确的 SKU")
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


def _load_pricing_context(db: Session, *, customer_id: str) -> dict:
    color_rows = db.query(PriceColorType).all()
    standard_rows = db.query(StdPrice).filter(StdPrice.product_kind == "hair").all()
    rule = (
        db.query(CustomerPriceRule)
        .filter(CustomerPriceRule.customer_id == customer_id, CustomerPriceRule.enabled == 1)
        .first()
    )
    return {
        "color_types": {
            price_service.normalize_color(row.color_code): row.color_type
            for row in color_rows
        },
        "standard_prices": standard_rows,
        "customer_rule": rule,
    }


def _apply_pricing(result: dict, context: dict, invoice_currency: str) -> dict:
    row = result["normalized"]
    color_code = price_service.normalize_color(row["color"])
    color_type = context["color_types"].get(color_code) or price_service._infer_color_type(color_code)
    standard = _find_standard_price(
        context["standard_prices"],
        product_display=row["product"],
        length=row["length"],
        unit=row["weight"],
        color_type=color_type,
    ) if color_type else None

    warnings = result["warnings"]
    if standard is None:
        warnings.append(f"第 {row['source_row']} 行没有可用的 {invoice_currency} 系统价格，将保留 Excel 成交价")
    elif str(standard.currency).upper() != invoice_currency:
        warnings.append(
            f"第 {row['source_row']} 行系统价格币种为 {str(standard.currency).upper()}，"
            f"当前发票币种为 {invoice_currency}，无法直接比较；将保留 Excel 成交价"
        )
    else:
        standard_price = Decimal(standard.price)
        customer_price = price_service.apply_rule(standard_price, context["customer_rule"])
        difference = (row["unit_price"] - customer_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        result["standard_price"] = standard_price
        result["customer_price"] = customer_price
        result["price_difference"] = difference
        if difference == 0:
            result["price_source"] = "customer_rule"
        else:
            result["price_source"] = "manual"
            warnings.append(
                f"第 {row['source_row']} 行 Excel 成交价与客户价相差 {difference} {invoice_currency}，"
                "将保留 Excel 成交价"
            )

    if result["errors"]:
        result["status"] = "blocked"
    elif warnings:
        result["status"] = "warning"
    else:
        result["status"] = "passed"
    return result


def _find_standard_price(
    rows: list[StdPrice],
    *,
    product_display: str,
    length: str,
    unit: str,
    color_type: str,
) -> StdPrice | None:
    display_norm = price_service.normalize_text(product_display)
    candidates = [
        row for row in rows
        if row.product_kind == "hair"
        and row.length == price_service.normalize_length(length)
        and row.weight_unit == price_service.normalize_text(unit)
        and row.color_type == color_type
    ]
    matched = []
    for row in candidates:
        series_norm = price_service.normalize_text(row.series_grade)
        if series_norm and (display_norm.startswith(series_norm) or series_norm.startswith(display_norm)):
            matched.append(row)
    if not matched:
        return None
    if len({price_service.normalize_text(row.series_grade) for row in matched}) > 1:
        return None
    return matched[0]


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
        raise ValueError("Weight 必须是克或千克，例如 100g / 37.5g")
    amount = Decimal(match.group(1))
    grams = amount * (Decimal("1000") if match.group(2) == "kg" else Decimal("1"))
    if grams <= 0:
        raise ValueError("Weight 必须大于 0")
    return f"{_format_grams(grams)}g"


def _format_grams(grams: Decimal) -> str:
    """100 / 100.00 -> '100'；37.50 -> '37.5'（去掉无意义的尾随 0，保留小数克重）。"""
    trimmed = grams.normalize()
    if trimmed == trimmed.to_integral_value():
        trimmed = trimmed.quantize(Decimal(1))
    return format(trimmed, "f")


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
