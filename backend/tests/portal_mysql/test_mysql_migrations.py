"""Inspect actual MySQL DDL, not compiled SQL alone."""
from sqlalchemy import inspect, text
from app.core.database import Base

def test_real_mysql_migration_columns_foreign_keys_and_existing_invoice(migrated):
    inspector = inspect(migrated)
    tables = [table for table in Base.metadata.tables.values() if table.name.startswith('ark_order_portal_')]
    assert len(tables) >= 20
    for table in tables:
        actual = {column['name']: column for column in inspector.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys()), table.name
        for column in table.columns:
            assert actual[column.name]['nullable'] == column.nullable, (table.name, column.name)
        expected_fks = {(tuple(fk.column_keys), next(iter(fk.elements)).column.table.name,
            tuple(element.column.name for element in fk.elements), fk.ondelete) for fk in table.foreign_key_constraints}
        actual_fks = {(tuple(fk['constrained_columns']), fk['referred_table'], tuple(fk['referred_columns']),
            fk.get('options', {}).get('ondelete')) for fk in inspector.get_foreign_keys(table.name)}
        assert actual_fks == expected_fks, table.name
        expected_checks = {constraint.name for constraint in table.constraints if constraint.__class__.__name__ == 'CheckConstraint'}
        assert {constraint['name'] for constraint in inspector.get_check_constraints(table.name)} == expected_checks, table.name
        expected_unique = {tuple(constraint.columns.keys()) for constraint in table.constraints if constraint.__class__.__name__ == 'UniqueConstraint'}
        assert {tuple(constraint['column_names']) for constraint in inspector.get_unique_constraints(table.name)} == expected_unique, table.name
    with migrated.connect() as connection:
        assert connection.execute(text('SELECT id, invoice_no, portal_document_version FROM ark_invoices WHERE id=7')).one() == (7, 'PI-LEGACY', 1)
        assert connection.scalar(text('SELECT @@transaction_isolation')) == 'REPEATABLE-READ'
    print('MySQL migration DDL/columns/FKs and existing invoice preservation verified')
