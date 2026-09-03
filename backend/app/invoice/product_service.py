"""Product/customer queries for invoice entry.

okki_products stays read-only (synced projection of the OKKI cloud library).
Free-form production products are sunk into ark_custom_products on the Ark
side, keyed by a normalized attribute tuple so re-entry reuses the same row.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.invoice.models import CustomProduct, InvoiceCustomerOverlay
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


def _owner_filter_clause(db: Session, owner_okki_id: int, alias: str = "ci") -> tuple[str, dict]:
    """私海过滤：owner_user_ids（JSON 数组，空数组=公海）包含指定 OKKI user_id。

    SQLite（测试态）没有 JSON_CONTAINS，用 LIKE 子串近似——夹具值可控；
    生产 MySQL 一律走 JSON_CONTAINS 精确匹配，不受子串误伤。
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return f"{alias}.owner_user_ids LIKE :owner_like", {"owner_like": f"%{owner_okki_id}%"}
    return f"JSON_CONTAINS({alias}.owner_user_ids, :owner_json)", {"owner_json": str(owner_okki_id)}


def search_customers(
    db: Session,
    keyword: str | None = None,
    limit: int = 20,
    owner_okki_id: int | None = None,
) -> list[dict]:
    limit = min(max(limit, 1), 50)
    schema = _schema()
    params: dict[str, object] = {"limit": limit}
    clauses: list[str] = []
    if keyword:
        clauses.append("(ci.company_id LIKE :kw OR ci.company_name LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if owner_okki_id is not None:
        clause, extra = _owner_filter_clause(db, owner_okki_id)
        clauses.append(clause)
        params.update(extra)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = [dict(row) for row in db.execute(text(f"""
        SELECT ci.company_id, ci.company_name, ci.country_name
        FROM `{schema}`.customer_info ci
        {where}
        ORDER BY ci.company_name
        LIMIT :limit
    """), params).mappings().all()]
    return _merge_customer_overlays(db, rows, keyword=keyword, limit=limit, owner_okki_id=owner_okki_id)


def _merge_customer_overlays(
    db: Session,
    rows: list[dict],
    *,
    keyword: str | None,
    limit: int,
    owner_okki_id: int | None,
) -> list[dict]:
    """合并手动同步 overlay（ark_invoice_customer_overlays，customer_sync_service 写入）。

    规则：镜像没有的客户直接补入；两源都有时，镜像 update_time 新于 overlay 的
    source_update_time 才让位给镜像（镜像已追上），否则以 overlay 为准——手动
    同步修的就是镜像过期/缺失。overlay 胜出时私海归属也按 overlay 重判
    （owner 已改走的客户不得再凭镜像的过期归属出现）。
    """
    query = db.query(InvoiceCustomerOverlay)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (InvoiceCustomerOverlay.company_id.like(like))
            | (InvoiceCustomerOverlay.company_name.like(like))
        )
    overlays = query.order_by(InvoiceCustomerOverlay.company_name).limit(limit).all()
    if not overlays:
        return rows

    merged = {str(r["company_id"]): r for r in rows}
    # 比新旧必须对全部 overlay 客户查镜像 update_time，不能用结果集交集：
    # 私海 SQL 会把 owner 过期的镜像行提前滤掉，交集里根本看不到它
    mirror_ts = _mirror_update_times(db, [o.company_id for o in overlays])

    for overlay in overlays:
        key = str(overlay.company_id)
        mirror_row = merged.get(key)
        mirror_dt = _parse_ts(mirror_ts.get(key))
        overlay_dt = _parse_ts(overlay.source_update_time)
        if mirror_dt is not None and overlay_dt is not None:
            mirror_fresh = mirror_dt >= overlay_dt  # 镜像已追上 → 让位回镜像
        else:
            # 任一侧时间戳缺失/不可解析 → 无法证明镜像更新，以手动同步为准
            mirror_fresh = False
            if mirror_ts.get(key) or overlay.source_update_time:
                logger.warning(
                    "customer overlay 时间戳不可比：mirror=%r overlay=%r，本次以 overlay 为准",
                    mirror_ts.get(key), overlay.source_update_time,
                )
        if mirror_fresh:
            continue
        if owner_okki_id is not None and str(owner_okki_id) not in {
            str(v) for v in (overlay.owner_user_ids or [])
        }:
            merged.pop(key, None)
            continue
        if mirror_row is None:
            merged[key] = {
                "company_id": overlay.company_id,
                "company_name": overlay.company_name,
                "country_name": overlay.country_name,
            }
        else:
            mirror_row["company_name"] = overlay.company_name or mirror_row["company_name"]
            mirror_row["country_name"] = overlay.country_name or mirror_row["country_name"]
    return sorted(merged.values(), key=lambda r: str(r["company_name"] or ""))[:limit]


