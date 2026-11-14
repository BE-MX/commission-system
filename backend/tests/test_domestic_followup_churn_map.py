"""客户流失态势接口：权限裁剪、释放倒计时、大区归一、近 30 天落海。"""
from datetime import timedelta

from app.core.time import beijing_now, beijing_today
from app.domestic import public_sea
from app.domestic_followup import config_service
from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup
from app.domestic_followup.stats_churn import region_of
from tests.domestic_followup_helpers import followup_client, make_customer, make_user

TODAY = beijing_today()
READ_ALL = ("domestic_followup:read", "domestic_followup:read_all")


def _aged(db, customer, days, province=None):
    customer.created_at = beijing_now() - timedelta(days=days)
    customer.province = province
    db.flush()
    return customer


def _followed(db, customer, author, days_ago):
    db.add(DomesticFollowup(author_user_id=author.id, customer_id=customer.id, followup_date=TODAY - timedelta(days=days_ago),
                            request_id=f"churn-{customer.id}-{days_ago}", status="confirmed"))
    db.flush()


def _get(db, user, permissions=None, **params):
    args = (db, user) if permissions is None else (db, user, permissions)
    with followup_client(*args) as client:
        response = client.get("/api/domestic-followup/stats/churn-map", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_region_normalization():
    assert region_of("广东省") == region_of("广东") == "华南"
    assert region_of("新疆维吾尔自治区") == "西北"
    assert region_of("上海市") == "华东"
    assert region_of("") == region_of(None) == region_of("火星") == "未填地区"


def test_rep_sees_owned_and_followup_customers_only(db):
    rep, other = make_user(db, "churn-rep"), make_user(db, "churn-other")
    mine = _aged(db, make_customer(db, rep, "我的临界", level="B级"), 29, "广东省")
    handed = _aged(db, make_customer(db, other, "我跟进的", level="B级"), 25, "浙江")
    db.add(FollowupResponsibility(customer_id=handed.id, owner_user_id=rep.id, status="following", stage="contacted"))
    _aged(db, make_customer(db, other, "别人的", level="B级"), 29, "广东")
    db.flush()
    data = _get(db, rep)
    ids = {row["id"] for row in data["customers"]}
    assert ids == {mine.id, handed.id}
    row = next(row for row in data["customers"] if row["id"] == handed.id)
    assert row["mine_as_followup"] and not row["mine_as_owner"]
    assert "owner_name" not in row and row["owner_user_id"] is None
    assert data["owners"] == [] and data["scope"] == "user"
    with followup_client(db, rep) as client:
        assert client.get("/api/domestic-followup/stats/churn-map", params={"user_id": other.id}).status_code == 403


def test_preview_countdown_and_tiers_before_launch(db):
    manager, rep = make_user(db, "churn-mgr"), make_user(db, "churn-rep2")
    critical = _aged(db, make_customer(db, rep, "快掉了", level="C级"), 60, "山东")
    _followed(db, critical, rep, 29)
    stable_b = _aged(db, make_customer(db, rep, "稳固B", level="B级"), 2, "山东")
    stable_s = _aged(db, make_customer(db, rep, "稳固S", level="S级"), 2, "山东")
    data = _get(db, manager, READ_ALL)

    assert data["rule"]["launch_date"] is None and data["rule"]["follow_enforced"] is False
    rows = {row["id"]: row for row in data["customers"]}
    assert stable_b.id not in rows and stable_s.id in rows  # S/A 级始终单画
    row = rows[critical.id]
    expected = public_sea.release_day(TODAY - timedelta(days=29), 1)
    assert row["release_date"] == expected.isoformat() and row["clock"] == "follow"
    assert row["tier"] == "critical" and row["remaining_days"] == (expected - TODAY).days
    assert row["owner_name"] == "churn-rep2"
    east = next(region for region in data["regions"] if region["key"] == "华东")
    assert (east["owned"], east["critical"], east["stable"]) == (3, 1, 2)
    assert data["kpis"]["critical"] == 1


def test_enforced_rule_uses_launch_anchor(db):
    manager, rep = make_user(db, "churn-mgr3"), make_user(db, "churn-rep3")
    quiet = _aged(db, make_customer(db, rep, "生效后", level="B级"), 40, "北京")
    config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: TODAY.isoformat()}, None, commit=False)
    row = next(row for row in _get(db, manager, READ_ALL)["customers"] if row["id"] == quiet.id) \
        if False else None
    data = _get(db, manager, READ_ALL)
    assert data["rule"]["follow_enforced"] is True
    region = next(region for region in data["regions"] if region["key"] == "华北")
    assert region["stable"] == 1  # 生效当天宽限 1 个自然月，不再按预演显示过期
    assert quiet.id not in {row["id"] for row in data["customers"]}


def test_fallen_details_follow_visibility(db):
    manager, rep, owner = make_user(db, "churn-mgr4"), make_user(db, "churn-rep4"), make_user(db, "churn-owner4")
    free = _aged(db, make_customer(db, owner, "落海客户", level="A级"), 10, "四川")
    managed = _aged(db, make_customer(db, owner, "协作中落海", level="B级"), 10, "四川")
    db.add(FollowupResponsibility(customer_id=managed.id, owner_user_id=owner.id, status="following", stage="contacted"))
    db.flush()
    free.owner_user_id = None
    managed.owner_user_id = None
    db.flush()  # 分析事件钩子记下归属从有到无

    full = _get(db, manager, READ_ALL)
    assert {row["id"] for row in full["fallen"]} == {free.id, managed.id}
    assert full["fallen"][0]["previous_owner_name"] == "churn-owner4"
    southwest = next(region for region in full["regions"] if region["key"] == "西南")
    assert (southwest["public_total"], southwest["fallen_recent"]) == (2, 2)
    assert full["kpis"]["fallen_30"] == 2
    assert {"value": owner.id, "label": "churn-owner4"} not in full["owners"]  # 已无归属

    limited = _get(db, rep)  # 业务员只看自己掉下去的：同事的落海客户只进各区公海总数
    assert limited["fallen"] == [] and limited["kpis"]["fallen_30"] == 0
    assert next(region for region in limited["regions"] if region["key"] == "西南")["public_total"] == 2

    mine = _get(db, owner)
    assert {row["id"] for row in mine["fallen"]} == {free.id, managed.id}
    assert mine["fallen"][0]["previous_owner_id"] is None and "previous_owner_name" not in mine["fallen"][0]
    assert mine["kpis"]["fallen_30"] == 2
