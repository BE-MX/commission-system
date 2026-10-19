from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def migration():
    backend = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("portal_catalog_families_migration",
                                   backend / "alembic/versions/199_portal_catalog_families.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return backend, module


def test_single_head_and_existing_items_untouched(monkeypatch):
    backend, module = migration()
    config = Config()
    config.set_main_option("script_location", str(backend / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert module.revision in {script.revision for script in scripts.walk_revisions()}
    assert len(scripts.get_heads()) == 1
    assert module.down_revision == "198_customer_media_playback" and len(module.revision) <= 32
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_order_portal_sites (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ark_order_portal_catalog_items (id INTEGER PRIMARY KEY, display_name TEXT)"))
        connection.execute(text("INSERT INTO ark_order_portal_catalog_items VALUES (1,'existing')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        row = connection.execute(text("SELECT display_name, family_id, grade FROM ark_order_portal_catalog_items")).one()
        assert row == ("existing", None, None)
    engine.dispose()


def test_mysql_ddl_is_additive_with_real_constraints(monkeypatch):
    _, module = migration()
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(module, "op", Operations(context))
    module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE ark_order_portal_product_families" in sql
    assert "CREATE TABLE ark_order_portal_color_swatches" in sql
    assert "ADD COLUMN family_id BIGINT" in sql and "ADD COLUMN grade VARCHAR(16)" in sql
    assert "fk_op_catalog_items_family_id" in sql and "ck_op_catalog_family_grade" in sql
    assert "DROP" not in sql and "UPDATE" not in sql
