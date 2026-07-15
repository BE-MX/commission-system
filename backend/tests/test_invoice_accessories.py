"""Schema coverage for accessory invoice products."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.invoice import schemas
from app.invoice.schemas import InvoiceItemPayload


def test_accessory_invoice_item_accepts_accessory_specific_fields():
    item = InvoiceItemPayload(
        product_kind="accessory",
        item_type="stock",
        product_id=104881553777436,
        sku_id=104881553777819,
        product_name="Hair Gripper",
        product_display="Hair Gripper",
        model="魔术贴",
        color="Hair Gripper",
        length=None,
        net_weight_grams=None,
        quantity=10,
        price_per_piece=Decimal("2.75"),
    )

    assert item.product_kind == "accessory"
    assert item.length is None
    assert item.net_weight_grams is None


def test_existing_hair_invoice_item_defaults_product_kind_to_hair():
    item = InvoiceItemPayload(
        item_type="stock",
        product_id=123,
        sku_id=456,
        product_name="Raw Hair/18/#1B/100g",
        product_display="Raw Hair",
        model="Raw Hair",
        color="#1B",
        length="18",
        net_weight_grams="100g",
        quantity=1,
        price_per_piece=Decimal("10.00"),
    )

    assert item.product_kind == "hair"


def test_accessory_price_payload_accepts_bound_okki_sku():
    assert hasattr(schemas, "AccessoryPricePayload")

    payload = schemas.AccessoryPricePayload(
        product_id=104881553777436,
        sku_id=104881553777819,
        accessory_name="Hair Gripper",
        accessory_model="魔术贴",
        accessory_color="Hair Gripper",
        price=Decimal("2.75"),
    )

    assert payload.currency == "USD"
    assert payload.price == Decimal("2.75")


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"accessory_name": ""}, "accessory_name"),
        ({"accessory_model": ""}, "accessory_model"),
        ({"accessory_color": ""}, "accessory_color"),
        ({"price": Decimal("-0.01")}, "price"),
    ],
)
def test_accessory_price_payload_rejects_invalid_required_values(override, field):
    assert hasattr(schemas, "AccessoryPricePayload")
    values = {
        "product_id": 104881553777436,
        "sku_id": 104881553777819,
        "accessory_name": "Hair Gripper",
        "accessory_model": "魔术贴",
        "accessory_color": "Hair Gripper",
        "price": Decimal("2.75"),
    }
    values.update(override)

    with pytest.raises(ValidationError) as exc_info:
        schemas.AccessoryPricePayload(**values)

    assert exc_info.value.errors()[0]["loc"] == (field,)
