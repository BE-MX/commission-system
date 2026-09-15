import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/143_whatsapp_reply_inquiries.py"
    spec = importlib.util.spec_from_file_location("reply_memory_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_preserves_existing_data_and_rollback_refuses_deletion():
    module = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE ark_whatsapp_translation_devices (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO ark_users VALUES (7)")
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert conn.exec_driver_sql("SELECT id FROM ark_users").all() == [(7,)]
        columns = {column["name"] for column in sa.inspect(conn).get_columns("ark_whatsapp_reply_inquiries")}
        assert {"instance_id", "revision", "entries", "expires_at"} <= columns
        with pytest.raises(RuntimeError, match="preserved"):
            module.downgrade()
        assert sa.inspect(conn).has_table("ark_whatsapp_reply_inquiries")
    engine.dispose()


def test_mysql_migration_keeps_unsigned_foreign_keys_and_instance_identity():
    module = migration()
    output = io.StringIO()
    module.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    module.upgrade()
    sql = output.getvalue()
    assert "user_id INTEGER UNSIGNED NOT NULL" in sql
    assert "device_id BIGINT UNSIGNED NOT NULL" in sql
    assert "instance_id VARCHAR(36) NOT NULL" in sql
    assert "ON DELETE CASCADE" in sql
