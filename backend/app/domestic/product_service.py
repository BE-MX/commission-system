"""内贸产品与工艺路线映射 service

产品不是手工维护的主数据：下单选完属性即 find-or-create 沉淀一行，
attrs_key（属性组合）就是产品身份。路线按「工艺→路线」映射自动继承，
下单人零操作；个别产品可在产品管理页人工改绑。
"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domestic.constants import PRODUCT_TYPES
from app.domestic.models import DomesticCraftRoute, DomesticOrderItem, DomesticProduct
from app.domestic.schemas import ProductAttrs
from app.production.models import ProcessRoute, ProcessRouteStep

logger = logging.getLogger("commission")


def build_attrs_key(attrs: ProductAttrs) -> str:
    """属性组合唯一键。中文直接入 key —— 可读性在排查时比紧凑更值钱。"""
    return "|".join([
        attrs.product_type,
        attrs.craft,
        attrs.net_color or "",
        attrs.size,
        attrs.length,
        attrs.density,
    ])


def build_display_name(attrs: ProductAttrs) -> str:
    """展示名，创建时快照。属性改名不回溯已有产品（旧单保持下单时的口径）。"""
    parts = [PRODUCT_TYPES.get(attrs.product_type, attrs.product_type), attrs.craft]
    if attrs.net_color:
        parts.append(attrs.net_color)
    parts += [attrs.size, attrs.length, attrs.density]
    return "/".join(p for p in parts if p)


def resolve_route_id(db: Session, product_type: str, craft: str) -> int | None:
    """查「工艺→路线」映射。没配返回 None，产品照样建，只是不能开工。"""
    row = (
        db.query(DomesticCraftRoute)
        .filter(
            DomesticCraftRoute.product_type == product_type,
            DomesticCraftRoute.craft == craft,
        )
        .first()
    )
    return row.route_id if row else None


def find_or_create_product(db: Session, attrs: ProductAttrs) -> DomesticProduct:
    """按属性组合取产品，没有就建。并发下单同一新组合时靠 unique(attrs_key) 兜底。"""
    key = build_attrs_key(attrs)
    product = db.query(DomesticProduct).filter(DomesticProduct.attrs_key == key).first()
    if product:
        # 已存在但当初没配上路线 —— 现在配好了就补上，免得老产品永远开不了工
        if product.route_id is None:
            route_id = resolve_route_id(db, attrs.product_type, attrs.craft)
            if route_id:
                product.route_id = route_id
                db.flush()
        return product

    product = DomesticProduct(
        attrs_key=key,
        name=build_display_name(attrs),
        product_type=attrs.product_type,
        craft=attrs.craft,
        net_color=attrs.net_color,
        size=attrs.size,
        length=attrs.length,
        density=attrs.density,
        route_id=resolve_route_id(db, attrs.product_type, attrs.craft),
        status=1,
        use_count=0,
    )
    db.add(product)
    try:
        db.flush()
    except IntegrityError:
        # 并发：另一笔下单刚建了同一组合。回滚这一条改取已存在的行
        db.rollback()
        logger.warning("domestic product race on attrs_key=%s, refetch", key)
        print(f"[domestic] product race attrs_key={key}, refetch", flush=True)
        product = db.query(DomesticProduct).filter(DomesticProduct.attrs_key == key).first()
        if product is None:  # 理论不可达：撞 unique 说明行已存在
            raise
    return product


def get_route_steps(db: Session, route_id: int) -> list[ProcessRouteStep]:
    """路线的工序序列，按顺序返回。"""
    return (
        db.query(ProcessRouteStep)
        .filter(ProcessRouteStep.route_id == route_id)
        .order_by(ProcessRouteStep.step_order.asc())
        .all()
    )


# ── 产品列表与改绑 ────────────────────────────────────


def list_products(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    product_type: str = "",
    route_bound: str = "",
    sort_field: str = "",
    sort_order: str = "",
) -> tuple[list[dict], int]:
    q = db.query(DomesticProduct)
    if keyword:
        q = q.filter(DomesticProduct.name.like(f"%{keyword}%"))
    if product_type:
        q = q.filter(DomesticProduct.product_type == product_type)
    if route_bound == "bound":
        q = q.filter(DomesticProduct.route_id.isnot(None))
    elif route_bound == "unbound":
        q = q.filter(DomesticProduct.route_id.is_(None))

    total = q.count()

    sortable = {
        "name": DomesticProduct.name,
        "use_count": DomesticProduct.use_count,
        "created_at": DomesticProduct.created_at,
    }
    col = sortable.get(sort_field, DomesticProduct.created_at)
    q = q.order_by(col.asc() if sort_order == "asc" else col.desc())

    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    route_names = _route_name_map(db, [r.route_id for r in rows if r.route_id])

    items = [{
        "id": r.id,
        "name": r.name,
        "product_type": r.product_type,
        "product_type_label": PRODUCT_TYPES.get(r.product_type, r.product_type),
        "craft": r.craft,
        "net_color": r.net_color,
        "size": r.size,
        "length": r.length,
        "density": r.density,
        "route_id": r.route_id,
        "route_name": route_names.get(r.route_id),
        "status": r.status,
        "use_count": r.use_count,
        "created_at": r.created_at,
    } for r in rows]
    return items, total


def _route_name_map(db: Session, route_ids: list[int]) -> dict[int, str]:
    if not route_ids:
        return {}
    rows = db.query(ProcessRoute.id, ProcessRoute.name).filter(ProcessRoute.id.in_(set(route_ids))).all()
    return {rid: name for rid, name in rows}


def rebind_product_route(db: Session, product_id: int, route_id: int | None) -> DomesticProduct:
    """人工改绑产品路线。只影响之后的新明细 —— 在制明细的路线是下单时快照的。"""
    product = db.query(DomesticProduct).get(product_id)
    if not product:
        raise ValueError("产品不存在")
    if route_id is not None:
        route = db.query(ProcessRoute).get(route_id)
        if not route:
            raise ValueError("工艺路线不存在")
        if route.status != 1:
            raise ValueError(f"工艺路线「{route.name}」已停用")
    product.route_id = route_id
    db.commit()
    return product


# ── 工艺→路线映射 ────────────────────────────────────


def list_craft_routes(db: Session) -> list[dict]:
    rows = db.query(DomesticCraftRoute).order_by(
        DomesticCraftRoute.product_type.asc(), DomesticCraftRoute.craft.asc()
    ).all()
    route_names = _route_name_map(db, [r.route_id for r in rows])
    counts = dict(
        db.query(DomesticProduct.craft, func.count(DomesticProduct.id))
        .group_by(DomesticProduct.craft)
        .all()
    )
    return [{
        "id": r.id,
        "product_type": r.product_type,
        "product_type_label": PRODUCT_TYPES.get(r.product_type, r.product_type),
        "craft": r.craft,
        "route_id": r.route_id,
        "route_name": route_names.get(r.route_id),
        "product_count": counts.get(r.craft, 0),
        "updated_at": r.updated_at,
    } for r in rows]


def upsert_craft_route(db: Session, *, product_type: str, craft: str, route_id: int, user_id: int) -> DomesticCraftRoute:
    """配好映射后，把此前因缺映射而没配上路线的同工艺产品一起补上。"""
    route = db.query(ProcessRoute).get(route_id)
    if not route:
        raise ValueError("工艺路线不存在")
    if route.status != 1:
        raise ValueError(f"工艺路线「{route.name}」已停用")
    if not get_route_steps(db, route_id):
        raise ValueError(f"工艺路线「{route.name}」还没有配工序，配好再绑")

    row = (
        db.query(DomesticCraftRoute)
        .filter(DomesticCraftRoute.product_type == product_type, DomesticCraftRoute.craft == craft)
        .first()
    )
    if row:
        row.route_id = route_id
        row.updated_by = user_id
    else:
        row = DomesticCraftRoute(product_type=product_type, craft=craft, route_id=route_id, updated_by=user_id)
        db.add(row)

    backfilled = (
        db.query(DomesticProduct)
        .filter(
            DomesticProduct.product_type == product_type,
            DomesticProduct.craft == craft,
            DomesticProduct.route_id.is_(None),
        )
        .update({DomesticProduct.route_id: route_id}, synchronize_session=False)
    )
    db.commit()
    if backfilled:
        print(f"[domestic] craft={craft} 映射配好，回填 {backfilled} 个未绑路线产品", flush=True)
    return row


def delete_craft_route(db: Session, mapping_id: int) -> None:
    row = db.query(DomesticCraftRoute).get(mapping_id)
    if not row:
        raise ValueError("映射不存在")
    db.delete(row)
    db.commit()


def get_product_usage(db: Session, product_id: int) -> int:
    return db.query(func.count(DomesticOrderItem.id)).filter(
        DomesticOrderItem.product_id == product_id
    ).scalar() or 0
