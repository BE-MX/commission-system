"""Compile the migration using MySQL dialect without opening a connection."""
import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_presale_migration_compiles_mysql_and_keeps_financial_history():
    path=Path(__file__).resolve().parents[1]/"alembic/versions/166_presale_settlement.py"
    spec=importlib.util.spec_from_file_location("presale_migration",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    output=io.StringIO()
    context=MigrationContext.configure(dialect_name="mysql",opts={"as_sql":True,"output_buffer":output})
    with Operations.context(context): module.upgrade()
    sql=output.getvalue()
    assert sql.count("CREATE TABLE") == 8
    assert "DEFAULT 'ordinary'" in sql
    assert "uq_receipt_batch_target" in sql
    assert "uq_shipment_sequence" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "VARCHAR(32) COLLATE utf8mb4_0900_ai_ci" in sql
    assert "DROP TABLE" not in sql and "UPDATE " not in sql and "DELETE " not in sql.replace("ON DELETE RESTRICT", "")
    config=Config()
    config.set_main_option("script_location",str(path.parents[1]))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1
    assert "167_invoice_merchandiser" in {
        revision.revision for revision in script.iterate_revisions(heads[0], "164_battle_posters")
    }
    assert [revision.revision for revision in script.iterate_revisions(
        "167_invoice_merchandiser", "164_battle_posters"
    )] == ["167_invoice_merchandiser", "166_presale_settlement"]


def test_presale_funding_adds_only_columns_and_keeps_original_cash():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/179_presale_funding.py"
    spec = importlib.util.spec_from_file_location("presale_funding_migration", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert sql.count("ADD COLUMN") == 7
    for column in ("presale_current_accessory", "presale_current_handling", "presale_archived",
                   "presale_shipped_quantity", "presale_shipped_amount", "purpose", "bank_charge"):
        assert f"ADD COLUMN {column} " in sql
    assert "DEFAULT '0'" in sql and "NUMERIC(14, 2)" in sql
    assert not any(word in sql for word in ("UPDATE ", "DELETE ", "DROP ", "ALTER COLUMN"))
    config = Config(); config.set_main_option("script_location", str(path.parents[1]))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["180_settlement_funding_amendment"]
    assert script.get_revision("180_settlement_funding_amendment").down_revision == module.revision
    import pytest
    with pytest.raises(RuntimeError, match="preserved"):
        module.downgrade()
