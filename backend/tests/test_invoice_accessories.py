"""Accessory invoice products and standard-pricing coverage."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import importlib
import importlib.util

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.auth import service as auth_service
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.invoice import import_service, price_service, schemas, service
from app.invoice.models import CustomerPriceRule, Invoice, InvoiceItem, StdPrice
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
        CREATE TABLE IF NOT EXISTS lsordertest.okki_product_skus (
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
    db.execute(text("""
        INSERT INTO lsordertest.okki_product_skus (product_id, sku_id, disable_flag)
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


@pytest.mark.parametrize("product_kind", ["hair", "accessory"])
@pytest.mark.parametrize("price_per_piece", ["1.000049", "100000000.0000"])
def test_invoice_api_rejects_prices_outside_numeric_12_4_boundary(
    db, product_kind, price_per_piece,
):
    with _api_client(db, permissions=["invoice:write"]) as client:
        response = client.post("/api/invoice/invoices", json={
            "customer_id": "CUST-DECIMAL",
            "customer_name": "Decimal Boundary Customer",
            "invoice_date": "2026-07-15",
            "items": [{
                "product_kind": product_kind,
                "item_type": "stock",
                "product_display": "Boundary Item",
                "color": "Black",
                "quantity": 999,
                "price_per_piece": price_per_piece,
            }],
        })

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "price_per_piece"


def test_accessory_invoice_item_roundtrip_preserves_product_kind(db):
    _seed_accessory_okki_product(db)
    _accessory_std_price(db)
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


def test_accessory_validation_uses_accessory_fields_without_hair_dimensions():
    invoice = Invoice(
        customer_id="CUST-ACCESSORY",
        customer_name="Accessory Customer",
        invoice_date=date(2026, 7, 15),
    )
    invoice.items.append(InvoiceItem(
        product_kind="accessory",
        item_type="custom",
        product_id=None,
        sku_id=None,
        product_name="",
        product_display="",
        model=None,
        color="",
        length=None,
        net_weight_grams=None,
        curl=None,
        quantity=0,
        price_per_piece=Decimal("0"),
        discount_amount=Decimal("-1"),
        total_price=Decimal("-1"),
    ))

    issues = service.validate_invoice(invoice)
    fields = {issue["field"] for issue in issues}

    assert {
        "items[1].item_type",
        "items[1].product_id",
        "items[1].sku_id",
        "items[1].product_name",
        "items[1].product_display",
        "items[1].model",
        "items[1].color",
        "items[1].quantity",
        "items[1].price_per_piece",
        "items[1].discount_amount",
    } <= fields
    assert "items[1].length" not in fields
    assert "items[1].net_weight_grams" not in fields
    assert "items[1].curl" not in fields


def test_hair_validation_still_requires_length_and_weight():
    invoice = Invoice(
        customer_id="CUST-HAIR",
        customer_name="Hair Customer",
        invoice_date=date(2026, 7, 15),
    )
    invoice.items.append(InvoiceItem(
        product_kind="hair",
        item_type="stock",
        product_id=1,
        sku_id=2,
        product_name="Raw Hair",
        product_display="Raw Hair",
        model="M1",
        color="Natural",
        length=None,
        net_weight_grams=None,
        quantity=1,
        price_per_piece=Decimal("10"),
        discount_amount=Decimal("0"),
        total_price=Decimal("10"),
    ))

    fields = {issue["field"] for issue in service.validate_invoice(invoice)}

    assert "items[1].length" in fields
    assert "items[1].net_weight_grams" in fields


def test_accessory_save_snapshots_exact_configured_price_and_keeps_transaction_price(db):
    _seed_accessory_okki_product(db)
    _accessory_std_price(db)
    db.add(CustomerPriceRule(
        customer_id="CUST-ACCESSORY",
        adjust_type="fixed",
        adjust_value=Decimal("0.2500"),
        enabled=1,
    ))
    db.flush()

    invoice = service.create_invoice(
        db,
        InvoiceCreate(
            customer_id="CUST-ACCESSORY",
            customer_name="Accessory Customer",
            invoice_date=date(2026, 7, 15),
            items=[InvoiceItemPayload(
                product_kind="accessory",
                item_type="stock",
                product_id=104881553777436,
                sku_id=104881553777819,
                product_name="Forged Name",
                product_display="Forged Display",
                model="Forged Model",
                color="Forged Color",
                quantity=2,
                price_per_piece=Decimal("4.20"),
            )],
        ),
    )

    item = invoice.items[0]
    assert item.standard_price == Decimal("2.7500")
    assert item.customer_price == Decimal("3.0000")
    assert item.price_per_piece == Decimal("4.20")
    assert item.price_source == "manual"
    assert item.total_price == Decimal("8.40")
    assert item.product_name == "Hair Gripper"
    assert item.product_display == "Hair Gripper"
    assert item.model == "Magic Tape"
    assert item.color == "Hair Gripper"


