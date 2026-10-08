from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.portal import catalog_service, inventory_source as service
from app.portal.inventory import validate_observation
from app.portal.errors import PortalError


@pytest.fixture
def stock(monkeypatch):
    settings = SimpleNamespace(PORTAL_OKKI_NAMESPACE='okki:test', PORTAL_INVENTORY_OBSERVED_COLUMN='synced_at',
        PORTAL_INVENTORY_SOURCE_TIMEZONE='Asia/Shanghai', PORTAL_INVENTORY_UNIT_BY_SKU={'101:201': 'piece', '102:202': 'set'},
        PORTAL_INVENTORY_MAX_AGE_SECONDS=120)
    now = datetime(2026, 10, 1, 0, 0, 30)
    monkeypatch.setattr(service, 'get_settings', lambda: settings)
    monkeypatch.setattr(service, 'beijing_now', lambda: now)
    monkeypatch.setattr(service.product_service, '_schema', lambda: 'main')
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        db.execute(text('CREATE TABLE okki_products (product_id INTEGER, disable_flag INTEGER)'))
        db.execute(text('CREATE TABLE okki_product_skus (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER)'))
        # TEXT represents the exact DECIMAL driver wire value without SQLite REAL rounding.
        db.execute(text('CREATE TABLE okki_inventory (product_id INTEGER, sku_id INTEGER, enable_count TEXT, disable_flag INTEGER, synced_at TEXT)'))
        db.execute(text('INSERT INTO okki_products VALUES (101,0),(102,0),(103,0)'))
        db.execute(text('INSERT INTO okki_product_skus VALUES (101,201,0),(101,203,0),(102,202,0),(103,203,0)'))
        for product, sku, amount, disabled, age in [(101,201,'12.25',0,30),(101,201,'2.125',0,60),
                (101,201,'999',1,0),(101,203,'999',0,0),(102,202,'0',0,10),(103,203,'999',0,0)]:
            db.execute(text('INSERT INTO okki_inventory VALUES (:p,:s,:q,:d,:t)'),
                {'p':product,'s':sku,'q':amount,'d':disabled,'t':(now-timedelta(seconds=age)).isoformat()})
        db.commit()
        items = [SimpleNamespace(public_id='item-a', source_namespace='okki:test', product_id='101', sku_id='201'),
                 SimpleNamespace(public_id='item-b', source_namespace='okki:test', product_id='102', sku_id='202')]
        yield SimpleNamespace(db=db, items=items, settings=settings, now=now)
    engine.dispose()


def test_exact_sku_sum_uses_oldest_observation_without_in_transit_or_disabled_rows(stock):
    found = service.load(stock.db, stock.items)
    assert found['item-a'].quantity == Decimal('14.375')
    assert found['item-a'].unit == 'piece'
    assert found['item-a'].observed_at == datetime(2026, 9, 30, 23, 59, 30)
    assert found['item-b'].quantity == 0 and found['item-b'].unit == 'set'
    assert 'okki_inventory:okki:test:101:201:synced_at' == found['item-a'].source


@pytest.mark.parametrize('setting,value', [('PORTAL_OKKI_NAMESPACE',''), ('PORTAL_INVENTORY_OBSERVED_COLUMN',''),
    ('PORTAL_INVENTORY_OBSERVED_COLUMN','update_time'), ('PORTAL_INVENTORY_SOURCE_TIMEZONE',''),
    ('PORTAL_INVENTORY_SOURCE_TIMEZONE','system'), ('PORTAL_INVENTORY_UNIT_BY_SKU',{})])
def test_unattested_configuration_never_reads_the_mirror(stock, monkeypatch, setting, value):
    setattr(stock.settings, setting, value)
    monkeypatch.setattr(service.product_service, '_table_columns', lambda *args: pytest.fail('unattested source reached SQL'))
    assert service.load(stock.db, stock.items) == {}


@pytest.mark.parametrize('bad_value', [None, '-1', 'NaN', 'Infinity', 'bad', '1000000000000000000'])
def test_one_invalid_quantity_invalidates_entire_sku_not_other_skus(stock, bad_value):
    stock.db.execute(text('UPDATE okki_inventory SET enable_count=:v WHERE product_id=101 AND enable_count=\'2.125\''), {'v':bad_value})
    found = service.load(stock.db, stock.items)
    assert set(found) == {'item-b'}


@pytest.mark.parametrize('stamp', [None, '2026-10-01', '2026-13-01T00:00:00', '2026-10-01T00:00:31',
    '2026-09-30T23:58:29', '2026-09-30T23:59:30Z'])
def test_one_invalid_stale_or_future_timestamp_cannot_be_hidden_by_fresh_row(stock, stamp):
    stock.db.execute(text('UPDATE okki_inventory SET synced_at=:v WHERE product_id=101 AND enable_count=\'2.125\''), {'v':stamp})
    assert set(service.load(stock.db, stock.items)) == {'item-b'}


@pytest.mark.parametrize('timezone,stamp', [('UTC','2026-09-30T15:59:30'),
    ('Asia/Shanghai','2026-09-30T15:59:30Z'), ('UTC','2026-09-30T23:59:30+08:00')])
def test_source_timezone_conversion_crosses_beijing_midnight_without_host_clock(stock, timezone, stamp, monkeypatch):
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    stock.settings.PORTAL_INVENTORY_SOURCE_TIMEZONE = timezone
    stock.db.execute(text('UPDATE okki_inventory SET synced_at=:v WHERE product_id=101'), {'v':stamp})
    assert service.load(stock.db, stock.items)['item-a'].observed_at == datetime(2026,9,30,23,59,30)


