import importlib.util
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.domestic import customer_service, order_service
from app.domestic.models import DomesticOrder
from app.domestic.schemas import OrderCreate, OrderUpdate
from app.domestic.export_service import build_order_workbook
from tests.test_domestic_customer_order_controls import _user, _customer
from tests.test_domestic_order_channel_source import context
from tests.test_domestic_export import _order_detail


def test_combined_customer_filters_and_pagination(db):
    owner, other = _user(db, "owner"), _user(db, "other")
    first = _customer(db, owner, "first")
    second = _customer(db, owner, "second")
    third = _customer(db, other, "third")
    first.customer_level, second.customer_level, third.customer_level = "A", "B", "A"
    db.flush()
    rows, total = customer_service.list_customers(db, customer_level="A", owner_user_id=owner.id, province="山东省", owner_scope="private")
    assert total == 1 and rows[0]["id"] == first.id
    assert customer_service.list_customers(db, customer_level="A", page_size=1)[1] == 2
    assert customer_service.list_customers(db, owner_user_id=owner.id)[1] == 2
    assert customer_service.list_customers(db, owner_user_id=owner.id, owner_scope="public")[1] == 0
    assert customer_service.list_customers(db)[1] == 3


def test_guest_create_detail_edit_clear_and_replay(db):
    user, customer, payload = context(db, "guest-field")
    data = payload.model_dump()
    data["guest_name"] = "  王女士  "
    request = OrderCreate.model_validate(data)
    result = order_service.create_order(db, request, user.id)
    order_id = result["id"]
    assert db.get(DomesticOrder, order_id).guest_name == "王女士"
    assert order_service.get_order_detail(db, order_id)["guest_name"] == "王女士"
    assert order_service.create_order(db, request, user.id)["replayed"]
    order_service.update_order(db, order_id, OrderUpdate(guest_name=" 李先生 "), user.id)
    assert order_service.get_order_detail(db, order_id)["guest_name"] == "李先生"
    order_service.update_order(db, order_id, OrderUpdate(guest_name="  "), user.id)
    assert order_service.get_order_detail(db, order_id)["guest_name"] is None
    with pytest.raises(ValidationError):
        OrderUpdate(guest_name="名" * 121)


def test_guest_printed_on_both_sheets_and_absent_from_production():
    detail = _order_detail()
    detail["guest_name"] = "=王女士"
    wb = load_workbook(build_order_workbook(detail, "销售"))
    assert len(wb.worksheets) == 2
    for ws in wb.worksheets:
        assert "顾客：'=王女士" in ws["A3"].value
        assert ws["A3"].data_type == "s"
    detail["order_kind"] = "production"
    wb = load_workbook(build_order_workbook(detail, "销售"))
    assert all("顾客：" not in ws["A3"].value for ws in wb.worksheets)


def test_guest_migration_preserves_existing_rows():
    engine = create_engine("sqlite:///:memory:")
    path = Path(__file__).parents[1] / "alembic/versions/145_domestic_order_guest.py"
    spec = importlib.util.spec_from_file_location("guest_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ark_domestic_orders (id INTEGER PRIMARY KEY, order_no VARCHAR(64))"))
        conn.execute(text("INSERT INTO ark_domestic_orders VALUES (1, 'legacy')"))
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert conn.execute(text("SELECT order_no, guest_name FROM ark_domestic_orders")).one() == ("legacy", None)
        assert next(c for c in inspect(conn).get_columns("ark_domestic_orders") if c["name"] == "guest_name")["nullable"]


@pytest.mark.parametrize("kind", ["business", "production"])
def test_empty_guest_preserves_existing_request_hash(db, kind):
    import hashlib
    import json
    user, customer, payload = context(db, "old-hash")
    data = payload.model_dump()
    data["order_kind"] = kind
    payload = OrderCreate.model_validate(data)
    old_data = payload.model_dump(mode="json", exclude={"request_id", "guest_name"})
    old_hash = hashlib.sha256(json.dumps(old_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert order_service._order_request_hash(payload) == old_hash
    if kind == "business":
        result = order_service.create_order(db, payload, user.id)
        db.get(DomesticOrder, result["id"]).request_hash = old_hash
        db.commit()
        assert order_service.create_order(db, payload, user.id)["replayed"]
        changed = payload.model_copy(update={"guest_name": "New guest"})
        assert order_service._order_request_hash(changed) != old_hash