def test_accessory_price_resolver_distinguishes_catalog_outage_from_stale_config(db):
    _accessory_std_price(db)

    with pytest.raises(ValueError) as exc_info:
        _accessory_price_service().resolve_configured_price(
            db,
            customer_id="CUST-ACCESSORY",
            product_id=104881553777436,
            sku_id=104881553777819,
            currency="USD",
        )

    assert "同步" in str(exc_info.value)
    assert "重新选择" not in str(exc_info.value)


@pytest.mark.parametrize("disabled", [False, True])
def test_accessory_save_requires_an_active_exact_standard_price(db, disabled):
    _seed_accessory_okki_product(db)
    if disabled:
        _accessory_std_price(db)
        db.execute(text("""
            UPDATE lsordertest.okki_product_skus
            SET disable_flag = 1
            WHERE product_id = 104881553777436 AND sku_id = 104881553777819
        """))

    with pytest.raises(ValueError) as exc_info:
        service.create_invoice(
            db,
            InvoiceCreate(
                customer_id="CUST-ACCESSORY",
                customer_name="Accessory Customer",
                invoice_date=date(2026, 7, 15),
                items=[InvoiceItemPayload(
                    product_kind="accessory",
                    item_type="stock",
                    product_id=104881553777436,
                    sku_id=104881553777819,
                    product_name="Hair Gripper",
                    product_display="Hair Gripper",
                    model="Magic Tape",
                    color="Hair Gripper",
                    quantity=2,
                    price_per_piece=Decimal("4.20"),
                )],
            ),
        )

    assert "标准价格表" in str(exc_info.value)


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
        ({"price": Decimal("0")}, "price"),
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


@pytest.mark.parametrize("price", [Decimal("1.23456"), Decimal("123456789.1234")])
def test_accessory_price_payload_rejects_database_precision_overflow(price):
    with pytest.raises(ValidationError) as exc_info:
        schemas.AccessoryPricePayload(
            product_id=REAL_PRODUCT_ID,
            sku_id=REAL_SKU_ID,
            accessory_name="Hair Gripper",
            accessory_model="魔术贴",
            accessory_color="Hair Gripper",
            price=price,
        )

    assert exc_info.value.errors()[0]["loc"] == ("price",)


def test_std_price_metadata_keeps_hair_and_accessory_unique_constraints():
    constraints = {constraint.name: constraint for constraint in StdPrice.__table__.constraints}

    assert "uq_ark_std_prices_key" in constraints
    assert "uq_ark_std_accessory_sku" in constraints
    assert [column.name for column in constraints["uq_ark_std_prices_key"].columns] == [
        "product_kind", "series_grade", "length", "weight_unit", "color_type",
    ]


def test_permission_seed_registers_accessory_price_write_and_backfills_invoice_admin_roles(db):
    role = ArkRole(name="invoice_price_manager", label="Invoice price manager", is_system=False)
    invoice_admin = ArkPermission(
        code="invoice:admin",
        module="invoice",
        action="admin",
        label="价格配置",
        kind="action",
        is_legacy=0,
        sort=10,
    )
    db.add_all([role, invoice_admin])
    db.flush()
    db.add(ArkRolePermission(role_id=role.id, permission_id=invoice_admin.id))
    db.commit()

    auth_service.seed_role_permissions(db)

    price_write = db.query(ArkPermission).filter(ArkPermission.code == "invoice_price:write").one()
    assert db.query(ArkRolePermission).filter_by(
        role_id=role.id,
        permission_id=price_write.id,
    ).one_or_none() is not None

    db.query(ArkRolePermission).filter_by(
        role_id=role.id,
        permission_id=price_write.id,
    ).delete()
    db.commit()
    auth_service.seed_role_permissions(db)
    assert db.query(ArkRolePermission).filter_by(
        role_id=role.id,
        permission_id=price_write.id,
    ).one_or_none() is None


