"""系统字典 — 业务逻辑层"""

from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.system.models import SysDict
from app.system.schemas import DictItemCreate, DictItemUpdate


def list_types(db: Session) -> list[dict]:
    """汇总所有字典类型及其项数。"""
    rows = (
        db.query(
            SysDict.type,
            func.count(SysDict.id).label("item_count"),
            func.sum(case((SysDict.is_active.is_(True), 1), else_=0)).label("active_count"),
        )
        .group_by(SysDict.type)
        .order_by(SysDict.type)
        .all()
    )
    return [
        {"type": r.type, "item_count": int(r.item_count or 0), "active_count": int(r.active_count or 0)}
        for r in rows
    ]


def list_items(db: Session, dict_type: str, only_active: bool = False) -> list[SysDict]:
    """按类型查询字典项，按 sort、id 排序。"""
    query = db.query(SysDict).filter(SysDict.type == dict_type)
    if only_active:
        query = query.filter(SysDict.is_active.is_(True))
    return query.order_by(SysDict.sort.asc(), SysDict.id.asc()).all()


def create_item(db: Session, data: DictItemCreate) -> SysDict:
    exists = (
        db.query(SysDict)
        .filter(SysDict.type == data.type, SysDict.code == data.code)
        .first()
    )
    if exists:
        raise ValueError(f"字典项已存在：type={data.type}, code={data.code}")

    item = SysDict(
        type=data.type.strip(),
        code=data.code.strip(),
        label=data.label.strip(),
        sort=data.sort or 0,
        is_active=data.is_active,
        remark=data.remark,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, item_id: int, data: DictItemUpdate) -> SysDict:
    item = db.query(SysDict).filter(SysDict.id == item_id).first()
    if not item:
        raise ValueError("字典项不存在")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "label" and value is not None:
            value = value.strip()
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> None:
    item = db.query(SysDict).filter(SysDict.id == item_id).first()
    if not item:
        raise ValueError("字典项不存在")
    db.delete(item)
    db.commit()


def get_label_map(db: Session, dict_type: str) -> dict[str, str]:
    """返回 {code: label}，常用于后端业务里把 code 反查成展示名。"""
    items = list_items(db, dict_type, only_active=False)
    return {it.code: it.label for it in items}
