"""Xiaoman order sync boundary.

The official order endpoint requires Xiaoman-side customer/product/sku IDs.
This module keeps the external API integration isolated from invoice editing.
Push settings (ark_xiaoman_settings, single row) are also maintained here:
credentials, the generic product used for custom lines, and push defaults.
"""

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.invoice import product_service
from app.invoice.models import Invoice, XiaomanSettings
from app.invoice.service import validate_invoice


def sync_invoice(invoice: Invoice) -> dict:
    issues = validate_invoice(invoice)
    if issues:
        return {"ok": False, "message": "发票未通过同步前校验", "issues": issues}

    invoice.sync_status = "sync_failed"
    invoice.status = "sync_failed"
    invoice.sync_error = "OKKI 推单字段映射尚未实现（凭证已就绪），已完成本地同步前校验。"
    invoice.synced_at = datetime.utcnow()
    return {
        "ok": False,
        "message": invoice.sync_error,
        "issues": [],
    }


# ── push settings (single row) ───────────────────────────────

def get_settings_row(db: Session) -> XiaomanSettings | None:
    return db.query(XiaomanSettings).order_by(XiaomanSettings.id).first()


def get_or_create_settings(db: Session) -> XiaomanSettings:
    row = get_settings_row(db)
    if row is not None:
        return row
    # 固定 id=1：并发首次保存时靠主键冲突挡住第二行，savepoint 回滚后改读赢家行
    try:
        with db.begin_nested():
            row = XiaomanSettings(id=1, default_currency="USD")
            db.add(row)
    except IntegrityError:
        row = get_settings_row(db)
        if row is None:
            raise
    return row


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 12:
        return "****"
    return f"{token[:4]}****{token[-4:]}"


def serialize_settings(row: XiaomanSettings | None) -> dict:
    settings = get_settings()
    client_configured = bool(settings.OKKI_CLIENT_ID and settings.OKKI_CLIENT_SECRET)
    if row is None:
        return {
            "generic_product_no": None,
            "generic_product_id": None,
            "generic_sku_id": None,
            "default_order_status": None,
            "default_currency": "USD",
            "has_token": False,
            "access_token_masked": None,
            "token_expires_at": None,
            "client_configured": client_configured,
            "updated_by": None,
            "updated_at": None,
        }
    return {
        "generic_product_no": row.generic_product_no,
        "generic_product_id": row.generic_product_id,
        "generic_sku_id": row.generic_sku_id,
        "default_order_status": row.default_order_status,
        "default_currency": row.default_currency,
        "has_token": bool(row.access_token),
        "access_token_masked": _mask_token(row.access_token),
        "token_expires_at": row.token_expires_at.isoformat() if row.token_expires_at else None,
        "client_configured": client_configured,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def resolve_generic_product(db: Session, product_no: str) -> dict | None:
    """Look up one okki product by product_no and list its enabled skus.

    okki_products / okki_inventory are read-only projections of the OKKI cloud
    library — this is the authoritative source for generic_product_id/sku_id.
    """
    schema = product_service._schema()
    product_columns = product_service._table_columns(db, "okki_products")
    if "product_no" not in product_columns:
        return None
    name_expr = product_service._quoted_column(product_columns, "product_name", "name")
    row = db.execute(text(f"""
        SELECT p.product_id, {name_expr} AS product_name, p.product_no
        FROM `{schema}`.okki_products p
        WHERE {product_service._disable_filter("okki_products", product_columns, alias="p")}
          AND p.product_no = :no
        ORDER BY p.product_id
        LIMIT 1
    """), {"no": product_no}).mappings().first()
    if row is None:
        return None
    inventory_columns = product_service._table_columns(db, "okki_inventory")
    # LIMIT 200 是 update_settings 校验 sku 归属的口径上限——超过它的 sku 会被误判"不属于该产品"
    skus = db.execute(text(f"""
        SELECT DISTINCT sku_id
        FROM `{schema}`.okki_inventory
        WHERE product_id = :pid
          AND {product_service._disable_filter("okki_inventory", inventory_columns)}
        ORDER BY sku_id
        LIMIT 200
    """), {"pid": row["product_id"]}).scalars().all()
    return {
        "product_id": int(row["product_id"]),
        "product_name": str(row["product_name"] or ""),
        "product_no": str(row["product_no"] or ""),
        "skus": [int(s) for s in skus if s is not None],
    }


def update_settings(
    db: Session,
    *,
    generic_product_no: str | None,
    generic_sku_id: int | None,
    default_order_status: str | None,
    default_currency: str,
    access_token: str | None,
    token_expires_at: datetime | None,
    user_id: int | None,
) -> XiaomanSettings:
    """Apply the admin form. access_token semantics: None keeps the stored
    token, empty string clears it, anything else overwrites it.

    generic_product_id/sku_id are resolved server-side from product_no — the
    client-picked sku is only accepted when it belongs to that product.
    """
    row = get_or_create_settings(db)

    product_no = (generic_product_no or "").strip() or None
    if product_no:
        resolved = resolve_generic_product(db, product_no)
        if resolved is None:
            raise ValueError(f"产品编号 {product_no} 在 OKKI 产品库中不存在或已停用")
        # 存库内规范值而非用户输入（MySQL CI 排序下 p001 也能解析到 P001）
        row.generic_product_no = resolved["product_no"] or product_no
        row.generic_product_id = resolved["product_id"]
        if generic_sku_id is not None:
            if generic_sku_id not in resolved["skus"]:
                raise ValueError(f"SKU {generic_sku_id} 不属于产品 {product_no}")
            row.generic_sku_id = generic_sku_id
        elif len(resolved["skus"]) == 1:
            row.generic_sku_id = resolved["skus"][0]
        else:
            row.generic_sku_id = None
    else:
        row.generic_product_no = None
        row.generic_product_id = None
        row.generic_sku_id = None

    row.default_order_status = (default_order_status or "").strip() or None
    row.default_currency = (default_currency or "USD").strip() or "USD"

    if access_token is not None:
        token = access_token.strip()
        row.access_token = token or None
        # 手动覆盖 token 时表单里的过期时间是旧 token 的残值，不可信：
        # 保守按"刚签发"算 8 小时；清除 token 则联动清空
        token_expires_at = datetime.utcnow() + timedelta(hours=8) if token else None
    row.token_expires_at = token_expires_at

    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    return row
