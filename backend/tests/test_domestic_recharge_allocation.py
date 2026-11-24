"""Recharge allocation reconciles delivery without creating a second cash movement."""
from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import balance_service, request_service, receipt_service
from app.domestic import shipment_service as ships
from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticCustomerRequest, DomesticOrder
from app.domestic.shipment_models import DomesticReceiptAllocation
from app.domestic.shipment_schemas import ReceiptAllocationInput
from app.domestic.shipment_router import router
from tests.test_domestic_conditional_routing import conditional_route, conditional_order
from tests.test_domestic_delivery import context, complete, ship, receipt
from tests.test_domestic_review_flow import _user


def recharge(db, ctx, amount="500", transaction_type="recharge", customer_id=None):
    ledger = balance_service.apply_balance_change(
        db, customer_id=customer_id or db.get(DomesticOrder, ctx.item.order_id).customer_id,
        amount=D(amount), transaction_type=transaction_type, user_id=ctx.worker.id,
    )
    db.commit()
    return ledger


def allocate(db, ctx, ledger, rows, customer_id=None, user_id=None):
    from app.domestic.recharge_allocation_service import allocate_recharge
    return allocate_recharge(db, customer_id or ledger.customer_id, ledger.id,
        [ReceiptAllocationInput(shipment_id=s, amount=D(str(a))) for s, a in rows],
        user_id or ctx.worker.id)


def client_for(db, user_id, permissions=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user_id), "roles": [], "permissions": permissions or ["domestic:read", "domestic:recharge"],
    }
    return TestClient(app)


def test_legacy_recharge_cross_batch_replay_preserves_cash_and_membership(db, context):
    ctx = context; complete(db, ctx, 6)
    first, _ = ship(db, ctx)
    second, _ = ship(db, ctx, 3, "recharge-second-batch")
    ledger = recharge(db, ctx)
    customer = db.get(DomesticCustomer, ledger.customer_id)
    customer.last_recharge_amount = D("888")
    db.commit()
    before = (customer.balance, customer.membership_level, customer.last_recharge_amount)
    count = db.query(DomesticCustomerLedger).count()
    assert db.query(DomesticCustomerRequest).count() == 0  # Historical ledger has no approval row.
    allocate(db, ctx, ledger, [(first["id"], 100)])
    allocate(db, ctx, ledger, [(first["id"], 200), (second["id"], 150)])
    row_count = db.query(DomesticReceiptAllocation).count()
    allocate(db, ctx, ledger, [(first["id"], 200), (second["id"], 150)])
    assert db.query(DomesticReceiptAllocation).count() == row_count == 3
    assert ships.paid_amount(db, first["id"]) == 200
    assert ships.paid_amount(db, second["id"]) == 150
    assert all(r.request_id is None and r.ledger_id == ledger.id for r in db.query(DomesticReceiptAllocation))
    db.refresh(customer)
    assert (customer.balance, customer.membership_level, customer.last_recharge_amount) == before
    assert db.query(DomesticCustomerLedger).count() == count
    with client_for(db, ctx.worker.id) as client:
        data = client.get(f"/api/domestic/customers/{customer.id}/delivery").json()["data"]
    row = data["recharges"][0]
    assert row["id"] == ledger.id and row["created_at"]
    assert (row["amount"], row["allocated_amount"], row["unallocated_amount"]) == (500, 350, 150)
    assert len(row["allocations"]) == 2
    assert data["summary"]["account_balance"] == float(before[0])
    assert data["summary"]["unallocated_recharges"] == 150
    assert data["summary"]["transit_unpaid_amount"] == 250


