from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.portal import sku_source as service
from app.portal.errors import PortalError


@pytest.fixture
def mirror(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(PORTAL_OKKI_NAMESPACE="okki:test"))
    monkeypatch.setattr(service.product_service, "_schema", lambda: "main")
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        db.execute(text("CREATE TABLE okki_products (product_id INTEGER, product_name TEXT, model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER)"))
        db.execute(text("CREATE TABLE okki_product_skus (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER)"))
        db.execute(text("INSERT INTO okki_products VALUES (101, 'Straight/20/1', 'ST', '1', '20', '20g', 0), (102, 'Other', 'OT', '2', '22', '25g', 0)"))
        db.execute(text("INSERT INTO okki_product_skus VALUES (101, 201, 0), (102, 202, 0)"))
        db.commit()
        yield db
    engine.dispose()


def load(db, **overrides):
    return service.load_snapshot(db, **{"namespace": "okki:test", "product_id": "101", "sku_id": "201", "product_kind": "hair", **overrides})


def test_exact_mirror_projection_and_alias_independence(mirror):
    snapshot = load(mirror)
    assert snapshot["standard_json"]["product_display"] == "Straight"
    assert snapshot["standard_json"]["price_unit"] == "20g"
    item = SimpleNamespace(**snapshot, display_name="Customer label", color_name="Midnight")
    assert service.revalidate(mirror, item) == snapshot
    mirror.execute(text("UPDATE okki_products SET unit='25g' WHERE product_id=101"))
    with pytest.raises(PortalError) as caught:
        service.revalidate(mirror, item)
    assert caught.value.code == "SKU_CHANGED"


@pytest.mark.parametrize("change", ["wrong_pair", "product_disabled", "sku_disabled", "duplicate", "missing_attribute"])
def test_invalid_or_ambiguous_identity_rejected(mirror, change):
    if change == "wrong_pair":
        mirror.execute(text("UPDATE okki_product_skus SET product_id=102 WHERE sku_id=201"))
    elif change == "product_disabled":
        mirror.execute(text("UPDATE okki_products SET disable_flag=1 WHERE product_id=101"))
    elif change == "sku_disabled":
        mirror.execute(text("UPDATE okki_product_skus SET disable_flag=1 WHERE sku_id=201"))
    elif change == "duplicate":
        mirror.execute(text("INSERT INTO okki_product_skus VALUES (101,201,0)"))
    else:
        mirror.execute(text("UPDATE okki_products SET unit='' WHERE product_id=101"))
    with pytest.raises(PortalError) as caught:
        load(mirror)
    assert caught.value.code == "SKU_UNAVAILABLE"


@pytest.mark.parametrize("value", [True, 1.0, "00101", "101 OR 1=1", "-1", "9223372036854775808"])
def test_invalid_identity_rejected_before_sql(mirror, value, monkeypatch):
    monkeypatch.setattr(service.product_service, "_table_columns", lambda *args: pytest.fail("Invalid identifier reached SQL"))
    with pytest.raises(PortalError) as caught:
        load(mirror, product_id=value)
    assert caught.value.status == 422


def test_namespace_rejected_before_sql(mirror, monkeypatch):
    monkeypatch.setattr(service.product_service, "_table_columns", lambda *args: pytest.fail("Wrong namespace reached SQL"))
    with pytest.raises(PortalError) as caught:
        load(mirror, namespace="okki:other")
    assert caught.value.status == 503


def test_incomplete_schema_is_not_assumed_active(mirror):
    mirror.execute(text("ALTER TABLE okki_product_skus RENAME COLUMN disable_flag TO old_flag"))
    with pytest.raises(PortalError) as caught:
        load(mirror)
    assert caught.value.status == 503


def test_accessory_does_not_invent_hair_weight(mirror):
    mirror.execute(text("UPDATE okki_products SET size=NULL, unit=NULL WHERE product_id=101"))
    snapshot = load(mirror, product_kind="accessory")
    assert snapshot["standard_json"]["length"] == snapshot["standard_json"]["weight"] == ""


def test_accessory_display_preserves_full_name_with_slash(mirror):
    mirror.execute(text("UPDATE okki_products SET product_name='Tape / replacement', size=NULL, unit=NULL WHERE product_id=101"))
    snapshot = load(mirror, product_kind="accessory")
    assert snapshot["standard_json"]["product_display"] == "Tape / replacement"

