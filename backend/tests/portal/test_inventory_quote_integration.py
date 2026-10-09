from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from test_quotes import quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, body
from app.core.time import beijing_now
from app.portal import auth_service, catalog_service, inventory_source, order_service, quote_service
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Quote
from app.portal.schemas import SubmitInput


@pytest.fixture
def live_source(quoting, monkeypatch):
    ctx = quoting
    ctx.settings.PORTAL_INVENTORY_OBSERVED_COLUMN = 'synced_at'
    ctx.settings.PORTAL_INVENTORY_SOURCE_TIMEZONE = 'Asia/Shanghai'
    ctx.settings.PORTAL_INVENTORY_UNIT_BY_SKU = {f'{item.product_id}:{item.sku_id}':'g' for item in ctx.items}
    monkeypatch.setattr(inventory_source, 'get_settings', lambda: ctx.settings)
    # Replace the older fixture's injected observations with the actual SQL adapter.
    monkeypatch.setattr(catalog_service, 'load_observations', inventory_source.load)
    ctx.db.execute(text('CREATE TABLE okki_inventory (product_id INTEGER, sku_id INTEGER, enable_count TEXT, disable_flag INTEGER, synced_at TEXT)'))
    for item in ctx.items:
        ctx.db.execute(text('INSERT INTO okki_inventory VALUES (:p,:s,\'1000\',0,:t)'),
            {'p':int(item.product_id),'s':int(item.sku_id),'t':(beijing_now()-timedelta(seconds=5)).isoformat()})
    ctx.db.commit()
    return ctx


def make_quote(ctx):
    result = quote_service.create(ctx.db, ctx.session_token, ctx.session_csrf, body(ctx))
    ctx.db.commit()
    return result


def submission(quote):
    return SubmitInput(quote_id=UUID(quote['quote_id']), quote_content_hash=quote['content_hash'], customer_po='PO-1', remark='Please review')


def test_catalog_quote_and_submission_read_actual_mirror_without_leaking_counts(live_source):
    ctx = live_source
    principal, _ = auth_service.authenticate(ctx.db, ctx.session_token)
    listing = catalog_service.list_catalog(ctx.db, principal)
    assert all(item['availability'] == 'available' for item in listing['items'])
    assert all('quantity' not in item and 'source' not in item for item in listing['items'])
    quote = make_quote(ctx)
    stored = ctx.db.scalar(select(Quote))
    snapshot = stored.lines_json[0]['inventory_snapshot']
    assert snapshot['quantity'] == '1000.000000' and snapshot['unit'] == 'g'
    assert snapshot['source'].startswith('okki_inventory:')
    assert 'inventory_snapshot' not in quote['items'][0]
    result = order_service.submit(ctx.db, ctx.session_token, ctx.session_csrf, uuid4(), submission(quote))
    ctx.db.commit()
    assert result['status'] == 'submitted'
    assert ctx.db.scalar(select(func.count()).select_from(OrderRequest)) == 1


@pytest.mark.parametrize('change,code', [('quantity','STOCK_CHANGED'), ('stale','INVENTORY_UNAVAILABLE'),
    ('unit','INVENTORY_UNAVAILABLE'), ('missing','INVENTORY_UNAVAILABLE')])
def test_submit_rechecks_mirror_after_quote_and_never_creates_order_on_failure(live_source, change, code):
    ctx = live_source
    quote = make_quote(ctx)
    if change == 'quantity':
        ctx.db.execute(text("UPDATE okki_inventory SET enable_count='0'"))
    elif change == 'stale':
        ctx.db.execute(text('UPDATE okki_inventory SET synced_at=:t'), {'t':(beijing_now()-timedelta(seconds=121)).isoformat()})
    elif change == 'unit':
        ctx.settings.PORTAL_INVENTORY_UNIT_BY_SKU = {key:'piece' for key in ctx.settings.PORTAL_INVENTORY_UNIT_BY_SKU}
    else:
        ctx.db.execute(text('DELETE FROM okki_inventory'))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        order_service.submit(ctx.db, ctx.session_token, ctx.session_csrf, uuid4(), submission(quote))
    assert caught.value.code == code
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(OrderRequest)) == 0


def test_successful_replay_does_not_depend_on_fresh_inventory(live_source):
    ctx = live_source
    quote = make_quote(ctx)
    key = uuid4()
    first = order_service.submit(ctx.db, ctx.session_token, ctx.session_csrf, key, submission(quote))
    ctx.db.commit()
    ctx.db.execute(text('DELETE FROM okki_inventory'))
    ctx.db.commit()
    second = order_service.submit(ctx.db, ctx.session_token, ctx.session_csrf, key, submission(quote))
    assert second['replayed'] and first['request_id'] == second['request_id']
    assert ctx.db.scalar(select(func.count()).select_from(OrderRequest)) == 1
