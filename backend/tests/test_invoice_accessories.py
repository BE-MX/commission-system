"""Schema coverage for accessory invoice products."""

from datetime import date
from decimal import Decimal

from pydantic import ValidationError
import pytest
from sqlalchemy import text

from app.invoice import import_service, price_service, schemas, service
from app.invoice.models import InvoiceItem, StdPrice
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


def _seed_accessory_okki_product(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT, name TEXT, model TEXT,
            color TEXT, size TEXT, unit TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
        (product_id, product_no, name, model, color, size, unit, disable_flag)
        VALUES
        (104881553777436, 'ACC001', 'Hair Gripper', 'Magic Tape',
         'Hair Gripper', NULL, NULL, 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (104881553777436, 104881553777819, 0)
    """))
    db.commit()


def _accessory_std_price(db, *, with_hair_dimensions=False):
    row = StdPrice(
        product_kind="accessory",
        accessory_name="Hair Gripper",
        accessory_model="Magic Tape",
        accessory_color="Hair Gripper",
        product_id=104881553777436,
        sku_id=104881553777819,
        series_grade="Hair Matrix" if with_hair_dimensions else None,
        length="18" if with_hair_dimensions else None,
        weight_unit="100g" if with_hair_dimensions else None,
        color_type="solid" if with_hair_dimensions else None,
        price=Decimal("2.7500"),
        currency="USD",
    )
    db.add(row)
    db.flush()
    return row


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


def test_accessory_invoice_item_roundtrip_preserves_product_kind(db):
    _seed_accessory_okki_product(db)
    invoice = service.create_invoice(
        db,
        InvoiceCreate(
            customer_id="CUST-ACCESSORY",
            customer_name="Accessory Customer",
            invoice_date=date(2026, 7, 15),
            items=[
                InvoiceItemPayload(
                    product_kind="accessory",
                    item_type="stock",
                    product_id=104881553777436,
                    sku_id=104881553777819,
                    product_name="Hair Gripper",
                    product_display="Hair Gripper",
                    model="Magic Tape",
                    color="Hair Gripper",
                    length=None,
                    net_weight_grams=None,
                    quantity=10,
                    price_per_piece=Decimal("2.75"),
                )
            ],
        ),
        user_id=None,
    )
    item_id = invoice.items[0].id
    db.expire_all()

    persisted = db.get(InvoiceItem, item_id)

    assert persisted.product_kind == "accessory"
    assert service._serialize_item(persisted)["product_kind"] == "accessory"


def test_legacy_hair_lookup_and_list_exclude_accessory_prices(db):
    _accessory_std_price(db, with_hair_dimensions=True)

    assert price_service.list_std_prices(db) == []
    resolved = price_service.resolve_price(
        db,
        customer_id=None,
        product_display="Hair Matrix",
        length="18",
        unit="100g",
        color="#1",
    )
    assert resolved["standard_price"] is None


def test_legacy_hair_import_pricing_excludes_accessory_prices(db):
    accessory = _accessory_std_price(db, with_hair_dimensions=True)

    context = import_service._load_pricing_context(db, customer_id="CUST-ACCESSORY")

    assert context["standard_prices"] == []
    assert import_service._find_standard_price(
        [accessory],
        product_display="Hair Matrix",
        length="18",
        unit="100g",
        color_type="solid",
    ) is None


def test_legacy_hair_key_upsert_does_not_mutate_accessory_price(db):
    accessory = _accessory_std_price(db, with_hair_dimensions=True)

    hair = price_service.upsert_std_price(
        db,
        series_grade="Hair Matrix",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("20.0000"),
    )
    db.flush()

    assert hair.id != accessory.id
    assert hair.product_kind == "hair"
    assert accessory.price == Decimal("2.7500")


def test_legacy_hair_id_edit_rejects_accessory_price(db):
    accessory = _accessory_std_price(db)

    with pytest.raises(ValueError, match="价格记录不存在"):
        price_service.upsert_std_price(
            db,
            price_id=accessory.id,
            series_grade="Hair Matrix",
            length="18",
            weight_unit="100g",
            color_type="solid",
            price=Decimal("20.0000"),
        )

    assert accessory.product_kind == "accessory"
    assert accessory.price == Decimal("2.7500")


def test_legacy_hair_delete_rejects_accessory_price(db):
    accessory = _accessory_std_price(db)

    assert price_service.delete_std_price(db, accessory.id) is False
    assert db.get(StdPrice, accessory.id) is accessory


def test_legacy_hair_crud_still_works(db):
    hair = price_service.upsert_std_price(
        db,
        series_grade="Hair Matrix",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("20.0000"),
    )
    db.flush()

    assert [row["id"] for row in price_service.list_std_prices(db)] == [hair.id]
    edited = price_service.upsert_std_price(
        db,
        price_id=hair.id,
        series_grade="Hair Matrix",
        length="20",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("22.0000"),
    )
    assert edited is hair
    assert edited.length == "20"
    assert price_service.delete_std_price(db, hair.id) is True


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
