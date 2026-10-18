"""Award business boundaries using pure facts and isolated SQLite only."""
import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.battle_report import award_statistics as stats, poster_delivery, poster_renderer, poster_service
from app.battle_report.models import BattleReport, BattleReportDelivery
from app.battle_report.schemas import ReportInput
from tests.test_battle_reports import setup, become
from tests.test_battle_posters import posters, mock_render


def member(i, team="A", captain=False):
    return SimpleNamespace(id=i, ark_user_id=i, okki_user_id=f"U{i}", user_name=f"业务员{i}", team=team, is_captain=captain)


def campaign(kind="annual_repurchase", baselines=None, targets=None):
    return SimpleNamespace(award_kind=kind, start_date=date(2026, 1, 1) if kind == "annual_repurchase" else date(2026, 11, 1),
        end_date=date(2026, 12, 31) if kind == "annual_repurchase" else date(2026, 11, 30),
        award_rules={"push_start_date": "2026-10-19" if kind == "annual_repurchase" else "2026-11-01",
                     "baselines": [{"ark_user_id": i, "gmv_2025_usd": str(b), "target_gmv_usd": str((targets or {}).get(i, Decimal(str(b))*Decimal("1.3")))} for i, b in (baselines or {1: 100}).items()]})


def fact(oid, uid="U1", cid="C1", day="2026-01-02", amount="100", new=True, goods=True):
    return dict(order_id=oid, user_id=uid, company_id=cid, account_date=day, amount_usd=amount,
                custom_fields=json.dumps({stats.NEW_DEAL_FIELD: "是" if new else "否"}), is_goods=goods)


@pytest.mark.parametrize('actual,qualified', [('843354.2909',False),('843354.291',True),('843354.30',True)])
def test_direct_excel_target_exact_boundary(actual,qualified):
    report=campaign(baselines={1:'648734.07'},targets={1:'843354.291'})
    data=stats.calculate(report,[member(1)],[fact('1',amount=actual)],datetime(2026,10,19))
    row=data['people'][0]
    assert data['currency']=='USD' and Decimal(row['target'])==Decimal('843354.291')
    assert row['qualified']==qualified
    assert 'usd_cny_rate' not in data and 'baseline_cny' not in row


def test_excel_target_is_authoritative_even_when_it_differs_from_derived_target():
    report=campaign(baselines={1:'420000'},targets={1:'800000.123456'})
    data=stats.calculate(report,[member(1)],[fact('1',amount='600000')],datetime(2026,10,19))
    row=data['people'][0]
    assert row['target']=='800000.123456' and not row['qualified']
    assert abs(row['progress_percent']-600000/800000.123456*100)<1e-9


def test_repeat_score_uses_dollars_and_ignores_rmb_source_amount():
    raw=[{**fact('1',amount='100'),'amount_rmb':'999999'},
         {**fact('2',amount='5000',new=False,day='2026-02-01'),'amount_rmb':'35714.5'}]
    data=stats.calculate(campaign(),[member(1)],raw,datetime(2026,10,19))
    row=data['people'][0]
    assert Decimal(row['gmv'])==5100 and Decimal(row['repeat_amount'])==5000
    assert Decimal(row['score'])==Decimal('1.0')


def test_cohort_repeat_dedup_owner_transfer_and_precise_amount():
    raw = [fact("1"), fact("2", uid="outsider", new=False, day="2026-02-01", amount="5000.001"),
           fact("3", uid="U2", new=False, day="2026-02-02", amount="4999.999"),
           fact("old", cid="OLD", new=False), fact("future", day="2026-12-01"),
           fact("freight", new=False, day="2026-02-03", amount="999", goods=False)]
    data = stats.calculate(campaign(baselines={1:100, 2:100}), [member(1), member(2)], raw, datetime(2026, 10, 19))
    one = next(r for r in data["people"] if r["member_id"] == 1)
    two = next(r for r in data["people"] if r["member_id"] == 2)
    assert (one["new_count"], one["repeat_count"], one["repeat_orders"], Decimal(one["repeat_amount"])) == (1,1,2,Decimal("10000"))
    assert Decimal(one["score"]) == Decimal("1.60")
    assert two["repeat_count"] == 0 and two["gmv"] == "4999.999"


