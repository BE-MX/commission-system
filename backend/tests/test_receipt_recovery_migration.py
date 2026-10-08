"""Additive upgrade in isolated SQLite and MySQL DDL compilation, no shared DB."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql

from app.receipt.models import Receipt, ReceiptAttempt, ReceiptIndexState


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/175_receipt_recovery.py"
    spec = importlib.util.spec_from_file_location("receipt_recovery_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_preserves_legacy_unknown_phase_and_financial_facts():
    engine = sa.create_engine("sqlite:///:memory:")
    additions = {"send_phase", "recovery_kind", "next_attempt_at", "recovery_attempts"}
    metadata = sa.MetaData()
    sa.Table("ark_invoices", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    sa.Table("ark_receipt_batches", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    sa.Table("ark_receivables", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    # Reconstruct the prior ledger schema; preserve constraints and original types.
    previous = Receipt.__table__.to_metadata(metadata)
    for name in additions:
        previous._columns.remove(previous.c[name])
    for index in list(previous.indexes):
        if any(column.name in additions for column in index.columns):
            previous.indexes.remove(index)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(previous.insert().values(id=1, receipt_no="HK-old", invoice_id=1,
            source="auto", request_key="old-key", request_hash="old-hash", amount="1439.47",
            bank_charge="69.00", currency="USD", collection_date=date(2026, 9, 4),
            payment_type="PayPal", attachment_ids=["proof"], customer_id="101", xiaoman_order_id="25875",
            sync_status="uncertain", status="active", created_by=1))
        before = conn.execute(sa.text("SELECT amount,bank_charge,attachment_ids,sync_status FROM ark_receipts")).one()
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        after = conn.execute(sa.text("SELECT amount,bank_charge,attachment_ids,sync_status FROM ark_receipts")).one()
        assert before == after
        assert tuple(conn.execute(sa.text("SELECT send_phase,recovery_kind,next_attempt_at,recovery_attempts FROM ark_receipts")).one()) == (None, None, None, 0)
        inspector = sa.inspect(conn)
        for model in (Receipt, ReceiptAttempt, ReceiptIndexState):
            assert {c["name"] for c in inspector.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
    engine.dispose()


def test_single_revision_head_and_no_destructive_downgrade():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    # The portal migrations (176/177) chain on top of this recovery migration.
    assert scripts.get_heads() == ["177_portal_pi_header"]
    assert migration().down_revision == "174_domestic_decision"
    assert scripts.get_revision("175_receipt_recovery").down_revision == "174_domestic_decision"
    with pytest.raises(RuntimeError, match="不可删除"):
        migration().downgrade()


def test_mysql_foreign_key_type_and_additive_ddl():
    assert str(ReceiptAttempt.__table__.c.receipt_id.type.compile(dialect=mysql.dialect())) == str(
        Receipt.__table__.c.id.type.compile(dialect=mysql.dialect()))
    ddl = str(sa.schema.CreateTable(ReceiptAttempt.__table__).compile(dialect=mysql.dialect()))
    assert "FOREIGN KEY(receipt_id) REFERENCES ark_receipts (id)" in ddl
