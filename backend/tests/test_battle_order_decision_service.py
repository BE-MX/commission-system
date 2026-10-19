"""Human decisions through real authenticated services and isolated SQLite."""
import json
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.battle_report import poster_service
from app.battle_report.models import BattleReport, BattleReportAudit, BattleReportMember
from tests.test_battle_reports import setup, become


def decision_input(order_id="710000000001", **changes):
    return {"order_id": order_id, "order_no": "CONFIRMED-NEW-ORDER", "company_id": "720000000001",
            "owner_id": "730000000001", "account_date": "2026-02-03", "role": "new_sign",
            "reason": "主管已确认本活动订单角色", **changes}


def annual_payload(s):
    return {"name": "年度新签复购裁定测试", "start_date": "2026-01-01", "end_date": "2026-12-31",
            "target_deadline": "2026-10-19T09:00:00", "award_kind": "annual_repurchase",
            "members": [{"ark_user_id": s.users[i].id, "team": "A", "is_captain": i == 1} for i in (1, 2)],
            "award_rules": {"push_start_date": "2026-10-19", "source_sha256": "a" * 64,
                            "baselines": [{"ark_user_id": s.users[i].id, "hired_date": "2020-01-01",
                                           "gmv_2025_usd": "100", "target_gmv_usd": "130"} for i in (1, 2)],
                            "order_decisions": [decision_input(),
                                decision_input("710000000002", order_no="CONFIRMED-REPEAT-ORDER", role="repeat"),
                                decision_input("710000000003", order_no="GMV-ONLY-ORDER", role="exclude_metrics")]}}


def mirror_snapshot(s):
    return [dict(row) for row in s.db.execute(text(
        "SELECT order_id, account_date, amount_usd, user_id, custom_fields FROM lsordertest.okki_orders ORDER BY order_id"
    )).mappings()]


@pytest.fixture
def annual(setup):
    s = setup
    payload = annual_payload(s)
    before_mirror = mirror_snapshot(s)
    response = s.client.post('/api/battle-reports', json=payload)
    assert response.status_code == 200, response.text
    created = response.json()['data']
    url = f"/api/battle-reports/{created['id']}"
    response = s.client.post(url + '/state', json={"action": "publish", "version": created['version']})
    assert response.status_code == 200, response.text
    return SimpleNamespace(s=s, payload=payload, created=created, url=url,
                           report=response.json()['data'], before_mirror=before_mirror)


def test_admin_create_persists_all_roles_and_complete_source_identity_audit(annual):
    a = annual
    expected = a.payload['award_rules']['order_decisions']
    assert a.created['award_rules']['order_decisions'] == expected
    a.s.db.expire_all()
    row = a.s.db.get(BattleReport, a.created['id'])
    assert row.award_rules['order_decisions'] == expected
    create = a.s.db.query(BattleReportAudit).filter_by(report_id=row.id, action='create').one()
    assert create.before is None
    assert create.after['award_rules'] == a.created['award_rules']
    assert {m['ark_user_id'] for m in create.after['members']} == {m['ark_user_id'] for m in a.payload['members']}
    assert create.actor_id == a.s.users[0].id
    assert create.created_at == datetime(2026, 9, 22, 12)
    assert mirror_snapshot(a.s) == a.before_mirror


def test_admin_correction_audits_full_before_after_and_operator_reason(annual):
    a = annual
    changed = deepcopy(a.payload)
    changed['award_rules']['order_decisions'][0].update(role='repeat', reason='业务负责人复核为2026新客复购')
    response = a.s.client.put(a.url, json={**changed, 'version': a.report['version'], 'reason': '主管复核订单角色'})
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    audit = a.s.db.query(BattleReportAudit).filter_by(report_id=a.created['id'], action='configure').one()
    assert audit.before['award_rules'] == a.created['award_rules']
    assert audit.after['award_rules'] == saved['award_rules']
    assert audit.after['award_rules']['order_decisions'] == changed['award_rules']['order_decisions']
    assert audit.actor_id == a.s.users[0].id and audit.reason == '主管复核订单角色'
    assert audit.after['version'] == audit.before['version'] + 1
    assert {m['ark_user_id'] for m in audit.after['members']} == {m['ark_user_id'] for m in a.payload['members']}
    assert mirror_snapshot(a.s) == a.before_mirror


def test_stale_version_cannot_replace_decisions_or_add_audit(annual):
    a = annual
    changed = deepcopy(a.payload)
    changed['award_rules']['order_decisions'][0].update(role='repeat', reason='已确认复购')
    response = a.s.client.put(a.url, json={**changed, 'version': a.report['version'], 'reason': '第一次确认'})
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    audit_count = a.s.db.query(BattleReportAudit).filter_by(report_id=a.created['id']).count()
    versions = [(m.id, m.version) for m in a.s.db.query(BattleReportMember).filter_by(report_id=a.created['id'])]
    stale = deepcopy(changed)
    stale['award_rules']['order_decisions'][0].update(role='exclude_metrics', reason='过期表单里的不同裁定')
    response = a.s.client.put(a.url, json={**stale, 'version': a.report['version'], 'reason': '过期提交'})
    assert response.status_code == 409, response.text
    a.s.db.expire_all()
    row = a.s.db.get(BattleReport, a.created['id'])
    assert row.version == saved['version'] and row.award_rules == saved['award_rules']
    assert a.s.db.query(BattleReportAudit).filter_by(report_id=row.id).count() == audit_count
    assert [(m.id, m.version) for m in a.s.db.query(BattleReportMember).filter_by(report_id=row.id)] == versions
    assert mirror_snapshot(a.s) == a.before_mirror


