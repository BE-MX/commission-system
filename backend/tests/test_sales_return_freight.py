"""Goods and freight quotas must survive the complete return lifecycle independently."""
from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.sales_return import balance, policy, read_service, schemas, service
from app.sales_return.models import ReturnAllocation, ReturnEffect, ReturnReceipt
from tests.test_sales_return_service import USER, env, facts  # noqa: F401


def freight_facts():
    source = facts('570.00')
    source.update(goods_amount='570.00', goods_amount_usd='570.00')
    line = source['lines'][0]
    source['lines'] = [dict(line, source_key=f'OUT-1:LINE-{i}', outbound_line_id=f'LINE-{i}',
        order_line_id=f'ORDER-LINE-{i}', quantity=qty, net_amount=amount, net_amount_usd=amount)
        for i, qty, amount in [(1, 150, '283.50'), (2, 100, '192.00'), (3, 50, '94.50')]]
    source['payments'][0].update(cash_principal='649.02', cash_principal_usd='649.02',
        non_goods_amount='79.02', non_goods_amount_usd='79.02', commission_basis_usd='649.02',
        freight_principal='48.11', freight_principal_usd='48.11')
    return source


def freight_body(**changes):
    values = dict(order_id='101', return_type='refund_only', reason_code='quality',
        reason='Verified goods and freight refund', freight_refund_amount='11.18', refund_amount='297.68',
        request_key='freight-draft-key-0001', lines=[
            dict(source_key='OUT-1:LINE-2', quantity=100, reduction_amount='192.00'),
            dict(source_key='OUT-1:LINE-3', quantity=50, reduction_amount='94.50')])
    return schemas.Create(**(values | changes))


def test_exact_26008_goods_and_freight_quote():
    quote = policy.price(freight_facts(), freight_body())
    assert quote['reduction_amount'] == '286.50'
    assert quote['freight_refund_amount'] == '11.18'
    assert quote['goods_refund_amount'] == '286.50'
    assert quote['refund_amount'] == quote['refund_usd'] == '297.68'
    assert quote['waived_amount'] == '0.00'
    assert quote['balance']['net_outstanding'] == '0.00'
    assert quote['freight_remaining'] == '36.93'
    allocation, = quote['allocations']
    assert allocation['original_principal'] == '618.11'  # excludes surcharge
    assert allocation['refund_amount'] == '297.68'
    assert allocation['freight_refund_amount'] == '11.18'


def test_goods_limit_cannot_be_bypassed_using_freight():
    body = freight_body()
    body.lines[0].reduction_amount = Decimal('202.12')
    with pytest.raises(ValueError, match='净货值'):
        policy.price(freight_facts(), body)
    with pytest.raises(ValueError, match='运费'):
        policy.price(freight_facts(), freight_body(freight_refund_amount='48.12', refund_amount=None))


