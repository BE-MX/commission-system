"""对外库存查询（无登录、无门禁）。

消费方：
1. leshine.work/inventory 客户公开查询页（全英文，直接访问）
2. 客户系统直接 API 拉取（如 Shopify 库存同步，客户主动拉取）

2026-08-19 二期起取消 key 门禁（一期曾走 PUBLIC_STOCK_KEYS，配置项已废弃保留兼容）。
响应字段收敛为「类型/尺寸/颜色/克重/是否有货」——不暴露具体库存数量，
销量/安全库存/在产等经营数据一律不出。
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock.overview_service import _parse_name


def _parse_display_name(name: str) -> dict:
    """产品名 → 类型/尺寸/颜色/克重（面向客户展示，避免内部拆分在短名称上的重复段）。

    真实库分布（2026-08-19）：4 段 353 条、5 段 417 条（完整约定）；
    2 段 17 条（Micro Beads/#1，第 2 段是颜色）；1 段 8 条；3 段 0 条。

    - 无 '/'：整段落入类型列，其余留空
    - 2 段：第 2 段以 # 开头判为颜色（Micro Beads/#1 → 颜色 #1），否则判为尺寸
    - 3 段：按 # 启发式判颜色（当前库无此类，防御性处理）
    - ≥4 段：完整约定 类型/尺寸/颜色/克重，复用内部一览同款拆分（含 #x/y 合并色）
    """
    if "/" not in name:
        return {"type": name, "size": "", "color": "", "weight": ""}
    parts = name.split("/")
    n = len(parts)
    if n >= 4:
        return _parse_name(name)
    if n == 2:
        if parts[1].startswith("#"):
            return {"type": parts[0], "size": "", "color": parts[1], "weight": ""}
        return {"type": parts[0], "size": parts[1], "color": "", "weight": ""}
    if parts[1].startswith("#"):
        return {"type": parts[0], "size": "", "color": parts[1], "weight": parts[2]}
    return {"type": parts[0], "size": parts[1], "color": "", "weight": parts[2]}


def query_public_inventory(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    in_stock_only: bool = False,
) -> dict:
    """产品四要素 + 有货标识分页查询（有货口径 = 小满可用库存 enable_count > 0）。"""
    business_db = get_settings().BUSINESS_DB_NAME

    kw_clause = ""
    params: dict = {}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw)"
        params["kw"] = f"%{keyword.strip()}%"

    stock_clause = "AND COALESCE(inv.enable_count, 0) > 0" if in_stock_only else ""

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
          {stock_clause}
    """

    total = int(db.execute(text(f"SELECT COUNT(*) {base}"), params).scalar() or 0)
    if total == 0:
        return {"total": 0, "items": []}

    rows = db.execute(
        text(f"""
            SELECT p.product_id AS product_id,
                   p.name       AS name,
                   COALESCE(inv.enable_count, 0) AS available
            {base}
            ORDER BY p.name, p.product_id
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()

    items = []
    for r in rows:
        items.append({
            "product_id": r["product_id"],
            **_parse_display_name(r["name"] or ""),
            # 库存异常为负时视为无货（负数会引起客户困惑，异常留内部系统排查）
            "in_stock": int(r["available"]) > 0,
        })
    return {"total": total, "items": items}