def test_freight_cannot_add_or_steal_cohort_or_block_ranking():
    raw = [fact("10"), fact("1", uid="U2", day="2026-01-01", goods=False),
           fact("freight-only", cid="FREIGHT", goods=False),
           {**fact("bad-freight", goods=False), "custom_fields": "{}"}]
    data = stats.calculate(campaign(baselines={1:100,2:100}),[member(1),member(2)],raw,datetime(2026,10,19))
    assert data["data_complete"]
    assert next(r for r in data["people"] if r["member_id"]==1)["new_count"]==1
    assert next(r for r in data["people"] if r["member_id"]==2)["new_count"]==0


def test_blank_new_deal_preserves_gmv_but_suspends_ranks():
    data=stats.calculate(campaign(),[member(1)],[{**fact("1",amount="200"),"custom_fields":"{}"}],datetime(2026,10,19))
    row=data["people"][0]
    assert row["gmv"]=="200" and row["gmv_complete"] and row["qualified"]
    assert row["rank"] is None and not row["top_five"] and data["issues"]


def test_exact_gmv_cannot_round_into_qualification():
    result = stats.calculate(campaign(), [member(1)], [fact("1", amount="129.999")], datetime(2026, 10, 19))
    assert not result["people"][0]["qualified"]
    result = stats.calculate(campaign(), [member(1)], [fact("1", amount="130")], datetime(2026, 10, 19))
    assert result["people"][0]["qualified"]


def test_same_day_repeat_uses_stable_numeric_order_id():
    data = stats.calculate(campaign(), [member(1)], [fact("10"), fact("9", new=False), fact("11", new=False)], datetime(2026, 10, 19))
    assert data["people"][0]["repeat_orders"] == 1


@pytest.mark.parametrize("change", [{"amount_usd":None}, {"amount_usd":"-1"}, {"custom_fields":"{}"}, {"company_id":None}, {"account_date":None}])
def test_bad_facts_suspend_awards(change):
    data = stats.calculate(campaign(), [member(1)], [{**fact("1", amount="999"), **change}], datetime(2026, 10, 19))
    assert data["issues"] and not data["data_complete"]
    assert data["people"][0]["rank"] is None and not data["people"][0]["top_five"]


def test_duplicate_conflict_suspends_ranking():
    data = stats.calculate(campaign(), [member(1)], [fact("1"), fact("1", amount="200")], datetime(2026, 10, 19))
    assert data["issues"] and not data["data_complete"]


def test_top_five_excludes_unqualified_and_flags_cutoff_tie():
    members = [member(i) for i in range(1,8)]
    raw = [fact(str(i), uid=f"U{i}", cid=f"C{i}", amount="999") for i in range(1,8)]
    data = stats.calculate(campaign(baselines={i:100 for i in range(1,8)}), members, raw, datetime(2026, 10, 19))
    assert data["cutoff_tie"] and not any(r["top_five"] for r in data["people"])
    # An unqualified high-score person must never displace an eligible candidate.
    raw += [fact("extra", cid="EXTRA", amount="1")]
    report = campaign(baselines={i:10000 if i == 1 else 100 for i in range(1,8)})
    data = stats.calculate(report, members, raw, datetime(2026, 10, 19))
    assert not next(r for r in data["people"] if r["member_id"]==1)["top_five"]


