"""工序路线管理 service"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.production.models import (
    Process, ProcessRoute, ProcessRouteStep, ProductProcessRoute, OrderProductProcessProgress,
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

    route_ids = [route.id for route in routes]
    if not route_ids:
        return [], total
    step_counts = dict(db.query(ProcessRouteStep.route_id, func.count(ProcessRouteStep.id))
                       .filter(ProcessRouteStep.route_id.in_(route_ids))
                       .group_by(ProcessRouteStep.route_id).all())
    product_counts = dict(db.query(ProductProcessRoute.route_id, func.count(ProductProcessRoute.id))
                          .filter(ProductProcessRoute.route_id.in_(route_ids))
                          .group_by(ProductProcessRoute.route_id).all())

    result = []
    for r in routes:
        result.append({
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "status": r.status,
            "step_count": step_counts.get(r.id, 0),
            "product_count": product_counts.get(r.id, 0),
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
    from app.domestic.models import (
        DomesticProduct, DomesticCraftRoute, DomesticOrderItem,
        DomesticItemProgress, DomesticRouteRule,
    )

    # Lock the parent until commit; MySQL FK checks serialize concurrent new references.
    obj = db.query(ProcessRoute).filter(ProcessRoute.id == route_id).with_for_update().first()
    if not obj:
        raise LookupError("路线不存在")
    for model, label in (
        (ProductProcessRoute, "外贸产品"), (OrderProductProcessProgress, "外贸生产进度"),
        (DomesticProduct, "内贸产品"), (DomesticCraftRoute, "内贸工艺映射"),
        (DomesticOrderItem, "内贸订单"), (DomesticItemProgress, "内贸生产进度"),
        (DomesticRouteRule, "内贸条件规则"),
    ):
        if db.query(model.id).filter(model.route_id == route_id).first():
            raise ValueError(f"该路线仍被{label}引用，不能删除；请先检查关联数据")
    db.query(ProcessRouteStep).filter(ProcessRouteStep.route_id == route_id).delete(synchronize_session=False)
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


def save_route_steps(
    db: Session,
    route_id: int,
    steps: list[dict],
    *,
    allow_conditional_rules: bool = False,
) -> list[dict]:
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

    current_steps = get_route_steps(db, route_id)
    current_process_ids = [step["process_id"] for step in current_steps]
    if process_ids == current_process_ids:
        return current_steps

    if not allow_conditional_rules:
        # 局部导入避免生产模块在加载期依赖整个内贸领域。
        from app.domestic.models import DomesticRouteRule

        has_rules = db.query(DomesticRouteRule.id).filter(
            DomesticRouteRule.route_id == route_id,
        ).first()
        if has_rules is not None:
            raise ValueError(
                "该路线已配置内贸条件规则，修改步骤需同时具备生产和内贸权限，"
                "请通过条件路线配置保存"
            )

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
