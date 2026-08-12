"""订单历史时间由 UTC 迁移为数据库北京时间的契约。"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.invoice.models import Invoice, InvoiceDelegateGrant, InvoiceItem, InvoiceSyncLog
from app.invoice.time_utils import beijing_now, to_beijing_time


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/108_invoice_beijing_time.py"
    spec = importlib.util.spec_from_file_location("migration_108_invoice_beijing_time", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_declares_exact_business_time_columns_and_backups():
    migration = _load_migration()

    assert migration.TIME_COLUMNS == {
        "ark_invoices": ("created_at", "updated_at", "synced_at"),
        "ark_invoice_items": ("created_at", "updated_at"),
        "ark_invoice_sync_logs": ("created_at",),
    }
    assert set(migration.BACKUP_TABLES) == set(migration.TIME_COLUMNS)
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert "时间备份不完整" in source
    assert "北京时间转换校验失败" in source


def test_database_naive_time_is_interpreted_as_beijing_without_second_shift():
    value = to_beijing_time(datetime(2026, 8, 12, 14, 58, 23))

    assert value.isoformat() == "2026-08-12T14:58:23+08:00"


def test_aware_time_is_converted_to_beijing_time():
    value = to_beijing_time(datetime(2026, 8, 12, 6, 58, 23, tzinfo=timezone.utc))

    assert value.isoformat() == "2026-08-12T14:58:23+08:00"


def test_invoice_business_models_write_beijing_time_by_default():
    defaults = (
        Invoice.__table__.c.created_at.default.arg,
        Invoice.__table__.c.updated_at.default.arg,
        InvoiceItem.__table__.c.created_at.default.arg,
        InvoiceItem.__table__.c.updated_at.default.arg,
        InvoiceSyncLog.__table__.c.created_at.default.arg,
        InvoiceDelegateGrant.__table__.c.created_at.default.arg,
    )
    for default in defaults:
        value = default(None)
        assert value.tzinfo is None
        assert abs(value - beijing_now()) < timedelta(seconds=2)
