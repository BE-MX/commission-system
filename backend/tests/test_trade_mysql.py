"""Actual trade DDL and native roster races in isolated MySQL RR schemas."""
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select
from sqlalchemy.schema import CreateColumn
from sqlalchemy.orm import Session, lazyload
from app.auth.models import ArkUser
from app.trade.models import SalesRoster
from app.trade.schemas import RosterWrite
from app.trade.roster_service import write_roster
from tests.test_inventory_mysql import mysql_engine


@pytest.fixture
def trade_tables(mysql_engine):
    # Minimal prerequisites exercise 183's DDL; the full migration-chain
    # acceptance remains separate from these focused concurrency tests.
    with mysql_engine.begin() as conn:
        for column in ArkUser.__table__.columns:
            if column.name != "id":
                conn.exec_driver_sql("ALTER TABLE ark_users ADD COLUMN " + str(CreateColumn(column).compile(dialect=conn.dialect)))
        conn.exec_driver_sql("CREATE TABLE ark_invoices (id BIGINT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE ark_invoice_items (id BIGINT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE ark_customer_orders (id BIGINT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE ark_customer_order_items (id BIGINT PRIMARY KEY, product_name VARCHAR(255), model VARCHAR(128), length VARCHAR(64))")
        spec = spec_from_file_location("trade_migration", Path(__file__).parents[1] / "alembic/versions/217_local_trade_projection.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE sys_dict (id INT PRIMARY KEY)")
        spec = spec_from_file_location("department_migration", Path(__file__).parents[1] / "alembic/versions/219_local_sales_department.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with Session(mysql_engine) as db:
        db.add(ArkUser(id=1, username="native", real_name="Native", password_hash="unused", is_active=True))
        db.commit()


def test_trade_migration_and_first_writer_race(mysql_engine, trade_tables):
    columns = {row["name"]: row for row in inspect(mysql_engine).get_columns("ark_customer_order_items")}
    assert columns["product_name"]["type"].length == 512
    assert columns["model"]["type"].length == 200
    gate = Barrier(2)
    def write(team):
        with Session(mysql_engine) as db:
            gate.wait(timeout=10)
            try:
                write_roster(db, 1, RosterWrite(expected_version=0, team=team), {"sub": "1"})
                db.commit()
                return "ok"
            except ValueError:
                db.rollback()
                return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["A", "B"])) == ["ok", "stale"]
    with Session(mysql_engine) as db:
        assert db.get(SalesRoster, 1).version == 1


def test_roster_current_read_rejects_old_rr_version_and_disabled_employee(mysql_engine, trade_tables):
    with Session(mysql_engine) as stale:
        # Establish both the repeatable-read snapshot and old identity-map user.
        employee = stale.scalar(select(ArkUser).options(lazyload(ArkUser.roles)))
        assert employee.is_active
        assert stale.scalar(select(SalesRoster)) is None
        with Session(mysql_engine) as writer:
            write_roster(writer, 1, RosterWrite(expected_version=0, team="current"), {"sub": "1"})
            writer.commit()
        with pytest.raises(ValueError, match="刷新"):
            write_roster(stale, 1, RosterWrite(expected_version=0), {"sub": "1"})
        stale.rollback()
        employee = stale.scalar(select(ArkUser).options(lazyload(ArkUser.roles)))
        with mysql_engine.begin() as conn:
            conn.exec_driver_sql("UPDATE ark_users SET is_active=0 WHERE id=1")
        with pytest.raises(ValueError, match="停用"):
            write_roster(stale, 1, RosterWrite(expected_version=1), {"sub": "1"})
        stale.rollback()


@pytest.fixture
def projection_tables(mysql_engine):
    # Runtime concurrency fixture; migration-chain acceptance is separate.
    # Keep all model columns/unique keys, omitting unrelated external FKs.
    from sqlalchemy import Column, MetaData, Table, UniqueConstraint
    from app.core.database import Base
    from app.trade import projection_service  # noqa: F401
    metadata = MetaData()
    prefixes = ("ark_customer_", "ark_invoice", "ark_finance_", "ark_aftersales_", "ark_trade_", "ark_receivables")
    for source in list(Base.metadata.tables.values()):
        if source.name.startswith(prefixes):
            table = Table(source.name, metadata, *[
                Column(col.name, col.type, primary_key=col.primary_key, autoincrement=col.autoincrement,
                       nullable=col.nullable, server_default=col.server_default)
                for col in source.columns])
            for constraint in source.constraints:
                if isinstance(constraint, UniqueConstraint):
                    table.append_constraint(UniqueConstraint(*[col.name for col in constraint.columns], name=constraint.name))
    metadata.create_all(mysql_engine)


