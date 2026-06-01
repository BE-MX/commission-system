"""工序管理 service"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.production.models import Process, ProcessRouteStep, UserProcessBinding


def list_processes(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    status: int | None = None,
) -> tuple[list[Process], int]:
    q = db.query(Process)
    if name:
        q = q.filter(Process.name.like(f"%{name}%"))
    if status is not None:
        q = q.filter(Process.status == status)
    total = q.count()
    items = (
        q.order_by(Process.sort_order.asc(), Process.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_process(db: Session, process_id: int) -> Process | None:
    return db.query(Process).get(process_id)


def create_process(db: Session, *, name: str, description: str | None = None, sort_order: int = 0) -> Process:
    existing = db.query(Process).filter(Process.name == name).first()
    if existing:
        raise ValueError(f"工序名称「{name}」已存在")
    obj = Process(name=name, description=description, sort_order=sort_order, status=1)
    db.add(obj)
    db.flush()
    return obj


def update_process(db: Session, process_id: int, **kwargs) -> Process:
    obj = db.query(Process).get(process_id)
    if not obj:
        raise LookupError("工序不存在")
    if "name" in kwargs and kwargs["name"] != obj.name:
        conflict = db.query(Process).filter(Process.name == kwargs["name"], Process.id != process_id).first()
        if conflict:
            raise ValueError(f"工序名称「{kwargs['name']}」已存在")
    for k, v in kwargs.items():
        if v is not None:
            setattr(obj, k, v)
    db.flush()
    return obj


def delete_process(db: Session, process_id: int) -> None:
    obj = db.query(Process).get(process_id)
    if not obj:
        raise LookupError("工序不存在")

    route_ref = db.query(ProcessRouteStep).filter(ProcessRouteStep.process_id == process_id).count()
    user_ref = db.query(UserProcessBinding).filter(UserProcessBinding.process_id == process_id).count()
    refs = []
    if route_ref:
        refs.append(f"{route_ref} 条路线")
    if user_ref:
        refs.append(f"{user_ref} 个用户")
    if refs:
        raise ValueError(f"该工序已被 {', '.join(refs)} 引用，请先移除后再删除")

    db.delete(obj)
    db.flush()


def get_active_processes(db: Session) -> list[Process]:
    """获取所有启用中的工序（用于选择器）"""
    return db.query(Process).filter(Process.status == 1).order_by(Process.sort_order.asc()).all()
