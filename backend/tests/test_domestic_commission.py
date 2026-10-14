"""Customer defaults and immutable order commission attribution (isolated SQLite)."""
from decimal import Decimal as D

import pytest

from app.domestic import customer_service, order_service
from app.domestic.schemas import CustomerCreate
from app.domestic.schemas import CustomerUpdate, DraftSubmitRequest, OrderUpdate
from tests.test_domestic_member_pricing import _operator
from tests.test_domestic_member_pricing import _order_pricing_context, _priced_order_payload
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission, DomesticOrderCommission, DomesticOrder
from app.domestic.commission_service import CommissionAllocationChanged


def test_new_customer_uses_selected_owner_for_default_commission(db):
    creator = _operator(db, "commission-creator")
    owner = _operator(db, "commission-owner")
    customer = customer_service.create_customer(db, CustomerCreate(
        shop_name="提成默认客户", owner_user_id=owner.id,
    ), creator.id)
    rows, _ = customer_service.list_customers(db)
    row = next(row for row in rows if row["id"] == customer.id)
    assert row["commission_allocations"] == [
        {"user_id": owner.id, "user_name": owner.real_name, "rate": "0.0400"},
    ]


def test_inline_customer_gets_default_without_committing_parent_transaction(db):
    owner = _operator(db, "commission-inline")
    customer = customer_service.find_or_create_by_shop_name(db, "下单建档客户", owner.id)
    rows, _ = customer_service.list_customers(db)
    assert rows[0]["commission_allocations"][0]["rate"] == "0.0400"
    assert rows[0]["commission_allocations"][0]["user_id"] == owner.id


def allocations(db, customer):
    rows, _ = customer_service.list_customers(db)
    return next(row["commission_allocations"] for row in rows if row["id"] == customer.id)


def configure(db, customer, user, *rates):
    return customer_service.update_customer(db, customer.id, CustomerUpdate(
        commission_allocations=[{"user_id": uid, "rate": rate} for uid, rate in rates],
    ), user.id)


@pytest.mark.parametrize("draft", [False, True])
def test_snapshot_survives_config_owner_name_changes_and_idempotent_replay(db, draft):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, f"snapshot-{draft}")
    other = _operator(db, "commission-second")
    configure(db, customer, user, (user.id, "0.03"), (other.id, "0.01"))
    request = _priced_order_payload(customer, attrs, quote, request_id=f"snapshot-{draft}", is_draft=draft)
    created = order_service.create_order(db, request, user.id)
    before = order_service.get_order_detail(db, created["id"])["commission_allocations"]
    configure(db, customer, user, (user.id, "0.02"), (other.id, "0.02"))
    other.real_name = "改名后的业务员"
    other.is_active = False
    db.commit()
    customer_service.update_customer(db, customer.id, CustomerUpdate(owner_user_id=other.id), user.id)
    replay = order_service.create_order(db, request, user.id)
    assert replay["id"] == created["id"] and replay["replayed"]
    after = order_service.get_order_detail(db, created["id"])["commission_allocations"]
    assert after == before
    assert [row["rate"] for row in after] == ["0.0300", "0.0100"]
    # Public progress/customer-facing detail must not disclose internal commission.
    assert "commission_allocations" not in order_service.get_order_detail(db, created["id"], include_finance=False)
    assert db.query(DomesticOrderCommission).filter_by(order_id=created["id"]).count() == 2


def test_new_order_uses_new_config_and_draft_submit_preserves_original(db):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "draft-snapshot")
    first = order_service.create_order(db, _priced_order_payload(
        customer, attrs, quote, request_id="draft-commission-first", is_draft=True), user.id)
    other = _operator(db, "new-recipient")
    configure(db, customer, user, (user.id, "0.02"), (other.id, "0.02"))
    second = order_service.create_order(db, _priced_order_payload(
        customer, attrs, quote, request_id="draft-commission-second", is_draft=True), user.id)
    first_detail = order_service.get_order_detail(db, first["id"])
    order_service.submit_draft(db, first["id"], DraftSubmitRequest(
        request_id="submit-commission-first", expected_quotes=first_detail["current_expected_quotes"]), user.id)
    assert order_service.get_order_detail(db, first["id"])["commission_allocations"][0]["rate"] == "0.0400"
    assert len(order_service.get_order_detail(db, second["id"])["commission_allocations"]) == 2