def test_same_value_different_decimal_scale_at_fifth_place():
    people=[member(i) for i in range(1,7)]
    raw=[]
    for i in range(1,7):
        raw.extend([fact(str(i*10),uid=f"U{i}",cid=f"C{i}",amount="1000"),
                    fact(str(i*10+1),uid=f"U{i}",cid=f"C{i}",amount="1000.00" if i==6 else "1000",new=False,day="2026-02-01")])
    data=stats.calculate(campaign(baselines={i:100 for i in range(1,7)}),people,raw,datetime(2026,10,19))
    assert data["cutoff_tie"] and not any(r["top_five"] for r in data["people"])


def pk_facts(a, b, amount_a="100", amount_b="100"):
    return [fact(str(100+i), cid=f"A{i}", amount=amount_a, day="2026-11-02") for i in range(a)] + [
        fact(str(200+i), uid="U2", cid=f"B{i}", amount=amount_b, day="2026-11-02") for i in range(b)]


@pytest.mark.parametrize("a,b,bonus,winner", [(0,0,"0.00",None),(6,5,"100.00",None),(6,6,"100.00",None),(7,6,"110.00","A")])
def test_pk_gate_and_overcompletion(a,b,bonus,winner):
    data = stats.calculate(campaign("new_sign_pk"), [member(1,"A",True),member(2,"B",True)], pk_facts(a,b), datetime(2026,11,30,16))
    assert data["teams"][0]["target_bonus"] == bonus and data["winner"] == winner
    assert data["teams"][0]["pk_bonus"] == ("500.00" if winner else "0.00")
    assert data["teams"][0]["inquiries"] == (10 if winner else 0)
    assert data["rewards_provisional"]


def test_pk_tiebreak_new_amount_then_month_gmv():
    members = [member(1,"A",True),member(2,"B",True)]
    data = stats.calculate(campaign("new_sign_pk"), members, pk_facts(6,6,"101","100"), datetime(2026,12,1))
    assert data["winner"] == "A" and not data["rewards_provisional"]
    raw = pk_facts(6,6) + [fact("old",uid="U2",cid="OLD",new=False,day="2026-11-20",amount="1")]
    data = stats.calculate(campaign("new_sign_pk"), members, raw, datetime(2026,12,1))
    assert data["winner"] == "B"


def test_pk_uses_per_capita_not_team_total():
    members = [member(1,"A",True),member(3,"A"),member(2,"B",True)]
    data = stats.calculate(campaign("new_sign_pk"), members, pk_facts(12,7), datetime(2026,11,30))
    assert data["winner"]=="B" and data["teams"][0]["target"]==12


@pytest.mark.parametrize("stamp,slot", [("2026-10-19T09:00:00+08:00","09:00"), ("2026-10-19T01:00:00+00:00","09:00"),
    ("2026-10-20T09:00:00+08:00",None),("2026-10-21T16:05:00+08:00","16:00"),
    ("2026-10-18T18:00:00-07:00","09:00"),("2026-10-23T16:15:00+08:00","16:00")])
def test_award_slots_in_beijing(stamp,slot):
    assert poster_delivery.due_slot(datetime.fromisoformat(stamp),campaign())==slot


def test_push_bounds_and_midnight():
    r=campaign(); r.poster_push_enabled=True; r.status="published";r.visibility="activity"
    assert not poster_delivery.eligible(r,datetime(2026,10,16,9))
    assert poster_delivery.eligible(r,datetime(2026,10,19,9))
    assert not poster_delivery.eligible(r,datetime.fromisoformat("2026-12-31T16:01:00+00:00"))
    assert not poster_delivery.eligible(r,datetime(2026,10,20,9))


