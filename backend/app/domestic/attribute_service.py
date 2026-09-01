"""内贸下单属性字典校验与特单值沉淀。"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domestic import constants as C
from app.domestic.models import DomesticCraftRoute
from app.domestic.schemas import ProductAttrs
from app.production.models import ProcessRoute, ProcessRouteStep
from app.system.models import SysDict

logger = logging.getLogger("commission")

_ATTR_LABELS = {
    "craft": "工艺",
    "net_color": "网帽颜色",
    "size": "尺码",
    "length": "发长",
    "density": "发量",
    "hair_style_series": "发型系列",
}


def _options(rows: list[SysDict]) -> list[dict]:
    return [{"value": row.code, "label": row.label} for row in rows]


def get_order_options(db: Session) -> dict:
    """返回下单所需的标准/特单值域和可用默认路线。"""
    standard_types = sorted({
        dict_type
        for mapping in C.ATTR_DICTS.values()
        for dict_type in mapping.values()
    })
    special_attr_dicts = {
        product_type: {
            field: f"{dict_type}_special"
            for field, dict_type in mapping.items()
        }
        for product_type, mapping in C.ATTR_DICTS.items()
    }
    special_types = sorted({
        dict_type
        for mapping in special_attr_dicts.values()
        for dict_type in mapping.values()
    })
    requested_types = [
        *standard_types,
        *special_types,
        C.ORDER_TYPE_DICT,
        C.ORDER_CHANNEL_DICT,
    ]
    rows = (
        db.query(SysDict)
        .filter(SysDict.type.in_(requested_types), SysDict.is_active.is_(True))
        .order_by(SysDict.type.asc(), SysDict.sort.asc(), SysDict.id.asc())
        .all()
    )
    by_type: dict[str, list[SysDict]] = {dict_type: [] for dict_type in requested_types}
    for row in rows:
        by_type[row.type].append(row)

    default_routes = {}
    route_rows = db.query(ProcessRoute).filter(
        ProcessRoute.name.in_(C.DEFAULT_ROUTE_NAMES.values()),
        ProcessRoute.status == 1,
    ).all()
    step_counts = dict(
        db.query(ProcessRouteStep.route_id, func.count(ProcessRouteStep.id))
        .filter(ProcessRouteStep.route_id.in_([row.id for row in route_rows] or {0}))
        .group_by(ProcessRouteStep.route_id)
        .all()
    )
    route_by_name = {row.name: row for row in route_rows}
    for product_type, route_name in C.DEFAULT_ROUTE_NAMES.items():
        route = route_by_name.get(route_name)
        step_count = step_counts.get(route.id, 0) if route else 0
        if route and step_count:
            default_routes[product_type] = {
                "id": route.id,
                "name": route.name,
                "step_count": step_count,
            }

    return {
        "product_types": [
            {"value": value, "label": label}
            for value, label in C.PRODUCT_TYPES.items()
        ],
        "order_categories": [
            {"value": value, "label": label}
            for value, label in C.ORDER_CATEGORIES.items()
        ],
        "order_types": _options(by_type[C.ORDER_TYPE_DICT]),
        "order_channels": _options(by_type[C.ORDER_CHANNEL_DICT]),
        "attr_dicts": C.ATTR_DICTS,
        "special_attr_dicts": special_attr_dicts,
        "standard_values": {
            dict_type: [row.code for row in by_type[dict_type]]
            for dict_type in standard_types
        },
        "special_values": {
            dict_type: [row.code for row in by_type[dict_type]]
            for dict_type in special_types
        },
        "default_routes": default_routes,
    }


def _active_value(
    db: Session,
    dict_type: str,
    code: str,
    *,
    lock: bool = False,
) -> SysDict | None:
    query = db.query(SysDict).filter(
        SysDict.type == dict_type,
        SysDict.code == code,
        SysDict.is_active.is_(True),
    )
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def validate_order_dimensions(
    db: Session,
    order_type: str | None = None,
    order_channel: str | None = None,
) -> None:
    """订单类型和渠道只接受对应启用字典项。"""
    for label, dict_type, value in (
        ("订单类型", C.ORDER_TYPE_DICT, order_type),
        ("订单渠道", C.ORDER_CHANNEL_DICT, order_channel),
    ):
        if value is None:
            continue
        if not _active_value(db, dict_type, value):
            raise ValueError(
                f"{label}「{value}」不是启用选项，请先在数据字典中启用或改选其他值"
            )


def _create_special_value(db: Session, dict_type: str, value: str) -> SysDict:
    inactive = db.query(SysDict).filter(
        SysDict.type == dict_type,
        SysDict.code == value,
        SysDict.is_active.is_(False),
    ).first()
    if inactive:
        raise ValueError(f"特单选项「{value}」已停用，请先在数据字典中启用")

    savepoint = db.begin_nested()
    row = SysDict(
        type=dict_type,
        code=value,
        label=value,
        sort=0,
        is_active=True,
    )
    db.add(row)
    try:
        db.flush()
        savepoint.commit()
        return row
    except IntegrityError:
        savepoint.rollback()
        logger.warning("domestic special attribute race type=%s code=%s", dict_type, value)
        print(f"[domestic] special attribute race type={dict_type} code={value}", flush=True)
        row = _active_value(db, dict_type, value, lock=True)
        if row is None:
            raise
        return row


def _default_route(db: Session, product_type: str) -> ProcessRoute:
    route_name = C.DEFAULT_ROUTE_NAMES[product_type]
    route = db.query(ProcessRoute).filter(ProcessRoute.name == route_name).first()
    if route is None:
        raise ValueError(f"默认工艺路线「{route_name}」不存在，请先创建并配置工序")
    if route.status != 1:
        raise ValueError(f"默认工艺路线「{route_name}」已停用，请先启用")
    if not db.query(ProcessRouteStep.id).filter(
        ProcessRouteStep.route_id == route.id
    ).first():
        raise ValueError(f"默认工艺路线「{route_name}」还没有配工序，请先配置工序")
    return route


def _ensure_special_craft_route(
    db: Session,
    *,
    product_type: str,
    craft: str,
    user_id: int,
) -> None:
    route = _default_route(db, product_type)
    mapping = db.query(DomesticCraftRoute).filter(
        DomesticCraftRoute.product_type == product_type,
        DomesticCraftRoute.craft == craft,
    ).first()
    if mapping:
        if mapping.route_id != route.id:
            mapping.route_id = route.id
            mapping.updated_by = user_id
            db.flush()
        return

    savepoint = db.begin_nested()
    mapping = DomesticCraftRoute(
        product_type=product_type,
        craft=craft,
        route_id=route.id,
        updated_by=user_id,
    )
    db.add(mapping)
    try:
        db.flush()
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        logger.warning(
            "domestic special craft route race product_type=%s craft=%s",
            product_type,
            craft,
        )
        print(
            f"[domestic] special craft route race product_type={product_type} craft={craft}",
            flush=True,
        )
        mapping = db.query(DomesticCraftRoute).filter(
            DomesticCraftRoute.product_type == product_type,
            DomesticCraftRoute.craft == craft,
        ).populate_existing().with_for_update().first()
        if mapping is None:
            raise
        if mapping.route_id != route.id:
            mapping.route_id = route.id
            mapping.updated_by = user_id
            db.flush()


def prepare_item_attrs(
    db: Session,
    *,
    order_category: str,
    attrs: ProductAttrs,
    user_id: int,
    line_no: int | None = None,
) -> ProductAttrs:
    """校验当前有效属性；特单缺值在订单事务内沉淀到专属字典。"""
    mapping = C.ATTR_DICTS[attrs.product_type]
    line_prefix = f"第 {line_no} 行" if line_no is not None else "当前明细"
    for field, standard_type in mapping.items():
        value = getattr(attrs, field)
        if value is None:
            continue
        if _active_value(db, standard_type, value):
            continue
        label = _ATTR_LABELS[field]
        if order_category == "normal":
            raise ValueError(
                f"{line_prefix}{label}「{value}」不是启用的标准选项，请改选标准值或切换为特单"
            )

        special_type = f"{standard_type}_special"
        if not _active_value(db, special_type, value):
            _create_special_value(db, special_type, value)
        if field == "craft":
            _ensure_special_craft_route(
                db,
                product_type=attrs.product_type,
                craft=value,
                user_id=user_id,
            )
    return attrs
