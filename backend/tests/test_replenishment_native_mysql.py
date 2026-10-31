"""Actual 187 DDL and native policy first-writer/batch races in MySQL RR."""
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.catalog.models import CatalogProduct, CatalogSku
from app.stock.local_query_service import save
from app.stock.models import SafetyStock
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_trade_mysql import projection_tables


@pytest.fixture
def policies(mysql_engine, stock_ids):
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("""CREATE TABLE ark_safety_stock (
            id INT PRIMARY KEY AUTO_INCREMENT, product_id BIGINT NOT NULL UNIQUE,
            safety_stock INT NOT NULL DEFAULT 0, lead_time_days SMALLINT NOT NULL DEFAULT 30,
            safety_factor DECIMAL(4,2) NOT NULL DEFAULT 1.5, source SMALLINT NOT NULL DEFAULT 0,
            updated_by INT NOT NULL, updated_at DATETIME NOT NULL, created_at DATETIME NOT NULL)""")
        conn.exec_driver_sql("""CREATE TABLE ark_production_cart (
            id INT PRIMARY KEY AUTO_INCREMENT, user_id INT NOT NULL, product_id BIGINT NOT NULL,
            product_name VARCHAR(255) NOT NULL, model VARCHAR(100),
            UNIQUE KEY uk_cart_user_product(user_id,product_id))""")
        conn.exec_driver_sql("INSERT INTO ark_safety_stock(product_id,safety_stock,updated_by,updated_at,created_at) VALUES(123,8,1,NOW(),NOW())")
        conn.exec_driver_sql("INSERT INTO ark_production_cart(user_id,product_id,product_name) VALUES(1,123,'Legacy')")
        spec = spec_from_file_location("replenishment_migration", Path(__file__).parents[1] / "alembic/versions/221_local_replenishment.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert tuple(conn.exec_driver_sql("SELECT product_id,safety_stock,local_sku_id,version FROM ark_safety_stock").one()) == (123,8,None,1)
        assert tuple(conn.exec_driver_sql("SELECT product_id,local_sku_id,product_name FROM ark_production_cart").one()) == (123,None,"Legacy")
    with Session(mysql_engine) as db:
        product = CatalogProduct(code="P2", name="Second", display_name="Second")
        db.add(product)
        db.flush()
        sku = CatalogSku(code="S2", product_id=product.id)
        db.add(sku)
        db.flush()
        identities = [f"ark:sku:{stock_ids[1]}", f"ark:sku:{sku.id}"]
        db.commit()
    return identities


def test_different_empty_policies_do_not_lock_unique_index_gaps(mysql_engine, policies):
    gate = Barrier(2)
    def write(identity):
        with Session(mysql_engine) as db:
            gate.wait(timeout=10)
            return save(db, [{"product_id": identity, "safety_stock": 10, "expected_version": 0}], 30, 1.5, "manual", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, policies))
    assert all(len(result["saved"]) == 1 and not result["failed"] for result in results)


def test_reversed_batches_lock_catalog_in_one_order(mysql_engine, policies):
    with Session(mysql_engine) as db:
        save(db, [{"product_id": identity, "safety_stock": 10, "expected_version": 0} for identity in policies], 30, 1.5, "manual", 1)
    gate = Barrier(2)
    def write(values):
        with Session(mysql_engine) as db:
            gate.wait(timeout=10)
            return save(db, [{"product_id": identity, "safety_stock": amount, "expected_version": 1}
                            for identity, amount in values], 30, 1.5, "manual", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [[(policies[0], 20), (policies[1], 20)], [(policies[1], 30), (policies[0], 30)]]))
    assert sorted(len(result["saved"]) for result in results) == [0, 2]
    with Session(mysql_engine) as db:
        rows = db.scalars(select(SafetyStock).where(SafetyStock.local_sku_id.is_not(None))).all()
        assert {row.version for row in rows} == {2} and len({row.safety_stock for row in rows}) == 1


def test_native_query_collation_and_daily_json(mysql_engine, policies, projection_tables, stock_ids):
    """Exercise SQL aggregates and persisted JSON with the real MySQL driver."""
    import json
    from sqlalchemy import Column, MetaData, Table
    from app.core.time import beijing_today
    from app.invoice.models import Invoice, InvoiceItem
    from app.trade.projection_service import project_invoice
    from tests.test_customer_facts import _customer
    from app.stock.models import ProductionOrder, ProductionOrderItem, StockDailyReport
    from app.stock.local_query_service import query
    from app.stock.daily_report_service import upsert_daily_report
    metadata = MetaData()
    for model in (ProductionOrder, ProductionOrderItem, StockDailyReport):
        Table(model.__tablename__, metadata, *[
            Column(col.name, col.type, primary_key=col.primary_key,
                   autoincrement=col.autoincrement, nullable=col.nullable,
                   server_default=col.server_default) for col in model.__table__.columns])
    metadata.create_all(mysql_engine)
    with Session(mysql_engine) as db:
        customer = _customer(db, "replenishment-mysql")
        invoice = Invoice(invoice_no="MYSQL-REPLENISH", customer_id="ark:1", customer_name="Buyer",
            invoice_date=beijing_today(), transaction_mode="local", commerce_status="confirmed",
            local_customer_id=customer.id, local_rate_to_usd=1, local_commercial={},
            currency="USD", total_amount=30, surcharge_amount=0)
        db.add(invoice)
        db.flush()
        item = InvoiceItem(invoice_id=invoice.id, local_sku_id=stock_ids[1], quantity=3,
            product_name="Hair", product_display="Hair", color="Black", commercial_kind="bulk",
            price_per_piece=10, total_price=30)
        db.add(item)
        db.flush()
        invoice_id = invoice.id
        db.commit()
    with Session(mysql_engine.execution_options(isolation_level="READ COMMITTED")) as db:
        project_invoice(db, invoice_id)
        db.commit()
    with Session(mysql_engine) as db:
        save(db, [{"product_id": policies[0], "safety_stock": 10, "expected_version": 0}], 30, 1.5, "manual", 1)
        result = query(db)
        row = next(row for row in result["items"] if row["product_id"] == policies[0])
        assert row["sales_30d"] == 3 and row["status"] == "shortage"
        json.dumps(result)
        report = upsert_daily_report(db, beijing_today(), [row], [], result["summary"])
        db.expire_all()
        assert db.get(StockDailyReport, report.id).shortage_skus[0]["enable_count"] == 0
