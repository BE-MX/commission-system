"""Human-confirmed order roles preserve GMV and original cohort attribution."""
import copy
import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.battle_report import award_statistics as stats


def fixture():
    report=SimpleNamespace(award_kind='annual_repurchase',start_date=date(2026,1,1),end_date=date(2026,12,31),
        award_rules={'baselines':[{'ark_user_id':i,'gmv_2025_usd':'100','target_gmv_usd':'130'} for i in (1,2)]})
    members=[SimpleNamespace(id=i,ark_user_id=i,okki_user_id=str(i),user_name=str(i),team='A',is_captain=False) for i in (1,2)]
    def fact(oid,no,cid,day,amount,mark='',owner='1'):
        return dict(order_id=str(oid),order_no=no,company_id=str(cid),user_id=owner,account_date=day,
                    amount_usd=amount,custom_fields=json.dumps({stats.NEW_DEAL_FIELD:mark}),is_goods=True)
    raw=[fact(1,'21184',101,'2026-02-05','100','是'),
         fact(2,'22100',101,'2026-03-22','1230.46'),fact(3,'23999',101,'2026-06-18','809.76'),
         fact(4,'22410',102,'2026-04-02','85'),fact(5,'inventory',102,'2026-04-02','85','是','2'),
         fact(6,'23997',102,'2026-06-17','1744.40','否','2'),
         fact(7,'23868',103,'2026-06-11','370.30'),fact(8,'23941',103,'2026-06-15','370.30','是'),
         fact(9,'excluded',101,'2026-07-01','9000',owner='2')]
    roles={2:'repeat',3:'repeat',4:'new_sign',7:'new_sign',9:'exclude_metrics'}
    decisions=[{'order_id':row['order_id'],'order_no':row['order_no'],'company_id':row['company_id'],
        'owner_id':row['user_id'],'account_date':row['account_date'],'role':roles[int(row['order_id'])],
        'reason':'Business owner confirmed order role'} for row in raw if int(row['order_id']) in roles]
    return report,members,raw,decisions


def test_confirmed_first_repeat_and_exclusion_preserve_gmv_and_cohort_owner():
    report,members,raw,decisions=fixture()
    original=copy.deepcopy(raw)
    before=stats.calculate(report,members,raw,datetime(2026,10,19))
    report.award_rules['order_decisions']=decisions
    after=stats.calculate(report,members,raw,datetime(2026,10,19))
    assert after['data_complete'] and not after['issues']
    one=next(row for row in after['people'] if row['ark_user_id']==1)
    two=next(row for row in after['people'] if row['ark_user_id']==2)
    assert (one['new_count'],one['repeat_count'],one['repeat_orders'])==(3,2,3)
    assert Decimal(one['repeat_amount'])==Decimal('4795.22')
    assert Decimal(one['score'])==Decimal('1.5754264')
    assert two['new_count']==two['repeat_count']==two['repeat_orders']==0
    assert {r['ark_user_id']:r['gmv'] for r in before['people']}=={r['ark_user_id']:r['gmv'] for r in after['people']}
    assert raw==original  # Source facts are neither mutated nor reclassified in the mirror.
    assert after['order_decision_count']==after['applied_order_decision_count']==5


def test_explicit_metrics_exclusion_does_not_treat_a_valid_flag_as_repeat():
    report,members,raw,decisions=fixture()
    raw[-1]['custom_fields']=json.dumps({stats.NEW_DEAL_FIELD:'是'})
    report.award_rules['order_decisions']=decisions
    data=stats.calculate(report,members,raw,datetime(2026,10,19))
    two=next(row for row in data['people'] if row['ark_user_id']==2)
    assert data['data_complete'] and Decimal(two['gmv'])==Decimal('10829.40')
    assert two['new_count']==two['repeat_count']==0


def test_source_identity_drift_suspends_award_but_preserves_gmv():
    report,members,raw,decisions=fixture()
    raw[1]['company_id']='999'
    report.award_rules['order_decisions']=decisions
    data=stats.calculate(report,members,raw,datetime(2026,10,19))
    assert not data['data_complete'] and any('人工' in issue for issue in data['issues'])
    assert all(row['gmv_complete'] and row['rank'] is None for row in data['people'])
    assert next(row for row in data['people'] if row['ark_user_id']==1)['gmv']=='2965.82'


def test_special_date_cannot_be_resurrected_by_an_old_confirmation():
    report,members,raw,decisions=fixture()
    raw[1]['account_date']='2019-12-31'
    decisions[0]['account_date']='2019-12-31'
    report.award_rules['order_decisions']=decisions
    data=stats.calculate(report,members,raw,datetime(2026,10,19))
    assert data['data_complete']
    assert next(row for row in data['people'] if row['ark_user_id']==1)['repeat_orders']==2


def test_malformed_stored_decisions_fail_closed_without_losing_valid_gmv():
    report,members,raw,_=fixture()
    report.award_rules['order_decisions']=[{'order_id':'2','role':'new_sign'}]
    data=stats.calculate(report,members,raw,datetime(2026,10,19))
    assert not data['data_complete'] and data['issues']
    assert all(row['gmv_complete'] and row['rank'] is None for row in data['people'])