def test_templates_escape_names_and_contain_business_annotations():
    r=campaign(); data=stats.calculate(r,[member(1)],[fact("1",amount="999")],datetime(2026,10,19),"2026-10-19T08:59:00")
    data["report"]={"name":"<img src='evil'>","start_date":"2026-01-01","end_date":"2026-12-31"}
    data['people'][0]['user_name']="<img src='evil'>"
    html=poster_renderer.render_html(data,"personal")
    assert "&lt;img" in html and "<img src='evil'>" not in html
    assert '复购金额：USD' in html and '目标直接引用Excel最低门槛列' in html
    assert '第1名展示位' in html and 'OKKI镜像最近同步：2026-10-19 08:59:00' in html
    assert '未达100%者先按完成进度、再按积分降序' in html
    data=stats.calculate(campaign("new_sign_pk"),[member(1,"A",True),member(2,"B",True)],[],datetime(2026,10,19))
    data["report"]={"name":"11月份新签PK奖","start_date":"2026-11-01","end_date":"2026-11-30"}
    assert "TEAM PK" in poster_renderer.render_html(data,"team")


def annual_rows(specs):
    """Independent GMV, target and score inputs expose ordering regressions."""
    data=dict(people=[dict(ark_user_id=i,user_name=f'Sample{i}',gmv_complete=True,
                          gmv=str(gmv),new_count=score*5,repeat_count=0,repeat_amount='0')
                     for i,(gmv,target,score) in enumerate(specs,1)], data_complete=True)
    report=campaign(baselines={i:1 for i in range(1,len(specs)+1)},
                    targets={i:t for i,(_,t,_) in enumerate(specs,1)})
    stats.annual(data,report)
    return data


def test_annual_ranking_groups_qualified_by_score_then_unqualified_by_progress_score():
    data=annual_rows([(200,100,1),(100,100,2),(80,100,100),(90,100,10),(180,200,20)])
    assert [r['ark_user_id'] for r in data['people']]==[2,1,5,4,3]
    assert [r['overall_rank'] for r in data['people']]==[1,2,3,4,5]
    assert [r['ark_user_id'] for r in data['qualified']]==[2,1]
    assert [r['ark_user_id'] for r in data['unqualified']]==[5,4,3]
    assert not any(r['top_five'] for r in data['unqualified'])


def test_annual_ranking_uses_exact_fractions_and_stable_ties():
    data=annual_rows([('0.99999999999999999998',1,100),('0.99999999999999999999',1,1),
                      (1,1,0),(50,100,1),(100,200,1)])
    assert [r['ark_user_id'] for r in data['people']]==[3,2,1,4,5]
    assert len(data['qualified'])==1


def test_annual_poster_percent_does_not_round_into_qualification_and_bar_caps():
    from app.battle_report.annual_poster import progress, values
    row=dict(gmv_complete=True,gmv='99.999',target='100')
    assert progress(row,True)=={'label':'99.9%','fill':'99.99900'}
    assert progress({**row,'gmv':'138.64'},True)['label']=='138.6%'
    assert progress({**row,'gmv':'138.64'},True)['fill']=='100'
    money_row=dict(user_name='Sample',score='1',new_count=1,repeat_count=1,repeat_amount='368000')
    assert values(money_row,True)[-1]=='368,000'
    assert values({**money_row,'repeat_amount':'368000.12'},True)[-1]=='368,000.12'


def test_annual_incomplete_poster_withholds_all_real_fields_and_labels_seat_numbers():
    raw=[fact('1',amount='987654.32'),{**fact('2'),'custom_fields':'{}'}]
    data=stats.calculate(campaign(),[member(1)],raw,datetime(2026,10,19))
    data['people'][0]['user_name']='REAL_PERSON_MUST_WAIT'
    html=poster_renderer.render_html(data,'personal')
    assert 'REAL_PERSON_MUST_WAIT' not in html and '987,654.32' not in html
    assert '未填正式数据' in html and '席位编号不代表排名' in html
    assert html.count('aria-label="第')==17
    assert '版式样张 · 模拟数据' not in html


