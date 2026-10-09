"""Compile the additive audit migration without opening the shared database."""
import importlib.util
import io
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def test_upgrade_audit_migration_preserves_history_and_unique_command():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/180_settlement_funding_amendment.py"
    spec = importlib.util.spec_from_file_location("funding_amendment_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE") == 1
    assert "CREATE TABLE ark_settlement_funding_amendments" in sql
    for name in ("before_snapshot", "after_snapshot", "evidence"):
        assert f"{name} JSON NOT NULL" in sql
    for constraint in ("uq_funding_amendment_settlement", "uq_funding_amendment_request"):
        assert constraint in sql
    for table in ("ark_shipment_settlements", "ark_invoices", "ark_receipts"):
        assert f"REFERENCES {table} (id)" in sql
    assert "created_at DATETIME NOT NULL" in sql
    assert not any(word in sql for word in ("UPDATE ", "DELETE ", "DROP ", "ALTER TABLE"))
    assert module.down_revision == "179_presale_funding"
    config = Config()
    config.set_main_option("script_location", str(path.parents[1]))
    assert ScriptDirectory.from_config(config).get_heads() == [module.revision]
    with pytest.raises(RuntimeError, match="preserved"):
        module.downgrade()