@pytest.mark.parametrize('table', ['okki_products', 'okki_product_skus'])
def test_inactive_standard_identity_is_not_orderable(stock, table):
    stock.db.execute(text(f'UPDATE {table} SET disable_flag=1 WHERE product_id=101'))
    assert set(service.load(stock.db, stock.items)) == {'item-b'}


def test_missing_rows_are_unknown_while_explicit_zero_is_known_out_of_stock(stock, monkeypatch):
    stock.db.execute(text('DELETE FROM okki_inventory WHERE product_id=101'))
    found = service.load(stock.db, stock.items)
    assert 'item-a' not in found
    monkeypatch.setattr(catalog_service, 'get_settings', lambda: stock.settings)
    monkeypatch.setattr(catalog_service, 'beijing_now', lambda: stock.now)
    item = SimpleNamespace(min_qty=1, step_qty=1, inventory_unit='set', conversion_factor=Decimal(1), safety_buffer=Decimal(0))
    assert catalog_service.availability(item, None) == ('unknown', None)
    assert catalog_service.availability(item, found['item-b'])[0] == 'unavailable'


def test_no_unit_inference_from_catalog_conversion_or_customer_labels(stock):
    stock.settings.PORTAL_INVENTORY_UNIT_BY_SKU = {'101:201': 'piece'}
    item = stock.items[0]
    item.inventory_unit = 'g'
    item.display_name = '20g customer label'
    observation = service.load(stock.db, stock.items)['item-a']
    with pytest.raises(PortalError) as caught:
        validate_observation(observation, now=stock.now, max_age_seconds=120, quantity=1,
            inventory_unit='g', conversion_factor=Decimal(20), safety_buffer=Decimal(0))
    assert caught.value.code == 'INVENTORY_UNAVAILABLE'


def test_namespace_and_malformed_ids_are_filtered_before_query(stock, monkeypatch):
    stock.items[0].source_namespace = 'okki:other'
    stock.items[1].sku_id = '202 OR 1=1'
    monkeypatch.setattr(service.product_service, '_table_columns', lambda *args: pytest.fail('invalid scope reached SQL'))
    assert service.load(stock.db, stock.items) == {}


def test_missing_sync_column_has_no_fallback_to_product_timestamp(stock):
    stock.db.execute(text('ALTER TABLE okki_inventory RENAME COLUMN synced_at TO update_time'))
    assert service.load(stock.db, stock.items) == {}


def test_database_errors_are_sanitized_and_do_not_publish_partial_stock(stock, monkeypatch, capsys):
    def broken(*args):
        raise OperationalError('SELECT secret', {}, Exception('password=SECRET'))
    monkeypatch.setattr(service.product_service, '_table_columns', broken)
    assert service.load(stock.db, stock.items) == {}
    output = capsys.readouterr().out
    assert 'OperationalError' in output and 'SECRET' not in output and 'SELECT' not in output


@pytest.mark.parametrize('value', [True, 1.25, Decimal('NaN'), Decimal('-1'), 'Infinity'])
def test_numeric_parser_rejects_ambiguous_or_invalid_values(value):
    assert service._amount(value) is None


def test_decimal_precision_and_datetime_driver_types():
    assert service._amount(Decimal('123456789.123456')) == Decimal('123456789.123456')
    assert service._timestamp(datetime(2026,9,30,16,0), 'UTC') == datetime(2026,10,1,0,0)


def test_batch_query_handles_more_than_200_exact_pairs(stock):
    stock.db.execute(text('DELETE FROM okki_inventory'))
    stock.db.execute(text('DELETE FROM okki_product_skus'))
    items = []
    for number in range(1, 206):
        stock.settings.PORTAL_INVENTORY_UNIT_BY_SKU[f'101:{number}'] = 'piece'
        stock.db.execute(text('INSERT INTO okki_product_skus VALUES (101,:s,0)'), {'s':number})
        stock.db.execute(text('INSERT INTO okki_inventory VALUES (101,:s,:v,0,:t)'), {'s':number,'v':str(number),'t':stock.now.isoformat()})
        items.append(SimpleNamespace(public_id=str(number), source_namespace='okki:test', product_id='101', sku_id=str(number)))
    found = service.load(stock.db, items)
    assert len(found) == 205 and found['205'].quantity == 205


def test_default_real_settings_keep_inventory_disabled():
    from app.core.config import Settings
    settings = Settings(_env_file=None)
    assert settings.PORTAL_INVENTORY_OBSERVED_COLUMN == ''
    assert settings.PORTAL_INVENTORY_SOURCE_TIMEZONE == ''
    assert settings.PORTAL_INVENTORY_UNIT_BY_SKU == {}


def test_excess_precision_cannot_round_up_into_an_orderable_piece(stock):
    stock.db.execute(text("UPDATE okki_inventory SET enable_count='0.99999999999999999999999999999' WHERE product_id=101"))
    assert 'item-a' not in service.load(stock.db, stock.items)
    assert service._amount('0.9999999') is None
    assert service._amount('1.000000000') == Decimal('1.000000')
    assert service._amount('0.000001') == Decimal('0.000001')


def test_aggregate_overflow_is_unavailable_not_rounded(stock):
    stock.db.execute(text("UPDATE okki_inventory SET enable_count='999999999999999999' WHERE product_id=101"))
    assert 'item-a' not in service.load(stock.db, stock.items)