def test_selected_allocation_changed_rejects_order_without_writes(db):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "stale-allocation")
    request = _priced_order_payload(customer, attrs, quote, request_id="stale-allocation-create")
    request = type(request).model_validate({**request.model_dump(),
        "expected_commission_allocations": [{"user_id": user.id, "rate": "0.04"}]})
    configure(db, customer, user, (user.id, "0.035"))
    with pytest.raises(CommissionAllocationChanged) as caught:
        order_service.create_order(db, request, user.id)
    assert caught.value.detail["commission_allocations"][0]["rate"] == "0.0350"
    assert db.query(DomesticOrder).count() == db.query(DomesticOrderCommission).count() == 0
    request.expected_commission_allocations[0].rate = D("0.035")
    created = order_service.create_order(db, request, user.id)
    configure(db, customer, user, (user.id, "0.04"))
    assert order_service.create_order(db, request, user.id)["id"] == created["id"]


def test_missing_configuration_never_falls_back_to_current_owner(db):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "missing-config")
    db.query(DomesticCustomerCommission).filter_by(customer_id=customer.id).delete()
    db.commit()
    with pytest.raises(ValueError, match="未配置提成"):
        order_service.create_order(db, _priced_order_payload(
            customer, attrs, quote, request_id="missing-commission-create"), user.id)
    assert db.query(DomesticOrder).count() == 0


@pytest.mark.parametrize("bad", [None, [], [{"user_id": 1, "rate": "0"}],
    [{"user_id": 1, "rate": "0.03"}, {"user_id": 1, "rate": "0.01"}],
    [{"user_id": 1, "rate": "0.7"}, {"user_id": 2, "rate": "0.7"}],
    [{"user_id": 999999, "rate": "0.04"}]])
def test_invalid_configuration_preserves_original(db, bad):
    user = _operator(db, "invalid-allocation")
    customer = customer_service.create_customer(db, CustomerCreate(shop_name="invalid-config"), user.id)
    before = allocations(db, customer)
    with pytest.raises(ValueError):
        customer_service.update_customer(db, customer.id, CustomerUpdate(commission_allocations=bad), user.id)
    db.rollback()
    assert allocations(db, customer) == before


def test_legacy_order_edit_does_not_infer_a_snapshot(db):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "legacy-snapshot")
    created = order_service.create_order(db, _priced_order_payload(
        customer, attrs, quote, request_id="legacy-snapshot-order"), user.id)
    order = db.get(DomesticOrder, created["id"])
    db.query(DomesticOrderCommission).filter_by(order_id=order.id).delete()
    db.commit()
    order_service.update_order(db, order.id, OrderUpdate(remark="历史订单修改备注"), user.id)
    assert order_service.get_order_detail(db, order.id)["commission_allocations"] == []


def test_unauthorized_user_cannot_change_commission(db):
    user = _operator(db, "allocation-owner")
    intruder = _operator(db, "allocation-intruder")
    customer = customer_service.create_customer(db, CustomerCreate(shop_name="restricted-commission"), user.id)
    with pytest.raises(ValueError):
        configure(db, customer, intruder, (intruder.id, "0.04"))
    assert allocations(db, customer)[0]["user_id"] == user.id


