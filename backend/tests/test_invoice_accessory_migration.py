"""Safety checks for the invoice accessory downgrade."""

import importlib.util
import inspect
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "073_invoice_accessory_products.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("invoice_accessory_migration_073", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CountingConnection:
    def __init__(self, counts):
        self.counts = counts
        self.queries = []

    def scalar(self, statement):
        sql = str(statement)
        self.queries.append(sql)
        for marker, count in self.counts.items():
            if marker in sql:
                return count
        return 0


def test_downgrade_preflight_reports_all_unsafe_data_before_ddl():
    migration = _load_migration()
    connection = _CountingConnection(
        {
            "ark_std_prices WHERE product_kind = 'accessory'": 2,
            "ark_invoice_items WHERE product_kind = 'accessory'": 3,
            "ark_std_prices WHERE product_kind = 'hair'": 4,
            "ark_invoice_items WHERE product_kind = 'hair'": 5,
        }
    )

    assert hasattr(migration, "_assert_downgrade_safe")
    with pytest.raises(RuntimeError) as exc_info:
        migration._assert_downgrade_safe(connection)

    message = str(exc_info.value)
    assert "ark_std_prices=2" in message
    assert "ark_invoice_items=3" in message
    assert "NULL dimensions=4" in message
    assert "NULL length/net_weight_grams=5" in message
    assert len(connection.queries) == 4


def test_downgrade_calls_preflight_before_any_ddl_and_never_deletes_data():
    migration = _load_migration()
    source = inspect.getsource(migration.downgrade)

    assert "DELETE FROM" not in source
    assert source.index("_assert_downgrade_safe(connection)") < source.index("op.drop_constraint")
    assert source.index("_assert_downgrade_safe(connection)") < source.index("op.alter_column")
