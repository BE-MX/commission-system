"""Structural safety checks for the standard-price unique-key migration."""

import importlib.util
import inspect
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "074_invoice_price_kind_key.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("invoice_price_kind_migration_074", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_replaces_unique_key_in_one_mysql_alter():
    source = inspect.getsource(_load_migration().upgrade)

    assert source.count("op.execute") == 1
    assert "DROP INDEX uq_ark_std_prices_key" in source
    assert "ADD UNIQUE KEY uq_ark_std_prices_key" in source
    assert "product_kind, series_grade, length, weight_unit, color_type" in source
    assert "op.drop_constraint" not in source


def test_downgrade_replaces_unique_key_in_one_mysql_alter():
    source = inspect.getsource(_load_migration().downgrade)

    assert source.count("op.execute") == 1
    assert "DROP INDEX uq_ark_std_prices_key" in source
    assert "ADD UNIQUE KEY uq_ark_std_prices_key" in source
    assert "(series_grade, length, weight_unit, color_type)" in source
    assert "op.drop_constraint" not in source
