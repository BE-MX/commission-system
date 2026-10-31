"""Exercise migration 228 and reservation contention in isolated MySQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier, Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import BigInteger, Column, MetaData, String, Table, event, select
from sqlalchemy.orm import Session

from app.invoice.models import Invoice, InvoiceItem
from app.inventory.models import StockBalance, StockReservation, Warehouse
from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.reservation_service import reserve_line, release_line, consume_line
from app.inventory.service import post_document
from tests.test_inventory_mysql import mysql_engine, stock_ids, body


@pytest.fixture
def orders(mysql_engine, stock_ids):
    # Structural prerequisite fixture, not a claim to replay the full application
    # migration history. Migration 228 itself runs unchanged with real MySQL DDL.
    previous = MetaData()
    Table("ark_customer_accounts", previous, Column("id", BigInteger, primary_key=True))
    added = {"transaction_mode", "commerce_status", "commerce_version", "local_customer_id", "local_sku_id",
             "stock_reserved_quantity", "stock_shipped_quantity"}
    for model in (Invoice, InvoiceItem):
        Table(model.__tablename__, previous, *[
            Column(col.name, String(128) if model is InvoiceItem and col.name == "model" else col.type, primary_key=col.primary_key,
                   autoincrement=col.autoincrement, nullable=col.nullable,
                   server_default=col.server_default)
            for col in model.__table__.columns if col.name not in added
        ])
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("CREATE INDEX idx_ark_invoice_items_invoice ON ark_invoice_items(invoice_id)")
        path = Path(__file__).parents[1] / "alembic/versions/228_invoice_stock_reservations.py"
        spec = spec_from_file_location("reservation_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        from tests.test_inventory_mysql import physical_scope_prerequisites
        physical_scope_prerequisites(conn)
    with Session(mysql_engine) as db:
        item_ids = []
        for index in range(2):
            invoice = Invoice(invoice_no=f"LOCAL-{index}", customer_id="legacy", customer_name="Buyer",
                              invoice_date=date(2026, 10, 3), transaction_mode="local", commerce_status="confirmed")
            db.add(invoice)
            db.flush()
            line = InvoiceItem(invoice_id=invoice.id, local_sku_id=stock_ids[1], quantity=10,
                               product_name="Hair", product_display="Hair", color="Black")
            db.add(line)
            db.flush()
            item_ids.append(line.id)
        post_document(db, body("opening", stock_ids, 10), actor_id=None)
        db.commit()
    return item_ids


def compete(engine, actions):
    gate = Barrier(len(actions))
    def run(action):
        with Session(engine) as db:
            gate.wait(timeout=10)
            try:
                doc = action(db)
                doc_id = doc.id
                db.commit()
                return "ok", doc_id
            except ValueError as exc:
                db.rollback()
                return "rejected", str(exc)
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_two_orders_cannot_reserve_the_same_stock(mysql_engine, stock_ids, orders):
    actions = [lambda db, item_id=item_id: reserve_line(db, item_id, stock_ids[2], 7,
                                                      f"reserve-{item_id}", None) for item_id in orders]
    results = compete(mysql_engine, actions)
    assert sorted(r[0] for r in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.reserved)) == 7
        assert sum(db.scalars(select(StockReservation.reserved))) == 7


def test_same_order_retry_then_release_vs_issue_is_atomic(mysql_engine, stock_ids, orders):
    action = lambda db: reserve_line(db, orders[0], stock_ids[2], 7, "same-command", None)
    results = compete(mysql_engine, [action, action])
    assert results[0] == results[1]
    assert results[0][0] == "ok"
    results = compete(mysql_engine, [
        lambda db: release_line(db, orders[0], stock_ids[2], 7, "release", "cancel", None),
        lambda db: consume_line(db, orders[0], stock_ids[2], 7, "issue", "shipment-1", None),
    ])
    assert sorted(r[0] for r in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        balance = db.scalar(select(StockBalance))
        reservation = db.scalar(select(StockReservation))
        assert balance.reserved == reservation.reserved == 0
        assert balance.on_hand + reservation.shipped == 10
        item = db.get(InvoiceItem, orders[0])
        assert item.stock_reserved_quantity == reservation.reserved
        assert item.stock_shipped_quantity == reservation.shipped


@pytest.mark.parametrize("empty_balances", [False, True])
def test_unrelated_empty_reservations_do_not_gap_lock(mysql_engine, stock_ids, orders, empty_balances):
    with Session(mysql_engine) as db:
        product = CatalogProduct(code="P2", name="Other", display_name="Other", kind="hair")
        db.add(product)
        db.flush()
        sku = CatalogSku(product_id=product.id, code="S2", unit="piece")
        warehouse = Warehouse(code="OTHER", name="Other")
        db.add_all([sku, warehouse])
        db.flush()
        other = (product.id, sku.id, warehouse.id)
        db.get(InvoiceItem, orders[1]).local_sku_id = sku.id
        if empty_balances:
            first_warehouse = Warehouse(code="EMPTY", name="Empty")
            db.add(first_warehouse)
            db.flush()
            first_warehouse_id = first_warehouse.id
        else:
            first_warehouse_id = stock_ids[2]
            post_document(db, body("receive-other", other, 10), actor_id=None)
        db.commit()
    # Force both transactions to attempt the outer policy mutex together.
    # Once it is held, a barrier at an inner reservation read would deadlock
    # the harness itself. Keep the final no-gap-deadlock and quantity checks.
    gate = Barrier(2)
    def barrier_after_read(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ark_commerce_transition_policy") and not conn.info.get("race_gate_seen"):
            conn.info["race_gate_seen"] = True
            gate.wait(timeout=10)
    # Both commands contend at the current outer policy mutex; inner reads
    # deliberately cannot run simultaneously while that mutex is held.
    event.listen(mysql_engine, "before_cursor_execute", barrier_after_read)
    try:
        results = compete(mysql_engine, [
            lambda db: reserve_line(db, orders[0], first_warehouse_id, 3, "first", None),
            lambda db: reserve_line(db, orders[1], other[2], 3, "second", None),
        ])
    finally:
        event.remove(mysql_engine, "before_cursor_execute", barrier_after_read)
    assert all(result[0] == ("rejected" if empty_balances else "ok") for result in results)
    with Session(mysql_engine) as db:
        expected = 0 if empty_balances else 6
        assert sum(db.scalars(select(StockReservation.reserved))) == expected
        assert sum(db.scalars(select(InvoiceItem.stock_reserved_quantity))) == expected


def test_same_order_cross_warehouse_cap_serializes_at_policy(mysql_engine, stock_ids, orders):
    with Session(mysql_engine) as db:
        warehouse = Warehouse(code="OTHER", name="Other")
        db.add(warehouse)
        db.flush()
        other = (stock_ids[0], stock_ids[1], warehouse.id)
        post_document(db, body("receive-other", other, 10), actor_id=None)
        db.commit()
    gate = Barrier(2)
    def synchronize_policy_attempt(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ark_commerce_transition_policy") and not conn.info.get("race_gate_seen"):
            conn.info["race_gate_seen"] = True
            gate.wait(timeout=10)
    event.listen(mysql_engine, "before_cursor_execute", synchronize_policy_attempt)
    try:
        results = compete(mysql_engine, [
            lambda db: reserve_line(db, orders[0], stock_ids[2], 7, "first", None),
            lambda db: reserve_line(db, orders[0], other[2], 7, "second", None),
        ])
    finally:
        event.remove(mysql_engine, "before_cursor_execute", synchronize_policy_attempt)
    assert sorted(result[0] for result in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(InvoiceItem, orders[0]).stock_reserved_quantity == 7
        assert sum(db.scalars(select(StockReservation.reserved))) == 7


def test_order_loader_rejects_mixed_versions_after_existing_snapshot(mysql_engine, stock_ids, orders):
    from app.invoice.commerce_service import _get
    with Session(mysql_engine) as stale:
        item = stale.get(InvoiceItem, orders[0])
        assert item.quantity == 10
        invoice_id = item.invoice_id
        with Session(mysql_engine) as writer:
            writer.get(InvoiceItem, orders[0]).quantity = 6
            writer.get(Invoice, invoice_id).commerce_version = 2
            writer.commit()
        with pytest.raises(ValueError, match="刷新"):
            _get(stale, invoice_id, {"sub": "1", "roles": ["super_admin"]})
        stale.rollback()
        invoice = _get(stale, invoice_id, {"sub": "1", "roles": ["super_admin"]})
        assert invoice.commerce_version == 2
        assert invoice.items[0].quantity == 6


def test_migration_preserves_full_catalog_model_snapshot(mysql_engine, stock_ids, orders):
    with Session(mysql_engine) as db:
        product = db.get(CatalogProduct, stock_ids[0])
        product.model = "M" * 200
        item = db.get(InvoiceItem, orders[0])
        item.model = product.model
        db.commit()
        db.expire_all()
        assert db.get(InvoiceItem, orders[0]).model == "M" * 200


def test_cancel_and_other_order_first_reservation_share_lock_order(mysql_engine, stock_ids, orders):
    from app.invoice.commerce_schemas import LocalInvoiceAction
    from app.invoice.commerce_service import cancel
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO ark_users (id) VALUES (1)")
        conn.exec_driver_sql("CREATE TABLE ark_receipts (id BIGINT PRIMARY KEY, invoice_id BIGINT, status VARCHAR(16))")
        conn.exec_driver_sql("CREATE TABLE ark_shipment_settlements (id BIGINT PRIMARY KEY, invoice_id BIGINT, state VARCHAR(32))")
    with Session(mysql_engine) as db:
        reserve_line(db, orders[0], stock_ids[2], 3, "reserve-first", None)
        invoice_id = db.get(InvoiceItem, orders[0]).invoice_id
        db.commit()
    policy_held, allow_reserve = Event(), Event()
    def before_execute(conn, cursor, statement, parameters, context, many):
        if conn.info.get("race_command") == "cancel" and statement.startswith("UPDATE ark_commerce_transition_policy"):
            allow_reserve.set()
    def after_execute(conn, cursor, statement, parameters, context, many):
        if conn.info.get("race_command") == "reserve" and statement.startswith("UPDATE ark_commerce_transition_policy"):
            policy_held.set()
            assert allow_reserve.wait(10)
    def run(kind):
        if kind == "cancel":
            assert policy_held.wait(10)
        with Session(mysql_engine) as db:
            info = db.connection().info
            info["race_command"] = kind
            try:
                if kind == "cancel":
                    cancel(db, invoice_id, LocalInvoiceAction(request_key="cancel", expected_version=0, reason="test"),
                           {"sub": "1", "roles": ["super_admin"]})
                else:
                    reserve_line(db, orders[1], stock_ids[2], 3, "reserve-other", None)
                db.commit()
                return "ok"
            finally:
                info.pop("race_command", None)
    event.listen(mysql_engine, "before_cursor_execute", before_execute)
    event.listen(mysql_engine, "after_cursor_execute", after_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reserved = pool.submit(run, "reserve")
            cancelled = pool.submit(run, "cancel")
            assert reserved.result() == cancelled.result() == "ok"
    finally:
        event.remove(mysql_engine, "before_cursor_execute", before_execute)
        event.remove(mysql_engine, "after_cursor_execute", after_execute)
    with Session(mysql_engine) as db:
        assert db.get(Invoice, invoice_id).commerce_status == "cancelled"
        assert db.scalar(select(StockBalance.reserved)) == 3
        assert sum(db.scalars(select(InvoiceItem.stock_reserved_quantity))) == 3


def test_cancel_retries_if_snapshot_missed_a_reserved_warehouse(mysql_engine, stock_ids, orders):
    from app.invoice.commerce_schemas import LocalInvoiceAction
    from app.invoice.commerce_service import cancel
    from app.invoice.models import InvoiceCommerceEvent
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO ark_users (id) VALUES (1)")
        conn.exec_driver_sql("CREATE TABLE ark_receipts (id BIGINT PRIMARY KEY, invoice_id BIGINT, status VARCHAR(16))")
        conn.exec_driver_sql("CREATE TABLE ark_shipment_settlements (id BIGINT PRIMARY KEY, invoice_id BIGINT, state VARCHAR(32))")
    with Session(mysql_engine) as stale:
        invoice_id = stale.get(InvoiceItem, orders[0]).invoice_id
        assert not stale.scalars(select(StockReservation)).all()
        with Session(mysql_engine) as writer:
            reserve_line(writer, orders[0], stock_ids[2], 3, "new-reserve", None)
            writer.commit()
        command = LocalInvoiceAction(request_key="cancel", expected_version=0, reason="test")
        user = {"sub": "1", "roles": ["super_admin"]}
        with pytest.raises(ValueError, match="仓库责任已变化"):
            cancel(stale, invoice_id, command, user)
        stale.rollback()
        assert stale.scalar(select(InvoiceCommerceEvent.id)) is None
        assert stale.get(Invoice, invoice_id).commerce_status == "confirmed"
        assert stale.scalar(select(StockBalance.reserved)) == 3
        cancel(stale, invoice_id, command, user)
        stale.commit()
        assert stale.get(Invoice, invoice_id).commerce_status == "cancelled"
        assert stale.scalar(select(StockBalance.reserved)) == 0