def test_pre_release_fingerprint_still_replays_without_backfilling_snapshot(db):
    import hashlib
    import json
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "old-fingerprint")
    request = _priced_order_payload(customer, attrs, quote, request_id="pre-release-replay")
    created = order_service.create_order(db, request, user.id)
    old_data = request.model_dump(mode="json", exclude={"request_id", "expected_commission_allocations"})
    for item in old_data["items"]:
        for field in ("guest_name", "guest_order_date"):
            if item.get(field) is None:
                item.pop(field, None)
    old_hash = hashlib.sha256(json.dumps(old_data, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    order = db.get(DomesticOrder, created["id"])
    order.request_hash = old_hash
    db.query(DomesticOrderCommission).filter_by(order_id=order.id).delete()
    db.commit()
    assert order_service.create_order(db, request, user.id)["replayed"]
    assert order_service.get_order_detail(db, order.id)["commission_allocations"] == []


def test_draft_customer_change_rebuilds_once_and_audits_new_customer(db):
    from app.domestic_decision import event_hooks  # noqa: F401
    from app.domestic_decision.models import DecisionEvent
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "switch-customer")
    created = order_service.create_order(db, _priced_order_payload(
        customer, attrs, quote, request_id="switch-customer-order", is_draft=True), user.id)
    other = _operator(db, "switch-other")
    target = customer_service.create_customer(db, CustomerCreate(shop_name="换客目标", owner_user_id=user.id), user.id)
    target.balance = D("10000")
    target.membership_level = customer.membership_level
    db.commit()
    configure(db, target, user, (user.id, "0.03"), (other.id, "0.01"))
    detail = order_service.get_order_detail(db, created["id"])
    change = OrderUpdate(customer_id=target.id, request_id="switch-customer-request",
                         expected_quotes=detail["current_expected_quotes"])
    from sqlalchemy import func
    last_event_id = db.query(func.max(DecisionEvent.id)).scalar() or 0
    order_service.update_order(db, created["id"], change, user.id)
    rows = db.query(DomesticOrderCommission).filter_by(order_id=created["id"]).all()
    assert [row.rate for row in sorted(rows, key=lambda row: row.user_id)] == [D("0.03"), D("0.01")]
    row_ids = {row.id for row in rows}
    events = db.query(DecisionEvent).filter_by(entity_type="order_commission", event_type="created").filter(DecisionEvent.id > last_event_id).all()
    assert len(events) == 2
    assert {event.entity_id for event in events} == row_ids
    assert all(event.customer_id == target.id for event in events)
    configure(db, target, user, (user.id, "0.02"), (other.id, "0.02"))
    assert order_service.update_order(db, created["id"], change, user.id)["replayed"]
    # Sending the same customer explicitly with a new request is also not a reallocation.
    same = change.model_copy(update={"request_id": "same-customer-request"})
    order_service.update_order(db, created["id"], same, user.id)
    assert order_service.get_order_detail(db, created["id"])["commission_allocations"][0]["rate"] == "0.0300"


def test_snapshot_and_default_timestamp_are_beijing_even_across_utc_midnight(db, monkeypatch):
    from datetime import datetime, timezone
    from app.core import time as clock
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 13, 16, 0, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(clock, "datetime", FrozenDatetime)
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "beijing-time")
    created = order_service.create_order(db, _priced_order_payload(
        customer, attrs, quote, request_id="beijing-time-order"), user.id)
    assert db.query(DomesticCustomerCommission).filter_by(customer_id=customer.id).one().created_at == datetime(2026, 10, 14, 0, 0, 1)
    assert db.query(DomesticOrderCommission).filter_by(order_id=created["id"]).one().created_at == datetime(2026, 10, 14, 0, 0, 1)


def test_order_config_read_is_mysql_current_read_and_refreshes_orm(db):
    from sqlalchemy import event, update
    from sqlalchemy.dialects import mysql
    from app.domestic.commission_service import locked_allocations
    user = _operator(db, "current-read")
    customer = customer_service.create_customer(db, CustomerCreate(shop_name="current-read"), user.id)
    cached = db.query(DomesticCustomerCommission).filter_by(customer_id=customer.id).one()
    db.connection().execute(update(DomesticCustomerCommission.__table__).where(
        DomesticCustomerCommission.id == cached.id).values(rate=D("0.03")))
    queries = []
    def capture(state):
        sql = str(state.statement.compile(dialect=mysql.dialect()))
        if "ark_domestic_customer_commissions" in sql:
            queries.append(sql)
    event.listen(db, "do_orm_execute", capture)
    try:
        assert locked_allocations(db, customer.id)[0]["rate"] == "0.0300"
    finally:
        event.remove(db, "do_orm_execute", capture)
    assert queries and "FOR UPDATE" in queries[-1]


