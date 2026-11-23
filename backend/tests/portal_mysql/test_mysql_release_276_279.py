"""Real incremental DDL on an owned MySQL; typed anchors are not a full schema clone."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def test_release_275_to_279_preserves_rows_and_mysql_foreign_keys(request):
    if len(request.session.items) != 1:
        pytest.skip("Run this migration replay alone on a fresh owned database")
    engine = request.getfixturevalue("mysql_engine")
    assert inspect(engine).get_table_names() == []
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE ark_users (id INT UNSIGNED PRIMARY KEY) ENGINE=InnoDB",
            "CREATE TABLE ark_shipping_inspections (id BIGINT PRIMARY KEY) ENGINE=InnoDB",
            "CREATE TABLE shipment_tracking (id BIGINT PRIMARY KEY) ENGINE=InnoDB",
            "CREATE TABLE ark_invoices (id INT PRIMARY KEY, invoice_no VARCHAR(64)) ENGINE=InnoDB",
            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY) ENGINE=InnoDB",
            "INSERT INTO ark_users VALUES (2147483648)",
            "INSERT INTO ark_shipping_inspections VALUES (1)",
            "INSERT INTO shipment_tracking VALUES (2)",
            "INSERT INTO ark_invoices VALUES (3, 'LEGACY-UNCHANGED')",
            "INSERT INTO alembic_version VALUES ('275_factory_inbound_batch')",
        ):
            connection.exec_driver_sql(statement)

    expected = {
        '276_invoice_alibaba_order': {'ark_invoices'},
        '277_cross_border_review': {'ark_cross_border_imports', 'ark_cross_border_declarations',
            'ark_cross_border_receipts', 'ark_cross_border_reviews', 'ark_cross_border_exports'},
        '278_devlog_tables': {'ark_devlog_items', 'ark_devlog_evidences', 'ark_devlog_item_events',
            'ark_devlog_releases', 'ark_devlog_sync_runs'},
        '279_shipping_waybill_photos': {'ark_shipping_waybill_photos'},
    }
    previous = '275_factory_inbound_batch'
    versions = Path(__file__).resolve().parents[2] / 'alembic' / 'versions'
    for revision, tables in expected.items():
        spec = spec_from_file_location('release_' + revision, versions / (revision + '.py'))
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        assert migration.revision == revision and migration.down_revision == previous
        with engine.begin() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == previous
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            # Operations invokes real DDL; this explicitly mirrors Alembic's version bookkeeping.
            changed = connection.execute(text('UPDATE alembic_version SET version_num=:new WHERE version_num=:old'),
                {'new': revision, 'old': previous})
            assert changed.rowcount == 1
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == revision
            assert tables <= set(inspect(connection).get_table_names())
            assert connection.execute(text('SELECT id, invoice_no, alibaba_order_no FROM ark_invoices')).all() == [
                (3, 'LEGACY-UNCHANGED', None)]
            assert connection.scalar(text('SELECT id FROM ark_users')) == 2147483648
        previous = revision

    with engine.connect() as connection:
        columns = dict(connection.execute(text("SELECT CONCAT(TABLE_NAME, '.', COLUMN_NAME), COLUMN_TYPE "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND "
            "((TABLE_NAME='ark_cross_border_imports' AND COLUMN_NAME='imported_by') OR "
            "(TABLE_NAME IN ('ark_cross_border_reviews','ark_cross_border_exports') AND COLUMN_NAME='created_by'))")).all())
        assert len(columns) == 3 and all(value == 'int unsigned' for value in columns.values())
        engines = connection.execute(text('SELECT DISTINCT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')).scalars().all()
        assert engines == ['InnoDB']
    schema = inspect(engine)
    for table, column in (('ark_cross_border_imports', 'imported_by'),
                          ('ark_cross_border_reviews', 'created_by'), ('ark_cross_border_exports', 'created_by')):
        assert any(fk['constrained_columns'] == [column] and fk['referred_table'] == 'ark_users'
            and fk['referred_columns'] == ['id'] for fk in schema.get_foreign_keys(table))
    waybill_fks = schema.get_foreign_keys('ark_shipping_waybill_photos')
    assert {(fk['constrained_columns'][0], fk['referred_table']) for fk in waybill_fks} == {
        ('inspection_id', 'ark_shipping_inspections'), ('shipment_tracking_id', 'shipment_tracking')}
