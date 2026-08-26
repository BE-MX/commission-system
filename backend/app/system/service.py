"""系统字典 — 业务逻辑层"""


from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.system.models import SysDict
from app.system.reserved_dict_types import RESERVED_DICT_TYPE_SET
from app.system.schemas import DictItemCreate, DictItemUpdate


class ProtectedDictTypeError(ValueError):
    """保留字典只能由其专用、强鉴权的业务接口维护。"""


def _ensure_not_protected(dict_type: str) -> None:
    if dict_type.strip() in RESERVED_DICT_TYPE_SET:
        raise ProtectedDictTypeError("该字典类型只能在 GMV 日报配置页维护")


def list_types(db: Session) -> list[dict]:
    """汇总所有字典类型及其项数。"""
    rows = (
        db.query(
            SysDict.type,
            func.count(SysDict.id).label("item_count"),
            func.sum(case((SysDict.is_active.is_(True), 1), else_=0)).label("active_count"),
        )
        .filter(SysDict.type.notin_(RESERVED_DICT_TYPE_SET))
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
    if dict_type.strip() in RESERVED_DICT_TYPE_SET:
        return []
    query = db.query(SysDict).filter(SysDict.type == dict_type)
    if only_active:
        query = query.filter(SysDict.is_active.is_(True))
    return query.order_by(SysDict.sort.asc(), SysDict.id.asc()).all()


def create_item(db: Session, data: DictItemCreate) -> SysDict:
    _ensure_not_protected(data.type)
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
    _ensure_not_protected(item.type)

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
    _ensure_not_protected(item.type)
    db.delete(item)
    db.commit()


def get_label_map(db: Session, dict_type: str) -> dict[str, str]:
    """返回 {code: label}，常用于后端业务里把 code 反查成展示名。"""
    items = list_items(db, dict_type, only_active=False)
    return {it.code: it.label for it in items}