# ── accessory standard pricing ───────────────────────────────

REAL_PRODUCT_ID = 104881553777436
REAL_SKU_ID = 104881553777819


def _accessory_price_service():
    module_name = "app.invoice.accessory_price_service"
    assert importlib.util.find_spec(module_name) is not None, "accessory pricing service is missing"
    return importlib.import_module(module_name)


def _create_accessory_candidate_tables(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT,
            name TEXT,
            model TEXT,
            color TEXT,
            group_name TEXT,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_product_skus (
            product_id INTEGER,
            sku_id INTEGER,
            disable_flag INTEGER
        )
    """))


def _seed_accessory_candidates(db):
    _create_accessory_candidate_tables(db)
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
        (product_id, product_no, name, model, color, group_name, disable_flag)
        VALUES
        (:real_pid, 'ACC001', 'Hair Gripper', '魔术贴', 'Hair Gripper', '假发产品', 0),
        (2002, 'ACC002', 'Needle Tool', 'Hook Model', 'Silver', 'Hair ExtensionsTools Fee', 0),
        (2003, 'ACC003', 'Disabled Product', 'Disabled Model', 'Black', 'Other', 1)
    """), {"real_pid": REAL_PRODUCT_ID})
    db.execute(text("""
        INSERT INTO lsordertest.okki_product_skus (product_id, sku_id, disable_flag)
        VALUES
        (:real_pid, :real_sku, 0),
        (:real_pid, 104881553777820, 0),
        (:real_pid, 104881553777821, 1),
        (2002, 22001, 0),
        (2003, 23001, 0)
    """), {"real_pid": REAL_PRODUCT_ID, "real_sku": REAL_SKU_ID})
    db.commit()


def _payload(**overrides):
    values = {
        "product_id": REAL_PRODUCT_ID,
        "sku_id": REAL_SKU_ID,
        # These are deliberately forged. The service must take a live OKKI snapshot.
        "accessory_name": "Forged Name",
        "accessory_model": "Forged Model",
        "accessory_color": "Forged Color",
        "price": Decimal("12.3456"),
        "currency": "USD",
    }
    values.update(overrides)
    return schemas.AccessoryPricePayload(**values)


@contextmanager
def _api_client(db, *, permissions):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": "9",
        "username": "accessory-tester",
        "roles": [],
        "permissions": permissions,
    })
    with TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
        raise_server_exceptions=False,
    ) as client:
        yield client


def test_accessory_price_service_module_exists():
    assert _accessory_price_service()


def test_candidate_search_missing_catalog_tables_is_not_an_empty_result(db, caplog, capsys):
    pricing = _accessory_price_service()
    assert hasattr(pricing, "AccessoryCatalogUnavailable")

    with pytest.raises(pricing.AccessoryCatalogUnavailable, match="同步任务|同步表"):
        pricing.search_candidates(db, keyword=None)

    assert "OKKI" in caplog.text
    assert "OKKI" in capsys.readouterr().out


def test_candidate_search_missing_required_columns_is_catalog_unavailable(db, caplog, capsys):
    db.execute(text("CREATE TABLE lsordertest.okki_products (product_id INTEGER, name TEXT)"))
    db.execute(text("CREATE TABLE lsordertest.okki_product_skus (product_id INTEGER, sku_id INTEGER)"))
    pricing = _accessory_price_service()

    with pytest.raises(pricing.AccessoryCatalogUnavailable, match="同步任务|同步表"):
        pricing.search_candidates(db, keyword=None)

    assert "缺少" in caplog.text
    assert "缺少" in capsys.readouterr().out


def test_catalog_column_probe_failure_is_wrapped_and_logged(db, monkeypatch, caplog, capsys):
    from app.invoice import product_service

    pricing = _accessory_price_service()

    def fail_probe(_db, _table_name):
        raise OperationalError("SHOW COLUMNS", {}, Exception("catalog offline"))

    monkeypatch.setattr(product_service, "_table_columns", fail_probe)

    with pytest.raises(pricing.AccessoryCatalogUnavailable, match="同步任务|同步表"):
        pricing.search_candidates(db, keyword=None)

    assert "探测" in caplog.text
    assert "探测" in capsys.readouterr().out


