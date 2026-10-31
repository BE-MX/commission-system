from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from io import StringIO
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_mysql_customer_settings_ddl_is_additive_and_preserves_defaults(monkeypatch):
    spec = spec_from_file_location("customer_settings_migration", Path(__file__).resolve().parents[2] / "alembic/versions/212_portal_customer_settings.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    monkeypatch.setattr(module, "op", SimpleNamespace(add_column=operations.add_column,
        create_foreign_key=operations.create_foreign_key,
        get_bind=lambda: SimpleNamespace(execute=lambda *args: [])))
    module.upgrade()
    sql = output.getvalue()
    assert "delivery_json JSON" in sql
    assert "delivery_version INTEGER NOT NULL" in sql and "DEFAULT '1'" in sql
    assert "unit_price NUMERIC(12, 4)" in sql
    assert "FOREIGN KEY(shipment_tracking_id) REFERENCES shipment_tracking (id) ON DELETE RESTRICT" in sql
    assert "shipment_version INTEGER NOT NULL" in sql and "DEFAULT '0'" in sql
    assert "DROP" not in sql and "customer_info" not in sql
