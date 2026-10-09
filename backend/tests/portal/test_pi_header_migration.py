from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from io import StringIO

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def migration():
    backend = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("portal_pi_header_migration",backend/"alembic/versions/177_portal_pi_header.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return backend,module


def test_additive_migration_preserves_existing_evidence_and_has_single_head(monkeypatch):
    backend,module = migration()
    config = Config()
    config.set_main_option("script_location",str(backend/"alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [module.revision]
    assert module.down_revision == "176_customer_order_portal" and len(module.revision) <= 32
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_order_portal_revisions (id INTEGER PRIMARY KEY, content_hash TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO ark_order_portal_revisions VALUES (1,'original-evidence')"))
        monkeypatch.setattr(module,"op",Operations(MigrationContext.configure(connection)))
        module.upgrade()
        row = connection.execute(text("SELECT content_hash, invoice_presentation_json FROM ark_order_portal_revisions")).one()
        assert row == ("original-evidence",None)
    engine.dispose()


def test_migration_mysql_ddl_is_nullable_addition(monkeypatch):
    _,module = migration()
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql",opts={"as_sql":True,"output_buffer":output})
    monkeypatch.setattr(module,"op",Operations(context))
    module.upgrade()
    sql = output.getvalue()
    assert "ADD COLUMN invoice_presentation_json JSON" in sql
    assert "NOT NULL" not in sql and "UPDATE" not in sql and "DROP" not in sql