@pytest.mark.parametrize("keyword", ["Hair Gripper", "魔术贴", "Hair Gripper"])
def test_candidate_search_joins_active_products_and_skus_without_group_dependency(db, keyword):
    _seed_accessory_candidates(db)

    rows = _accessory_price_service().search_candidates(db, keyword=keyword, limit=50)

    assert rows == [
        {
            "product_id": REAL_PRODUCT_ID,
            "sku_id": REAL_SKU_ID,
            "accessory_name": "Hair Gripper",
            "accessory_model": "魔术贴",
            "accessory_color": "Hair Gripper",
        },
        {
            "product_id": REAL_PRODUCT_ID,
            "sku_id": 104881553777820,
            "accessory_name": "Hair Gripper",
            "accessory_model": "魔术贴",
            "accessory_color": "Hair Gripper",
        },
    ]


def test_candidate_search_filters_disabled_rows_and_caps_limit(db):
    _create_accessory_candidate_tables(db)
    for offset in range(55):
        db.execute(text("""
            INSERT INTO lsordertest.okki_products
            (product_id, product_no, name, model, color, group_name, disable_flag)
            VALUES (:pid, :pno, :name, 'Model', 'Color', NULL, 0)
        """), {"pid": 3000 + offset, "pno": f"P{offset}", "name": f"Tool {offset:02d}"})
        db.execute(text("""
            INSERT INTO lsordertest.okki_product_skus (product_id, sku_id, disable_flag)
            VALUES (:pid, :sku, 0)
        """), {"pid": 3000 + offset, "sku": 4000 + offset})
    db.commit()

    rows = _accessory_price_service().search_candidates(db, keyword="Tool", limit=500)

    assert len(rows) == 50
    assert len({row["sku_id"] for row in rows}) == 50


def test_accessory_upsert_refreshes_okki_snapshot_and_preserves_four_decimals(db):
    _seed_accessory_candidates(db)

    row = _accessory_price_service().upsert_price(db, _payload(), user_id=9)
    db.flush()

    assert row.product_kind == "accessory"
    assert row.product_id == REAL_PRODUCT_ID
    assert row.sku_id == REAL_SKU_ID
    assert row.accessory_name == "Hair Gripper"
    assert row.accessory_model == "魔术贴"
    assert row.accessory_color == "Hair Gripper"
    assert row.price == Decimal("12.3456")
    assert row.currency == "USD"
    assert row.updated_by == 9


def test_accessory_upsert_rejects_duplicate_product_sku(db):
    _seed_accessory_candidates(db)
    pricing = _accessory_price_service()
    pricing.upsert_price(db, _payload(), user_id=9)
    db.flush()

    with pytest.raises(ValueError, match="已配置"):
        pricing.upsert_price(db, _payload(price=Decimal("15.0000")), user_id=9)


def test_accessory_edit_only_accepts_accessory_rows_and_refreshes_snapshot(db):
    _seed_accessory_candidates(db)
    pricing = _accessory_price_service()
    accessory = pricing.upsert_price(db, _payload(), user_id=9)
    hair = StdPrice(
        product_kind="hair",
        series_grade="Hair Matrix",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("20.0000"),
        currency="USD",
    )
    db.add(hair)
    db.flush()
    db.execute(text("""
        UPDATE lsordertest.okki_products
        SET name='Hair Gripper New', model='魔术贴 New', color='Hair Gripper New'
        WHERE product_id=:pid
    """), {"pid": REAL_PRODUCT_ID})

    edited = pricing.upsert_price(
        db,
        _payload(id=accessory.id, price=Decimal("13.4567")),
        user_id=10,
    )
    assert edited.id == accessory.id
    assert edited.accessory_name == "Hair Gripper New"
    assert edited.accessory_model == "魔术贴 New"
    assert edited.accessory_color == "Hair Gripper New"
    assert edited.price == Decimal("13.4567")

    with pytest.raises(ValueError, match="配件价格"):
        pricing.upsert_price(db, _payload(id=hair.id), user_id=9)


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        ("DELETE FROM lsordertest.okki_products WHERE product_id=:pid", "产品"),
        ("UPDATE lsordertest.okki_products SET disable_flag=1 WHERE product_id=:pid", "产品"),
        ("DELETE FROM lsordertest.okki_product_skus WHERE sku_id=:sku", "SKU"),
        ("UPDATE lsordertest.okki_product_skus SET disable_flag=1 WHERE sku_id=:sku", "SKU"),
    ],
)
def test_accessory_upsert_rejects_missing_or_disabled_okki_identity(db, mutation, error_fragment):
    _seed_accessory_candidates(db)
    db.execute(text(mutation), {"pid": REAL_PRODUCT_ID, "sku": REAL_SKU_ID})

    with pytest.raises(ValueError, match=f"{error_fragment}.*重新"):
        _accessory_price_service().upsert_price(db, _payload(), user_id=9)


