from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.time import beijing_now
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation, item_stock_threshold, validate_observation
from app.portal.schemas import CustomerQuoteInput, Delivery


@pytest.mark.parametrize("name,threshold", [("Genius Weft",30),("Tape Hair",200),
    ("K Tape",200),("Nano Tape",200),("I Tape",200),("Butterfly Weft",5),("K Tip",30)])
def test_type_threshold_boundaries(name, threshold):
    item = SimpleNamespace(family_id=None, standard_json={"product_display":name}, conversion_factor=Decimal("2"))
    gate = item_stock_threshold(item)
    assert gate == threshold * 2
    now = beijing_now()
    def check(units):
        validate_observation(InventoryObservation(Decimal(units)*2,"g",now,"test"),now=now,
            max_age_seconds=30,quantity=1,inventory_unit="g",conversion_factor=Decimal("2"),
            safety_buffer=Decimal("0"),stock_threshold=gate)
    check(threshold)
    with pytest.raises(PortalError, match="Available inventory"):
        check(threshold-1)


def test_quote_delivery_can_be_omitted_or_partial():
    quote = CustomerQuoteInput(items=[{"item_id":"11111111-1111-4111-8111-111111111111","quantity":1}])
    assert quote.delivery == Delivery()
    assert Delivery(city="Paris").city == "Paris"
    with pytest.raises(ValueError):
        Delivery(country_code="USA")


def test_release_migrates_existing_type_thresholds_and_inventory_unit_conversion(monkeypatch):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    migration = Path(__file__).resolve().parents[2] / "alembic/versions/212_portal_customer_settings.py"
    spec = importlib.util.spec_from_file_location("customer_settings_migration", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ark_order_portal_product_families (id INTEGER PRIMARY KEY, code TEXT, out_of_stock_below NUMERIC, row_version INTEGER)"))
        conn.execute(text("CREATE TABLE ark_order_portal_catalog_items (family_id INTEGER, conversion_factor NUMERIC, safety_buffer NUMERIC, row_version INTEGER)"))
        codes = [(1,"genius_weft_50g",30),(2,"tape_hair",200),(3,"butterfly_weft",5),(4,"k_tip",30),(5,"k_tape",200),(6,"nano_tape",200),(7,"i_tape",200)]
        for identifier,code,_ in codes:
            conn.execute(text("INSERT INTO ark_order_portal_product_families VALUES (:id,:code,8,1)"), {"id":identifier,"code":code})
            conn.execute(text("INSERT INTO ark_order_portal_catalog_items VALUES (:id,2,16,1)"), {"id":identifier})
        monkeypatch.setattr(module.op, "add_column", lambda *args, **kw: None)
        monkeypatch.setattr(module.op, "create_foreign_key", lambda *args, **kw: None)
        monkeypatch.setattr(module.op, "get_bind", lambda: conn)
        module.upgrade()
        for identifier,_,expected in codes:
            assert conn.execute(text("SELECT out_of_stock_below,row_version FROM ark_order_portal_product_families WHERE id=:id"), {"id":identifier}).one() == (expected,2)
            assert conn.execute(text("SELECT safety_buffer,row_version FROM ark_order_portal_catalog_items WHERE family_id=:id"), {"id":identifier}).one() == (expected*2,2)
    engine.dispose()
