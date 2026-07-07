"""Read-only product/customer queries for invoice entry."""

from decimal import Decimal
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()


def _schema() -> str:
    return settings.BUSINESS_DB_NAME


def _table_columns(db: Session, table_name: str) -> set[str]:
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    schema = _schema()
    if dialect == "sqlite":
        rows = db.execute(text(f"PRAGMA {schema}.table_info({table_name})")).mappings().all()
        return {str(row["name"]) for row in rows}
    rows = db.execute(text(f"SHOW COLUMNS FROM `{schema}`.`{table_name}`")).mappings().all()
    return {str(row["Field"]) for row in rows}


def _quoted_column(columns: set[str], preferred: str, fallback: str | None = None) -> str:
    if preferred in columns:
        return f"p.`{preferred}`"
    if fallback and fallback in columns:
        return f"p.`{fallback}`"
    return "NULL"


def _product_display(product_name: str) -> str:
    if not product_name:
        return ""
    return product_name.split("/", 1)[0].strip() or product_name


def search_customers(db: Session, keyword: str | None = None, limit: int = 20) -> list[dict]:
    schema = _schema()
    params: dict[str, object] = {"limit": min(max(limit, 1), 50)}
    where = ""
    if keyword:
        where = "WHERE company_id LIKE :kw OR company_name LIKE :kw"
        params["kw"] = f"%{keyword}%"
    rows = db.execute(text(f"""
        SELECT company_id, company_name, country_name
        FROM `{schema}`.customer_info
        {where}
        ORDER BY company_name
        LIMIT :limit
    """), params).mappings().all()
    return [dict(row) for row in rows]


def get_filter_options(
    db: Session,
    *,
    model: str | None = None,
    color: str | None = None,
    size: str | None = None,
    unit: str | None = None,
) -> dict[str, list[str]]:
    return {
        "models": _distinct_values(db, "model", {"model": model, "color": color, "size": size, "unit": unit}),
        "colors": _distinct_values(db, "color", {"model": model, "color": color, "size": size, "unit": unit}),
        "sizes": _distinct_values(db, "size", {"model": model, "color": color, "size": size, "unit": unit}),
        "units": _distinct_values(db, "unit", {"model": model, "color": color, "size": size, "unit": unit}),
    }


def _distinct_values(db: Session, target: str, filters: dict[str, str | None]) -> list[str]:
    schema = _schema()
    product_columns = _table_columns(db, "okki_products")
    if target not in product_columns:
        return []
    where, params = _build_product_where(product_columns, filters, exclude={target})
    rows = db.execute(text(f"""
        SELECT DISTINCT p.`{target}` AS value
        FROM `{schema}`.okki_products p
        WHERE {where}
          AND p.`{target}` IS NOT NULL
          AND p.`{target}` != ''
        ORDER BY p.`{target}`
        LIMIT 300
    """), params).scalars().all()
    return [str(v) for v in rows if v is not None and str(v) != ""]


def match_product(
    db: Session,
    *,
    model: str,
    color: str,
    size: str,
    unit: str,
) -> dict:
    schema = _schema()
    product_columns = _table_columns(db, "okki_products")
    inventory_columns = _table_columns(db, "okki_inventory")
    name_expr = _quoted_column(product_columns, "product_name", "name")
    product_no_expr = _quoted_column(product_columns, "product_no")
    if not {"model", "color", "size", "unit", "product_id"}.issubset(product_columns):
        return {"is_unique": False, "item": None, "matches": []}

    inventory_join = ""
    sku_select = "NULL AS sku_id, 0 AS sku_count"
    if {"product_id", "sku_id"}.issubset(inventory_columns):
        inventory_join = f"""
            LEFT JOIN (
                SELECT product_id,
                       MIN(sku_id) AS sku_id,
                       COUNT(DISTINCT sku_id) AS sku_count
                FROM `{schema}`.okki_inventory
                WHERE { _disable_filter("okki_inventory", inventory_columns) }
                GROUP BY product_id
            ) inv ON inv.product_id = p.product_id
        """
        sku_select = "inv.sku_id AS sku_id, COALESCE(inv.sku_count, 0) AS sku_count"

    rows = db.execute(text(f"""
        SELECT p.product_id,
               {sku_select},
               {name_expr} AS product_name,
               {product_no_expr} AS product_no,
               p.model,
               p.color,
               p.size,
               p.unit
        FROM `{schema}`.okki_products p
        {inventory_join}
        WHERE {_disable_filter("okki_products", product_columns, alias="p")}
          AND p.model = :model
          AND p.color = :color
          AND p.size = :size
          AND p.unit = :unit
        ORDER BY p.product_id
        LIMIT 20
    """), {"model": model, "color": color, "size": size, "unit": unit}).mappings().all()

    matches = [_map_product_row(row) for row in rows]
    return {
        "is_unique": len(matches) == 1,
        "item": matches[0] if len(matches) == 1 else None,
        "matches": matches,
    }


def _build_product_where(
    product_columns: set[str],
    filters: dict[str, str | None],
    exclude: Iterable[str] = (),
) -> tuple[str, dict]:
    params: dict[str, object] = {}
    clauses = [_disable_filter("okki_products", product_columns, alias="p")]
    excluded = set(exclude)
    for key in ("model", "color", "size", "unit"):
        value = filters.get(key)
        if value and key in product_columns and key not in excluded:
            clauses.append(f"p.`{key}` = :{key}")
            params[key] = value
    return " AND ".join(clauses), params


def _disable_filter(table_name: str, columns: set[str], alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    if "disable_flag" in columns:
        return f"{prefix}disable_flag = 0"
    if "is_deleted" in columns:
        return f"{prefix}is_deleted = 0"
    return "1=1"


def _map_product_row(row) -> dict:
    product_name = str(row["product_name"] or row["product_no"] or row["product_id"])
    return {
        "product_id": int(row["product_id"]),
        "sku_id": int(row["sku_id"]) if row["sku_id"] is not None else None,
        "sku_count": int(row["sku_count"] or 0),
        "product_name": product_name,
        "product_display": _product_display(product_name),
        "model": str(row["model"] or ""),
        "color": str(row["color"] or ""),
        "size": str(row["size"] or ""),
        "unit": str(row["unit"] or ""),
        "price_per_piece": None,
        "price_source": "missing",
    }

