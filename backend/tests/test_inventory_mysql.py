"""Real MySQL RR races; opt-in URL must be loopback and contain no database.

Each test owns a fresh random schema, applies the actual stock migration, and
drops only that schema. The application database is never used by this fixture.
"""

from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockBalance, StockDocument, StockLedger, Warehouse
from app.inventory.schemas import DocumentCreate, MovementLine
from app.inventory.service import post_document


class MySQLTestSettings(BaseSettings):
    COMMERCE_TEST_MYSQL_URL: str = ""


def isolated_mysql_url(raw):
    url = make_url(raw)
    if url.drivername != "mysql+pymysql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.database or url.query:
        pytest.fail("COMMERCE_TEST_MYSQL_URL must use mysql+pymysql on loopback, with no database or query overrides")
    return url


@pytest.fixture
def mysql_engine():
    raw = MySQLTestSettings().COMMERCE_TEST_MYSQL_URL
    if not raw:
        pytest.skip("requires isolated loopback COMMERCE_TEST_MYSQL_URL")
    url = isolated_mysql_url(raw)
    schema = "ark_inventory_test_" + uuid4().hex[:16]
    control = create_engine(url, hide_parameters=True)
    with control.begin() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    engine = create_engine(url.set(database=schema), isolation_level="REPEATABLE READ", hide_parameters=True)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE ark_users (id INT UNSIGNED PRIMARY KEY)")
            migration_path = Path(__file__).parents[1] / "alembic/versions/227_local_commerce.py"
            spec = spec_from_file_location("stock_migration", migration_path)
            migration = module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        # Narrow primitive fixture: the inventory DDL is exercised above.
        # Current commands additionally require real persistent coordination;
        # this empty schema explicitly represents a completed local-only pilot.
        from app.commerce_transition.models import PlatformPolicy, WriterReceipt, ResourceScope, BankAccountDomain, BankIdentity
        with engine.begin() as conn:
            for model in (PlatformPolicy, WriterReceipt, ResourceScope, BankAccountDomain, BankIdentity):
                model.__table__.create(conn)
            conn.execute(PlatformPolicy.__table__.insert().values(id=1, phase="local_only",
                writer_inventory_verified=True, inventory_evidence={"synthetic_empty_schema": schema}))
            conn.execute(WriterReceipt.__table__.insert().values(writer_key="mysql-isolated-fixture",
                protocol_version=1, status="compatible", evidence={"synthetic_empty_schema": schema}))
        yield engine
    finally:
        engine.dispose()
        with control.begin() as conn:
            conn.exec_driver_sql(f"DROP DATABASE `{schema}`")
        control.dispose()


def physical_scope_prerequisites(connection):
    """Empty current read-side tables for old focused physical DDL fixtures.

    This is a structural prerequisite, not migration evidence. Full-chain tests
    separately verify their real DDL, constraints and historical preservation.
    """
    from sqlalchemy import Column, MetaData, Table, UniqueConstraint
    from app.invoice.models import Invoice, InvoiceItemGroup, OkkiOutboundTask
    from app.commerce_transition.models import InvoiceAuthority, AuthorityEvent, SendingClaim
    from app.shipping_inspection.models import ShippingOperationEvent
    from app.semifinished.models import InvoiceAllocation
    metadata = MetaData()
    for model in (Invoice, InvoiceItemGroup, InvoiceAuthority, AuthorityEvent, SendingClaim,
                  OkkiOutboundTask, ShippingOperationEvent, InvoiceAllocation):
        source = model.__table__
        table = Table(source.name, metadata, *[
            Column(col.name, col.type, primary_key=col.primary_key, autoincrement=col.autoincrement,
                   nullable=col.nullable, server_default=col.server_default) for col in source.columns])
        for constraint in source.constraints:
            if isinstance(constraint, UniqueConstraint):
                table.append_constraint(UniqueConstraint(*[col.name for col in constraint.columns], name=constraint.name))
    metadata.create_all(connection)


@pytest.fixture
def stock_ids(mysql_engine):
    with Session(mysql_engine) as db:
        product = CatalogProduct(code="P1", name="Hair", display_name="Hair", kind="hair")
        db.add(product)
        db.flush()
        sku = CatalogSku(product_id=product.id, code="S1", unit="piece")
        wh = Warehouse(code="MAIN", name="Main")
        db.add_all([sku, wh])
        db.flush()
        ids = (product.id, sku.id, wh.id)
        db.commit()
        return ids


