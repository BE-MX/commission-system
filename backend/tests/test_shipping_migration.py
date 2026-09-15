import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_migration_preserves_existing_rows_and_can_resume(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/152_shipping_media_recall.py'
    spec = importlib.util.spec_from_file_location('shipping_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        # Simulate partial MySQL DDL. The shared test compiler rewrites new BIGINT
        # columns to INTEGER for SQLite autoincrement, so retain this type explicitly.
        connection.execute(text('CREATE TABLE ark_shipping_inspections (id INTEGER PRIMARY KEY, status TEXT, recalled_by BIGINT)'))
        connection.execute(text("INSERT INTO ark_shipping_inspections (id, status) VALUES (1, 'submitted')"))
        connection.execute(text('CREATE TABLE ark_shipping_inspection_photos (id INTEGER PRIMARY KEY, file_path TEXT)'))
        connection.execute(text("INSERT INTO ark_shipping_inspection_photos VALUES (1, 'aa/photo.jpg')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(text('SELECT status, edit_version, recalled_at FROM ark_shipping_inspections')).one() == ('submitted', 0, None)
        assert connection.execute(text('SELECT file_path, media_type FROM ark_shipping_inspection_photos')).one() == ('aa/photo.jpg', 'image')
        with pytest.raises(RuntimeError, match='preserved'):
            migration.downgrade()
    engine.dispose()
