"""Restarting never reopens the old authority after a native economic fact."""
import pytest
from sqlalchemy import create_engine, text
from app.commerce_migration.runtime_service import verify_transaction_authority


@pytest.mark.parametrize('table,ddl,insert', [
    ('ark_stock_ledger', 'id INTEGER', '1'),
    ('ark_finance_events', 'id INTEGER', '1'),
    ('ark_invoice_commerce_events', 'id INTEGER', '1'),
    ('ark_production_events', 'id INTEGER', '1'),
    ('ark_invoices', 'transaction_mode TEXT', "'local'"),
    ('ark_production_orders', 'transaction_mode TEXT', "'local'"),
    ('ark_commerce_migration_records', 'role TEXT', "'opening'"),
])
def test_persisted_fact_blocks_legacy_restart_and_preserves_current_journal(tmp_path, table, ddl, insert):
    url = f'sqlite:///{tmp_path / "authority.db"}'
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE TABLE {table} ({ddl})'))
    assert verify_transaction_authority(engine, 'legacy')['transaction_mode'] == 'legacy'
    with engine.begin() as connection:
        connection.execute(text(f'INSERT INTO {table} VALUES ({insert})'))
    engine.dispose()
    resumed = create_engine(url)
    with pytest.raises(RuntimeError, match='向前恢复'):
        verify_transaction_authority(resumed, 'legacy')
    with pytest.raises(RuntimeError, match='尚未安装'):
        verify_transaction_authority(resumed, 'local')
    with resumed.begin() as connection:
        connection.execute(text('CREATE TABLE ark_commerce_transition_policy '
            '(id INTEGER PRIMARY KEY, phase TEXT, version INTEGER, min_writer_version INTEGER, '
            'writer_inventory_verified INTEGER, inventory_evidence TEXT)'))
        connection.execute(text("INSERT INTO ark_commerce_transition_policy VALUES (1,'transition',1,1,1,:evidence)"),
            {'evidence': '{"isolated_fixture_all_writers": true}'})
        connection.execute(text('CREATE TABLE ark_commerce_writer_receipts (protocol_version INTEGER,status TEXT)'))
        connection.execute(text("INSERT INTO ark_commerce_writer_receipts VALUES (1,'compatible')"))
    result = verify_transaction_authority(resumed, 'local', 'transition')
    assert any(result['native_facts'].values())
    assert result['phase'] == 'transition'
    with pytest.raises(RuntimeError, match='不一致'):
        verify_transaction_authority(resumed, 'local', 'local_only')
    with resumed.connect() as connection:
        assert connection.scalar(text(f'SELECT COUNT(*) FROM {table}')) == 1
    resumed.dispose()


def test_customer_only_legacy_schema_and_archives_do_not_seal_native_authority():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE ark_invoices (id INTEGER)'))
        connection.execute(text('CREATE TABLE ark_commerce_migration_records (role TEXT)'))
        connection.execute(text("INSERT INTO ark_commerce_migration_records VALUES ('archive')"))
    assert not any(verify_transaction_authority(engine, 'legacy')['native_facts'].values())
    with pytest.raises(RuntimeError, match='模式无效'):
        verify_transaction_authority(engine, '')
