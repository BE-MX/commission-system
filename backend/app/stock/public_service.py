"""对外库存查询（无登录，key 门禁）。

供两类消费方：
1. 客户官网嵌入的独立查询页（/inventory?key=xxx）
2. 客户系统直接 API 对接（如 Shopify 库存同步，客户主动拉取）

只暴露产品标识 + 可用数量，销量/安全库存/在产等经营数据一律不出。
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

# 可用性分层阈值（低于此数量提示 Low Stock，帮客户判断要不要抓紧下单）
LOW_STOCK_THRESHOLD = 10


def parse_keys(raw: str | None) -> set[str]:
    """PUBLIC_STOCK_KEYS 逗号分隔 → 有效 key 集合（空串条目剔除）。"""
    return {k.strip() for k in (raw or "").split(",") if k.strip()}


def is_valid_key(key: str | None) -> bool:
    """key 门禁：未配置任何 key 时端点视为关闭（默认安全）。"""
    keys = parse_keys(get_settings().PUBLIC_STOCK_KEYS)
    return bool(key) and key in keys


def availability_tier(qty: int) -> str:
    if qty <= 0:
        return "out_of_stock"
    if qty < LOW_STOCK_THRESHOLD:
        return "low_stock"
    return "in_stock"


def query_public_inventory(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
) -> dict:
    """产品 + 可用库存分页查询（口径与 stock/overview 的 enable_count 一致）。"""
    business_db = get_settings().BUSINESS_DB_NAME

    kw_clause = ""
    params: dict = {}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw)"
        params["kw"] = f"%{keyword.strip()}%"

    base = f"""
        FROM `{business_db}`.okki_products p
        LEFT JOIN (
            SELECT product_id, SUM(enable_count) AS enable_count
            FROM `{business_db}`.okki_inventory
            WHERE disable_flag = 0
            GROUP BY product_id
        ) inv ON inv.product_id = p.product_id
        WHERE p.disable_flag = 0
          {kw_clause}
    """

    total = int(db.execute(text(f"SELECT COUNT(*) {base}"), params).scalar() or 0)
    if total == 0:
        return {"total": 0, "items": []}

    rows = db.execute(
        text(f"""
            SELECT p.product_id AS product_id,
                   p.name       AS name,
                   p.model      AS model,
                   COALESCE(inv.enable_count, 0) AS available
            {base}
            ORDER BY p.model, p.name
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()

    items = []
    for r in rows:
        # 库存异常为负时对客户钳位到 0（负数会引起客户困惑，异常留内部系统排查）
        available = max(0, int(r["available"]))
        items.append({
            "product_id": r["product_id"],
            "name": r["name"],
            "model": r["model"],
            "available": available,
            "availability": availability_tier(available),
        })
    return {"total": total, "items": items}