def test_recharge_and_receipt_share_batch_capacity_and_keep_receipt_workflow(db, context):
    ctx = context; complete(db, ctx, 6)
    first, _ = ship(db, ctx)
    second, _ = ship(db, ctx, 3, "receipt-and-recharge-batch")
    ledger = recharge(db, ctx, "500")
    pending = receipt(db, ctx, D("200"), [{"shipment_id": first["id"], "amount": 200}], "receipt-before-recharge")
    allocate(db, ctx, ledger, [(first["id"], 150)])
    reviewer = _user(db, "recharge-receipt-reviewer"); db.commit()
    with pytest.raises(ValueError, match="超过批次未结"):
        request_service.approve_request(db, pending["id"], reviewer_id=reviewer.id, can_admin=False)
    db.rollback()
    valid = receipt(db, ctx, D("250"), [{"shipment_id": first["id"], "amount": 150}], "receipt-after-recharge")
    request_service.approve_request(db, valid["id"], reviewer_id=reviewer.id, can_admin=False)
    receipt_service.allocate_approved_receipt(db, valid["id"], [ReceiptAllocationInput(shipment_id=second["id"], amount=100)], ctx.worker.id)
    assert ships.paid_amount(db, first["id"]) == 300
    assert ships.paid_amount(db, second["id"]) == 100
    with pytest.raises(ValueError, match="超过批次未结"):
        allocate(db, ctx, ledger, [(second["id"], 201)])
    db.rollback()
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count() == 1


@pytest.mark.parametrize("rows", [[(0, 301)], [(0, 200), (1, 101)]])
def test_recharge_rejects_batch_or_source_overallocation_atomically(db, context, rows):
    ctx = context; complete(db, ctx, 6)
    batches = [ship(db, ctx)[0], ship(db, ctx, 3, "overallocate-second-batch")[0]]
    ledger = recharge(db, ctx, "300")
    with pytest.raises(ValueError):
        allocate(db, ctx, ledger, [(batches[i]["id"], amount) for i, amount in rows])
    db.rollback()
    assert db.query(DomesticReceiptAllocation).count() == 0


def test_cumulative_recharge_rechecks_prior_allocation_and_rejects_decrease(db, context):
    ctx = context; complete(db, ctx, 6)
    first, _ = ship(db, ctx)
    second, _ = ship(db, ctx, 3, "cumulative-second-batch")
    ledger = recharge(db, ctx, "300")
    allocate(db, ctx, ledger, [(first["id"], 200)])
    with pytest.raises(ValueError):
        allocate(db, ctx, ledger, [(second["id"], 101)])
    db.rollback()
    with pytest.raises(ValueError):
        allocate(db, ctx, ledger, [(first["id"], 199)])
    db.rollback()
    allocate(db, ctx, ledger, [(second["id"], 100)])
    assert ships.paid_amount(db, first["id"]) == 200
    assert ships.paid_amount(db, second["id"]) == 100


def test_cancelled_batch_rejected_and_allocated_batch_cannot_cancel(db, context):
    ctx = context; complete(db, ctx, 6)
    cancelled, _ = ship(db, ctx)
    ships.cancel_shipment(db, cancelled["id"], ctx.worker.id)
    ledger = recharge(db, ctx)
    with pytest.raises(ValueError, match="取消"):
        allocate(db, ctx, ledger, [(cancelled["id"], 100)])
    db.rollback()
    active, _ = ship(db, ctx, 3, "allocated-not-cancellable")
    allocate(db, ctx, ledger, [(active["id"], 100)])
    with pytest.raises(ValueError):
        ships.cancel_shipment(db, active["id"], ctx.worker.id)
    db.rollback()
    assert ships.paid_amount(db, active["id"]) == 100


@pytest.mark.parametrize("kind,amount", [("receipt", "100"), ("order_refund", "100"), ("recharge", "-100")])
def test_only_positive_recharge_ledger_is_a_source(db, context, kind, amount):
    ctx = context; complete(db, ctx, 3); batch, _ = ship(db, ctx)
    ledger = recharge(db, ctx, amount, kind)
    with pytest.raises(ValueError):
        allocate(db, ctx, ledger, [(batch["id"], 50)])
    db.rollback()
    assert db.query(DomesticReceiptAllocation).count() == 0