def test_independent_history_and_reverse_restore_freight(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    body = freight_body()
    quote = service.preview(db, body, USER)
    row = service.create(db, body, USER)
    assert read_service.draft_body(db, row).freight_refund_amount == Decimal('11.18')
    command = schemas.Activate(version=row.version, quote_version=quote['quote_version'], request_key='freight-activate-0001')
    service.activate(db, row.id, command, USER)
    assert service.activate(db, row.id, command, USER).id == row.id
    effect = db.scalar(select(ReturnEffect))
    assert effect.amount == effect.amount_usd == Decimal('-286.50')
    assert effect.freight_amount == effect.freight_amount_usd == Decimal('-11.18')
    assert db.scalar(select(ReturnReceipt.amount)) == Decimal('-297.68')
    history = read_service.history(db, '101')
    assert history['refunds']['PAY-1'] == Decimal('286.50')
    assert history['freight_refunds']['PAY-1'] == Decimal('11.18')
    summary = {'total_amount':'649.02', 'registered_amount':'649.02', 'effective_amount':'649.02', 'version':'before'}
    adjusted = balance.overlay(db, '101', summary)
    assert adjusted['remaining_amount'] == '0.00'
    assert adjusted['total_amount'] == adjusted['registered_amount'] == '351.34'
    reverse = schemas.Reverse(version=row.version, request_key='freight-reverse-0001', reason='Verified correction')
    service.reverse(db, row.id, reverse, USER)
    assert sum(db.scalars(select(ReturnEffect.freight_amount))) == 0
    assert sum(db.scalars(select(ReturnReceipt.amount))) == 0
    assert balance.overlay(db, '101', summary) == summary
    assert service.preview(db, body, USER)['freight_remaining'] == '36.93'


def test_cumulative_goods_then_freight_caps_exclude_surcharge(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    first = freight_body()
    quote = service.preview(db, first, USER)
    row = service.create(db, first, USER)
    service.activate(db, row.id, schemas.Activate(version=row.version, quote_version=quote['quote_version'],
        request_key='freight-activate-first'), USER)
    second = freight_body(request_key='freight-create-second', freight_refund_amount='36.93', refund_amount=None,
        lines=[dict(source_key='OUT-1:LINE-1', quantity=150, reduction_amount='283.50')])
    quote = service.preview(db, second, USER)
    assert quote['refund_amount'] == '320.43'
    assert quote['freight_remaining'] == '0.00'
    assert quote['balance']['net_received'] == quote['balance']['net_receivable'] == '0.00'
    excessive = second.model_copy(update={'freight_refund_amount': Decimal('36.94')})
    with pytest.raises(ValueError, match='运费'):
        service.preview(db, excessive, USER)
    row = service.create(db, second, USER)
    service.activate(db, row.id, schemas.Activate(version=row.version, quote_version=quote['quote_version'],
        request_key='freight-activate-second'), USER)
    assert sum(db.scalars(select(ReturnAllocation.refund_amount))) == Decimal('618.11')
    summary = dict(total_amount='649.02', registered_amount='649.02', effective_amount='649.02', version='original')
    result = balance.overlay(db, '101', summary)
    assert result['total_amount'] == result['registered_amount'] == '30.91'
    assert result['remaining_amount'] == '0.00'


@pytest.mark.parametrize('kind', ['return_refund', 'refund_only'])
def test_default_cash_includes_freight_and_canonicalizes_decimal_input(kind):
    implicit = policy.price(freight_facts(), freight_body(return_type=kind, refund_amount=None))
    explicit = policy.price(freight_facts(), freight_body(return_type=kind, freight_refund_amount='11.180'))
    assert implicit['refund_amount'] == '297.68'
    assert implicit['quote_version'] == explicit['quote_version']


@pytest.mark.parametrize('change', ['missing', 'foreign', 'presale', 'multiple', 'surcharge', 'cash', 'fx'])
def test_unproven_freight_does_not_become_refundable(change):
    source = freight_facts()
    if change == 'missing':
        source['payments'][0].pop('freight_principal')
    elif change == 'foreign':
        source['currency'] = 'EUR'
    elif change == 'presale':
        source['funding_batches'] = []
    elif change == 'multiple':
        source['payments'].append(dict(source['payments'][0], payment_id='PAY-2'))
    elif change == 'surcharge':
        source['payments'][0]['freight_principal'] = '79.03'
    elif change == 'cash':
        source['payments'][0]['cash_principal'] = '600.00'
    else:
        source['payments'][0]['freight_principal_usd'] = '47.00'
    with pytest.raises(ValueError, match='运费|本金'):
        policy.price(source, freight_body())


def test_goods_only_second_refund_does_not_consume_prior_freight(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    body = freight_body()
    quote = service.preview(db, body, USER)
    row = service.create(db, body, USER)
    service.activate(db, row.id, schemas.Activate(version=1, quote_version=quote['quote_version'],
        request_key='first-freight-activation'), USER)
    next_body = freight_body(freight_refund_amount='0', refund_amount=None, lines=[
        dict(source_key='OUT-1:LINE-1', quantity=150, reduction_amount='283.50')])
    next_quote = service.preview(db, next_body, USER)
    assert next_quote['refund_amount'] == '283.50'
    assert next_quote['balance']['net_outstanding'] == '0.00'
    assert next_quote['freight_remaining'] == '36.93'
    lines = read_service.order_lines(db, '101', USER)
    assert lines['freight_refund_available'] == '36.93'


def test_two_drafts_cannot_spend_same_freight_twice(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    first_body = freight_body(freight_refund_amount='40.00', refund_amount=None)
    second_body = freight_body(request_key='competing-freight-draft', freight_refund_amount='20.00',
        refund_amount=None, lines=[dict(source_key='OUT-1:LINE-1', quantity=150, reduction_amount='283.50')])
    first_quote = service.preview(db, first_body, USER)
    second_quote = service.preview(db, second_body, USER)
    first = service.create(db, first_body, USER)
    second = service.create(db, second_body, USER)
    service.activate(db, first.id, schemas.Activate(version=1, quote_version=first_quote['quote_version'],
        request_key='competing-freight-first'), USER)
    with pytest.raises(ValueError, match='运费'):
        service.activate(db, second.id, schemas.Activate(version=1, quote_version=second_quote['quote_version'],
            request_key='competing-freight-second'), USER)
    assert second.status == 'draft'
    assert len(db.scalars(select(ReturnReceipt)).all()) == 1


def test_freight_evidence_change_invalidates_quote_and_effective_snapshot(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    body = freight_body()
    quote = service.preview(db, body, USER)
    row = service.create(db, body, USER)
    source['payments'][0].update(freight_principal='48.10', freight_principal_usd='48.10')
    with pytest.raises(HTTPException, match='409'):
        service.activate(db, row.id, schemas.Activate(version=1, quote_version=quote['quote_version'],
            request_key='changed-freight-activation'), USER)
    fresh = service.preview(db, body, USER)
    service.activate(db, row.id, schemas.Activate(version=1, quote_version=fresh['quote_version'],
        request_key='fresh-freight-activation'), USER)
    source['payments'][0].update(freight_principal='48.11', freight_principal_usd='48.11')
    with pytest.raises(HTTPException, match='运费'):
        service.preview(db, body, USER)


def test_old_zero_freight_request_hash_and_draft_remain_valid(env):
    from tests.test_sales_return_service import draft
    db, _, _ = env
    body = draft()
    old_payload = body.model_dump(mode='json', exclude={'version', 'request_key', 'freight_refund_amount'})
    old_hash = policy.digest(old_payload)
    assert service._body_hash(body) == old_hash
    row = service.create(db, body, USER)
    row.request_hash = old_hash
    assert service.create(db, body, USER).id == row.id
    assert read_service.draft_body(db, row).freight_refund_amount == 0
    assert read_service.describe(db, row)['freight_refund_amount'] == '0.00'


def test_freight_cash_requires_recovery_before_reversal(env):
    db, source, _ = env
    source.clear(); source.update(freight_facts())
    quote = service.preview(db, freight_body(), USER)
    row = service.create(db, freight_body(), USER)
    service.activate(db, row.id, schemas.Activate(version=1, quote_version=quote['quote_version'],
        request_key='freight-cash-activation'), USER)
    service.cash(db, row.id, schemas.Cash(version=row.version, status='paid', evidence='Verified USD297.68 refund'), USER)
    with pytest.raises(HTTPException, match='资金收回'):
        service.reverse(db, row.id, schemas.Reverse(version=row.version,
            request_key='freight-cash-reversal', reason='Verified correction'), USER)
    service.cash(db, row.id, schemas.Cash(version=row.version, status='recovered', evidence='Verified USD297.68 recovery'), USER)
    service.reverse(db, row.id, schemas.Reverse(version=row.version,
        request_key='freight-cash-reversal', reason='Verified correction'), USER)
    assert sum(db.scalars(select(ReturnReceipt.amount))) == 0
    assert read_service.history(db, '101')['freight_refunds'] == {}


def test_http_freight_create_reopen_update_preview_activate(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.sales_return import receipt_sources
    from app.sales_return.router import router
    db, source, monkeypatch = env
    source.clear(); source.update(freight_facts())
    monkeypatch.setattr(receipt_sources, 'prepare', lambda *_args, **_kwargs: None)
    app = FastAPI()
    app.include_router(router, prefix='/api/sales-returns')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    body = freight_body().model_dump(mode='json')
    response = client.post('/api/sales-returns', json=body)
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    assert saved['freight_refund_amount'] == '11.18'
    identity = saved['id']
    read = client.get(f'/api/sales-returns/{identity}').json()['data']
    assert read['refund_amount'] == '297.68' and read['freight_refund_amount'] == '11.18'
    draft = {key: value for key, value in body.items() if key != 'request_key'}
    update = client.put(f'/api/sales-returns/{identity}', json={**draft, 'version': read['version']})
    assert update.status_code == 200, update.text
    preview = client.post('/api/sales-returns/preview', json=draft)
    assert preview.status_code == 200, preview.text
    quote = preview.json()['data']
    command = dict(version=update.json()['data']['version'], quote_version=quote['quote_version'],
        request_key='http-freight-activation')
    activated = client.post(f'/api/sales-returns/{identity}/activate', json=command)
    assert activated.status_code == 200, activated.text
    result = activated.json()['data']
    assert result['freight_refund_amount'] == '11.18'
    assert result['allocations'][0]['freight_refund_amount'] == '11.18'
    assert result['receipts'][0]['amount'] == '-297.68'
