"""备货管理 — 销量备货一览(分页/筛选/统计摘要)"""

from typing import Optional

from sqlalchemy.orm import Session

from app.stock.sku_query import query_all_sku_status


def query_stock_overview(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[list[str]] = None,
    sort_by: str = "sales_30d",
    order: str = "desc",
    keyword: Optional[str] = None,
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