def test_accessory_list_filters_kind_keyword_and_applies_customer_rules(db):
    _seed_accessory_candidates(db)
    pricing = _accessory_price_service()
    accessory = pricing.upsert_price(db, _payload(), user_id=9)
    db.add(StdPrice(
        product_kind="hair",
        series_grade="Hair Gripper Hair",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("99.0000"),
        currency="USD",
    ))
    db.add_all([
        CustomerPriceRule(
            customer_id="FIXED", adjust_type="fixed", adjust_value=Decimal("1.2345"), enabled=1,
        ),
        CustomerPriceRule(
            customer_id="PERCENT", adjust_type="percent", adjust_value=Decimal("10.0000"), enabled=1,
        ),
    ])
    db.flush()

    no_rule = pricing.list_prices(db, keyword="魔术贴", customer_id=None)
    fixed = pricing.list_prices(db, keyword="Gripper", customer_id="FIXED")
    percent = pricing.list_prices(db, customer_id="PERCENT")
    missing = pricing.list_prices(db, customer_id="NO-RULE")

    assert [item["id"] for item in no_rule] == [accessory.id]
    assert no_rule[0]["standard_price"] == Decimal("12.3456")
    assert no_rule[0]["customer_price"] == Decimal("12.3456")
    assert fixed[0]["customer_price"] == Decimal("13.5801")
    assert percent[0]["customer_price"] == Decimal("13.5802")
    assert missing[0]["customer_price"] == Decimal("12.3456")
    assert no_rule[0]["currency"] == "USD"
    assert db.get(StdPrice, accessory.id).price == Decimal("12.3456")


def test_accessory_list_filters_invoice_currency_without_hiding_other_history(db):
    usd = StdPrice(
        product_kind="accessory", accessory_name="USD Tool", accessory_model="M1",
        accessory_color="Black", product_id=101, sku_id=1001,
        price=Decimal("2.0000"), currency="USD",
    )
    eur = StdPrice(
        product_kind="accessory", accessory_name="EUR Tool", accessory_model="M2",
        accessory_color="Brown", product_id=102, sku_id=1002,
        price=Decimal("3.0000"), currency="EUR",
    )
    db.add_all([usd, eur])
    db.flush()

    pricing = _accessory_price_service()
    assert {row["id"] for row in pricing.list_prices(db)} == {usd.id, eur.id}
    assert [row["id"] for row in pricing.list_prices(db, currency="usd")] == [usd.id]

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        response = client.get("/api/invoice/price/accessories", params={"currency": "EUR"})

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]["items"]] == [eur.id]


def test_accessory_delete_cannot_delete_hair_or_missing_rows(db):
    _seed_accessory_candidates(db)
    pricing = _accessory_price_service()
    accessory = pricing.upsert_price(db, _payload(), user_id=9)
    hair = StdPrice(
        product_kind="hair",
        series_grade="Hair Matrix",
        length="18",
        weight_unit="100g",
        color_type="solid",
        price=Decimal("20.0000"),
        currency="USD",
    )
    db.add(hair)
    db.flush()

    assert pricing.delete_price(db, hair.id) is False
    assert db.get(StdPrice, hair.id) is hair
    assert pricing.delete_price(db, 999999) is False
    assert pricing.delete_price(db, accessory.id) is True


def test_accessory_price_read_api_uses_price_page_permission_and_ok_envelope(db):
    _seed_accessory_candidates(db)

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        candidates = client.get("/api/invoice/price/accessory-candidates", params={"keyword": "魔术贴"})
        prices = client.get("/api/invoice/price/accessories")

    assert candidates.status_code == 200
    assert candidates.json()["code"] == 200
    assert candidates.json()["data"]["items"][0]["product_id"] == REAL_PRODUCT_ID
    assert prices.status_code == 200
    assert prices.json() == {"code": 200, "message": "ok", "data": {"items": []}}

    with _api_client(db, permissions=[]) as client:
        assert client.get("/api/invoice/price/accessories").status_code == 403


