from datetime import date, datetime
from decimal import Decimal as D
import pytest
from app.domestic import shipment_service as ships, receipt_service, request_service, order_service, report_service, balance_service, unit_service
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticItemProgress, DomesticItemUnit, DomesticReportLog, DomesticReportUnit, DomesticCustomerLedger, DomesticCustomer
from app.domestic.shipment_models import DomesticShipmentUnit
from app.domestic.shipment_schemas import ShipmentCreate, ShipmentReceive, ReceiptCreate, ReceiptAllocationInput
from app.domestic.schemas import OrderItemUpdate
from app.core.time import beijing_now, beijing_today
from tests.test_domestic_conditional_routing import conditional_route, conditional_order
from tests.test_domestic_review_flow import _user


@pytest.fixture
def context(db, conditional_order):
    ctx = conditional_order
    item = ctx.item
    order = db.get(DomesticOrder, item.order_id)
    customer = db.get(DomesticCustomer, order.customer_id)
    customer.settle_mode = "credit"
    customer.owner_user_id = ctx.worker.id
    customer.membership_level = "black"
    item.unit_price = D("100")
    item.original_price = D("100")
    item.guest_name = "张女士"
    balance_service.sync_order_finance(db, order, user_id=ctx.worker.id, reason="test")
    db.commit()
    return ctx


def complete(db, ctx, count):
    last = db.query(DomesticItemProgress).filter_by(item_id=ctx.item.id).order_by(DomesticItemProgress.step_order.desc()).first()
    units = db.query(DomesticItemUnit).filter_by(item_id=ctx.item.id).order_by(DomesticItemUnit.unit_no).limit(count).all()
    log = DomesticReportLog(item_id=ctx.item.id, progress_id=last.id, process_id=last.process_id,
        step_order=last.step_order, report_qty=count, reported_by_user_id=ctx.worker.id,
        reported_at=beijing_now(), revoked=0)
    db.add(log); db.flush()
    db.add_all([DomesticReportUnit(log_id=log.id, progress_id=last.id, unit_id=u.id, completed_at=beijing_now()) for u in units])
    last.completed_qty = count
    db.commit()
    return units, log


def ship_payload(ctx, qty=3, key="shipment-test-001", ids=None):
    order = ctx.item.order
    return ShipmentCreate(customer_id=order.customer_id, ship_time=beijing_now(),
                          request_id=key, items=[{"item_id": ctx.item.id, "quantity": qty, "unit_ids": ids}])


def ship(db, ctx, qty=3, key="shipment-test-001", ids=None):
    # noload relationship is intentional; avoid relying on it in fixtures.
    order = db.get(DomesticOrder, ctx.item.order_id)
    payload = ShipmentCreate(customer_id=order.customer_id, ship_time=datetime(2026, 9, 30, 10),
                            request_id=key, items=[{"item_id": ctx.item.id, "quantity": qty, "unit_ids": ids}])
    return ships.create_shipment(db, payload, ctx.worker.id), payload


def receipt(db, ctx, amount, allocations, key):
    order = db.get(DomesticOrder, ctx.item.order_id)
    return receipt_service.create_receipt_request(db, order.customer_id, ReceiptCreate(
        request_id=key, receipt_date=beijing_today(), amount=amount, allocations=allocations,
    ), "test/voucher.png", ctx.worker.id)


def test_partial_delivery_uses_actual_units_and_replay(db, context):
    ctx = context
    units, _ = complete(db, ctx, 6)
    batch, payload = ship(db, ctx)
    assert batch["total_amount"] == 300
    assert batch["items"][0]["unit_codes"] == ["A1-01", "A1-02", "A1-03"]
    order = db.get(DomesticOrder, ctx.item.order_id)
    candidates = ships.candidate_rows(db, order.customer_id, ctx.worker.id)
    assert candidates[0]["available_qty"] == 3
    assert candidates[0]["guest_name"] == "张女士"
    replay = ships.create_shipment(db, payload, ctx.worker.id)
    assert replay["replayed"] and replay["id"] == batch["id"]
    assert db.query(DomesticShipmentUnit).count() == 3
    payload.items[0].quantity = 2
    with pytest.raises(ValueError, match="不同发货内容"):
        ships.create_shipment(db, payload, ctx.worker.id)
    db.rollback()
    with pytest.raises(ValueError, match="未完工|已发货"):
        ship(db, ctx, 1, "shipment-selected-used", [units[0].id])
    db.rollback()
    ship(db, ctx, 3, "shipment-test-002")
    assert ships.candidate_rows(db, order.customer_id, ctx.worker.id) == []
    assert ctx.item.status != 2  # 14 unfinished units remain.
    assert db.get(DomesticCustomer, order.customer_id).balance == D("-2000")


