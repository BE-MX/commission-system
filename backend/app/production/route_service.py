"""工序路线管理 service"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.production.models import (
    Process, ProcessRoute, ProcessRouteStep, ProductProcessRoute,
)


def list_routes(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    status: int | None = None,
) -> tuple[list[dict], int]:
    """返回路线列表，含 step_count / product_count 聚合"""
    q = db.query(ProcessRoute)
    if name:
        q = q.filter(ProcessRoute.name.like(f"%{name}%"))
    if status is not None:
        q = q.filter(ProcessRoute.status == status)
    total = q.count()
    routes = q.order_by(ProcessRoute.id.asc()).offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for r in routes:
        step_count = db.query(func.count()).filter(ProcessRouteStep.route_id == r.id).scalar()
        product_count = db.query(func.count()).filter(ProductProcessRoute.route_id == r.id).scalar()
        result.append({
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "status": r.status,
            "step_count": step_count,
            "product_count": product_count,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        })
    return result, total


def get_route(db: Session, route_id: int) -> ProcessRoute | None:
    return db.query(ProcessRoute).get(route_id)


def create_route(db: Session, *, name: str, description: str | None = None) -> ProcessRoute:
    existing = db.query(ProcessRoute).filter(ProcessRoute.name == name).first()
    if existing:
        raise ValueError(f"路线名称「{name}」已存在")
    obj = ProcessRoute(name=name, description=description, status=1)
    db.add(obj)
    db.flush()
    return obj


def update_route(db: Session, route_id: int, **kwargs) -> ProcessRoute:
    obj = db.query(ProcessRoute).get(route_id)
    if not obj:
        raise LookupError("路线不存在")
    if "name" in kwargs and kwargs["name"] != obj.name:
        conflict = db.query(ProcessRoute).filter(ProcessRoute.name == kwargs["name"], ProcessRoute.id != route_id).first()
        if conflict:
            raise ValueError(f"路线名称「{kwargs['name']}」已存在")
    for k, v in kwargs.items():
        if v is not None:
            setattr(obj, k, v)
    db.flush()
    return obj


def delete_route(db: Session, route_id: int) -> None:
    obj = db.query(ProcessRoute).get(route_id)
    if not obj:
        raise LookupError("路线不存在")
    product_count = db.query(func.count()).filter(ProductProcessRoute.route_id == route_id).scalar()
    if product_count:
        raise ValueError(f"该路线已被 {product_count} 个产品绑定，请先解绑所有产品")
    # CASCADE 会自动删除 process_route_step
    db.delete(obj)
    db.flush()


def get_route_steps(db: Session, route_id: int) -> list[dict]:
    """获取路线步骤列表"""
    rows = (
        db.query(ProcessRouteStep, Process.name.label("process_name"))
        .join(Process, ProcessRouteStep.process_id == Process.id)
        .filter(ProcessRouteStep.route_id == route_id)
        .order_by(ProcessRouteStep.step_order.asc())
        .all()
    )
    return [
        {
            "id": step.id,
            "route_id": step.route_id,
            "process_id": step.process_id,
            "process_name": process_name,
            "step_order": step.step_order,
        }
        for step, process_name in rows
    ]


def save_route_steps(db: Session, route_id: int, steps: list[dict]) -> list[dict]:
    """全量覆盖保存路线步骤"""
    route = db.query(ProcessRoute).get(route_id)
    if not route:
        raise LookupError("路线不存在")

    process_ids = [s["process_id"] for s in steps]
    # 校验无重复
    if len(process_ids) != len(set(process_ids)):
        raise ValueError("同一路线中不能包含重复工序")
    # 校验所有工序存在且启用
    for pid in process_ids:
        proc = db.query(Process).get(pid)
        if not proc or proc.status != 1:
            raise ValueError(f"工序ID {pid} 不存在或已禁用")

    # 删除原有明细
    db.query(ProcessRouteStep).filter(ProcessRouteStep.route_id == route_id).delete()

    # 按顺序插入
    for i, s in enumerate(steps, start=1):
        db.add(ProcessRouteStep(route_id=route_id, process_id=s["process_id"], step_order=i))
    db.flush()

    return get_route_steps(db, route_id)


def get_active_routes(db: Session) -> list[ProcessRoute]:
    """获取所有启用中的路线（用于绑定弹窗下拉）"""
    return db.query(ProcessRoute).filter(ProcessRoute.status == 1).order_by(ProcessRoute.id.asc()).all()
