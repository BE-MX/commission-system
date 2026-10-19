"""Source detail reconciliation and authorization, isolated SQLite + pure facts."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.battle_report import award_statistics as stats, order_details
from app.auth.service import _perm_kind
from tests.test_battle_awards import campaign, fact, member
from tests.test_battle_reports import setup, become


@pytest.fixture
def details(setup, monkeypatch):
    s = setup
    raw = [
        fact('10', uid='U2', day='2026-09-15', amount='100.001'),
        fact('11', uid='U3', day='2026-09-16', amount='200.009'),
        fact('12', uid='outside', day='2026-09-20', amount='300', new=False),
        fact('9', uid='U2', day='2026-09-15', amount='999', new=False),
        fact('20', uid='U3', cid='C2', day='2026-09-18', amount='40'),
        fact('21', uid='U3', cid='C2', day='2026-09-21', amount='50', new=False),
        fact('30', uid='U1', cid='C3', day='2026-09-19', amount='60'),
        fact('40', uid='U2', cid='OLD', day='2026-09-20', amount='999', new=False),
        fact('freight', uid='U2', day='2026-09-20', amount='999', goods=False),
        fact('future', uid='U2', day='2026-09-24', amount='999'),
    ]
    for row in raw:
        row.update(order_no='NO-' + row['order_id'], order_name='发制品-' + row['order_id'],
                   company_name='客户-' + row['company_id'])
    raw.append(dict(raw[0]))
    monkeypatch.setattr(order_details, 'source_facts', lambda *args: (raw, '2026-09-22T10:00:00'))
    monkeypatch.setattr(order_details, 'beijing_now', lambda: datetime(2026, 9, 22, 12))
    s.raw = raw
    return s


def get(s, metric='combined', **params):
    return s.client.get(s.url + '/metric-orders', params={'metric': metric, **params})


def test_tabs_reconcile_to_same_annual_statistics(details):
    s = details
    # Summary membership IDs match the stored roster; original cohort ownership
    # survives both a new-sign transfer and a repeat to a nonparticipant.
    roster = [member(i) for i in (1, 2, 3)]
    data = stats.calculate(campaign(baselines={1: 100, 2: 100, 3: 100}), roster, s.raw, datetime(2026, 9, 22))
    new = get(s, 'new_sign').json()['data']
    repeat = get(s, 'repeat').json()['data']
    combined = get(s).json()['data']
    assert new['customer_count'] == sum(r['new_count'] for r in data['people']) == 3
    assert repeat['customer_count'] == sum(r['repeat_count'] for r in data['people']) == 2
    assert repeat['total'] == sum(r['repeat_orders'] for r in data['people']) == 2
    assert Decimal(combined['total_amount']) == sum(Decimal(r['repeat_amount']) for r in data['people']) == Decimal('750.010')
    assert new['total'] == 4 and combined['total'] == 6


def test_scope_cannot_be_expanded_by_transfer_or_filters(details):
    s = details
    become(s, 2)
    data = get(s).json()['data']
    assert {r['order_id'] for r in data['items']} == {'10', '11', '12'}
    assert data['total_amount'] == '600.01'
    assert get(s, member_id=s.report['members'][2]['id']).status_code == 403
    assert get(s, team='B').status_code == 403
    become(s, 3)
    assert {r['order_id'] for r in get(s).json()['data']['items']} == {'20', '21'}
    become(s, 1)  # Captain can inspect own team, but not team B.
    assert {r['order_id'] for r in get(s).json()['data']['items']} == {'10', '11', '12', '30'}


def test_read_all_nonparticipant_can_read_but_not_administer(details):
    s = details
    become(s, 4, ('battle_report:read', 'battle_report:read_all'))
    assert get(s).json()['data']['total'] == 6
    assert s.client.get('/api/battle-reports').json()['data']['items'][0]['id'] == s.report['id']
    assert not s.client.get(s.url).json()['data']['can_admin']
    assert s.client.put(s.url, json={**s.payload, 'version': 2}).status_code == 403
    assert s.client.post(s.url + '/state', json={'action': 'archive', 'version': 2}).status_code == 403
    assert s.client.get(s.url + '/audits').status_code == 403
    become(s, 4, ('battle_report:read', 'battle_report:read_all', 'battle_report:write'))
    assert s.client.put(s.url + '/targets', json={'targets': [
        {'member_id': s.report['members'][0]['id'], 'version': 1, 'target_usd': '100'}]}).status_code == 403
    assert _perm_kind('battle_report:read_all', 'read_all') == 'data'
    # Scope permission never substitutes for the page permission.
    become(s, 4, ('battle_report:read_all',))
    assert get(s).status_code == 403


def test_nonparticipant_and_draft_denied(details):
    s = details
    become(s, 4)
    assert get(s).status_code == 403
    become(s, 0, ('battle_report:admin',))
    draft = s.client.post('/api/battle-reports', json=s.payload).json()['data']['id']
    become(s, 4, ('battle_report:read', 'battle_report:read_all'))
    assert s.client.get(f'/api/battle-reports/{draft}/metric-orders?metric=combined').status_code == 403
    assert draft not in [r['id'] for r in s.client.get('/api/battle-reports').json()['data']['items']]


def test_binding_revocation_is_enforced(details):
    s = details
    become(s, 2)
    from app.auth.models import ArkUserExternalBinding
    s.db.query(ArkUserExternalBinding).filter_by(ark_user_id=s.users[2].id).update({'binding_status': 'disabled'})
    s.db.commit()
    assert get(s).status_code == 422


def test_filters_and_full_totals_before_pagination(details):
    s = details
    first = get(s, customer='客户-C1', page_size=1).json()['data']
    second = get(s, customer='客户-C1', page_size=1, page=2).json()['data']
    assert first['total'] == second['total'] == 3
    assert first['total_amount'] == second['total_amount'] == '600.01'
    assert first['items'][0]['order_id'] == '12' and second['items'][0]['order_id'] == '11'
    filtered = get(s, customer='客户-C1', order_name='发制品-11', start_date='2026-09-16', end_date='2026-09-16').json()['data']
    assert filtered['total'] == 1 and filtered['total_amount'] == '200.01'
    assert get(s, start_date='2026-09-22', end_date='2026-09-15').status_code == 422
    for params in ({'page_size': 101}, {'page': 0}, {'start_date': 'bad'}):
        assert get(s, **params).status_code == 422
    assert get(s, metric='unknown').status_code == 422
    for field in ('account_date', 'amount_usd', 'company_name', 'order_name', 'order_no', 'user_name'):
        assert get(s, sort_field=field, sort_order='asc', page_size=1).status_code == 200
    ascending = get(s, sort_field='amount_usd', sort_order='asc', page_size=1).json()['data']
    assert ascending['items'][0]['order_id'] == '20'
    empty = get(s, customer='does-not-exist').json()['data']
    assert empty['total'] == empty['customer_count'] == 0 and empty['total_amount'] == '0.00'


def test_incomplete_warning_does_not_leak_other_order_identity(details):
    s = details
    s.raw.append({**fact('SECRET-ORDER', uid='U3', day='2026-09-18'), 'custom_fields': '{}'})
    become(s, 2)
    response = get(s)
    assert not response.json()['data']['data_complete']
    assert '待核对' in response.json()['data']['warning']
    assert 'SECRET-ORDER' not in response.text


def test_real_source_query_returns_names_and_filters_status(setup, monkeypatch):
    s = setup
    # Existing fixture uses a private attached SQLite mirror. Add only its missing
    # sync column and substitute the MySQL-specific freight predicate for SQLite.
    s.db.execute(text('ALTER TABLE lsordertest.okki_orders ADD COLUMN synced_at TEXT'))
    monkeypatch.setattr(stats, 'goods_order_sql', lambda alias: '1')
    monkeypatch.setattr(order_details, 'beijing_now', lambda: datetime(2026, 9, 22, 12))
    s.db.execute(text("INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES ('DETAIL-C', '来源客户')"))
    s.db.execute(text("""UPDATE lsordertest.okki_orders SET company_id='DETAIL-C', name='来源订单',
        custom_fields='{"22595163468":"是"}' WHERE order_id='O1'"""))
    response = get(s, 'new_sign')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['total'] == 1
    assert data['items'][0]['company_name'] == '来源客户'
    assert data['items'][0]['order_name'] == '来源订单'


def test_pk_cohort_details_explicitly_distinguish_owner_based_pk_amount(details):
    from app.battle_report.models import BattleReport
    s = details
    report = s.db.get(BattleReport, s.report['id'])
    report.award_kind = 'new_sign_pk'
    s.db.flush()
    become(s, 2)
    data = get(s, 'new_sign').json()['data']
    assert data['customer_count'] == 1 and data['total_amount'] == '300.01'
    assert data['amount_scope'] == 'original_new_customer_cohort'
    assert '订单负责人' in data['amount_note']
    # Do not silently change existing PK reward/tiebreak statistics.
    pk_report = campaign('new_sign_pk')
    pk_report.start_date, pk_report.end_date = report.start_date, report.end_date
    snapshot = stats.calculate(pk_report, [member(2), member(3)], s.raw, datetime(2026, 9, 22))
    assert snapshot['people'][0]['new_amount'] == '100.001'