def test_partial_ship_blocks_edit_revoke_and_refunds_only_unshipped(db, context):
    ctx = context
    units, log = complete(db, ctx, 6)
    ship(db, ctx)
    with pytest.raises(ValueError, match="已有发货"):
        order_service.update_item(db, ctx.item.id, OrderItemUpdate(unit_price=D("90")), ctx.worker.id)
    db.rollback()
    with pytest.raises(ValueError, match="相关单件已发货"):
        report_service.revoke_report(db, log.id, ctx.worker.id)
    db.rollback()
    with pytest.raises(ValueError, match="已有发货"):
        order_service.delete_order(db, ctx.item.order_id, ctx.worker.id)
    db.rollback()
    order_service.terminate_order(db, ctx.item.order_id, "cancel remaining", ctx.worker.id)
    order = db.get(DomesticOrder, ctx.item.order_id)
    assert order.charged_amount == D("300")
    assert db.get(DomesticCustomer, order.customer_id).balance == D("-300")
    assert ships.candidate_rows(db, order.customer_id, ctx.worker.id) == []


def test_receipt_partial_cross_batch_and_membership_unchanged(db, context):
    ctx = context
    complete(db, ctx, 6)
    first, _ = ship(db, ctx)
    second, _ = ship(db, ctx, 3, "shipment-test-002")
    ships.confirm_received(db, first["id"], ShipmentReceive(received_date=date(2026, 10, 1)), ctx.worker.id)
    reviewer = _user(db, "receipt-reviewer"); db.commit()
    req = receipt(db, ctx, D("200"), [{"shipment_id": first["id"], "amount": 200}], "receipt-test-001")
    assert ships.paid_amount(db, first["id"]) == 0
    request_service.approve_request(db, req["id"], reviewer_id=reviewer.id, can_admin=False)
    assert ships.paid_amount(db, first["id"]) == 200
    req2 = receipt(db, ctx, D("400"), [{"shipment_id": first["id"], "amount": 100},
                                    {"shipment_id": second["id"], "amount": 300}], "receipt-test-002")
    request_service.approve_request(db, req2["id"], reviewer_id=reviewer.id, can_admin=False)
    customer = db.get(DomesticCustomer, req["customer_id"]); db.refresh(customer)
    assert customer.balance == D("-1400")
    assert customer.membership_level == "black"
    assert customer.last_recharge_amount is None
    assert ships.customer_summary(db, customer.id)["received_unpaid_amount"] == 0
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count() == 2
    with pytest.raises(ValueError, match="已审核"):
        request_service.approve_request(db, req2["id"], reviewer_id=reviewer.id, can_admin=False)


def test_pending_competing_receipts_recheck_at_approval(db, context):
    ctx = context; complete(db, ctx, 6); batch, _ = ship(db, ctx)
    reviewer = _user(db, "competing-reviewer"); db.commit()
    allocation = [{"shipment_id": batch["id"], "amount": 200}]
    first = receipt(db, ctx, D("200"), allocation, "competing-receipt-1")
    second = receipt(db, ctx, D("200"), allocation, "competing-receipt-2")
    request_service.approve_request(db, first["id"], reviewer_id=reviewer.id, can_admin=False)
    with pytest.raises(ValueError, match="超过批次未结"):
        request_service.approve_request(db, second["id"], reviewer_id=reviewer.id, can_admin=False)
    db.rollback()
    assert ships.paid_amount(db, batch["id"]) == 200
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count() == 1


def test_unallocated_receipt_later_allocation_idempotent(db, context):
    ctx = context; complete(db, ctx, 6); batch, _ = ship(db, ctx)
    reviewer = _user(db, "unallocated-reviewer"); db.commit()
    req = receipt(db, ctx, D("500"), [], "unallocated-receipt-001")
    request_service.approve_request(db, req["id"], reviewer_id=reviewer.id, can_admin=False)
    rows = [ReceiptAllocationInput(shipment_id=batch["id"], amount=D("300"))]
    receipt_service.allocate_approved_receipt(db, req["id"], rows, ctx.worker.id)
    receipt_service.allocate_approved_receipt(db, req["id"], rows, ctx.worker.id)
    assert ships.customer_summary(db, req["customer_id"])["unallocated_receipts"] == 200
    assert ships.paid_amount(db, batch["id"]) == 300
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count() == 1


