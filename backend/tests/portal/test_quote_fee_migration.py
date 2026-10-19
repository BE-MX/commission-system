from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def migration():
    backend = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("portal_quote_fee_estimate_migration",
                                   backend / "alembic/versions/200_portal_quote_fee_estimate.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return backend, module


def test_single_head_after_catalog_families():
    backend, module = migration()
    config = Config()
    config.set_main_option("script_location", str(backend / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [module.revision]
    assert module.down_revision == "199_portal_catalog_families" and len(module.revision) <= 32


def test_mysql_ddl_adds_one_nullable_column(monkeypatch):
    _, module = migration()
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(module, "op", Operations(context))
    module.upgrade()
    sql = output.getvalue()
    assert "ALTER TABLE ark_order_portal_quotes ADD COLUMN fee_estimate_json JSON" in sql
    assert "NOT NULL" not in sql and "DROP" not in sql and "UPDATE" not in sql
