"""Single-product sync tests use an isolated SQLite mirror and fake OKKI calls."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.stock import inventory_sync_service as sync
from app.stock.inventory_sync_models import InventorySyncLog


def provider_row(**changes):
    return dict(product_id=11, sku_id=22, warehouse_id=33,
                enable_count='7.2500', real_count='10', disable_flag=0, **changes)


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine('sqlite://')
    InventorySyncLog.__table__.create(engine)
    db = Session(engine)
    db.execute(text("ATTACH DATABASE ':memory:' AS lsordertest"))
    db.execute(text('CREATE TABLE lsordertest.okki_products (product_id INTEGER PRIMARY KEY, disable_flag INTEGER)'))
    db.execute(text('CREATE TABLE lsordertest.okki_product_skus (sku_id INTEGER PRIMARY KEY, product_id INTEGER)'))
    db.execute(text('CREATE TABLE lsordertest.okki_inventory (sku_id INTEGER, warehouse_id INTEGER, product_id INTEGER, '
        'enable_count NUMERIC, real_count NUMERIC, disable_flag INTEGER, synced_at TIMESTAMP, '
        'PRIMARY KEY(sku_id, warehouse_id))'))
    db.execute(text('INSERT INTO lsordertest.okki_products VALUES (11, 0), (12, 0)'))
    db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (22, 11), (23, 12)'))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (22,33,11,2,3,0,'2026-11-01 12:00:00'),"
                    "(23,33,12,50,60,0,'2026-11-01 12:00:00')"))
    db.commit()
    settings = SimpleNamespace(BUSINESS_DB_NAME='lsordertest', TRANSACTION_MODE='legacy')
    monkeypatch.setattr(sync, 'get_settings', lambda: settings)
    monkeypatch.setattr(sync, 'legacy_excluded_products', lambda db: set())
    monkeypatch.setattr(sync, 'employee_principal', lambda db, actor, *permissions: {'id': actor})
    calls = []
    monkeypatch.setattr(sync.okki_client, 'fetch_token', lambda **kwargs: (calls.append(kwargs) or 'fake-token', None))
    data = {'count': 1, 'list': [provider_row()]}
    def fetch(path, token, **kwargs):
        assert not db.in_transaction(), 'provider request must not hold DB locks'
        calls.append(kwargs)
        return deepcopy(data)
    monkeypatch.setattr(sync.okki_client, '_get_json', fetch)
    monkeypatch.setattr(sync, 'beijing_now', lambda: datetime(2026, 11, 6, 12, 0))
    yield SimpleNamespace(db=db, data=data, calls=calls, settings=settings)
    db.close()
    engine.dispose()


def rows(db):
    return db.execute(text('SELECT product_id, enable_count, real_count, disable_flag '
        'FROM lsordertest.okki_inventory ORDER BY product_id,warehouse_id')).all()


def run(ctx):
    return sync.sync_product_inventory(ctx.db, 11, {'sub': '1'})


def test_sync_exact_product_all_warehouses_and_audit(ctx):
    other = {**provider_row(), 'warehouse_id': 34, 'enable_count': '0', 'disable_flag': 1}
    ctx.data['list'].append(other)
    ctx.data['count'] = 2
    result = run(ctx)
    assert result == {'product_id': 11, 'inventory_rows': 2, 'synced_at': '2026-11-06T12:00:00'}
    assert rows(ctx.db) == [(11, 7.25, 10, 0), (11, 0, 10, 1), (12, 50, 60, 0)]
    log = ctx.db.scalar(select(InventorySyncLog))
    assert log.created_by == 1 and log.product_id == 11
    assert log.before_data[0]['enable_count'] == 2
    assert log.after_data[0]['enable_count'] == '7.2500'
    assert ctx.calls[0]['scope'] == 'invoices company product'
    assert ctx.calls[1]['params'] == {'sku_id': '22', 'count': 100, 'start_index': 1}


@pytest.mark.parametrize('field,value', [('enable_count', None), ('real_count', 'NaN'),
    ('real_count', 'Infinity'), ('real_count', '100000000000'), ('enable_count', '0.00001'),
    ('disable_flag', True), ('disable_flag', 2), ('product_id', 12), ('sku_id', 23), ('warehouse_id', None)])
def test_invalid_provider_data_preserves_existing_stock(ctx, field, value):
    ctx.data['list'][0][field] = value
    with pytest.raises(HTTPException) as error:
        run(ctx)
    assert error.value.status_code == 502
    assert rows(ctx.db) == [(11, 2, 3, 0), (12, 50, 60, 0)]
    assert not ctx.db.scalar(select(InventorySyncLog))


@pytest.mark.parametrize('case', ['partial', 'empty', 'duplicate', 'missing_warehouse', 'auth'])
def test_incomplete_or_denied_observation_never_zeroes_stock(ctx, monkeypatch, case):
    if case == 'partial': ctx.data['count'] = 2
    if case == 'empty': ctx.data.update(count=0, list=[])
    if case == 'duplicate': ctx.data.update(count=2, list=ctx.data['list'] * 2)
    if case == 'missing_warehouse': ctx.data['list'][0]['warehouse_id'] = 34
    if case == 'auth': monkeypatch.setattr(sync.okki_client, '_get_json', lambda *a, **kw: None)
    with pytest.raises(HTTPException): run(ctx)
    assert rows(ctx.db) == [(11, 2, 3, 0), (12, 50, 60, 0)]


def test_provider_fetch_failure_on_second_sku_is_atomic(ctx, monkeypatch):
    ctx.db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (24,11)'))
    ctx.db.commit()
    original = sync.okki_client._get_json
    def fetch(*args, **kwargs):
        if kwargs['params']['sku_id'] == '24': raise sync.okki_client.OkkiApiError('unavailable')
        return original(*args, **kwargs)
    monkeypatch.setattr(sync.okki_client, '_get_json', fetch)
    with pytest.raises(HTTPException) as error: run(ctx)
    assert error.value.status_code == 502
    assert rows(ctx.db)[0] == (11, 2, 3, 0)
    assert not ctx.db.scalar(select(InventorySyncLog))


@pytest.mark.parametrize('case', ['stock', 'mapping', 'disabled', 'permission', 'local_route'])
def test_changed_state_during_fetch_blocks_write(ctx, monkeypatch, case):
    original = sync._fetch
    def fetch(*args):
        result = original(*args)
        if case == 'stock': ctx.db.execute(text('UPDATE lsordertest.okki_inventory SET enable_count=99 WHERE product_id=11'))
        if case == 'mapping': ctx.db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (24,11)'))
        if case == 'disabled': ctx.db.execute(text('UPDATE lsordertest.okki_products SET disable_flag=1 WHERE product_id=11'))
        if case == 'permission':
            def denied(*a): raise sync.PortalError('forbidden', 'denied', 403)
            monkeypatch.setattr(sync, 'employee_principal', denied)
        if case == 'local_route': monkeypatch.setattr(sync, 'legacy_excluded_products', lambda db: {'11'})
        ctx.db.commit()
        return result
    monkeypatch.setattr(sync, '_fetch', fetch)
    with pytest.raises(HTTPException): run(ctx)
    assert rows(ctx.db)[0][1] == (99 if case == 'stock' else 2)
    assert not ctx.db.scalar(select(InventorySyncLog))


def test_commit_failure_rolls_back_stock_and_audit(ctx, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    def fail(): raise SQLAlchemyError('failed')
    monkeypatch.setattr(ctx.db, 'commit', fail)
    with pytest.raises(HTTPException) as error: run(ctx)
    assert error.value.status_code == 503
    assert rows(ctx.db)[0] == (11, 2, 3, 0)
    assert not ctx.db.scalar(select(InventorySyncLog))


def test_existing_fresher_snapshot_is_not_relabelled(ctx):
    ctx.db.execute(text("UPDATE lsordertest.okki_inventory SET synced_at='2026-11-06 12:00:00' WHERE product_id=11"))
    ctx.db.commit()
    with pytest.raises(HTTPException) as error: run(ctx)
    assert error.value.status_code == 409
    assert rows(ctx.db)[0] == (11, 2, 3, 0)


@pytest.mark.parametrize('mode', ['local', 'routed', 'missing'])
def test_ineligible_product_does_not_call_provider(ctx, monkeypatch, mode):
    if mode == 'local': ctx.settings.TRANSACTION_MODE = 'local'
    if mode == 'routed': monkeypatch.setattr(sync, 'legacy_excluded_products', lambda db: {'11'})
    if mode == 'missing':
        ctx.db.execute(text('DELETE FROM lsordertest.okki_products WHERE product_id=11'))
        ctx.db.commit()
    with pytest.raises(HTTPException): run(ctx)
    assert ctx.calls == []


def test_route_requires_both_permissions_and_valid_product_identity(ctx, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.stock.router import router
    from app.core.database import get_db
    from app.auth.dependencies import get_current_user
    app = FastAPI()
    app.include_router(router, prefix='/api/stock')
    app.dependency_overrides[get_db] = lambda: ctx.db
    user = {'sub': '1', 'permissions': ['stock:read'], 'roles': []}
    app.dependency_overrides[get_current_user] = lambda: user
    calls = []
    monkeypatch.setattr(sync, 'sync_product_inventory', lambda db, pid, actor: calls.append(pid) or {'product_id': pid})
    with TestClient(app) as client:
        assert client.post('/api/stock/overview/11/sync-inventory').status_code == 403
        assert calls == []
        user['permissions'].append('stock:write')
        assert client.post('/api/stock/overview/0/sync-inventory').status_code == 422
        assert client.post('/api/stock/overview/ark:sku:11/sync-inventory').status_code == 422
        response = client.post('/api/stock/overview/11/sync-inventory')
        assert response.status_code == 200 and response.json()['data']['product_id'] == 11
        assert calls == [11]


def test_audit_model_is_registered_for_migrations():
    from app.models import InventorySyncLog as registered
    assert registered is InventorySyncLog


@pytest.mark.parametrize('hour,minute,expected', [(15,59,'2026-11-06T23:59:00'), (16,0,'2026-11-07T00:00:00')])
def test_beijing_observation_time_across_midnight(ctx, monkeypatch, hour, minute, expected):
    from app.core import time
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026,11,6,hour,minute,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(time, 'datetime', Clock)
    monkeypatch.setattr(sync, 'beijing_now', time.beijing_now)
    assert run(ctx)['synced_at'] == expected