def test_accessory_price_api_preserves_four_decimal_customer_rule_for_invoice(db):
    _seed_accessory_okki_product(db)
    row = _accessory_std_price(db)
    row.price = Decimal("12.3500")
    db.add(CustomerPriceRule(
        customer_id="PERCENT-4DP",
        adjust_type="percent",
        adjust_value=Decimal("10.0000"),
        enabled=1,
    ))
    db.flush()

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        response = client.get("/api/invoice/price/accessories", params={
            "customer_id": "PERCENT-4DP",
            "active_only": "true",
        })

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert Decimal(str(item["standard_price"])) == Decimal("12.3500")
    assert Decimal(str(item["customer_price"])) == Decimal("13.5850")


@pytest.mark.parametrize("disable_product", [True, False], ids=["product-disabled", "sku-disabled"])
def test_accessory_price_list_keeps_history_by_default_and_filters_inactive_for_invoice(db, disable_product):
    _seed_accessory_okki_product(db)
    historical = _accessory_std_price(db)
    db.add(StdPrice(
        product_kind="accessory",
        accessory_name="Legacy orphan",
        accessory_model="Legacy",
        accessory_color="Black",
        product_id=None,
        sku_id=None,
        price=Decimal("1.0000"),
        currency="USD",
    ))
    db.flush()
    if disable_product:
        db.execute(text("""
            UPDATE lsordertest.okki_products
            SET disable_flag = 1
            WHERE product_id = 104881553777436
        """))
    else:
        db.execute(text("""
            UPDATE lsordertest.okki_product_skus
            SET disable_flag = 1
            WHERE product_id = 104881553777436 AND sku_id = 104881553777819
        """))

    pricing = _accessory_price_service()
    assert historical.id in [row["id"] for row in pricing.list_prices(db)]
    assert pricing.list_prices(db, active_only=True) == []


def test_accessory_price_active_only_catalog_outage_is_actionable_503_but_history_still_lists(db):
    _accessory_std_price(db)

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        history = client.get("/api/invoice/price/accessories")
        active = client.get("/api/invoice/price/accessories", params={"active_only": "true"})

    assert history.status_code == 200
    assert len(history.json()["data"]["items"]) == 1
    assert active.status_code == 503
    assert "检查OKKI产品同步任务/同步表" in active.json()["detail"]


def test_accessory_price_active_only_wraps_catalog_query_failure(db, monkeypatch, caplog, capsys):
    from app.invoice import product_service

    _accessory_std_price(db)

    def pretend_catalog_columns_exist(_db, table_name):
        if table_name == "okki_products":
            return {"product_id", "name", "model", "color", "disable_flag"}
        return {"product_id", "sku_id", "disable_flag"}

    monkeypatch.setattr(product_service, "_table_columns", pretend_catalog_columns_exist)
    pricing = _accessory_price_service()

    with pytest.raises(pricing.AccessoryCatalogUnavailable, match="同步任务|同步表"):
        pricing.list_prices(db, active_only=True)

    assert "查询失败" in caplog.text
    assert "查询失败" in capsys.readouterr().out


@pytest.mark.parametrize("operation", ["search", "upsert"])
def test_accessory_catalog_select_failures_are_actionable(operation, db, monkeypatch, caplog, capsys):
    from app.invoice import product_service

    def pretend_catalog_columns_exist(_db, table_name):
        if table_name == "okki_products":
            return {"product_id", "name", "model", "color", "disable_flag"}
        return {"product_id", "sku_id", "disable_flag"}

    def fail_catalog_query(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, RuntimeError("catalog offline"))

    monkeypatch.setattr(product_service, "_table_columns", pretend_catalog_columns_exist)
    monkeypatch.setattr(db, "execute", fail_catalog_query)
    pricing = _accessory_price_service()

    with pytest.raises(pricing.AccessoryCatalogUnavailable, match="同步任务|同步表"):
        if operation == "search":
            pricing.search_candidates(db, keyword="Gripper")
        else:
            pricing.upsert_price(db, _payload(), user_id=9)

    assert "查询失败" in caplog.text
    assert "查询失败" in capsys.readouterr().out


