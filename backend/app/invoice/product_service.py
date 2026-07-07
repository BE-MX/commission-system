"""Product/customer queries for invoice entry.

okki_products stays read-only (synced projection of the OKKI cloud library).
Free-form production products are sunk into ark_custom_products on the Ark
side, keyed by a normalized attribute tuple so re-entry reuses the same row.
"""

import logging
from decimal import Decimal
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.invoice.models import CustomProduct
from app.invoice.price_service import make_match_key, normalize_color, normalize_length, normalize_text

logger = logging.getLogger(__name__)

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


def get_entry_options(db: Session) -> dict[str, list[str]]:
    """Candidate values for free-form production entry: okki UNION custom."""
    schema = _schema()
    product_columns = _table_columns(db, "okki_products")
    name_col = "product_name" if "product_name" in product_columns else "name"

    def _distinct(expr: str, where_extra: str = "") -> list[str]:
        rows = db.execute(text(f"""
            SELECT DISTINCT {expr} AS value
            FROM `{schema}`.okki_products p
            WHERE {_disable_filter("okki_products", product_columns, alias="p")} {where_extra}
            ORDER BY value LIMIT 500
        """)).scalars().all()
        return [str(v) for v in rows if v not in (None, "")]

    displays = _distinct(f"SUBSTRING_INDEX(p.`{name_col}`, '/', 1)", f"AND p.`{name_col}` LIKE '%/%'")
    options = {
        "displays": displays,
        "models": _distinct("p.`model`") if "model" in product_columns else [],
        "colors": _distinct("p.`color`") if "color" in product_columns else [],
        "sizes": _distinct("p.`size`") if "size" in product_columns else [],
        "units": _distinct("p.`unit`") if "unit" in product_columns else [],
    }

    custom_rows = db.query(CustomProduct).order_by(CustomProduct.updated_at.desc()).limit(500).all()
    merge = {
        "displays": [c.product_display for c in custom_rows],
        "models": [c.model for c in custom_rows if c.model],
        "colors": [c.color for c in custom_rows],
        "sizes": [c.size for c in custom_rows],
        "units": [c.unit for c in custom_rows],
    }
    for key, extras in merge.items():
        seen = {normalize_text(v) for v in options[key]}
        for value in extras:
            if normalize_text(value) not in seen:
                options[key].append(value)
                seen.add(normalize_text(value))
    return options


def _load_okki_rows(db: Session) -> list:
    schema = _schema()
    product_columns = _table_columns(db, "okki_products")
    if not {"color", "size", "unit", "product_id"}.issubset(product_columns):
        return []
    name_expr = _quoted_column(product_columns, "product_name", "name")
    return db.execute(text(f"""
        SELECT p.product_id, {name_expr} AS product_name, p.color, p.size, p.unit
        FROM `{schema}`.okki_products p
        WHERE {_disable_filter("okki_products", product_columns, alias="p")}
        LIMIT 5000
    """)).mappings().all()


def find_okki_by_attributes(
    db: Session,
    *,
    product_display: str,
    color: str,
    size: str,
    unit: str,
    okki_rows: list | None = None,
) -> dict | None:
    """Match one okki product by normalized (name-prefix, color, size, unit).

    Returns the mapped row only when the match is unique; ambiguity returns None.
    """
    rows = okki_rows if okki_rows is not None else _load_okki_rows(db)

    want = (
        normalize_text(product_display),
        normalize_color(color),
        normalize_length(size),
        normalize_text(unit),
    )
    hits = []
    for row in rows:
        name = str(row["product_name"] or "")
        prefix = name.split("/", 1)[0]
        got = (
            normalize_text(prefix),
            normalize_color(row["color"]),
            normalize_length(row["size"]),
            normalize_text(row["unit"]),
        )
        if got == want:
            hits.append(row)
    if len(hits) != 1:
        return None
    hit = hits[0]
    schema = _schema()
    sku = db.execute(text(f"""
        SELECT MIN(sku_id) AS sku_id, COUNT(DISTINCT sku_id) AS sku_count
        FROM `{schema}`.okki_inventory
        WHERE product_id = :pid AND { _disable_filter("okki_inventory", _table_columns(db, "okki_inventory")) }
    """), {"pid": hit["product_id"]}).mappings().first()
    return {
        "product_id": int(hit["product_id"]),
        "product_name": str(hit["product_name"]),
        "sku_id": int(sku["sku_id"]) if sku and sku["sku_id"] is not None else None,
        "sku_count": int(sku["sku_count"] or 0) if sku else 0,
    }


def ensure_custom_product(
    db: Session,
    *,
    product_display: str,
    model: str | None,
    color: str,
    size: str,
    unit: str,
    user_id: int | None = None,
) -> dict:
    """Resolve a free-form production line to a product identity.

    1. Unique okki match -> use the real cloud product (no local row needed).
    2. Existing custom row (by match_key) -> reuse, bump use_count.
    3. Otherwise insert a new ark_custom_products row.
    """
    okki = find_okki_by_attributes(db, product_display=product_display, color=color, size=size, unit=unit)
    if okki:
        return {"source": "okki", "custom_product_id": None, **okki}

    key = make_match_key(product_display, model, color, size, unit)
    row = db.query(CustomProduct).filter(CustomProduct.match_key == key).first()
    if row:
        row.use_count = (row.use_count or 0) + 1
    else:
        row = CustomProduct(
            match_key=key,
            product_display=product_display.strip(),
            product_name=compose_product_name(product_display, size, color, unit),
            model=(model or "").strip() or None,
            color=color.strip(),
            size=size.strip(),
            unit=unit.strip(),
            created_by=user_id,
        )
        db.add(row)
        db.flush()
    return {
        "source": "custom",
        "custom_product_id": row.id,
        "product_id": row.okki_product_id,
        "sku_id": row.okki_sku_id,
        "product_name": row.product_name,
        "sku_count": 0,
    }


def compose_product_name(product_display: str, size: str, color: str, unit: str) -> str:
    """Mirror okki naming (display/size/color/unit) so reconciliation stays trivial."""
    return "/".join(part.strip() for part in (product_display, size, color, unit))


def reconcile_custom_products(db: Session) -> dict:
    """Backfill okki IDs for custom rows once OKKI officially creates them."""
    pending = db.query(CustomProduct).filter(CustomProduct.okki_product_id.is_(None)).all()
    linked = 0
    okki_rows = _load_okki_rows(db) if pending else []
    for row in pending:
        okki = find_okki_by_attributes(
            db, product_display=row.product_display, color=row.color, size=row.size, unit=row.unit,
            okki_rows=okki_rows,
        )
        if okki:
            row.okki_product_id = okki["product_id"]
            row.okki_sku_id = okki["sku_id"]
            linked += 1
    return {"checked": len(pending), "linked": linked}


def list_custom_products(db: Session, *, keyword: str | None = None, limit: int = 200) -> list[dict]:
    query = db.query(CustomProduct)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (CustomProduct.product_name.like(like)) | (CustomProduct.model.like(like))
        )
    rows = query.order_by(CustomProduct.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "product_display": r.product_display,
            "product_name": r.product_name,
            "model": r.model,
            "color": r.color,
            "size": r.size,
            "unit": r.unit,
            "okki_product_id": r.okki_product_id,
            "okki_sku_id": r.okki_sku_id,
            "use_count": r.use_count,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


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