def test_projector_rejects_rr_and_rc_preserves_other_committed_order(mysql_engine, projection_tables):
    from datetime import date
    from app.customer.models import CustomerAccount, CustomerOrder
    from app.invoice.models import Invoice, InvoiceItem
    from app.trade.projection_service import project_invoice
    from app.trade.refresh_service import projection_status
    from tests.test_customer_facts import _customer
    with Session(mysql_engine) as db:
        customer = _customer(db, "native-mysql")
        customer.relationship_stage = "developing"
        customer_id = customer.id
        ids = []
        for number in range(2):
            invoice = Invoice(invoice_no=f"MYSQL-TRADE-{number}", customer_id="local", customer_name="Native",
                invoice_date=date(2026, 10, 3), transaction_mode="local", commerce_status="confirmed",
                local_customer_id=customer_id, local_rate_to_usd=1, local_commercial={}, currency="USD",
                total_amount=100, surcharge_amount=0)
            db.add(invoice)
            db.flush()
            db.add(InvoiceItem(invoice_id=invoice.id, product_name="Hair", product_display="Hair", color="Black",
                quantity=1, price_per_piece=100, total_price=100, commercial_kind="bulk"))
            ids.append(invoice.id)
        db.commit()
    with Session(mysql_engine) as stale:
        assert stale.scalar(select(CustomerOrder)) is None
        with pytest.raises(ValueError, match="READ COMMITTED"):
            project_invoice(stale, ids[0])
    rc = mysql_engine.execution_options(isolation_level="READ COMMITTED")
    with Session(rc) as reader:
        # Establish a view before another transaction projects the second order.
        assert reader.scalar(select(CustomerOrder)) is None
        with Session(rc) as writer:
            project_invoice(writer, ids[1])
            writer.commit()
        project_invoice(reader, ids[0])
        reader.commit()
        assert len(reader.scalars(select(CustomerOrder)).all()) == 2
        invoice = reader.get(Invoice, ids[0])
        invoice.commerce_status = "cancelled"
        invoice.commerce_version += 1
        reader.flush()
        project_invoice(reader, ids[0])
        reader.commit()
        assert reader.get(CustomerAccount, customer_id).relationship_stage == "active_customer"
        assert projection_status(reader)["pending_count"] == 0
    from sqlalchemy import func
    from app.customer.models import CustomerSourceRecord
    with Session(rc) as writer:
        invoice = writer.get(Invoice, ids[1])
        invoice.commerce_version += 1
        writer.commit()
        before = writer.scalar(select(func.count()).select_from(CustomerSourceRecord).where(CustomerSourceRecord.source_entity_type == "order"))
    gate = Barrier(2)
    def replay(_):
        with Session(rc) as db:
            gate.wait(timeout=10)
            order = project_invoice(db, ids[1])
            order_id = order.id
            db.commit()
            return order_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replay, range(2)))
    assert results[0] == results[1]
    with Session(rc) as db:
        assert db.scalar(select(func.count()).select_from(CustomerSourceRecord).where(CustomerSourceRecord.source_entity_type == "order")) == before + 1


def test_native_battle_migration_keeps_legacy_and_allows_multiple_unbound_members(mysql_engine):
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE ark_battle_report_members (id INT PRIMARY KEY, report_id INT NOT NULL, ark_user_id INT NOT NULL, okki_user_id VARCHAR(100) NOT NULL, UNIQUE KEY uq_battle_report_okki(report_id,okki_user_id), UNIQUE KEY uq_battle_report_ark(report_id,ark_user_id))")
        conn.exec_driver_sql("INSERT INTO ark_battle_report_members VALUES (1,1,1,'old-owner')")
        spec = spec_from_file_location("battle_native_migration", Path(__file__).parents[1] / "alembic/versions/218_native_battle_members.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        conn.exec_driver_sql("INSERT INTO ark_battle_report_members VALUES (2,1,2,NULL),(3,1,3,NULL)")
        assert conn.exec_driver_sql("SELECT okki_user_id FROM ark_battle_report_members WHERE id=1").scalar() == "old-owner"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM ark_battle_report_members").scalar() == 3
    assert next(row for row in inspect(mysql_engine).get_columns("ark_battle_report_members") if row["name"] == "okki_user_id")["nullable"]