def test_annual_mock_is_explicit_and_over_capacity_is_rejected():
    data=stats.calculate(campaign(),[member(1)],[fact('1',amount='999')],datetime(2026,10,19))
    data['data_mode']='demo'
    html=poster_renderer.render_html(data,'personal')
    assert '版式样张 · 模拟数据' in html and '全部姓名与数值为模拟示例' in html
    data['people']*=18
    with pytest.raises(RuntimeError,match='仅支持17人'):
        poster_renderer.render_html(data,'personal')


def test_incomplete_pk_preview_labels_lower_bound_and_hides_rewards():
    raw=pk_facts(5,6)+[{**fact('blank',cid='UNKNOWN',day='2026-11-02'), 'custom_fields':'{}'}]
    data=stats.calculate(campaign('new_sign_pk'),[member(1,'A',True),member(2,'B',True)],raw,datetime(2026,11,16))
    data['report']={'name':'11月份新签PK奖','start_date':'2026-11-01','end_date':'2026-11-30'}
    html=poster_renderer.render_html(data,'team')
    assert '已核实至少' in html and '目标奖金、PK奖金及队长询盘均待核对' in html
    assert '目标奖金 ¥0.00' not in html and '还差 1 个新签' not in html


def test_award_routes_persist_rules_and_block_usd_targets(setup, monkeypatch):
    s=setup
    payload={**s.payload,"name":"11月份新签PK奖","start_date":"2026-11-01","end_date":"2026-11-30",
             "award_kind":"new_sign_pk","award_rules":{"push_start_date":"2026-11-01"}}
    payload["members"][2]["is_captain"]=True
    response=s.client.post('/api/battle-reports',json=payload)
    assert response.status_code==200,response.text
    r=response.json()["data"]; assert r["currency"]=="USD" and r["award_rules"]["push_start_date"]=="2026-11-01"
    url=f"/api/battle-reports/{r['id']}"
    assert s.client.post(url+'/state',json={"action":"publish","version":1}).status_code==200
    # Future awards do not query the shared mirror at all.
    overview=s.client.get(url+'/overview').json()["data"]
    assert overview["period_state"]=="upcoming" and len(overview["teams"])==2
    assert s.client.put(url+'/targets',json={"targets":[{"member_id":s.report["members"][0]["id"],"version":1,"target_usd":"1"}]}).status_code==422
    config=s.client.get(url+'/poster-config').json()["data"]
    assert config["poster_kinds"]==["team"] and config["send_times"]==["09:00","16:00"]
    assert s.client.put(url+'/poster-config',json={"version":config['version'],"work_dates":[],"push_enabled":False}).status_code==200
    become(s,4)
    assert s.client.get(url+'/overview').status_code==403


def test_source_query_uses_usd_and_cross_owner_repeats(setup):
    s=setup
    for column, type_ in (("synced_at","DATETIME"),):
        s.db.execute(text(f"ALTER TABLE lsordertest.okki_orders ADD COLUMN {column} {type_}"))
    s.db.execute(text("""UPDATE lsordertest.okki_orders SET
        synced_at='2026-09-22 11:59:00',custom_fields=:fields,company_id=order_id"""),{"fields":json.dumps({stats.NEW_DEAL_FIELD:"是"})})
    s.db.execute(text("""INSERT INTO lsordertest.okki_orders(order_id,name,company_id,user_id,account_date,amount_usd,status,custom_fields,synced_at)
        VALUES ('repeat','goods','O1','outsider','2026-09-22',5000,'13972831656',:fields,'2026-09-22 11:59:00')"""),{"fields":json.dumps({stats.NEW_DEAL_FIELD:"否"})})
    raw,synced=stats.source_facts(s.db,campaign(),[member(1),member(2),member(3)],datetime(2026,9,22,12))
    assert synced=="2026-09-22 11:59:00" or synced=="2026-09-22T11:59:00"
    assert any(r["user_id"]=="outsider" for r in raw)
    data=stats.calculate(campaign(baselines={1:100,2:100,3:100}),[member(1),member(2),member(3)],raw,datetime(2026,9,22,12),synced)
    assert data["data_complete"] and Decimal(next(r for r in data["people"] if r["member_id"]==1)["repeat_amount"])==Decimal('5000')