def test_api_stale_allocation_returns_409_and_blocks_unauthorized_change(db):
    from tests.test_domestic_customer_order_controls import _api_client
    from app.domestic.schemas import OrderCreate
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "api-stale")
    request = _priced_order_payload(customer, attrs, quote, request_id="api-stale-request")
    request = OrderCreate.model_validate({**request.model_dump(),
        "expected_commission_allocations": [{"user_id": user.id, "rate": "0.03"}]})
    client = _api_client(db, user, "domestic:write")
    response = client.post("/api/domestic/orders", json=request.model_dump(mode="json"))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "COMMISSION_ALLOCATION_CHANGED"
    assert db.query(DomesticOrder).count() == 0
    intruder = _operator(db, "api-allocation-intruder")
    denied = _api_client(db, intruder, "domestic:write").put(f"/api/domestic/customers/{customer.id}",
        json={"commission_allocations": [{"user_id": intruder.id, "rate": "0.04"}]})
    assert denied.status_code == 404


def test_snapshot_failure_rolls_back_order_items_and_customer_charge(db, monkeypatch):
    from app.domestic import commission_service
    from app.domestic.models import DomesticCustomerLedger, DomesticOrderItem
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "snapshot-rollback")
    before = customer.balance
    original = commission_service.save_order_snapshot
    def fail_after_snapshot(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic snapshot failure")
    monkeypatch.setattr(commission_service, "save_order_snapshot", fail_after_snapshot)
    with pytest.raises(RuntimeError, match="synthetic snapshot"):
        order_service.create_order(db, _priced_order_payload(
            customer, attrs, quote, request_id="snapshot-rollback-request"), user.id)
    db.commit()
    assert customer.balance == before
    assert db.query(DomesticOrder).count() == db.query(DomesticOrderCommission).count() == 0
    assert db.query(DomesticOrderItem).count() == db.query(DomesticCustomerLedger).count() == 0


def test_import_defaults_only_new_customers_and_preserves_existing_allocation(db):
    from app.domestic import customer_import_service
    from tests.test_domestic_customer_import import _row, _workbook, HEADER
    owner = _operator(db, "import-commission-owner")
    owner.real_name = "王语涵"
    creator = _operator(db, "import-commission-creator")
    data = _workbook({"王语涵": [HEADER, _row()]})
    rows, _, _ = customer_import_service.parse_workbook(data)
    customer_import_service.import_customers(db, rows, creator.id)
    customer = db.query(DomesticCustomer).one()
    assert allocations(db, customer) == [{"user_id": owner.id, "user_name": "王语涵", "rate": "0.0400"}]
    configure(db, customer, owner, (owner.id, "0.035"))
    customer_import_service.import_customers(db, rows, creator.id)
    assert allocations(db, customer)[0]["rate"] == "0.0350"


def test_migration_creates_empty_snapshot_tables_in_isolated_database():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text, inspect
    path = Path(__file__).parents[1] / "alembic/versions/196_domestic_commission.py"
    spec = importlib.util.spec_from_file_location("domestic_commission_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE ark_domestic_customers (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE ark_domestic_orders (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO ark_domestic_orders VALUES (1)"))
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
            assert module.down_revision == "195_main_portal_merge"
            assert connection.scalar(text("SELECT COUNT(*) FROM ark_domestic_order_commissions")) == 0
            assert connection.scalar(text("SELECT COUNT(*) FROM ark_domestic_customer_commissions")) == 0
            assert connection.scalar(text("SELECT COUNT(*) FROM ark_domestic_orders")) == 1
            fks = inspect(connection).get_foreign_keys("ark_domestic_order_commissions")
            assert next(fk for fk in fks if fk["referred_table"] == "ark_users")["options"]["ondelete"] == "RESTRICT"
    finally:
        engine.dispose()


def test_migration_mysql_ddl_preserves_unsigned_user_fk_and_has_one_head():
    from io import StringIO
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("commission_mysql_migration", root / "alembic/versions/196_domestic_commission.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    module.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    module.upgrade()
    sql = output.getvalue()
    assert sql.count("user_id INTEGER UNSIGNED NOT NULL") == 2
    assert "NUMERIC(5, 4)" in sql and "ON DELETE RESTRICT" in sql
    assert "INSERT" not in sql and "UPDATE" not in sql
    assert ScriptDirectory(str(root / "alembic")).get_heads() == ["196_domestic_commission"]