def test_legacy_shipments_not_invented_and_scope(db, context):
    ctx = context
    ctx.item.status = 2; db.commit()
    order = db.get(DomesticOrder, ctx.item.order_id)
    assert ships.candidate_rows(db, order.customer_id, ctx.worker.id) == []
    assert ships.customer_summary(db, order.customer_id)["legacy_shipped_items"] == 1
    assert ships.customer_summary(db, order.customer_id)["received_unpaid_amount"] == 0
    stranger = _user(db, "ship-stranger"); db.commit()
    with pytest.raises(ValueError, match="本人创建"):
        ship_data = ShipmentCreate(customer_id=order.customer_id, ship_time=beijing_now(), request_id="other-user-ship", items=[{"item_id": ctx.item.id, "quantity": 1}])
        ships.create_shipment(db, ship_data, stranger.id)


def test_offset_time_beijing_day(monkeypatch):
    payload = ShipmentCreate(customer_id=1, ship_time="2026-10-01T16:10:00Z", request_id="timezone-shipment", items=[{"item_id": 1, "quantity": 1}])
    assert payload.ship_time == datetime(2026, 10, 2, 0, 10)
    monkeypatch.setenv("TZ", "America/New_York")
    assert ShipmentCreate(customer_id=1, ship_time="2026-10-02T00:10:00+08:00", request_id="timezone-shipment2", items=[{"item_id": 1, "quantity": 1}]).ship_time == payload.ship_time


def test_existing_receipt_can_append_to_same_batch_without_erasing_history(db, context):
    ctx = context; complete(db, ctx, 6); batch, _ = ship(db, ctx)
    reviewer = _user(db, "append-allocation-reviewer"); db.commit()
    req = receipt(db, ctx, D("300"), [{"shipment_id": batch["id"], "amount": 100}], "append-receipt-001")
    request_service.approve_request(db, req["id"], reviewer_id=reviewer.id, can_admin=False)
    target = [ReceiptAllocationInput(shipment_id=batch["id"], amount=D("300"))]
    receipt_service.allocate_approved_receipt(db, req["id"], target, ctx.worker.id)
    receipt_service.allocate_approved_receipt(db, req["id"], target, ctx.worker.id)
    from app.domestic.shipment_models import DomesticReceiptAllocation
    rows = db.query(DomesticReceiptAllocation).filter_by(request_id=req["id"]).order_by(DomesticReceiptAllocation.id).all()
    assert [r.amount for r in rows] == [D("100"), D("200")]
    assert all(r.ledger_id for r in rows)
    assert ships.paid_amount(db, batch["id"]) == D("300")
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count() == 1


def test_delivery_api_separates_owner_and_order_creator_scopes(db, context):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.domestic.shipment_router import router
    ctx = context; complete(db, ctx, 6); batch, _ = ship(db, ctx)
    customer = db.get(DomesticCustomer, batch["customer_id"])
    new_owner = _user(db, "new-delivery-owner")
    outsider = _user(db, "delivery-outsider")
    customer.owner_user_id = new_owner.id
    db.commit()
    identity = {"sub": str(ctx.worker.id), "roles": [], "permissions": ["domestic:read", "domestic:write"]}
    app = FastAPI(); app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app)
    response = client.get(f"/api/domestic/customers/{customer.id}/delivery")
    assert response.status_code == 200
    assert response.json()["data"]["scope"] == "own_orders"
    options = client.get("/api/domestic/delivery-customers").json()["data"]
    assert isinstance(options, list) and options[0]["id"] == customer.id
    identity["sub"] = str(outsider.id)
    assert client.get(f"/api/domestic/customers/{customer.id}/delivery").status_code == 404
    identity["sub"] = str(new_owner.id)
    assert client.get(f"/api/domestic/customers/{customer.id}/delivery").json()["data"]["scope"] == "customer"
    identity["permissions"].append("domestic:read_all")
    assert client.get(f"/api/domestic/shipment-candidates?customer_id={customer.id}").json()["data"] == []
    malicious = ShipmentCreate(customer_id=customer.id, ship_time=beijing_now(), request_id="read-all-not-write-all",
                               items=[{"item_id": ctx.item.id, "quantity": 1}])
    assert client.post("/api/domestic/shipments", json=malicious.model_dump(mode="json")).status_code == 400
    identity["permissions"] = ["domestic:recharge"]
    assert client.get(f"/api/domestic/customers/{customer.id}/delivery").status_code == 200
    assert client.get(f"/api/domestic/shipment-candidates?customer_id={customer.id}").status_code == 200