def test_single_award_delivery_is_idempotent_and_uncertain_not_resent(posters, monkeypatch):
    s=posters; r=s.report_obj
    r.award_kind="annual_repurchase"; r.award_rules={"push_start_date":"2026-10-19"};r.start_date=date(2026,1,1);r.end_date=date(2026,12,31);r.poster_push_enabled=True
    s.db.commit()
    now=datetime(2026,10,19,9)
    monkeypatch.setattr(poster_delivery,"beijing_now",lambda:now)
    monkeypatch.setattr(poster_delivery,"build_snapshot",lambda *a:{"calculated_at":now.isoformat(),"report":{"name":"年度奖"}})
    mock_render(monkeypatch)
    poster_delivery.send_slot(s.db,r.id,now,s.sender)
    poster_delivery.send_slot(s.db,r.id,now,s.sender)
    assert s.sender.send_markdown.await_count==1
    row=s.db.query(BattleReportDelivery).one()
    assert list(row.deliveries)==["personal"]
    row.deliveries={"personal":{"status":"uncertain","attempts":1}};s.db.commit()
    poster_delivery.send_slot(s.db,r.id,now,s.sender)
    assert s.sender.send_markdown.await_count==1


def test_presets_require_complete_identity_mapping_and_admin(setup):
    s=setup
    data=s.client.get('/api/battle-reports/award-presets').json()['data']
    assert len(data['items'])==2 and all(not p['ready'] for p in data['items'])
    assert [len(p['missing']) for p in data['items']]==[17,10]
    assert s.db.query(BattleReport).count()==1
    become(s,1)
    assert s.client.get('/api/battle-reports/award-presets').status_code==403


def test_annual_excel_target_is_persisted_and_change_is_audited_and_disables_push(setup):
    s=setup
    payload={**s.payload,'name':'年度奖','start_date':'2026-01-01','end_date':'2026-12-31',
        'award_kind':'annual_repurchase','award_rules':{'push_start_date':'2026-10-19',
        'baselines':[{'ark_user_id':m['ark_user_id'],'hired_date':'2024-01-01','gmv_2025_usd':'648734.07','target_gmv_usd':'843354.291'} for m in s.payload['members']]}}
    response=s.client.post('/api/battle-reports',json=payload)
    assert response.status_code==200,response.text
    rid=response.json()['data']['id'];url=f'/api/battle-reports/{rid}'
    assert response.json()['data']['award_rules']['baselines'][0]['target_gmv_usd']=='843354.291'
    assert s.client.post(url+'/state',json={'action':'publish','version':1}).status_code==200
    report=s.db.get(BattleReport,rid);report.poster_push_enabled=True;s.db.commit()
    payload['award_rules']['baselines'][0]['target_gmv_usd']='800000.123456'
    response=s.client.put(url,json={**payload,'version':2,'reason':'更正附件目标'})
    assert response.status_code==200,response.text
    s.db.refresh(report)
    assert report.currency=='USD' and not report.poster_push_enabled
    from app.battle_report.models import BattleReportAudit
    audit=s.db.query(BattleReportAudit).filter_by(report_id=rid,action='configure').one()
    assert audit.before['award_rules']['baselines'][0]['target_gmv_usd']=='843354.291'
    assert audit.after['award_rules']['baselines'][0]['target_gmv_usd']=='800000.123456'


@pytest.mark.parametrize('value',[None,'0','-1','NaN','Infinity','800000.1234567'])
def test_missing_or_invalid_excel_target_is_rejected(value):
    from pydantic import ValidationError
    from app.battle_report.schemas import AwardBaseline
    with pytest.raises(ValidationError):
        AwardBaseline(ark_user_id=1,hired_date='2024-01-01',gmv_2025_usd='100',target_gmv_usd=value)
