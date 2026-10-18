"""PK artwork selection and name-to-seat mapping without business DB access."""
import re

import pytest

from app.battle_report import award_statistics, pk_poster, poster_renderer
from app.battle_report.award_presets import PK_TEAMS, ALIASES


def sample(one=(18,12,10,9,11),two=(13,8,7,6,9),*,complete=True,period='running'):
    people=[]
    for team,counts in zip(PK_TEAMS,(one,two)):
        for i,(name,count) in enumerate(zip(PK_TEAMS[team],counts)):
            people.append(dict(user_name=ALIASES.get(name,name),team=team,is_captain=i==0,
                               new_count=count,new_amount=str(count*1000),gmv=str(count*1200)))
    data=dict(award_kind='new_sign_pk',people=people,data_complete=complete,
              issues=[] if complete else ['Source mark pending'],period_state=period,
              calculated_at='2026-11-15T09:00:00',source_synced_at='2026-11-15T08:30:00')
    award_statistics.pk(data)
    return data


def html_for(data):
    return pk_poster.render_html(data,poster_renderer.ASSETS,'ONE_IMAGE','TWO_IMAGE')


@pytest.mark.parametrize('left,right,mode,background',[
    ((18,12,10,9,11),(13,8,7,6,9),'one','ONE_IMAGE'),
    ((13,8,7,6,9),(18,12,10,9,11),'two','TWO_IMAGE')])
def test_leading_background_and_correct_bonus(left,right,mode,background):
    data=sample(left,right)
    html=html_for(data)
    assert f'data-background="{mode}"' in html and f'src="{background}"' in html
    assert '团队奖金 ¥1,050' in html and '目标奖 ¥550 + PK奖 ¥500' in html
    assert '官网询盘 10个' in html and '奖励预测' in html
    assert '¥2,000' not in html and '当前领先' in html


def test_matching_names_and_captains_are_required_for_fixed_artwork():
    data=sample()
    assert pk_poster.matches_roster(data)
    data['teams'][0]['people'][0]['user_name']='Other person'
    assert not pk_poster.matches_roster(data)
    data=sample();data['teams'][1]['people'][0]['is_captain']=False
    assert not pk_poster.matches_roster(data)
    data=sample();data['teams'][0]['people'].append(data['teams'][0]['people'][0])
    assert not pk_poster.matches_roster(data)


def test_shuffled_teams_and_people_keep_name_count_and_captain_positions():
    data=sample()
    data['teams'].reverse()
    for team in data['teams']:team['people'].reverse()
    html=html_for(data)
    sections=re.findall(r'<section aria-label="([^"]+)">(.*?)</section>',html,re.S)
    assert [name for name,_ in sections]==['罗馨瑜','胡宁宁','张心茹 队长','韩玥','刘婷',
                                           '高瑞杰','刘也','凯丽 队长','栾奕','李秀玉']
    assert [re.search(r'class="pk-count[^>]+>([^<]+)',body).group(1) for _,body in sections]==['12','10','18','9','11','8','7','13','6','9']
    assert '凯丽比努尔' not in html


def test_lead_before_both_teams_reach_targets_does_not_grant_pk_reward():
    data=sample((8,7,6,5,5),(5,4,3,3,2))
    assert not data['pk_eligible'] and data['winner'] is None
    html=html_for(data)
    assert 'data-background="one"' in html and '团队奖金 ¥500' in html
    assert '双方达标后再评PK胜利奖' in html
    assert 'PK奖 ¥500' not in html and '官网询盘 10个' not in html


@pytest.mark.parametrize('tiebreak',['new_amount','gmv'])
def test_same_count_uses_existing_amount_then_gmv_tiebreak(tiebreak):
    data=sample((6,6,6,6,6),(6,6,6,6,6))
    data['people'][5][tiebreak]=str(int(data['people'][5][tiebreak])+1)
    award_statistics.pk(data)
    assert 'data-background="two"' in html_for(data)


@pytest.mark.parametrize('period',['running','upcoming','ended'])
def test_equal_metrics_have_no_crowned_background(period):
    data=sample((6,6,6,6,6),(6,6,6,6,6),period=period)
    html=html_for(data)
    assert 'data-background="neutral"' in html and 'neutral-left' in html and 'neutral-right' in html
    assert '暂无领先' in html and '领先底图' not in html
    assert 'PK胜利奖待决出' in html if period!='upcoming' else '活动未开始' in html


def test_incomplete_data_hides_all_formal_counts_progress_and_bonuses():
    data=sample(complete=False)
    html=html_for(data)
    assert 'data-background="neutral"' in html and '正式数据待填' in html
    assert html.count('>—</div>')==10 and html.count('>—</strong>')==2
    assert '200.0%' not in html and '团队奖金 ¥' not in html
    assert '目标奖金、PK奖金及队长询盘均待核对' in html


def test_mock_label_and_completed_period_reward_status():
    data=sample(period='ended');data['data_mode']='demo'
    html=html_for(data)
    assert '版式样张 · 全部数值为模拟数据' in html
    assert '不代表真实业绩或已获奖励' in html
    assert '一组胜出 · 计算结果' in html and '尚未发放' in html


@pytest.mark.parametrize('one,two', [((0,0,0,0,0),(0,0,0,0,0)),((8,7,6,5,5),(5,4,3,3,2)),((6,6,6,6,5),(6,6,6,5,5))])
def test_ended_campaign_without_both_targets_does_not_promise_future_pk_rewards(one,two):
    html=html_for(sample(one,two,period='ended'))
    assert 'PK胜利奖不予发放' in html and '队长询盘不予发放' in html
    assert '队长询盘待评' not in html and 'PK胜利奖待决出' not in html
    assert '目标奖金待达标' not in html
    if sum(one)==29:assert '未获目标奖' in html


def test_upcoming_period_never_uses_a_crowned_artwork():
    html=html_for(sample(period='upcoming'))
    assert 'data-background="neutral"' in html and '活动未开始' in html


def test_renderer_integrates_fixed_art_and_blocks_conflicting_leader_flags():
    data=sample()
    assert 'class="pk-sheet"' in poster_renderer.render_html(data,'team')
    for team in data['teams']:team['leading']=True
    with pytest.raises(RuntimeError,match='领先状态冲突'):html_for(data)
