"""方舟洞见 — 情报条目服务 (CRUD + 筛选 + 批量操作)"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.insight.models import InsightItem
from app.insight.schemas import InsightItemCreate, InsightItemUpdate

logger = logging.getLogger("insight")


def list_items(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    source_ids: Optional[list[int]] = None,
    source_types: Optional[list[str]] = None,
    item_types: Optional[list[str]] = None,
    credibility_labels: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    is_featured: Optional[bool] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    sort_by: str = "collected_at",
    sort_desc: bool = True,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """情报条目列表 — 支持多维筛选、分页、排序。"""
    query = db.query(InsightItem)

    if start_date:
        query = query.filter(InsightItem.collected_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(InsightItem.collected_at <= datetime.combine(end_date, datetime.max.time()))
    if source_ids:
        query = query.filter(InsightItem.source_id.in_(source_ids))
    if source_types:
        query = query.filter(InsightItem.source_type.in_(source_types))
    if item_types:
        query = query.filter(InsightItem.item_type.in_(item_types))
    if credibility_labels:
        query = query.filter(InsightItem.credibility_label.in_(credibility_labels))
    if is_featured is not None:
        query = query.filter(InsightItem.is_featured == is_featured)
    if status:
        query = query.filter(InsightItem.status == status)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                InsightItem.title.ilike(like),
                InsightItem.content_md.ilike(like),
                InsightItem.related_competitor.ilike(like),
            )
        )
    if tags:
        # JSON 数组包含任一标签
        for tag in tags:
            query = query.filter(InsightItem.tags.contains(tag))

    total = query.count()

    order_col = getattr(InsightItem, sort_by, InsightItem.collected_at)
    if sort_desc:
        query = query.order_by(desc(order_col))
    else:
        query = query.order_by(order_col)

    rows = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {"total": total, "items": rows, "page": page, "page_size": page_size}


def get_item(db: Session, item_id: int) -> InsightItem:
    item = db.query(InsightItem).filter(InsightItem.id == item_id).first()
    if not item:
        raise ValueError(f"情报条目不存在: id={item_id}")
    return item


def create_item(db: Session, data: InsightItemCreate) -> InsightItem:
    item = InsightItem(**data.model_dump(exclude_unset=True))
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Created insight item id=%s source_type=%s", item.id, item.source_type)
    return item


def update_item(db: Session, item_id: int, data: InsightItemUpdate) -> InsightItem:
    item = get_item(db, item_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def toggle_feature(db: Session, item_id: int) -> InsightItem:
    item = get_item(db, item_id)
    item.is_featured = not item.is_featured
    db.commit()
    db.refresh(item)
    return item


def update_status(db: Session, item_id: int, status: str) -> InsightItem:
    if status not in ("active", "archived", "flagged"):
        raise ValueError(f"非法状态: {status}")
    item = get_item(db, item_id)
    item.status = status
    db.commit()
    db.refresh(item)
    return item


def batch_toggle_feature(db: Session, item_ids: list[int], is_featured: bool) -> int:
    """批量标记/取消精选。返回影响行数。"""
    result = (
        db.query(InsightItem)
        .filter(InsightItem.id.in_(item_ids))
        .update({"is_featured": is_featured}, synchronize_session=False)
    )
    db.commit()
    return result


def batch_update_status(db: Session, item_ids: list[int], status: str) -> int:
    if status not in ("active", "archived", "flagged"):
        raise ValueError(f"非法状态: {status}")
    result = (
        db.query(InsightItem)
        .filter(InsightItem.id.in_(item_ids))
        .update({"status": status}, synchronize_session=False)
    )
    db.commit()
    return result


def upload_manual_md(db: Session, title: str, content_md: str, tags: Optional[list] = None) -> InsightItem:
    """手工上传 Markdown 文件入库。"""
    item = InsightItem(
        source_type="manual",
        collected_at=datetime.utcnow(),
        published_at=datetime.utcnow(),
        title=title,
        content_mode="full_text",
        content_md=content_md,
        credibility_label="verified",
        credibility_score=5,
        credibility_note="人工整理，视为已核实",
        tags=tags or [],
        item_type="manual_upload",
        status="active",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Manual MD uploaded item id=%s title=%s", item.id, title)
    return item
