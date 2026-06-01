"""产品路线绑定 + 用户工序绑定 service"""

from datetime import datetime

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.production.models import (
    Process, ProductProcessRoute, ProcessRoute, ProcessRouteStep,
    UserProcessBinding,
)
from app.auth.models import ArkUser

settings = get_settings()


# ── 产品路线绑定 ──────────────────────────────────────────

def list_products(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    model: str | None = None,
    group_name: str | None = None,
    route_bound: str = "all",
    show_disabled: bool = False,
) -> tuple[list[dict], int]:
    """产品列表，跨库 JOIN okki_products"""
    biz = settings.BUSINESS_DB_NAME
    offset = (page - 1) * page_size

    where_clauses = []
    params: dict = {}

    if not show_disabled:
        where_clauses.append("p.disable_flag = 0")
    if keyword:
        where_clauses.append("(p.name LIKE :kw OR p.product_no LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if model:
        where_clauses.append("p.model = :model")
        params["model"] = model
    if group_name:
        where_clauses.append("p.group_name = :group_name")
        params["group_name"] = group_name
    if route_bound == "bound":
        where_clauses.append("ppr.route_id IS NOT NULL")
    elif route_bound == "unbound":
        where_clauses.append("ppr.route_id IS NULL")

    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    count_sql = f"""
        SELECT COUNT(*)
        FROM {biz}.okki_products p
        LEFT JOIN product_process_route ppr ON ppr.product_id = p.product_id
        WHERE 1=1 {where_sql}
    """
    total = db.execute(text(count_sql), params).scalar()

    data_sql = f"""
        SELECT p.product_id, p.product_no, p.name, p.model,
               p.disable_flag,
               ppr.route_id, pr.name AS route_name
        FROM {biz}.okki_products p
        LEFT JOIN product_process_route ppr ON ppr.product_id = p.product_id
        LEFT JOIN process_route pr ON pr.id = ppr.route_id
        WHERE 1=1 {where_sql}
        ORDER BY p.product_id DESC
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = page_size
    params["offset"] = offset
    rows = db.execute(text(data_sql), params).fetchall()

    items = []
    for r in rows:
        items.append({
            "product_id": r.product_id,
            "product_no": r.product_no,
            "name": r.name,
            "model": r.model,
            "disable_flag": r.disable_flag,
            "process_route": {
                "route_id": r.route_id,
                "route_name": r.route_name,
            } if r.route_id else None,
        })
    return items, total


def get_product_filter_options(db: Session) -> dict:
    """获取型号/分组去重列表"""
    biz = settings.BUSINESS_DB_NAME
    models = db.execute(text(f"""
        SELECT DISTINCT model FROM {biz}.okki_products
        WHERE disable_flag = 0 AND model IS NOT NULL AND model != ''
        ORDER BY model
    """)).scalars().all()

    group_names = db.execute(text(f"""
        SELECT DISTINCT group_name FROM {biz}.okki_products
        WHERE disable_flag = 0 AND group_name IS NOT NULL AND group_name != ''
        ORDER BY group_name
    """)).scalars().all()

    return {"models": models, "group_names": group_names}


def get_product_route(db: Session, product_id: int) -> dict | None:
    """获取产品绑定的路线详情（含步骤）"""
    binding = db.query(ProductProcessRoute).filter(ProductProcessRoute.product_id == product_id).first()
    if not binding:
        return None
    route = db.query(ProcessRoute).get(binding.route_id)
    from app.production.route_service import get_route_steps
    steps = get_route_steps(db, route.id)
    return {
        "product_id": product_id,
        "route_id": route.id,
        "route_name": route.name,
        "steps": steps,
        "updated_at": binding.updated_at,
    }


def bind_product_route(db: Session, product_id: int, route_id: int | None) -> dict:
    """绑定/更换/解绑产品路线"""
    if route_id is not None:
        route = db.query(ProcessRoute).get(route_id)
        if not route or route.status != 1:
            raise ValueError("路线不存在或已禁用")

    existing = db.query(ProductProcessRoute).filter(ProductProcessRoute.product_id == product_id).first()
    if route_id is None:
        # 解绑
        if existing:
            db.delete(existing)
            db.flush()
        return {"product_id": product_id, "route_id": None, "route_name": None, "updated_at": None}

    if existing:
        existing.route_id = route_id
    else:
        db.add(ProductProcessRoute(product_id=product_id, route_id=route_id))
    db.flush()

    route = db.query(ProcessRoute).get(route_id)
    return {
        "product_id": product_id,
        "route_id": route_id,
        "route_name": route.name,
        "updated_at": datetime.utcnow().isoformat(),
    }


def batch_bind_route(db: Session, product_ids: list[int], route_id: int) -> dict:
    """批量绑定路线"""
    route = db.query(ProcessRoute).get(route_id)
    if not route or route.status != 1:
        raise ValueError("路线不存在或已禁用")

    overwritten = db.query(ProductProcessRoute).filter(
        ProductProcessRoute.product_id.in_(product_ids)
    ).count()

    for pid in product_ids:
        db.execute(text("""
            INSERT INTO product_process_route (product_id, route_id)
            VALUES (:pid, :rid)
            ON DUPLICATE KEY UPDATE route_id = :rid, updated_at = NOW()
        """), {"pid": pid, "rid": route_id})
    db.flush()

    return {
        "total": len(product_ids),
        "success": len(product_ids),
        "failed": 0,
        "overwritten": overwritten,
        "message": f"成功绑定 {len(product_ids)} 个产品（其中 {overwritten} 个为更换路线）",
    }


# ── 用户工序绑定 ──────────────────────────────────────────

def get_user_bindings(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(UserProcessBinding, Process.name.label("process_name"))
        .join(Process, UserProcessBinding.process_id == Process.id)
        .filter(UserProcessBinding.user_id == user_id)
        .order_by(Process.sort_order.asc())
        .all()
    )
    return [
        {"process_id": b.process_id, "process_name": name, "bound_at": b.created_at}
        for b, name in rows
    ]


def update_user_bindings(db: Session, user_id: int, process_ids: list[int]) -> None:
    """全量更新用户工序绑定"""
    for pid in process_ids:
        proc = db.query(Process).get(pid)
        if not proc:
            raise ValueError(f"工序ID {pid} 不存在")

    db.query(UserProcessBinding).filter(UserProcessBinding.user_id == user_id).delete()
    for pid in process_ids:
        db.add(UserProcessBinding(user_id=user_id, process_id=pid))
    db.flush()


def update_user_wx_id(db: Session, user_id: int, wx_id: str | None) -> str | None:
    """更新用户微信ID，返回更新后的值"""
    if wx_id is not None:
        conflict = db.query(ArkUser).filter(ArkUser.wx_id == wx_id, ArkUser.id != user_id).first()
        if conflict:
            raise ValueError("该微信ID已绑定到其他用户")
    user = db.query(ArkUser).get(user_id)
    if not user:
        raise LookupError("用户不存在")
    user.wx_id = wx_id
    db.flush()
    return wx_id
