"""Actual native-price migration preserves external prices and enforces identities."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from tests.test_inventory_mysql import mysql_engine, stock_ids


def test_native_price_migration(mysql_engine, stock_ids):
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE ark_std_prices (id INT PRIMARY KEY, product_id BIGINT, sku_id BIGINT, price DECIMAL(12,4), accessory_model VARCHAR(128))")
        conn.exec_driver_sql("INSERT INTO ark_std_prices (id,product_id,sku_id,price) VALUES (1,10,20,8.5000)")
        spec = spec_from_file_location("accessory_migration", Path(__file__).parents[1] / "alembic/versions/239_local_accessory_price.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert tuple(conn.exec_driver_sql("SELECT product_id,sku_id,price,local_sku_id FROM ark_std_prices WHERE id=1").one()) == (10,20,8.5,None)
        conn.exec_driver_sql("INSERT INTO ark_std_prices (id,price,local_sku_id) VALUES (2,9,%s)", (stock_ids[1],))
        conn.exec_driver_sql("INSERT INTO ark_std_prices (id,price) VALUES (3,10)")
        conn.exec_driver_sql("UPDATE ark_std_prices SET accessory_model=%s WHERE id=2", ("X" * 200,))
    with pytest.raises(IntegrityError), mysql_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO ark_std_prices (id,price,local_sku_id) VALUES (4,9,%s)", (stock_ids[1],))
    with pytest.raises(IntegrityError), mysql_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO ark_std_prices (id,price,local_sku_id) VALUES (5,9,999999)")
