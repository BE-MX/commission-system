"""备货管理 — 销量备货一览(分页/筛选/统计摘要)"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock.sku_query import query_all_sku_status


def _parse_name(name: str) -> dict:
    """产品名称拆分: 类型/尺寸/颜色/克重

    颜色规则:
      - >=5 段且倒数第 3 段以 # 开头 → 倒数第 3 段/倒数第 2 段
      - 否则 → 倒数第 2 段
    """
    if not name:
        return {"type": "", "size": "", "color": "", "weight": ""}
    parts = name.split("/")
    n = len(parts)
    # 类型: 第 1 段
    t = parts[0] if n > 0 else ""
    # 尺寸: 第 2 段
    s = parts[1] if n > 1 else ""
    # 颜色
    if n >= 5 and parts[-3].startswith("#"):
        c = f"{parts[-3]}/{parts[-2]}"
    else:
        c = parts[-2] if n >= 2 else ""
    # 克重: 最后 1 段
    w = parts[-1] if n >= 1 else ""
    return {"type": t, "size": s, "color": c, "weight": w}


def query_stock_overview(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[list[str]] = None,
    sort_by: str = "sales_30d",
    order: str = "desc",
    keyword: Optional[str] = None,
    model: Optional[str] = None,
    product_type: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    weight: Optional[str] = None,
) -> dict:
    """销量备货一览,返回分页 + 统计摘要 (摘要反映总体,在筛选之前计算)。"""
    all_items = query_all_sku_status(db, keyword=keyword)

    # 统计(在筛选之前,反映总体)
    summary = {"shortage_count": 0, "warning_count": 0, "sufficient_count": 0, "unset_count": 0}
    for it in all_items:
        st = it["status"]
        if st == "shortage":
            summary["shortage_count"] += 1
        elif st == "warning":
            summary["warning_count"] += 1
        elif st == "sufficient":
            summary["sufficient_count"] += 1
        elif st == "unset":
            summary["unset_count"] += 1

    # 状态筛选
    if status_filter:
        all_items = [it for it in all_items if it["status"] in status_filter]

    # 型号/类型/尺寸/颜色/克重 筛选（逗号分隔多选）
    model_list = [m for m in (model or "").split(",") if m] or None
    if model_list:
        all_items = [it for it in all_items if it.get("model") in model_list]
    type_list = [t for t in (product_type or "").split(",") if t] or None
    if type_list:
        all_items = [
            it for it in all_items
            if _parse_name(it.get("product_name", ""))["type"] in type_list
        ]
    size_list = [s for s in (size or "").split(",") if s] or None
    if size_list:
        all_items = [
            it for it in all_items
            if _parse_name(it.get("product_name", ""))["size"] in size_list
        ]
    color_list = [c for c in (color or "").split(",") if c] or None
    if color_list:
        all_items = [
            it for it in all_items
            if _parse_name(it.get("product_name", ""))["color"] in color_list
        ]
    weight_list = [w for w in (weight or "").split(",") if w] or None
    if weight_list:
        all_items = [
            it for it in all_items
            if _parse_name(it.get("product_name", ""))["weight"] in weight_list
        ]

    # 排序
    valid_sorts = {"sales_30d", "sales_90d", "enable_count"}
    sort_key = sort_by if sort_by in valid_sorts else "sales_30d"
    reverse = (order == "desc")
    all_items.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)

    # 分页
    total = len(all_items)
    start = (page - 1) * page_size
    items = all_items[start:start + page_size]

    return {"total": total, "summary": summary, "items": items}


def get_filter_options(db: Session) -> dict:
    """返回所有启用产品的筛选维度可选值(model/type/size/color/weight)。"""
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    # model
    model_rows = db.execute(
        text(f"""
            SELECT DISTINCT model
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND model IS NOT NULL AND model != ''
            ORDER BY model
        """)
    ).all()
    models = [r[0] for r in model_rows]

    # type: SUBSTRING_INDEX(name, '/', 1)
    type_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(name, '/', 1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%'
            ORDER BY val
        """)
    ).all()
    types = [r[0] for r in type_rows if r[0]]

    # size: SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', 2), '/', -1)
    size_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', 2), '/', -1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%/%'
            ORDER BY val
        """)
    ).all()
    sizes = [r[0] for r in size_rows if r[0]]

    # color: 倒数第2段; 若>=5段且倒数第3段以#开头则拼接倒数第3/2段
    color_rows = db.execute(
        text(f"""
            SELECT DISTINCT
                CASE
                    WHEN (LENGTH(name) - LENGTH(REPLACE(name, '/', '')) + 1) >= 5
                         AND SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -3), '/', 1) LIKE '#%'
                    THEN CONCAT(
                        SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -3), '/', 1),
                        '/',
                        SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -2), '/', 1)
                    )
                    ELSE SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -2), '/', 1)
                END AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%/%/%'
            ORDER BY val
        """)
    ).all()
    colors = [r[0] for r in color_rows if r[0]]

    # weight: SUBSTRING_INDEX(name, '/', -1)
    weight_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(name, '/', -1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%'
            ORDER BY val
        """)
    ).all()
    weights = [r[0] for r in weight_rows if r[0]]

    return {
        "models": models,
        "types": types,
        "sizes": sizes,
        "colors": colors,
        "weights": weights,
    }
