"""Read-only report corrections tested with pure facts and isolated SQLite."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import pytest
from sqlalchemy import event, text
from app.battle_report import award_statistics as stats, order_details, poster_renderer
from app.battle_report.annual_order_corrections import PAN_CORRECTIONS, PAN_OWNER, JOHN_COMPANY
from tests.test_battle_awards import campaign, fact, member
from tests.test_battle_reports import setup

NOW = datetime(2026, 11, 23)

def context():
    report = campaign()
    report.id = 2
    owner = member(1)
    owner.okki_user_id = PAN_OWNER
    return report, [owner]

def facts():
    return [{**fact(oid, uid=PAN_OWNER, cid=c[2], day=c[1].isoformat(), amount=str((i+1)*100)),
             'order_no': c[0], 'order_name': c[0], 'company_name': 'original', 'custom_fields': '{}'}
            for i, (oid, c) in enumerate(PAN_CORRECTIONS.items())]

def test_cohort_dedup_poster_and_source_immutability():
    report, members = context()
    raw = facts()
    raw += [dict(raw[0]), fact('later', uid='outside', cid=JOHN_COMPANY, day='2026-08-01', new=False, amount='400'),
            fact('katie', uid=PAN_OWNER, cid='12536643201371', day='2026-08-02', new=False, amount='500'),
            fact('kaelyn-later', uid=PAN_OWNER, cid='89639526739793', day='2026-08-03', new=False, amount='600')]
    before = deepcopy(raw)
    result = stats.calculate(report, members, raw, NOW)
    row = result['people'][0]
    assert result['data_complete'] and raw == before
    assert (row['new_count'], row['repeat_count'], row['repeat_orders']) == (2, 2, 3)
    assert Decimal(row['repeat_amount']) == 1600 and Decimal(row['gmv']) == 1700
    first = stats.normalize_facts(report, raw, NOW)[0][0]
    assert (first['cid'], first['cohort_cid'], first['company_name']) == ('12536643201371', JOHN_COMPANY, 'John Watkins')
    assert '业务员1' in poster_renderer.render_html(result, 'personal')

@pytest.mark.parametrize('change', [{'id': 3}, {'award_kind': 'new_sign_pk'},
    {'start_date': date(2026, 1, 2)}, {'end_date': date(2026, 12, 30)}])
def test_report_scope(change):
    report, _ = context()
    for key, value in change.items():
        setattr(report, key, value)
    orders, issues, *_ = stats.normalize_facts(report, facts(), NOW)
    assert issues and all(o['new'] is None and o['company_name'] == 'original' for o in orders)

@pytest.mark.parametrize('change', [{'order_no': 'Pan260605'}, {'user_id': 'other'},
    {'company_id': 'other'}, {'account_date': '2026-06-06'}])
def test_identity_drift(change):
    report, _ = context()
    orders, issues, gmv_issues, *_ = stats.normalize_facts(report, [{**facts()[2], **change}], NOW)
    assert issues and not gmv_issues and orders[0]['new'] is None
    assert orders[0]['company_name'] == 'original' and orders[0]['amount'] == 300

def test_corrected_source_and_native_scope():
    report, _ = context()
    raw = facts()[:2]
    for row in raw:
        row['company_id'] = JOHN_COMPANY
    orders, issues, *_ = stats.normalize_facts(report, raw, NOW)
    assert not issues and [o['new'] for o in orders] == [True, False]
    for row in raw:
        row['source_type'] = 'formal_projection'
    assert stats.normalize_facts(report, raw, NOW)[1]
    assert stats.normalize_facts(report, facts(), NOW, native=True)[1]

def test_sql_transfer_details_filters_and_readonly(setup, monkeypatch):
    db = setup.db
    report, members = context()
    monkeypatch.setattr(stats, 'goods_order_sql', lambda alias: '1')
    db.execute(text('ALTER TABLE lsordertest.okki_orders ADD COLUMN synced_at TEXT'))
    db.execute(text('DELETE FROM lsordertest.okki_orders'))
    raw = facts() + [{**fact('later', uid='outside', cid=JOHN_COMPANY, day='2026-08-01', new=False, amount='400'),
                      'order_no': 'later', 'order_name': 'later'}]
    for row in raw:
        db.execute(text('''INSERT INTO lsordertest.okki_orders
            (order_id, order_no, name, company_id, user_id, account_date, amount_usd, status, trail, custom_fields)
            VALUES (:order_id, :order_no, :order_name, :company_id, :user_id, :account_date, :amount_usd,
                    '13972831656', '公司', :custom_fields)'''), row)
    db.commit()
    before = db.execute(text('SELECT * FROM lsordertest.okki_orders ORDER BY order_id')).all()
    def read_only(conn, cursor, statement, parameters, ctx, many):
        assert statement.lstrip().upper().startswith('SELECT'), statement
    event.listen(db.bind, 'before_cursor_execute', read_only)
    try:
        source, _ = stats.source_facts(db, report, members, NOW)
        assert {r['order_id'] for r in source} == {r['order_id'] for r in raw}
        monkeypatch.setattr(order_details, 'load_report', lambda *args: (report, members, None))
        monkeypatch.setattr(order_details, 'visible_members', lambda *args, **kw: members)
        monkeypatch.setattr(order_details, 'select_members', lambda *args, **kw: members)
        monkeypatch.setattr(order_details, 'beijing_now', lambda: NOW)
        results = [order_details.list_metric_orders(db, 2, {}, metric=m) for m in ['new_sign','repeat','combined']]
        assert [r['total'] for r in results] == [2, 2, 4]
        assert results[-1]['customer_count'] == 2 and results[-1]['total_amount'] == '1000.00'
        john = order_details.list_metric_orders(db, 2, {}, metric='combined', customer='John Watkins')
        assert john['total'] == 2 and {r['cohort_company_id'] for r in john['items']} == {JOHN_COMPANY}
        kaelyn = order_details.list_metric_orders(db, 2, {}, metric='new_sign', customer='Kaelyn Hawley')
        assert kaelyn['total'] == 1 and kaelyn['items'][0]['company_id'] == '89639526739793'
        report.id = 3
        assert 'later' not in {r['order_id'] for r in stats.source_facts(db, report, members, NOW)[0]}
        assert db.execute(text('SELECT * FROM lsordertest.okki_orders ORDER BY order_id')).all() == before
    finally:
        event.remove(db.bind, 'before_cursor_execute', read_only)

def test_unrelated_id_and_conflicting_duplicate_do_not_silently_win():
    report, members = context()
    unrelated = {**facts()[0], 'order_id': 'unrelated'}
    assert stats.normalize_facts(report, [unrelated], NOW)[0][0]['new'] is None
    raw = facts() + [{**facts()[0], 'amount_usd': '999'}]
    result = stats.calculate(report, members, raw, NOW)
    assert not result['data_complete'] and result['people'][0]['rank'] is None
    assert not result['people'][0]['gmv_complete']

def test_verified_literal_production_shape_preserves_existing_kaelyn_cohort():
    report, members = context()
    raw = []
    for oid, number, cid, day, mark in [
        ('100348581118834', 'Pan260611', '12536643201371', '2026-06-16', '否'),
        ('105647122909622', 'Pan260717', '12536643201371', '2026-07-23', '否'),
        ('98809111290128', 'Pan 260605', '89639526739793', '2026-06-05', '否'),
        ('kaelyn-april', 'earlier', '89639526739793', '2026-04-07', '是'),
        ('kaelyn-may', 'repeat', '89639526739793', '2026-05-07', '否'),
        ('katie-other', 'other', '12536643201371', '2026-08-01', '否'),
    ]:
        raw.append({**fact(oid, uid='55296478', cid=cid, day=day), 'order_no': number,
                    'custom_fields': {stats.NEW_DEAL_FIELD: mark}})
    before = deepcopy(raw)
    orders, issues, *_ = stats.normalize_facts(report, raw, NOW)
    assert not issues and raw == before
    by_id = {o['id']: o for o in orders}
    assert by_id['100348581118834']['cohort_cid'] == '101592033446449'
    assert by_id['100348581118834']['new'] is True
    assert by_id['105647122909622']['cohort_cid'] == '101592033446449'
    assert by_id['105647122909622']['new'] is False
    assert by_id['98809111290128']['cohort_cid'] == '89639526739793'
    assert by_id['98809111290128']['new'] is True
    assert by_id['katie-other']['cohort_cid'] == '12536643201371'
    row = stats.calculate(report, members, raw, NOW)['people'][0]
    assert (row['new_count'], row['repeat_count'], row['repeat_orders']) == (2, 2, 2)
    assert Decimal(row['repeat_amount']) == 500 and Decimal(row['gmv']) == 600

@pytest.mark.parametrize('role,mark,change,applied', [
    ('new_sign', '是', {}, 1), ('new_sign', '否', {}, 0),
    ('repeat', '否', {}, 0), ('new_sign', '是', {'owner_id':'999'}, 0),
])
def test_manual_decision_overlap_keeps_conflicts_drift_and_applied_count(role, mark, change, applied):
    report, _ = context()
    raw = facts()[:1]
    raw[0]['custom_fields'] = {stats.NEW_DEAL_FIELD: mark}
    report.award_rules['order_decisions'] = [{
        'order_id':'100348581118834', 'order_no':'Pan260611', 'company_id':'12536643201371',
        'owner_id':'55296478', 'account_date':'2026-06-16', 'role':role, 'reason':'verified correction', **change}]
    orders, issues, gmv_issues, count, actual = stats.normalize_facts(report, raw, NOW)
    assert count == 1 and actual == applied and not gmv_issues
    assert bool(issues) == (not applied)
    assert orders[0]['new'] is (True if applied else None)