def test_customer_boundary_and_own_order_reader_cannot_access_recharge(db, context):
    ctx = context; complete(db, ctx, 3); batch, _ = ship(db, ctx)
    ledger = recharge(db, ctx)
    stranger = _user(db, "recharge-outsider")
    other = DomesticCustomer(shop_name="Other recharge customer", owner_user_id=ctx.worker.id,
        created_by=ctx.worker.id, settle_mode="credit")
    db.add(other); db.commit()
    other_ledger = recharge(db, ctx, "500", customer_id=other.id)
    with pytest.raises(ValueError):
        allocate(db, ctx, other_ledger, [(batch["id"], 50)])
    db.rollback()
    with pytest.raises(ValueError):
        allocate(db, ctx, ledger, [(batch["id"], 50)], customer_id=other.id)
    db.rollback()
    customer = db.get(DomesticCustomer, ledger.customer_id)
    customer.owner_user_id = stranger.id  # Worker retains own-order scope only.
    db.commit()
    with client_for(db, ctx.worker.id) as client:
        data = client.get(f"/api/domestic/customers/{customer.id}/delivery").json()["data"]
        assert data["scope"] == "own_orders"
        assert not data["recharges"]
        assert data["summary"].get("account_balance") is None
        assert data["summary"].get("unallocated_recharges") is None
        response = client.post(f"/api/domestic/customers/{customer.id}/recharges/{ledger.id}/allocate",
            json=[{"shipment_id": batch["id"], "amount": 50}])
        assert response.status_code in (400, 403, 404)
    assert db.query(DomesticReceiptAllocation).count() == 0


@pytest.mark.parametrize("body", [[], [{"shipment_id": 1, "amount": 1}] * 2,
    [{"shipment_id": 1, "amount": 0}], [{"shipment_id": 1, "amount": "1.001"}]])
def test_recharge_route_validates_allocation_list(db, context, body):
    ledger = recharge(db, context)
    with client_for(db, context.worker.id) as client:
        response = client.post(f"/api/domestic/customers/{ledger.customer_id}/recharges/{ledger.id}/allocate", json=body)
    assert response.status_code in (400, 422)


def test_recharge_allocate_requires_fund_permission(db, context):
    ledger = recharge(db, context)
    with client_for(db, context.worker.id, ["domestic:read"]) as client:
        response = client.post(f"/api/domestic/customers/{ledger.customer_id}/recharges/{ledger.id}/allocate",
            json=[{"shipment_id": 1, "amount": 1}])
    assert response.status_code == 403


def test_recharge_route_returns_cumulative_allocations_and_replays(db, context):
    ctx = context; complete(db, ctx, 3); batch, _ = ship(db, ctx)
    ledger = recharge(db, ctx)
    path = f"/api/domestic/customers/{ledger.customer_id}/recharges/{ledger.id}/allocate"
    with client_for(db, ctx.worker.id) as client:
        for amount in (100, 250, 250):
            response = client.post(path, json=[{"shipment_id": batch["id"], "amount": amount}])
            assert response.status_code == 200
            allocations = response.json()["data"]
            assert len(allocations) == 1
            assert allocations[0]["shipment_id"] == batch["id"]
            assert allocations[0]["amount"] == amount
    assert db.query(DomesticReceiptAllocation).count() == 2


def test_recharge_migration_preserves_receipts_and_refuses_lossy_downgrade():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.exc import IntegrityError
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/280_domestic_recharge_allocate.py"
    spec = importlib.util.spec_from_file_location("recharge_allocation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ark_domestic_receipt_allocations (id INTEGER PRIMARY KEY, request_id BIGINT NOT NULL, ledger_id BIGINT, amount NUMERIC(14,2) NOT NULL)"))
        conn.execute(text("INSERT INTO ark_domestic_receipt_allocations VALUES (1, 11, 21, 80)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text("SELECT * FROM ark_domestic_receipt_allocations WHERE id=1")).one() == (1, 11, 21, 80)
            assert next(c for c in inspect(conn).get_columns("ark_domestic_receipt_allocations") if c["name"] == "request_id")["nullable"]
            conn.execute(text("INSERT INTO ark_domestic_receipt_allocations VALUES (2, NULL, 22, 50)"))
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO ark_domestic_receipt_allocations VALUES (3, NULL, NULL, 20)"))
            with pytest.raises(RuntimeError, match="Recharge allocations exist"):
                migration.downgrade()
            assert conn.execute(text("SELECT amount FROM ark_domestic_receipt_allocations WHERE id=2")).scalar() == 50
            conn.execute(text("DELETE FROM ark_domestic_receipt_allocations WHERE id=2"))
            migration.downgrade()
            assert not next(c for c in inspect(conn).get_columns("ark_domestic_receipt_allocations") if c["name"] == "request_id")["nullable"]
    engine.dispose()
