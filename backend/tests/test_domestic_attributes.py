"""内贸订单头与产品属性的结构契约。"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.domestic import constants as C
from app.domestic.models import DomesticOrder, DomesticProduct
from app.domestic.schemas import OrderCreate, OrderItemInput, OrderUpdate, ProductAttrs


def _cap_attrs(**overrides):
    values = {
        "product_type": "cap",
        "craft": "递旋",
        "net_color": "紫网全头套",
        "size": "M",
        "length": "15厘米",
        "density": "80%",
        "hair_style_series": "直发",
    }
    values.update(overrides)
    return values


def _order_payload(**overrides):
    values = {
        "request_id": "attributes-test-1",
        "order_no": "DOM-ATTR-001",
        "order_date": date(2026, 9, 1),
        "customer_id": 1,
        "order_category": "special",
        "order_type": "first_order",
        "order_channel": "wechat",
        "items": [
            OrderItemInput(
                attrs=ProductAttrs(**_cap_attrs()),
                order_qty=1,
            )
        ],
    }
    values.update(overrides)
    return values


def test_new_order_fields_are_required():
    order = OrderCreate(**_order_payload())
    assert order.order_category == "special"
    assert order.order_type == "first_order"
    assert order.order_channel == "wechat"

    for field_name in ("order_type", "order_channel"):
        payload = _order_payload()
        payload.pop(field_name)
        with pytest.raises(ValidationError):
            OrderCreate(**payload)


def test_order_type_no_longer_accepts_category_values():
    with pytest.raises(ValidationError):
        OrderCreate(**_order_payload(order_type="normal"))

    assert C.ORDER_CATEGORIES == {"normal": "普货", "special": "特单"}
    assert C.ORDER_TYPE_DICT == "domestic_order_type"
    assert C.ORDER_CHANNEL_DICT == "domestic_order_channel"


def test_order_update_keeps_patch_semantics():
    partial = OrderUpdate(remark="只改备注")
    assert partial.model_dump(exclude_unset=True) == {"remark": "只改备注"}

    update = OrderUpdate(order_type="repurchase", order_channel="phone")
    assert update.order_type == "repurchase"
    assert update.order_channel == "phone"

    with pytest.raises(ValidationError):
        OrderUpdate(order_type="normal")


def test_piece_has_one_combined_craft_size_attribute():
    attrs = ProductAttrs(
        product_type="piece",
        craft="U型13*15",
        length="20厘米",
        net_color="紫网全头套",
        size="13*15",
        density="90%",
        hair_style_series="直发",
    )

    assert attrs.craft == "U型13*15"
    assert attrs.net_color is None
    assert attrs.size is None
    assert attrs.density is None
    assert attrs.hair_style_series is None


def test_15cm_cap_requires_density():
    with pytest.raises(ValidationError, match="15厘米"):
        ProductAttrs(**_cap_attrs(density=None))


def test_non_15cm_cap_clears_residual_density():
    attrs = ProductAttrs(**_cap_attrs(length="20厘米", density="90%"))
    assert attrs.density is None


@pytest.mark.parametrize("missing_field", ["size", "hair_style_series"])
def test_cap_requires_size_and_hair_style_series(missing_field):
    values = _cap_attrs()
    values.pop(missing_field)
    with pytest.raises(ValidationError):
        ProductAttrs(**values)


def test_models_expose_new_nullable_database_contract():
    order_columns = DomesticOrder.__table__.c
    assert order_columns.order_category.nullable is False
    assert order_columns.order_type.nullable is True
    assert order_columns.order_channel.nullable is True

    product_columns = DomesticProduct.__table__.c
    assert product_columns.size.nullable is True
    assert product_columns.density.nullable is True
    assert product_columns.hair_style_series.nullable is True
