"""Battle reports: isolated SQLite, real routes/services; no production connections."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser, ArkUserExternalBinding
from app.battle_report import query_service, service
from app.battle_report.models import BattleReportAudit, BattleReportMember
from app.battle_report.router import router
from app.battle_report.schemas import ReportInput
from app.battle_report.statistics import normalize_orders, time_progress
from app.core.database import get_db


@pytest.fixture
def setup(db, monkeypatch):
    now = datetime(2026, 9, 22, 12)
    monkeypatch.setattr(service, "beijing_now", lambda: now)
    monkeypatch.setattr(query_service, "beijing_now", lambda: now)
    users = [ArkUser(username=f"battle-{i}", password_hash="test-only", real_name=f"业务员{i}") for i in range(5)]
    db.add_all(users); db.flush()
    for i, user in enumerate(users[1:4], 1):
        db.add(ArkUserExternalBinding(ark_user_id=user.id, provider="okki", external_account_id=f"U{i}",
                                      is_primary=True, binding_status="active"))
    db.commit()
    app = FastAPI(); app.include_router(router, prefix="/api/battle-reports")
    app.dependency_overrides[get_db] = lambda: db
    identity = {"sub": str(users[0].id), "roles": ["super_admin"]}
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app)
    payload = {"name": "九月冲刺", "start_date": "2026-09-15", "end_date": "2026-09-28",
               "target_deadline": "2026-09-23T23:59:59", "members": [
                   {"ark_user_id": users[i].id, "team": "A" if i < 3 else "B", "is_captain": i == 1} for i in range(1, 4)]}
    response = client.post('/api/battle-reports', json=payload)
    assert response.status_code == 200, response.text
    report_id = response.json()['data']['id']
    url = f'/api/battle-reports/{report_id}'
    assert client.post(url+'/state', json={"action": "publish", "version": 1}).status_code == 200
    report = client.get(url).json()['data']
    for oid, uid, day, amount, status, trail in [
        ('O1', 'U1', '2026-09-15', '10.10', '13972831656', '公司'),
        ('O2', 'U1', '2026-09-22', '20.20', '13972831656', '公司'),
        ('O3', 'U2', '2026-09-22', '30.30', '13972831654', '公司'),
        ('O4', 'U3', '2026-09-22', '40.40', '13972831656', '公司'),
        ('future', 'U1', '2026-09-23', '999', '13972831656', '公司'),
        ('before', 'U1', '2026-09-14', '999', '13972831656', '公司'),
        ('cancelled', 'U1', '2026-09-22', '999', 'cancelled', '公司'),
        ('personal', 'U1', '2026-09-22', '999', '13972831656', '个人'),
    ]:
        db.execute(text("""INSERT INTO lsordertest.okki_orders
            (order_id, order_no, user_id, account_date, amount_usd, status, status_name, trail)
            VALUES (:oid,:oid,:uid,:day,:amount,:status,'已结清',:trail)"""),
                   dict(oid=oid, uid=uid, day=day, amount=amount, status=status, trail=trail))
    db.commit()
    yield SimpleNamespace(db=db, client=client, identity=identity, users=users, payload=payload, url=url, report=report)
    client.close()


def become(s, index, permissions=('battle_report:read', 'battle_report:write')):
    s.identity.clear(); s.identity.update(sub=str(s.users[index].id), roles=[], permissions=list(permissions))


def test_aggregates_reconcile_with_daily_and_orders(setup):
    s = setup
    targets = [{"member_id": m['id'], "version": 1, "target_usd": "20.00"} for m in s.report['members']]
    assert s.client.put(s.url+'/targets', json={"targets": targets}).status_code == 200
    data = s.client.get(s.url+'/overview').json()['data']
    assert data['summary']['gmv'] == '101.00'
    assert data['summary']['order_count'] == 4
    assert data['summary']['progress_percent'] == 168.3
    assert sum(Decimal(t['gmv']) for t in data['teams']) == Decimal('101')
    assert sum(Decimal(p['gmv']) for p in data['people']) == Decimal('101')
    assert sum(Decimal(d['gmv']) for d in data['daily']) == Decimal('101')
    daily = s.client.get(s.url+'/daily?start=2026-09-22').json()['data']
    assert sum(Decimal(r['cells'][0]['gmv']) for r in daily['rows']) == Decimal('90.90')
    assert daily['rows'][0]['cells'][1]['state'] == 'future'
    detail = s.client.get(s.url+'/orders?day=2026-09-22&page_size=1').json()['data']
    assert detail['gmv'] == '90.90' and detail['total'] == 3 and len(detail['items']) == 1


def test_missing_target_is_not_zero_attainment(setup):
    data = setup.client.get(setup.url+'/overview').json()['data']
    assert data['summary']['progress_percent'] is None
    assert data['summary']['filled'] == 0
    assert data['summary']['gmv'] == '101.00'


def test_member_can_see_summary_but_not_colleague_orders(setup):
    s = setup; become(s, 2)
    assert len(s.client.get(s.url+'/overview').json()['data']['people']) == 3
    mine = s.client.get(s.url+'/orders').json()['data']
    assert [o['order_id'] for o in mine['items']] == ['O3']
    other = s.report['members'][0]['id']
    assert s.client.get(s.url+f'/orders?member_id={other}').status_code == 403
    assert s.client.get(s.url+'/orders/O1').status_code == 404
    assert s.client.put(s.url+'/targets', json={"targets": [{"member_id": other,"version": 1,"target_usd": "10"}]}).status_code == 403


def test_captain_can_read_own_team_only(setup):
    s = setup; become(s, 1)
    assert s.client.get(s.url+'/orders').json()['data']['total'] == 3
    assert s.client.get(s.url+'/orders?team=B').status_code == 403
    assert s.client.get(s.url+'/orders/O4').status_code == 404


def test_nonparticipant_and_draft_are_denied(setup):
    s = setup; become(s, 4)
    assert s.client.get('/api/battle-reports').json()['data']['items'] == []
    assert s.client.get(s.url).status_code == 403
    assert s.client.get('/api/battle-reports/participants').status_code == 403


def test_scope_visibility_is_enforced_for_matrix_and_overview(setup):
    s = setup
    response = s.client.put(s.url, json={**s.payload, 'version': 2, 'visibility': 'self', 'reason': '调整可见范围'})
    assert response.status_code == 200, response.text
    become(s, 2)
    assert len(s.client.get(s.url+'/overview').json()['data']['people']) == 1
    assert len(s.client.get(s.url+'/daily').json()['data']['rows']) == 1
    assert s.client.get(s.url+'/overview?team=B').status_code == 403


def test_target_version_conflict_rolls_back_entire_batch(setup):
    s = setup; a, b = s.report['members'][:2]
    response = s.client.put(s.url+'/targets', json={'targets': [
        {'member_id': a['id'], 'version': 1, 'target_usd': '100'},
        {'member_id': b['id'], 'version': 99, 'target_usd': '200'}]})
    assert response.status_code == 409
    s.db.expire_all()
    assert s.db.get(BattleReportMember, a['id']).target_usd is None
    assert not s.db.query(BattleReportAudit).filter_by(action='targets').count()


@pytest.mark.parametrize('amount', ['0', '-1', 'NaN', 'Infinity', '1.001', '100000000000000'])
def test_invalid_targets_are_rejected(setup, amount):
    s = setup
    assert s.client.put(s.url+'/targets', json={'targets': [
        {'member_id': s.report['members'][0]['id'], 'version': 1, 'target_usd': amount}]}).status_code == 422


def test_deadline_and_admin_audit(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(service, 'beijing_now', lambda: datetime(2026, 9, 24))
    become(s, 2)
    target = {'targets': [{'member_id': s.report['members'][1]['id'], 'version': 1, 'target_usd': '50'}]}
    assert s.client.put(s.url+'/targets', json=target).status_code == 403
    s.identity['roles'] = ['super_admin']
    assert s.client.put(s.url+'/targets', json=target).status_code == 422
    assert s.client.put(s.url+'/targets', json={**target, 'reason': '修正录入金额'}).status_code == 200
    log = s.db.query(BattleReportAudit).filter_by(action='targets').one()
    assert log.before[0]['target_usd'] is None and log.after[0]['target_usd'] == '50.00'
    assert log.created_at == datetime(2026, 9, 24)


def test_activity_lifecycle_and_conflicts(setup):
    s = setup
    assert s.client.post(s.url+'/state', json={'action':'publish','version':2}).status_code == 409
    assert s.client.post(s.url+'/state', json={'action':'archive','version':1}).status_code == 409
    assert s.client.post(s.url+'/state', json={'action':'archive','version':2}).status_code == 200
    assert s.client.get('/api/battle-reports').json()['data']['items'] == []
    assert len(s.client.get('/api/battle-reports?archived=true').json()['data']['items']) == 1
    assert s.client.put(s.url+'/targets', json={'targets':[{'member_id':s.report['members'][0]['id'],'version':1,'target_usd':'10'}]}).status_code == 409
    assert s.client.post(s.url+'/state', json={'action':'restore','version':3}).status_code == 200


def test_anomalies_are_not_silent_zero(setup):
    s = setup
    s.db.execute(text("UPDATE lsordertest.okki_orders SET amount_usd=NULL WHERE order_id='O1'")); s.db.commit()
    data = s.client.get(s.url+'/overview').json()['data']
    assert data['issue_count'] == 1 and not data['summary']['data_complete']
    assert data['summary']['gmv'] == '90.90'
    assert data['teams'][1]['data_complete']
    assert s.client.get(s.url+'/orders').json()['data']['issues'][0]['order_no'] == 'O1'


def test_external_binding_revocation_fails_closed(setup):
    s = setup; become(s, 2)
    s.db.query(ArkUserExternalBinding).filter_by(ark_user_id=s.users[2].id).update({'binding_status':'inactive'}); s.db.commit()
    assert s.client.get(s.url+'/overview').status_code == 422


def test_snapshot_team_does_not_follow_live_organization(setup):
    s = setup
    s.users[1].okki_department_name = '其他部门'; s.db.commit()
    assert s.client.get(s.url).json()['data']['members'][0]['team'] == 'A'
    assert s.client.put(s.url, json={**s.payload,'version':2}).status_code == 422


def test_invalid_period_and_unbound_roster(setup):
    s = setup
    assert s.client.post('/api/battle-reports', json={**s.payload,'end_date':'2026-09-01'}).status_code == 422
    assert s.client.post('/api/battle-reports', json={**s.payload,'members':[{'ark_user_id':s.users[4].id,'team':'A'}]}).status_code == 422


def test_config_change_invalidates_old_goal_form(setup):
    s = setup
    assert s.client.put(s.url, json={**s.payload,'version':2,'reason':'调整周期',
        'start_date':'2026-10-01','end_date':'2026-10-07'}).status_code == 200
    stale = {'targets':[{'member_id':s.report['members'][0]['id'],'version':1,'target_usd':'100'}]}
    assert s.client.put(s.url+'/targets', json=stale).status_code == 409


def test_read_only_user_is_not_given_edit_controls(setup):
    s = setup; become(s, 2, ('battle_report:read',))
    assert not any(m['can_edit'] for m in s.client.get(s.url).json()['data']['members'])


def test_replace_member_after_external_account_transfer(setup):
    s = setup
    s.db.query(ArkUserExternalBinding).filter_by(ark_user_id=s.users[1].id).update({'binding_status':'inactive'})
    s.db.add(ArkUserExternalBinding(ark_user_id=s.users[4].id,provider='okki',external_account_id='U1',binding_status='active',is_primary=True))
    s.db.commit()
    members = [{**m, 'ark_user_id':s.users[4].id} if m['ark_user_id']==s.users[1].id else m for m in s.payload['members']]
    response = s.client.put(s.url,json={**s.payload,'members':members,'version':2,'reason':'修正重复账号'})
    assert response.status_code == 200, response.text
    assert s.client.get(s.url+'/overview').json()['data']['summary']['gmv'] == '101.00'


def test_beijing_midnight_and_source_deduplication():
    report = SimpleNamespace(start_date=date(2026,9,22),end_date=date(2026,9,22))
    member = SimpleNamespace(id=1,okki_user_id='U1',user_name='A',team='A')
    row = {'order_id':'O','user_id':'U1','account_date':'2026-09-22','amount_usd':'0.10'}
    rows, errors = normalize_orders([row,row], report, [member], date(2026,9,22))
    assert len(rows)==1 and rows[0]['included_usd']=='0.10' and not errors
    rows, errors = normalize_orders([row,{**row,'amount_usd':'0.20'}], report,[member],date(2026,9,22))
    assert not rows and errors
    assert time_progress(report, datetime(2026,9,22)) == 0
    assert time_progress(report, datetime(2026,9,23)) == 100


@pytest.mark.parametrize('server_zone', ['America/Los_Angeles','UTC'])
def test_offset_deadline_normalizes_independent_of_server_timezone(setup, monkeypatch, server_zone):
    monkeypatch.setenv('TZ', server_zone)
    payload = ReportInput(**{**setup.payload, 'target_deadline':'2026-09-22T16:00:00Z'})
    assert payload.target_deadline == datetime(2026,9,23,0,0)