def test_accessory_price_write_delete_api_require_invoice_price_write(db):
    _seed_accessory_candidates(db)
    body = _payload().model_dump(mode="json")

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        assert client.post("/api/invoice/price/accessories", json=body).status_code == 403
    with _api_client(db, permissions=["invoice:admin"]) as client:
        assert client.post("/api/invoice/price/accessories", json=body).status_code == 403
    with _api_client(db, permissions=["invoice_price:write"]) as client:
        created = client.post("/api/invoice/price/accessories", json=body)
        price_id = db.query(StdPrice).filter_by(product_kind="accessory").one().id
        deleted = client.delete(f"/api/invoice/price/accessories/{price_id}")

    assert created.status_code == 200
    assert created.json()["code"] == 200
    assert deleted.status_code == 200
    assert deleted.json()["code"] == 200


def test_accessory_price_api_maps_actionable_business_errors(db):
    _create_accessory_candidate_tables(db)
    body = _payload().model_dump(mode="json")

    with _api_client(db, permissions=["invoice_price:write"]) as client:
        invalid = client.post("/api/invoice/price/accessories", json=body)
        missing = client.delete("/api/invoice/price/accessories/999999")

    assert invalid.status_code == 400
    assert "重新" in invalid.json()["detail"]
    assert missing.status_code == 404
    assert "配件价格" in missing.json()["detail"]


def test_accessory_catalog_api_returns_actionable_503(db):
    body = _payload().model_dump(mode="json")

    with _api_client(db, permissions=["invoice_price:read"]) as client:
        candidates = client.get("/api/invoice/price/accessory-candidates")
    with _api_client(db, permissions=["invoice_price:write"]) as client:
        saved = client.post("/api/invoice/price/accessories", json=body)

    assert candidates.status_code == 503
    assert saved.status_code == 503
    assert "检查OKKI产品同步任务/同步表" in candidates.json()["detail"]
    assert "检查OKKI产品同步任务/同步表" in saved.json()["detail"]


@pytest.mark.parametrize("price", ["1.23456", "123456789.1234"])
def test_accessory_price_api_rejects_database_precision_overflow(db, price):
    body = _payload().model_dump(mode="json")
    body["price"] = price

    with _api_client(db, permissions=["invoice_price:write"]) as client:
        response = client.post("/api/invoice/price/accessories", json=body)

    assert response.status_code == 422


def test_accessory_price_api_rolls_back_real_sqlite_duplicate(db):
    _seed_accessory_candidates(db)
    body = _payload().model_dump(mode="json")

    def inject_competing_row(session, _flush_context, _instances):
        session.connection().execute(text("""
            INSERT INTO ark_std_prices
            (product_kind, accessory_name, accessory_model, accessory_color,
             product_id, sku_id, price, currency, created_at, updated_at)
            VALUES
            ('accessory', 'Concurrent Hair Gripper', '魔术贴', 'Hair Gripper',
             :product_id, :sku_id, 10.0000, 'USD', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"product_id": REAL_PRODUCT_ID, "sku_id": REAL_SKU_ID})

    event.listen(db, "before_flush", inject_competing_row, once=True)

    with _api_client(db, permissions=["invoice_price:write"]) as client:
        response = client.post("/api/invoice/price/accessories", json=body)

    assert response.status_code == 400
    assert "已配置" in response.json()["detail"]
    assert db.query(StdPrice).filter_by(product_kind="accessory").count() == 0
    assert db.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.parametrize(
    "original_error",
    [
        Exception(1452, "Cannot add or update a child row"),
        Exception(1062, "Duplicate entry for key 'some_other_constraint'"),
    ],
)
def test_accessory_price_api_does_not_misreport_other_integrity_errors(
    db, monkeypatch, caplog, capsys, original_error,
):
    _seed_accessory_candidates(db)
    body = _payload().model_dump(mode="json")
    original_rollback = db.rollback
    rolled_back = {"value": False}

    def fail_commit():
        raise IntegrityError("INSERT ark_std_prices", {}, original_error)

    def track_rollback():
        rolled_back["value"] = True
        original_rollback()

    monkeypatch.setattr(db, "commit", fail_commit)
    monkeypatch.setattr(db, "rollback", track_rollback)

    with _api_client(db, permissions=["invoice_price:write"]) as client:
        response = client.post("/api/invoice/price/accessories", json=body)

    assert response.status_code == 500
    assert rolled_back["value"] is True
    assert "完整性错误" in caplog.text
    assert "integrity error" in capsys.readouterr().out