@pytest.mark.parametrize('target', ['create', 'update'])
def test_blank_decision_reason_is_rejected_without_persistent_changes(annual, target):
    a = annual
    invalid = deepcopy(a.payload)
    invalid['award_rules']['order_decisions'][0]['reason'] = ' \n '
    count_before = a.s.db.query(BattleReport).count()
    audits_before = a.s.db.query(BattleReportAudit).count()
    if target == 'create':
        response = a.s.client.post('/api/battle-reports', json=invalid)
    else:
        response = a.s.client.put(a.url, json={**invalid, 'version': a.report['version'], 'reason': '活动更正'})
    assert response.status_code == 422, response.text
    a.s.db.expire_all()
    assert a.s.db.query(BattleReport).count() == count_before
    assert a.s.db.query(BattleReportAudit).count() == audits_before
    assert a.s.db.get(BattleReport, a.created['id']).award_rules == a.created['award_rules']


def test_published_activity_correction_requires_overall_reason(annual):
    a = annual
    response = a.s.client.put(a.url, json={**a.payload, 'version': a.report['version'], 'reason': ' '})
    assert response.status_code == 422, response.text
    assert not a.s.db.query(BattleReportAudit).filter_by(report_id=a.created['id'], action='configure').count()


def test_draft_decision_change_requires_reason_and_resets_enabled_poster_config(setup, monkeypatch):
    s = setup
    payload = annual_payload(s)
    response = s.client.post('/api/battle-reports', json=payload)
    assert response.status_code == 200, response.text
    report = response.json()['data']
    url = f"/api/battle-reports/{report['id']}"
    monkeypatch.setattr(poster_service, 'push_ready', lambda settings=None: True)
    response = s.client.put(url + '/poster-config', json={
        'version': report['version'], 'work_dates': ['2026-10-19'], 'push_enabled': True})
    assert response.status_code == 200, response.text
    version = response.json()['data']['version']
    s.db.expire_all()
    before = s.db.get(BattleReport, report['id'])
    assert before.status == 'draft' and before.poster_push_enabled
    assert before.work_dates == ['2026-10-19']
    old_rules = deepcopy(before.award_rules)
    old_audits = s.db.query(BattleReportAudit).filter_by(report_id=report['id']).count()
    changed = deepcopy(payload)
    changed['award_rules']['order_decisions'][0].update(role='repeat', reason='草稿复核为2026新客复购')
    response = s.client.put(url, json={**changed, 'version': version, 'reason': ' '})
    assert response.status_code == 422, response.text
    s.db.expire_all()
    rejected = s.db.get(BattleReport, report['id'])
    assert rejected.version == version and rejected.award_rules == old_rules
    assert rejected.poster_push_enabled and rejected.work_dates == ['2026-10-19']
    assert s.db.query(BattleReportAudit).filter_by(report_id=report['id']).count() == old_audits
    response = s.client.put(url, json={**changed, 'version': version, 'reason': '主管复核草稿裁定'})
    assert response.status_code == 200, response.text
    s.db.expire_all()
    saved = s.db.get(BattleReport, report['id'])
    assert saved.version == version + 1 and saved.status == 'draft'
    assert saved.award_rules['order_decisions'] == changed['award_rules']['order_decisions']
    assert not saved.poster_push_enabled and saved.work_dates is None
    audit = s.db.query(BattleReportAudit).filter_by(report_id=report['id'], action='configure').one()
    assert audit.reason == '主管复核草稿裁定' and audit.before['award_rules'] == old_rules
    assert audit.after['award_rules'] == saved.award_rules


@pytest.mark.parametrize('reader_index', [1, 2])
def test_captain_and_regular_summary_reader_cannot_see_decision_identities(annual, reader_index):
    a = annual
    become(a.s, reader_index, permissions=('battle_report:read',))
    response = a.s.client.get(a.url)
    assert response.status_code == 200, response.text
    detail = response.json()['data']
    listing = a.s.client.get('/api/battle-reports').json()['data']
    listed = next(item for item in listing['items'] if item['id'] == a.created['id'])
    assert 'order_decisions' not in detail['award_rules']
    assert 'order_decisions' not in listed['award_rules']
    visible = json.dumps({'detail': detail, 'list': listing}, ensure_ascii=False)
    for decision in a.payload['award_rules']['order_decisions']:
        assert decision['order_id'] not in visible
        assert decision['order_no'] not in visible
        assert decision['company_id'] not in visible
        assert decision['owner_id'] not in visible
    assert a.s.client.get(a.url + '/audits').status_code == 403
    assert a.s.client.put(a.url, json={**a.payload, 'version': a.report['version'], 'reason': '普通读者不能改裁定'}).status_code == 403
    a.s.db.expire_all()
    assert a.s.db.get(BattleReport, a.created['id']).award_rules == a.created['award_rules']


def test_report_admin_permission_retains_decisions_in_detail_list_and_audit(annual):
    a = annual
    become(a.s, 2, permissions=('battle_report:admin',))
    response = a.s.client.get(a.url)
    assert response.status_code == 200, response.text
    detail = response.json()['data']
    listing = a.s.client.get('/api/battle-reports').json()['data']
    listed = next(item for item in listing['items'] if item['id'] == a.created['id'])
    expected = a.payload['award_rules']['order_decisions']
    assert detail['award_rules']['order_decisions'] == expected
    assert listed['award_rules']['order_decisions'] == expected
    response = a.s.client.get(a.url + '/audits')
    assert response.status_code == 200, response.text
    create = next(item for item in response.json()['data']['items'] if item['action'] == 'create')
    assert create['after']['award_rules']['order_decisions'] == expected
