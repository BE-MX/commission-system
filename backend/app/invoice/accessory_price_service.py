"""Standard pricing for accessories bound to active OKKI product/SKU rows."""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.invoice import price_service, product_service
from app.invoice.models import StdPrice


_DISPLAY_MONEY = Decimal("0.01")


def search_candidates(db: Session, keyword: str | None, limit: int = 50) -> list[dict]:
    """Return one active OKKI product/SKU candidate per SKU."""
    product_columns = product_service._table_columns(db, "okki_products")
    sku_columns = product_service._table_columns(db, "okki_product_skus")
    required_product = {"product_id", "model", "color", "disable_flag"}
    required_sku = {"product_id", "sku_id", "disable_flag"}
    if not required_product.issubset(product_columns) or not required_sku.issubset(sku_columns):
        return []

    name_column = _name_column(product_columns)
    if not name_column:
        return []

    params: dict[str, object] = {"limit": min(max(int(limit), 1), 50)}
    keyword_clause = ""
    if keyword and keyword.strip():
        keyword_clause = (
            f"AND (p.`{name_column}` LIKE :keyword "
            "OR p.model LIKE :keyword OR p.color LIKE :keyword)"
        )
        params["keyword"] = f"%{keyword.strip()}%"

    schema = product_service._schema()
    rows = db.execute(text(f"""
        SELECT DISTINCT
               p.product_id,
               s.sku_id,
               p.`{name_column}` AS accessory_name,
               p.model AS accessory_model,
               p.color AS accessory_color
        FROM `{schema}`.okki_products p
        JOIN `{schema}`.okki_product_skus s ON s.product_id = p.product_id
        WHERE p.disable_flag = 0
          AND s.disable_flag = 0
          {keyword_clause}
        ORDER BY p.`{name_column}`, p.product_id, s.sku_id
        LIMIT :limit
    """), params).mappings().all()
    return [
        {
            "product_id": int(row["product_id"]),
            "sku_id": int(row["sku_id"]),
            "accessory_name": str(row["accessory_name"] or ""),
            "accessory_model": str(row["accessory_model"] or ""),
            "accessory_color": str(row["accessory_color"] or ""),
        }
        for row in rows
    ]


def list_prices(
    db: Session,
    keyword: str | None = None,
    customer_id: str | None = None,
) -> list[dict]:
    query = db.query(StdPrice).filter(StdPrice.product_kind == "accessory")
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(
            StdPrice.accessory_name.like(like),
            StdPrice.accessory_model.like(like),
            StdPrice.accessory_color.like(like),
        ))
    rows = query.order_by(StdPrice.accessory_name, StdPrice.accessory_model, StdPrice.id).all()
    rule = price_service.get_customer_rule_row(db, customer_id) if customer_id else None
    return [_serialize_price(row, rule) for row in rows]


def upsert_price(db: Session, payload, user_id: int | None) -> StdPrice:
    snapshot = _load_active_snapshot(db, int(payload.product_id), int(payload.sku_id))
    price_id = getattr(payload, "id", None)

    row = None
    if price_id is not None:
        row = (
            db.query(StdPrice)
            .filter(StdPrice.id == int(price_id), StdPrice.product_kind == "accessory")
            .first()
        )
        if not row:
            raise ValueError("配件价格记录不存在或不是配件价格，无法编辑")

    duplicate_query = db.query(StdPrice).filter(
        StdPrice.product_kind == "accessory",
        StdPrice.product_id == int(payload.product_id),
        StdPrice.sku_id == int(payload.sku_id),
    )
    if row is not None:
        duplicate_query = duplicate_query.filter(StdPrice.id != row.id)
    if duplicate_query.first():
        raise ValueError("该 OKKI 产品/SKU 已配置配件标准价，请直接编辑现有记录")

    if row is None:
        row = StdPrice(product_kind="accessory")
        db.add(row)

    row.product_id = int(payload.product_id)
    row.sku_id = int(payload.sku_id)
    row.accessory_name = snapshot["accessory_name"]
    row.accessory_model = snapshot["accessory_model"]
    row.accessory_color = snapshot["accessory_color"]
    row.series_grade = None
    row.length = None
    row.weight_unit = None
    row.color_type = None
    row.price = Decimal(payload.price)
    row.currency = str(payload.currency).upper()
    row.updated_by = user_id
    return row


def delete_price(db: Session, id: int) -> bool:
    row = (
        db.query(StdPrice)
        .filter(StdPrice.id == id, StdPrice.product_kind == "accessory")
        .first()
    )
    if not row:
        return False
    db.delete(row)
    return True


def _name_column(columns: set[str]) -> str | None:
    if "name" in columns:
        return "name"
    if "product_name" in columns:
        return "product_name"
    return None


def _load_active_snapshot(db: Session, product_id: int, sku_id: int) -> dict:
    product_columns = product_service._table_columns(db, "okki_products")
    sku_columns = product_service._table_columns(db, "okki_product_skus")
    name_column = _name_column(product_columns)
    if not name_column or not {"product_id", "model", "color", "disable_flag"}.issubset(product_columns):
        raise ValueError("OKKI 产品表缺少必要字段，请联系管理员检查同步后重新选择")
    if not {"product_id", "sku_id", "disable_flag"}.issubset(sku_columns):
        raise ValueError("OKKI SKU 表缺少必要字段，请联系管理员检查同步后重新选择")

    schema = product_service._schema()
    product = db.execute(text(f"""
        SELECT p.`{name_column}` AS accessory_name,
               p.model AS accessory_model,
               p.color AS accessory_color
        FROM `{schema}`.okki_products p
        WHERE p.product_id = :product_id AND p.disable_flag = 0
        LIMIT 1
    """), {"product_id": product_id}).mappings().first()
    if not product:
        raise ValueError("OKKI 产品不存在或已停用，请重新搜索并选择有效产品")

    sku_exists = db.execute(text(f"""
        SELECT 1
        FROM `{schema}`.okki_product_skus s
        WHERE s.product_id = :product_id
          AND s.sku_id = :sku_id
          AND s.disable_flag = 0
        LIMIT 1
    """), {"product_id": product_id, "sku_id": sku_id}).first()
    if not sku_exists:
        raise ValueError("OKKI SKU 不存在、已停用或不属于该产品，请重新搜索并选择有效 SKU")

    snapshot = {
        "accessory_name": str(product["accessory_name"] or "").strip(),
        "accessory_model": str(product["accessory_model"] or "").strip(),
        "accessory_color": str(product["accessory_color"] or "").strip(),
    }
    missing = [key.removeprefix("accessory_").title() for key, value in snapshot.items() if not value]
    if missing:
        raise ValueError(f"OKKI 产品缺少 {'/'.join(missing)}，请修正产品资料后重新选择")
    return snapshot


def _serialize_price(row: StdPrice, rule) -> dict:
    standard_price = Decimal(row.price)
    customer_price = price_service.apply_rule(standard_price, rule)
    return {
        "id": row.id,
        "product_kind": row.product_kind,
        "product_id": row.product_id,
        "sku_id": row.sku_id,
        "accessory_name": row.accessory_name,
        "accessory_model": row.accessory_model,
        "accessory_color": row.accessory_color,
        "standard_price": standard_price.quantize(_DISPLAY_MONEY, rounding=ROUND_HALF_UP),
        "customer_price": customer_price.quantize(_DISPLAY_MONEY, rounding=ROUND_HALF_UP),
        "currency": row.currency,
        "updated_at": row.updated_at,
    }
