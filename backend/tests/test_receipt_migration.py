"""Migration contract, restartability and no-data-loss guard in isolated SQLite."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/156_receipt_management.py"
    spec = importlib.util.spec_from_file_location("receipt_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_restart_preserves_rows_and_matches_model(monkeypatch):
    from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment, ReceiptLog
    module = migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(module.op, "get_bind", lambda: conn)
        monkeypatch.setattr(module.op, "execute", conn.execute)
        module.upgrade()
        conn.execute(sa.text("INSERT INTO ark_receipt_logs (id, receipt_id, action, message, created_at) VALUES (1, 1, 'test', 'preserved', '2026-09-17 00:00:00')"))
        module.upgrade()
        assert conn.execute(sa.text("SELECT message FROM ark_receipt_logs WHERE id=1")).scalar() == "preserved"
        for model, table in zip((Receipt, ReceiptIntent, ReceiptAttachment, ReceiptLog), module.TABLES):
            assert set(table.columns.keys()) == set(model.__table__.columns.keys())
            ddl = str(sa.schema.CreateTable(table).compile(dialect=mysql.dialect()))
            assert "ENGINE=InnoDB" in ddl and "CHARSET=utf8mb4" in ddl
        conn.execute(sa.text("ALTER TABLE ark_receipts RENAME COLUMN amount TO missing_amount"))
        with pytest.raises(RuntimeError, match="amount"):
            module.validate_schema()
    engine.dispose()


def test_downgrade_cannot_delete_ledger():
    with pytest.raises(RuntimeError, match="preserved"):
        migration().downgrade()
