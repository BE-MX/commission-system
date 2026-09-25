"""The customer-label migration preserves live historical asset labels."""

import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from app.customer_media.models import CustomerMediaAsset, CustomerMediaAssetTag
from tests.test_customer_media_tags import _make_dim, _seed_batch_with_asset


@pytest.mark.parametrize("existing_table", [False, True])
@pytest.mark.parametrize("mysql_comparison", [False, True])
def test_backfill_live_asset_tags_is_idempotent(db, monkeypatch, existing_table, mysql_comparison):
    dimension, values = _make_dim(db, "customer_scene", "场景", values=["白底", "废弃"])
    _applicant, designer, _outsider, batch, live = _seed_batch_with_asset(db)
    deleted = CustomerMediaAsset(
        batch_id=batch.id, file_name="deleted.png", media_type="image",
        content_type="image/png", file_size=100, sha256="d" * 64,
        storage_provider="local", object_key="customers/deleted.png",
        uploaded_by=designer.id, deleted_at=datetime(2026, 9, 1, 10, 0),
    )
    db.add(deleted)
    db.flush()
    db.add_all([
        CustomerMediaAssetTag(asset_id=live.id, dimension_id=dimension.id, tag_value_id=values[0].id),
        CustomerMediaAssetTag(asset_id=deleted.id, dimension_id=dimension.id, tag_value_id=values[1].id),
    ])
    db.commit()

    path = Path(__file__).resolve().parents[1] / "alembic/versions/168_customer_media_customer_tags.py"
    spec = importlib.util.spec_from_file_location("customer_tags_168", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    if not existing_table:
        connection.exec_driver_sql("DROP TABLE ark_customer_media_customer_tags")
    migration.op = Operations(MigrationContext.configure(connection))
    if mysql_comparison:
        # Exercise the MySQL expression in the isolated SQLite database.
        # Actual mixed-collation validation uses read-only MySQL EXPLAIN.
        connection.connection.driver_connection.create_collation(
            "utf8mb4_unicode_ci", lambda a, b: (a > b) - (a < b)
        )
        proxy = Mock(wraps=connection)
        proxy.dialect = SimpleNamespace(name="mysql")
        monkeypatch.setattr(migration.op, "get_bind", lambda: proxy)
        real_inspect = migration.sa.inspect
        monkeypatch.setattr(migration.sa, "inspect", lambda _: real_inspect(connection))
    migration.upgrade()
    migration.upgrade()
    if mysql_comparison:
        sql = str(proxy.execute.call_args.args[0])
        assert "existing.customer_id COLLATE utf8mb4_unicode_ci" in sql
        assert "b.customer_id COLLATE utf8mb4_unicode_ci" in sql
    rows = connection.execute(text(
        "SELECT customer_id, dimension_id, tag_value_id FROM ark_customer_media_customer_tags"
    )).all()
    assert rows == [(batch.customer_id, dimension.id, values[0].id)]
