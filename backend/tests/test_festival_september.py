"""September screen: isolated SQLite facts and exact first-team ranking."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.festival import public_router, september_service as svc, service


@pytest.fixture
def september_db(monkeypatch):
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS lsordertest"))
        conn.execute(text('CREATE TABLE lsordertest.user_rel_team (user_id TEXT, Team TEXT)'))
        conn.execute(text('CREATE TABLE lsordertest.okki_orders (order_id TEXT PRIMARY KEY, company_id TEXT, '
                          'user_id TEXT, account_date TEXT, amount_usd NUMERIC, custom_fields TEXT, '
                          'trail TEXT, status TEXT, status_name TEXT)'))
        conn.commit()
    with Session(engine) as db:
        for index, (name, _) in enumerate(svc.TARGETS):
            users = [svc.JIASHU_USER_ID] if name == '嘉树' else [f'U{index}a', f'U{index}b']
            for uid in users:
                db.execute(text('INSERT INTO lsordertest.user_rel_team VALUES (:uid, :team)'),
                           {'uid': uid, 'team': '个人队' if name == '嘉树' else name})
        monkeypatch.setattr(svc, 'beijing_today', lambda: date(2026, 9, 17))
        yield db
    engine.dispose()


def order(db, oid, cid, uid='U0a', day='2026-09-10', amount=100, mark='是', status='13972831656', trail='公司'):
    db.execute(text('INSERT INTO lsordertest.okki_orders VALUES (:oid,:cid,:uid,:day,:amt,:mark,:trail,:status,:sn)'),
               {'oid': oid, 'cid': cid, 'uid': uid, 'day': day, 'amt': amount,
                'mark': json.dumps({'22595163468': mark}, ensure_ascii=False), 'trail': trail,
                'status': status, 'sn': '已结清' if status == '13972831656' else '待回款'})


def test_monthly_distinct_history_status_and_scope(september_db):
    db = september_db
    order(db, 'one', 'C1', amount=10)
    order(db, 'split', 'C1', amount=20, uid='U0b')
    order(db, 'old', 'C2', day='2026-08-31', uid='outside')
    order(db, 'duplicate-old', 'C2')
    order(db, 'future', 'C3', day='2026-09-18')
    order(db, 'october', 'C4', day='2026-10-01')
    order(db, 'cancelled', 'C5', status='cancelled')
    order(db, 'unsettled', 'C6', status='13972831654')
    order(db, 'private', 'C7', trail='个人订单')
    order(db, 'outside', 'C8', uid='outside')
    order(db, 'repurchase', 'C9', mark='否')
    order(db, 'zero-sample', 'C10', amount=0)
    payload = svc.get_payload(db)
    assert payload['total']['done'] == 2
    assert payload['total']['target'] == 113
    assert payload['groups'][0]['done'] == 2
    assert sum(row['done'] for row in payload['groups']) == 2
    assert payload['data_quality']['ok']
    assert 'amount' not in json.dumps(payload)  # Sorting amounts never leave service.
    assert service.COMPANY_NEW_SIGN_TARGET == 143
    assert service.ACTIVITY_NEW_SIGN_WINDOW == ('2026-08-01', '2026-08-31')


def test_status_refund_and_negative_correction_recalculate(september_db):
    db = september_db
    order(db, 'sale', 'C1', amount=100)
    assert svc.get_payload(db)['total']['done'] == 1
    db.execute(text("UPDATE lsordertest.okki_orders SET status='cancelled' WHERE order_id='sale'"))
    assert svc.get_payload(db)['total']['done'] == 0
    db.execute(text("UPDATE lsordertest.okki_orders SET status='13972831656' WHERE order_id='sale'"))
    order(db, 'refund', 'C1', amount=-100)
    order(db, 'negative-only', 'C2', amount=-1)
    assert svc.get_payload(db)['total']['done'] == 0
    db.execute(text("UPDATE lsordertest.okki_orders SET amount_usd=-40 WHERE order_id='refund'"))
    assert svc.get_payload(db)['total']['done'] == 1


def test_prior_effective_sales_without_new_mark_and_reversed_history(september_db):
    db = september_db
    order(db, 'history-unmarked', 'old', day='2026-08-02', mark='否', uid='outside')
    order(db, 'incorrect-new', 'old')
    order(db, 'history-sale', 'reversed', day='2026-08-02', amount=100)
    order(db, 'history-refund', 'reversed', day='2026-08-03', amount=-100, mark='否')
    order(db, 'first-effective', 'reversed', uid='U1a')
    order(db, 'history-sample', 'sample', day='2026-08-02', amount=0)
    order(db, 'duplicate-sample', 'sample')
    result = svc.get_payload(db)
    assert result['total']['done'] == 1
    assert result['groups'][0]['done'] == 0
    assert result['groups'][1]['done'] == 1


def test_cross_team_conflict_blocks_champion_and_total(september_db):
    order(september_db, 'one', 'C1')
    order(september_db, 'other', 'C1', uid='U1a')
    result = svc.get_payload(september_db)
    assert result['total']['done'] is None
    assert result['champion']['state'] == 'data_issue'
    assert not result['champion']['names']
    assert result['data_quality']['counts']['conflicting_customers'] == 1
    assert 'C1' not in json.dumps(result)


def test_unknown_missing_and_departed_roster(september_db):
    db = september_db
    db.execute(text("INSERT INTO lsordertest.user_rel_team VALUES ('57130433','星星之火')"))
    order(db, 'departed', 'C1', uid='57130433')
    assert svc.get_payload(db)['total']['done'] == 0
    assert svc.get_payload(db)['groups'][2]['members'] == 2
    db.execute(text("UPDATE lsordertest.user_rel_team SET Team='未分组' WHERE user_id='U0a'"))
    assert not svc.get_payload(db)['data_quality']['ok']
    db.execute(text('DELETE FROM lsordertest.user_rel_team'))
    result = svc.get_payload(db)
    assert result['total']['done'] is None
    assert result['data_quality']['counts']['missing_groups'] == 8


def test_duplicate_roster_does_not_duplicate_orders(september_db):
    september_db.execute(text("INSERT INTO lsordertest.user_rel_team VALUES ('U0a','乘风')"))
    order(september_db, 'one', 'C1')
    result = svc.get_payload(september_db)
    assert result['total']['done'] == 1
    assert result['groups'][0]['members'] == 2


def test_missing_customer_fails_closed(september_db):
    order(september_db, 'one', None)
    assert not svc.get_payload(september_db)['data_quality']['ok']


def test_exact_ratio_amount_tie_and_eligibility():
    rows = [
        {'name': 'A', 'done': 12, 'target': 10, 'members': 2, 'solo': False, '_amount': Decimal('100.01')},
        {'name': 'B', 'done': 18, 'target': 15, 'members': 2, 'solo': False, '_amount': Decimal('100.02')},
        {'name': '嘉树', 'done': 9, 'target': 5, 'members': 1, 'solo': True, '_amount': Decimal('1000')},
        {'name': 'one', 'done': 30, 'target': 5, 'members': 1, 'solo': False, '_amount': Decimal('1000')},
    ]
    assert svc.champion_names(rows) == ['B']
    rows[0]['_amount'] = Decimal('100.02')
    assert svc.champion_names(rows) == ['A', 'B']
    rows[0].update(done=12001, target=10000)
    assert svc.champion_names(rows) == ['A']  # Both display 120.0%, but A is greater.
    rows[0]['done'] = rows[1]['done'] = 0
    assert svc.champion_names(rows) == []


def test_phase_uses_beijing_boundary(september_db, monkeypatch):
    from app.core import time as core_time
    monkeypatch.setattr(svc, 'beijing_today', core_time.beijing_today)
    class Clock:
        @classmethod
        def now(cls, tz):
            return cls.instant.astimezone(tz)
    monkeypatch.setattr(core_time, 'datetime', Clock)
    Clock.instant = datetime(2026, 8, 31, 15, 59, tzinfo=timezone.utc)
    assert svc.get_payload(september_db)['phase'] == 'upcoming'
    Clock.instant = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
    assert svc.get_payload(september_db)['phase'] == 'ongoing'
    Clock.instant = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
    assert svc.get_payload(september_db)['phase'] == 'pending_review'
    assert svc.get_payload(september_db, finalized=True)['phase'] == 'finalized'


def test_endpoint_key_cache_and_fixed_period(monkeypatch):
    app = FastAPI()
    app.include_router(public_router.router, prefix='/api/public/festival')
    app.dependency_overrides[get_db] = lambda: None
    cfg = SimpleNamespace(FESTIVAL_SCREEN_KEYS='test-key', FESTIVAL_SEPTEMBER_FINALIZED=False)
    monkeypatch.setattr(public_router, 'get_settings', lambda: cfg)
    calls = []
    monkeypatch.setattr(svc, 'get_payload', lambda db, **kwargs: calls.append(kwargs) or {'period': {'start': '2026-09-01'}})
    public_router._CACHE.clear()
    with TestClient(app) as client:
        url = '/api/public/festival/september-new-sign'
        assert client.get(url).status_code == 403
        assert client.get(url + '?key=wrong').status_code == 403
        assert not calls
        assert client.get(url + '?key=test-key&date_from=2026-08-01').json()['data']['period']['start'] == '2026-09-01'
        assert client.get(url + '?key=test-key').status_code == 200
        assert len(calls) == 1
        cfg.FESTIVAL_SCREEN_KEYS = ''
        assert client.get(url + '?key=test-key').status_code == 403  # Cache cannot bypass revoked key.
    public_router._CACHE.clear()