def _parse_ts(value) -> datetime | None:
    """解析 OKKI/镜像时间戳：'YYYY-MM-DD HH:MM:SS'、ISO 或 epoch 秒；失败返回 None。"""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text))
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _mirror_update_times(db: Session, company_ids: list[str]) -> dict[str, str]:
    """镜像行的 update_time（老镜像/测试夹具无此列时返回空，合并退化为 overlay 优先）。"""
    if not company_ids or "update_time" not in _table_columns(db, "customer_info"):
        return {}
    schema = _schema()
    rows = db.execute(
        text(f"SELECT company_id, update_time FROM `{schema}`.customer_info WHERE company_id IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"ids": [str(c) for c in company_ids]},
    ).mappings().all()
    return {str(r["company_id"]): str(r["update_time"] or "") for r in rows}


def search_customer_contacts(
    db: Session,
    *,
    keyword: str | None = None,
    company_id: str | None = None,
    owner_okki_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """联系人维度搜客户：customer_contacts JOIN customer_info（双筛选联动）。

    company_id 给定时收敛到该客户名下（公司→联系人联动）；keyword 匹配联系人
    姓名；owner_okki_id 私海口径与 search_customers 一致。返回带公司信息，
    前端选中联系人即可反向定位客户。
    """
    schema = _schema()
    params: dict[str, object] = {"limit": min(max(limit, 1), 50)}
    clauses: list[str] = []
    if keyword:
        clauses.append("cc.name LIKE :kw")
        params["kw"] = f"%{keyword}%"
    if company_id:
        clauses.append("cc.company_id = :company_id")
        params["company_id"] = str(company_id)
    if owner_okki_id is not None:
        clause, extra = _owner_filter_clause(db, owner_okki_id)
        clauses.append(clause)
        params.update(extra)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(f"""
        SELECT cc.id AS contact_id, cc.name, cc.email, cc.tel, cc.is_main,
               ci.company_id, ci.company_name, ci.country_name
        FROM `{schema}`.customer_contacts cc
        JOIN `{schema}`.customer_info ci ON ci.company_id = cc.company_id
        {where}
        ORDER BY cc.is_main DESC, cc.name
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
    """级联候选：models/colors/sizes/units 按其余维度过滤（自身维度不参与）；
    all_* 为该维度全量候选，供前端「全部」分组——整行复制后其余三维已满时，
    级联列表会锁死换型号的路，全量组是唯一出口。其余维度无过滤时 all == 级联结果，
    不重复查询。
    """
    filters = {"model": model, "color": color, "size": size, "unit": unit}
    columns = _table_columns(db, "okki_products")
    result: dict[str, list[str]] = {}
    for target, key in (("model", "models"), ("color", "colors"), ("size", "sizes"), ("unit", "units")):
        matched = _distinct_values(db, target, filters, columns=columns)
        others_active = any(value for dim, value in filters.items() if dim != target)
        result[key] = matched
        result[f"all_{key}"] = _distinct_values(db, target, {}, columns=columns) if others_active else matched
    return result


def _distinct_values(
    db: Session,
    target: str,
    filters: dict[str, str | None],
    columns: set[str] | None = None,
) -> list[str]:
    schema = _schema()
    product_columns = _table_columns(db, "okki_products") if columns is None else columns
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


def load_okki_rows(db: Session, *, limit: int | None = 10000) -> list:
    """Attribute projection of okki_products for in-memory matching.

    Deterministic ORDER BY so a future >10000-row library degrades loudly
    (newest products first) instead of randomly.
    """
    schema = _schema()
    product_columns = _table_columns(db, "okki_products")
    if not {"color", "size", "unit", "product_id"}.issubset(product_columns):
        return []
    name_expr = _quoted_column(product_columns, "product_name", "name")
    product_no_expr = _quoted_column(product_columns, "product_no")
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    return db.execute(text(f"""
        SELECT p.product_id, {product_no_expr} AS product_no,
               {name_expr} AS product_name, p.color, p.size, p.unit
        FROM `{schema}`.okki_products p
        WHERE {_disable_filter("okki_products", product_columns, alias="p")}
        ORDER BY p.product_id DESC
        {limit_sql}
    """)).mappings().all()


def valid_okki_product_skus(db: Session, pairs: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Return active product/SKU pairs in one query for final-save verification."""
    if not pairs:
        return set()
    product_columns = _table_columns(db, "okki_products")
    inventory_columns = _table_columns(db, "okki_inventory")
    if not {"product_id"}.issubset(product_columns) or not {"product_id", "sku_id"}.issubset(inventory_columns):
        return set()
    schema = _schema()
    statement = text(f"""
        SELECT DISTINCT i.product_id, i.sku_id
        FROM `{schema}`.okki_inventory i
        JOIN `{schema}`.okki_products p ON p.product_id = i.product_id
        WHERE i.product_id IN :product_ids
          AND {_disable_filter("okki_inventory", inventory_columns, alias="i")}
          AND {_disable_filter("okki_products", product_columns, alias="p")}
    """).bindparams(bindparam("product_ids", expanding=True))
    rows = db.execute(statement, {"product_ids": sorted({product_id for product_id, _ in pairs})}).mappings().all()
    available = {(int(row["product_id"]), int(row["sku_id"])) for row in rows if row["sku_id"] is not None}
    return pairs & available


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
    rows = okki_rows if okki_rows is not None else load_okki_rows(db)

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
    okki_rows: list | None = None,
    skip_bump_ids: set[int] | None = None,
) -> dict:
    """Resolve a free-form production line to a product identity.

    1. Unique okki match -> use the real cloud product (no local row needed).
    2. Existing custom row (by match_key) -> reuse; bump use_count unless the
       row id is in skip_bump_ids (re-saving the same invoice must not inflate it).
    3. Otherwise insert a new ark_custom_products row (savepoint-guarded so a
       concurrent insert of the same match_key degrades to reuse, not a 500).
    """
    if not all(str(v or "").strip() for v in (product_display, color, size, unit)):
        raise ValueError("自定义产品必须填写 Product/Color/Length/Unit")

    okki = find_okki_by_attributes(
        db, product_display=product_display, color=color, size=size, unit=unit, okki_rows=okki_rows
    )
    if okki:
        return {"source": "okki", "custom_product_id": None, **okki}

    key = make_match_key(product_display, model, color, size, unit)
    row = db.query(CustomProduct).filter(CustomProduct.match_key == key).first()
    if row:
        if row.id not in (skip_bump_ids or set()):
            row.use_count = (row.use_count or 0) + 1
    else:
        try:
            with db.begin_nested():
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
        except Exception as exc:  # noqa: BLE001 - unique race: another request inserted the same key
            logger.warning("custom product 并发插入回退为复用 key=%s: %s", key, exc)
            print(f"[invoice] custom product insert race, reuse key={key}: {exc}", flush=True)
            row = db.query(CustomProduct).filter(CustomProduct.match_key == key).first()
            if row is None:
                raise
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
    okki_rows = load_okki_rows(db) if pending else []
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
