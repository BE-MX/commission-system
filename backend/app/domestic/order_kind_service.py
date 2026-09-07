"""内贸订单大类：毛坯备货无价格，路线在订单明细上按用途锁定。"""

from decimal import Decimal

from app.domestic import constants as C
from app.production.models import ProcessRoute, ProcessRouteStep


PRODUCTION_FIELDS = ("hairstyle", "hairstyle_images", "style_requirement", "style_images")
PRODUCTION_HEADER_EXCLUDED = {
    "customer_id", "order_category", "order_type", "order_channel", "required_ship_date",
}


def is_production(order) -> bool:
    return getattr(order, "order_kind", None) == "production"


def normalize_production_input(item) -> None:
    item.attrs.hair_style_series = None
    item.expected_quote = None
    item.manual_discount_price = None
    item.special_price = None
    item.labor_fee = Decimal("0")
    for field in PRODUCTION_FIELDS:
        setattr(item, field, [] if field.endswith("images") else None)


def route_name(order_kind: str, order_category: str | None, product_type: str) -> str:
    source = C.DEFAULT_ROUTE_NAMES[product_type]
    if order_kind == "production":
        return f"生产订单 · {source}"
    if order_category == "normal":
        return f"业务普单 · {source}"
    return source


def resolve_order_route(db, *, order_kind, order_category, product_type) -> int | None:
    name = route_name(order_kind, order_category, product_type)
    route = db.query(ProcessRoute).filter(
        ProcessRoute.name == name, ProcessRoute.status == 1,
    ).first()
    if route is None:
        return None
    if not db.query(ProcessRouteStep.id).filter(ProcessRouteStep.route_id == route.id).first():
        return None
    return route.id


def order_routes_view(db) -> dict:
    """和实际下单共用同一匹配表，不再用产品的单一 route_id 推测。"""
    result = {}
    for group, kind, category in (
        ("production", "production", None),
        ("normal", "business", "normal"),
        ("special", "business", "special"),
    ):
        result[group] = {}
        for product_type in C.PRODUCT_TYPES:
            rid = resolve_order_route(
                db, order_kind=kind, order_category=category, product_type=product_type,
            )
            if rid is not None:
                result[group][product_type] = {
                    "route_id": rid,
                    "route_name": route_name(kind, category, product_type),
                }
    return result