def body(key, ids, qty, kind="receipt"):
    return DocumentCreate(idempotency_key=key, kind=kind, reason="concurrency", lines=[
        MovementLine(sku_id=ids[1], warehouse_id=ids[2], quantity=qty)
    ])


def race(engine, commands):
    gate = Barrier(len(commands))
    def worker(command):
        with Session(engine) as db:
            gate.wait(timeout=10)
            try:
                result = post_document(db, command, actor_id=None)
                doc_id = result.id
                db.commit()
                return ("ok", doc_id)
            except ValueError as exc:
                db.rollback()
                return ("rejected", str(exc))
    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        return list(pool.map(worker, commands))


def test_same_key_first_writers_post_once(mysql_engine, stock_ids):
    results = race(mysql_engine, [body("same", stock_ids, 10)] * 2)
    assert results[0] == results[1]
    assert results[0][0] == "ok"
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 10
        assert db.scalar(select(func.count()).select_from(StockDocument)) == 1
        assert db.scalar(select(func.count()).select_from(StockLedger)) == 1


def test_same_key_different_payload_rejected(mysql_engine, stock_ids):
    results = race(mysql_engine, [body("same", stock_ids, qty) for qty in (10, 11)])
    assert sorted(r[0] for r in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) in {10, 11}
        assert db.scalar(select(func.count()).select_from(StockLedger)) == 1


def test_different_keys_first_bucket_no_lost_receipt(mysql_engine, stock_ids):
    results = race(mysql_engine, [body(key, stock_ids, 10) for key in ("first", "second")])
    assert all(r[0] == "ok" for r in results)
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 20
        assert db.scalar(select(func.count()).select_from(StockBalance)) == 1
        assert db.scalar(select(func.sum(StockLedger.on_hand_delta))) == 20


def test_competing_issues_do_not_oversell(mysql_engine, stock_ids):
    with Session(mysql_engine) as db:
        post_document(db, body("opening", stock_ids, 10), actor_id=None)
        db.commit()
    results = race(mysql_engine, [body(key, stock_ids, -7, "adjustment") for key in ("issue1", "issue2")])
    assert sorted(r[0] for r in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 3
        assert db.scalar(select(func.count()).select_from(StockDocument)) == 2
        assert db.scalar(select(func.sum(StockLedger.on_hand_delta))) == 3


def test_stale_product_snapshot_cannot_bypass_deactivation(mysql_engine, stock_ids):
    with Session(mysql_engine) as stale:
        cached = stale.get(CatalogProduct, stock_ids[0])
        assert cached.active
        with Session(mysql_engine) as other:
            product = other.get(CatalogProduct, stock_ids[0])
            product.active = False
            other.commit()
        with pytest.raises(ValueError, match="停用"):
            post_document(stale, body("disabled", stock_ids, 10), actor_id=None)
        assert not cached.active
        assert stale.scalar(select(func.count()).select_from(StockDocument)) == 0


def test_unrelated_first_receipts_cannot_deadlock_on_empty_balance_gap(mysql_engine, stock_ids):
    with Session(mysql_engine) as db:
        product = CatalogProduct(code="P2", name="Other", display_name="Other", kind="hair")
        db.add(product)
        db.flush()
        sku = CatalogSku(product_id=product.id, code="S2", unit="piece")
        wh = Warehouse(code="OTHER", name="Other")
        db.add_all([sku, wh])
        db.flush()
        other = product.id, sku.id, wh.id
        db.commit()
    gate = Barrier(2)
    def synchronize_empty_read(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ark_commerce_transition_policy") and not conn.info.get("race_gate_seen"):
            conn.info["race_gate_seen"] = True
            gate.wait(timeout=10)
    # All writers now serialize at the policy row before bucket discovery.
    event.listen(mysql_engine, "before_cursor_execute", synchronize_empty_read)
    try:
        results = race(mysql_engine, [body("first", stock_ids, 5), body("second", other, 7)])
    finally:
        event.remove(mysql_engine, "before_cursor_execute", synchronize_empty_read)
    assert all(result[0] == "ok" for result in results)
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.sum(StockBalance.on_hand))) == 12
        assert db.scalar(select(func.sum(StockLedger.on_hand_delta))) == 12