def test_one_batch_from_three_orders_preserves_price_and_guest_snapshots(db, context):
    from types import SimpleNamespace
    ctx = context; complete(db, ctx, 6)
    source = db.get(DomesticOrder, ctx.item.order_id)
    selected = [{"item_id": ctx.item.id, "quantity": 1}]
    for index, price in enumerate((D("75"), D("125")), start=2):
        order = DomesticOrder(domestic_no=f"DO-CROSS-{index}", order_no=f"cross-{index}", order_date=source.order_date,
                              customer_id=source.customer_id, order_category="normal", created_by=ctx.worker.id)
        db.add(order); db.flush()
        item = DomesticOrderItem(order_id=order.id, line_no=1, product_id=ctx.item.product_id,
                                guest_name=f"顾客{index}", product_name=ctx.item.product_name, route_id=ctx.item.route_id,
                                order_qty=3, unit_price=price, original_price=price, discount_amount=0,
                                pricing_rule="legacy_manual", pricing_version="test", base_price_version_snapshot=0)
        db.add(item); db.flush()
        from app.domestic import progress_service
        progress_service.init_item_progress(db, item); unit_service.ensure_item_units(db, item)
        balance_service.sync_order_finance(db, order, user_id=ctx.worker.id, reason="cross-order test")
        complete(db, SimpleNamespace(item=item, worker=ctx.worker), 3)
        selected.append({"item_id": item.id, "quantity": index-1})
    batch = ships.create_shipment(db, ShipmentCreate(customer_id=source.customer_id,
        ship_time=beijing_now(), request_id="cross-three-orders", items=selected), ctx.worker.id)
    assert batch["total_amount"] == 425
    assert len({row["domestic_no"] for row in batch["items"]}) == 3
    assert [row["guest_name"] for row in batch["items"]] == ["张女士", "顾客2", "顾客3"]


def test_shipment_current_read_rechecks_replay_before_finished_order_rejection(db, context, monkeypatch):
    """Simulate an initial old snapshot, then a committed batch after order-lock acquisition."""
    from sqlalchemy.orm import Query
    from app.domestic.shipment_models import DomesticShipment
    ctx = context; complete(db, ctx, 20)
    batch, payload = ship(db, ctx, 20)
    original = Query.first
    seen = False
    def stale_first(query):
        nonlocal seen
        entity = query.column_descriptions[0].get("entity")
        if entity is DomesticShipment and not seen:
            seen = True
            return None
        return original(query)
    monkeypatch.setattr(Query, "first", stale_first)
    replay = ships.create_shipment(db, payload, ctx.worker.id)
    assert replay["replayed"] and replay["id"] == batch["id"]
    assert db.query(DomesticShipmentUnit).count() == 20


@pytest.mark.parametrize("error_code,expected_attempts", [(1213, 2), (2006, 1)])
def test_only_explicit_deadlock_rollback_can_retry(db, context, monkeypatch, error_code, expected_attempts):
    from sqlalchemy.exc import OperationalError
    ctx = context; complete(db, ctx, 6)
    original = ships._create_shipment_once
    calls = 0
    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("test", {}, Exception(error_code, "simulated database error"))
        return original(*args)
    monkeypatch.setattr(ships, "_create_shipment_once", fail_once)
    if error_code == 1213:
        batch, _payload = ship(db, ctx)
        assert batch["total_amount"] == 300
        assert db.query(DomesticShipmentUnit).count() == 3
    else:
        with pytest.raises(OperationalError):
            ship(db, ctx)
        db.rollback()
        assert db.query(DomesticShipmentUnit).count() == 0
    assert calls == expected_attempts


def test_migration_preserves_existing_requests_and_matches_models():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.domestic import shipment_models
    path = Path(__file__).resolve().parents[1] / "alembic/versions/186_domestic_delivery.py"
    spec = importlib.util.spec_from_file_location("delivery_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for table in ("ark_users", "ark_domestic_customers", "ark_domestic_order_items",
                      "ark_domestic_item_units", "ark_domestic_customer_ledger"):
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE ark_domestic_customer_requests (id INTEGER PRIMARY KEY, request_type VARCHAR(16) NOT NULL, CONSTRAINT ck_dom_request_type CHECK (request_type IN ('recharge','adjust')))"))
        conn.execute(text("INSERT INTO ark_domestic_customer_requests VALUES (1, 'recharge')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.execute(text("SELECT request_type FROM ark_domestic_customer_requests WHERE id=1")).scalar() == "recharge"
        inspector = inspect(conn)
        for model in (shipment_models.DomesticShipment, shipment_models.DomesticShipmentLine,
                      shipment_models.DomesticShipmentUnit, shipment_models.DomesticReceiptAllocation):
            actual = {col["name"] for col in inspector.get_columns(model.__tablename__)}
            assert actual == set(model.__table__.columns.keys())
        conn.execute(text("INSERT INTO ark_domestic_customer_requests (id, request_type) VALUES (2, 'receipt')"))
    engine.dispose()
