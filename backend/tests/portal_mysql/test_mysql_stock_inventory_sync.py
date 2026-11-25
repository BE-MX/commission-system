"""Exercise the inventory sync against an owned MySQL with column grants."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.stock import inventory_sync_service as sync
from app.stock.inventory_sync_models import InventorySyncLog


@pytest.fixture(scope="module")
def app_engine(mysql_engine):
    InventorySyncLog.__table__.create(mysql_engine)
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("CREATE DATABASE stock_sync_mirror")
        conn.exec_driver_sql("""CREATE TABLE stock_sync_mirror.okki_products (
            product_id BIGINT PRIMARY KEY, disable_flag TINYINT NOT NULL) ENGINE=InnoDB""")
        conn.exec_driver_sql("""CREATE TABLE stock_sync_mirror.okki_product_skus (
            sku_id BIGINT PRIMARY KEY, product_id BIGINT NOT NULL, INDEX (product_id)) ENGINE=InnoDB""")
        conn.exec_driver_sql("""CREATE TABLE stock_sync_mirror.okki_inventory (
            sku_id BIGINT NOT NULL, warehouse_id BIGINT NOT NULL, product_id BIGINT NOT NULL,
            product_no VARCHAR(100), enable_count DECIMAL(15,4), real_count DECIMAL(15,4),
            disable_flag TINYINT, synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sku_id, warehouse_id), INDEX (product_id)) ENGINE=InnoDB""")
        conn.exec_driver_sql("INSERT INTO stock_sync_mirror.okki_products VALUES (11, 0), (12, 0)")
        conn.exec_driver_sql("INSERT INTO stock_sync_mirror.okki_product_skus VALUES (22, 11), (23, 12)")
        conn.exec_driver_sql("""INSERT INTO stock_sync_mirror.okki_inventory
            VALUES (22, 33, 11, 'PRODUCT-11', 2, 3, 0, '2026-11-01 12:00:00')""")
        conn.execute(text("CREATE USER 'stock_sync_app'@'127.0.0.1' IDENTIFIED BY :password"),
                     {"password": mysql_engine.url.password})
        conn.exec_driver_sql(f"""GRANT SELECT, INSERT ON `{mysql_engine.url.database}`.ark_inventory_sync_logs
            TO 'stock_sync_app'@'127.0.0.1'""")
        conn.exec_driver_sql("GRANT SELECT ON stock_sync_mirror.* TO 'stock_sync_app'@'127.0.0.1'")
        conn.exec_driver_sql("""GRANT UPDATE (enable_count, real_count, disable_flag, synced_at),
            INSERT (sku_id, warehouse_id, product_id, enable_count, real_count, disable_flag, synced_at)
            ON stock_sync_mirror.okki_inventory TO 'stock_sync_app'@'127.0.0.1'""")

    engine = create_engine(mysql_engine.url.set(username="stock_sync_app"),
                           isolation_level="READ COMMITTED", hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def fake_provider(monkeypatch):
    settings = SimpleNamespace(BUSINESS_DB_NAME="stock_sync_mirror", TRANSACTION_MODE="legacy")
    monkeypatch.setattr(sync, "get_settings", lambda: settings)
    monkeypatch.setattr(sync, "legacy_excluded_products", lambda db: set())
    monkeypatch.setattr(sync, "employee_principal", lambda db, actor, *permissions: {"id": actor})
    monkeypatch.setattr(sync, "beijing_now", lambda: datetime(2026, 11, 6, 12))
    monkeypatch.setattr(sync.okki_client, "fetch_token", lambda **kwargs: ("fake-token", None))

    def supply(*snapshots):
        responses = iter(snapshots)

        def fetch(*args, **kwargs):
            rows = next(responses)
            return {"count": len(rows), "list": rows}

        monkeypatch.setattr(sync.okki_client, "_get_json", fetch)

    return supply


def provider_row(product_id, sku_id, warehouse_id, enable_count="7.25"):
    return dict(product_id=product_id, sku_id=sku_id, warehouse_id=warehouse_id,
                enable_count=enable_count, real_count="10", disable_flag=0)


def test_sync_with_read_only_catalog_and_column_inventory_grants(app_engine, fake_provider):
    fake_provider([provider_row(11, 22, 33), provider_row(11, 22, 34, "0")])
    with Session(app_engine) as db:
        result = sync.sync_product_inventory(db, 11, {"sub": "1"})
        assert result["inventory_rows"] == 2
        inventory = db.execute(text("""SELECT warehouse_id, enable_count, product_no
            FROM stock_sync_mirror.okki_inventory WHERE product_id=11 ORDER BY warehouse_id""")).all()
        assert inventory == [(33, Decimal("7.25"), "PRODUCT-11"), (34, 0, None)]
        log = db.scalars(select(InventorySyncLog).where(InventorySyncLog.product_id == 11)).one()
        assert log.created_by == 1
        assert len(log.before_data) == 1 and len(log.after_data) == 2


def test_concurrent_initial_sync_cannot_merge_disjoint_observations(app_engine, fake_provider, monkeypatch):
    fake_provider([provider_row(12, 23, 35)], [provider_row(12, 23, 36)])
    first_saving = Event()
    release_first = Event()
    apply = sync._apply

    def coordinated_apply(db, product_id, old_rows, new_rows, observed_at):
        if new_rows[0]["warehouse_id"] == 35:
            first_saving.set()
            assert release_first.wait(timeout=10)
        apply(db, product_id, old_rows, new_rows, observed_at)

    monkeypatch.setattr(sync, "_apply", coordinated_apply)

    def save():
        with Session(app_engine) as db:
            return sync.sync_product_inventory(db, 12, {"sub": "1"})

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(save)
        try:
            assert first_saving.wait(timeout=10)
            with pytest.raises(HTTPException) as error:
                save()
            assert error.value.status_code == 409
        finally:
            release_first.set()
        assert first.result(timeout=10)["inventory_rows"] == 1

    with Session(app_engine) as db:
        warehouses = db.scalars(text("SELECT warehouse_id FROM stock_sync_mirror.okki_inventory WHERE product_id=12"))
        assert warehouses.all() == [35]
        log = db.scalars(select(InventorySyncLog).where(InventorySyncLog.product_id == 12)).one()
        assert log.before_data == [] and log.after_data[0]["warehouse_id"] == 35
