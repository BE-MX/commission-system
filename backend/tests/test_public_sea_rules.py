"""公海双钟规则：3 个月未下单 或 1 个月未跟进（2026-11-13 Q1~Q6）。"""
import json
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.time import beijing_now, beijing_today
from app.domestic import customer_service, public_sea
from app.domestic.models import DomesticCustomer, DomesticOrder
from app.domestic.router import router
from app.domestic.schemas import CustomerCreate
from app.domestic_followup import config_service
from app.domestic_followup.collaboration_models import FollowupCollaborator, FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask

TODAY = beijing_today()


def _user(db, name):
    user = ArkUser(username=name, password_hash="x", real_name=name)
    db.add(user)
    db.flush()
    return user


def _customer(db, owner, name, *, age_days=0):
    customer = customer_service.create_customer(db, CustomerCreate(shop_name=name, custom_code=f"PS-{name}"), owner.id)
    customer.created_at = beijing_now() - timedelta(days=age_days)
    db.flush()
    return customer


def _followup(db, customer, author, days_ago, status="confirmed"):
    db.add(DomesticFollowup(author_user_id=author.id, customer_id=customer.id, request_id=f"ps-{customer.id}-{days_ago}-{status}",
                            followup_date=TODAY - timedelta(days=days_ago), status=status))
    db.flush()


def _order(db, customer, creator, days_ago, status=1):
    db.add(DomesticOrder(domestic_no=f"PS-{customer.id}-{days_ago}", order_no=f"PSN-{customer.id}-{days_ago}",
                         order_date=TODAY - timedelta(days=days_ago), customer_id=customer.id, created_by=creator.id,
                         status=status))
    db.flush()


def _launch(db, days_ago):
    """测试里直接写库：界面与接口拒绝过去的生效日，这里要模拟「已生效一段时间」。"""
    from app.domestic_followup.models import DomesticFollowupConfig

    value = None if days_ago is None else (TODAY - timedelta(days=days_ago)).isoformat()
    row = db.get(DomesticFollowupConfig, public_sea.LAUNCH_CONFIG_KEY)
    if row is None:
        db.add(DomesticFollowupConfig(key=public_sea.LAUNCH_CONFIG_KEY, value=value))
    else:
        row.value = value
    db.flush()


def _reload(db, *rows):
    for row in rows:
        db.refresh(row)


# ---------- 释放日的日期算术 ----------

@pytest.mark.parametrize("effective,months,expected", [
    (date(2026, 11, 29), 3, date(2027, 3, 1)),
    (date(2026, 11, 30), 3, date(2027, 3, 1)),
    (date(2026, 11, 28), 3, date(2027, 2, 28)),
    (date(2026, 1, 31), 1, date(2026, 3, 1)),
    (date(2026, 1, 15), 1, date(2026, 2, 15)),
    (date(2027, 12, 31), 3, date(2028, 3, 31)),
])
def test_release_day_month_ends(effective, months, expected):
    assert public_sea.release_day(effective, months) == expected


@pytest.mark.parametrize("months", [1, 3])
def test_release_day_matches_cutoff_rule_every_day(months):
    """图上的释放日必须与任务判定 `effective <= months_ago(today)` 逐日一致。"""
    start = date(2027, 10, 15)
    for offset in range(0, 500, 3):
        effective = start + timedelta(days=offset)
        due = public_sea.release_day(effective, months)
        for today in (due - timedelta(days=1), due, due + timedelta(days=1)):
            assert (effective <= public_sea.months_ago(today, months)) == (today >= due)


# ---------- 释放任务 ----------

def test_follow_clock_only_runs_after_launch(db):
    owner = _user(db, "ps-owner")
    quiet = _customer(db, owner, "沉默客户", age_days=45)

    _launch(db, None)
    assert customer_service.release_stale_private_customers(db) == 0
    clock = public_sea.compute_clocks(db, [quiet], TODAY)[quiet.id]
    assert clock.follow_due is None and clock.display()[1] == public_sea.REASON_FOLLOW
    assert clock.display()[0] < TODAY  # 预演里已经过期

    _launch(db, 0)  # 生效当天：从生效日起算，宽限 1 个自然月
    assert customer_service.release_stale_private_customers(db) == 0
    clock = public_sea.compute_clocks(db, [quiet], TODAY)[quiet.id]
    assert clock.follow_due == public_sea.release_day(TODAY, 1)

    _launch(db, 40)
    assert customer_service.release_stale_private_customers(db) == 1
    _reload(db, quiet)
    assert quiet.owner_user_id is None


def test_followup_and_order_both_reset_follow_clock(db):
    owner = _user(db, "ps-owner2")
    followed = _customer(db, owner, "有跟进", age_days=60)
    ordered = _customer(db, owner, "刚下单", age_days=60)
    draft_only = _customer(db, owner, "只有草稿", age_days=60)
    pending_order = _customer(db, owner, "待审核订单", age_days=60)
    _followup(db, followed, owner, 5)
    _order(db, ordered, owner, 10)
    _followup(db, draft_only, owner, 2, status="draft")
    _order(db, pending_order, owner, 3, status=5)  # 待审核
    _launch(db, 90)

    assert customer_service.release_stale_private_customers(db) == 2
    _reload(db, followed, ordered, draft_only, pending_order)
    assert followed.owner_user_id == owner.id
    assert ordered.owner_user_id == owner.id
    assert draft_only.owner_user_id is None
    assert pending_order.owner_user_id is None


def test_paused_customer_waits_until_day_after_agreed_date(db):
    owner = _user(db, "ps-owner3")
    paused = _customer(db, owner, "暂缓客户", age_days=60)
    db.add(FollowupResponsibility(customer_id=paused.id, owner_user_id=owner.id, status="following",
                                  stage="paused", next_plan_date=TODAY + timedelta(days=5)))
    db.flush()
    _launch(db, 90)
    assert customer_service.release_stale_private_customers(db) == 0
    clock = public_sea.compute_clocks(db, [paused], TODAY)[paused.id]
    assert clock.follow_due == TODAY + timedelta(days=6)
    assert clock.order_due > TODAY  # 订单钟照走，不受暂缓影响


def _task(db, customer, owner, kind):
    task = DomesticFollowupTask(task_type=kind, customer_id=customer.id, assignee_user_id=owner.id,
                                source_key=f"ps-{customer.id}-{kind}", title=kind, due_date=TODAY)
    db.add(task)
    db.flush()
    return task


def test_follow_release_ends_responsibility_and_tasks(db):
    owner, helper = _user(db, "ps-owner4"), _user(db, "ps-helper")
    customer = _customer(db, owner, "因未跟进释放", age_days=60)
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=owner.id, status="following",
                                            stage="contacted", next_plan_date=TODAY - timedelta(days=3))
    db.add(responsibility)
    db.add(FollowupCollaborator(customer_id=customer.id, user_id=helper.id, added_by_user_id=owner.id))
    plan, issue = _task(db, customer, owner, "plan"), _task(db, customer, owner, "issue")
    _launch(db, 90)

    assert customer_service.release_stale_private_customers(db) == 1
    _reload(db, customer, responsibility, plan, issue)
    assert customer.owner_user_id is None
    assert (responsibility.owner_user_id, responsibility.status, responsibility.next_plan_date) == (None, "unassigned", None)
    assert responsibility.version == 2
    assert db.query(FollowupCollaborator).filter_by(customer_id=customer.id).count() == 0
    assert (plan.status, plan.closed_reason) == ("cancelled", "客户释放")
    assert issue.status == "todo"  # 异常与意见不随归属走


def test_order_release_keeps_responsibility(db):
    owner = _user(db, "ps-owner5")
    customer = _customer(db, owner, "因未下单释放", age_days=120)
    _followup(db, customer, owner, 2)
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=owner.id, status="following",
                                            stage="contacted")
    db.add(responsibility)
    plan = _task(db, customer, owner, "plan")
    _launch(db, 90)

    assert customer_service.release_stale_private_customers(db) == 1
    _reload(db, customer, responsibility, plan)
    assert customer.owner_user_id is None
    assert (responsibility.owner_user_id, responsibility.status) == (owner.id, "following")  # 11-09 D07
    assert plan.status == "todo"


# ---------- 认领 ----------

def _client(db, user, *permissions):
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user.id), "roles": [], "permissions": list(permissions)}
    return TestClient(app)


def test_claim_resets_only_the_follow_clock(db):
    """2026-11-13 亮哥定：认领不重置订单钟，防止放掉再认领回来无限续期。"""
    old_owner, claimer = _user(db, "ps-old"), _user(db, "ps-claimer")
    stale = _customer(db, old_owner, "久未下单公海客户", age_days=200)
    recent = _customer(db, old_owner, "近期下过单公海客户", age_days=200)
    _order(db, recent, old_owner, 40)
    stale.owner_user_id = recent.owner_user_id = None
    db.flush()
    _launch(db, 90)
    client = _client(db, claimer, "domestic:write")

    response = client.post(f"/api/domestic/customers/{stale.id}/claim")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["order_expired"] is True and "今天不下单" in body["message"]
    _reload(db, stale)
    assert stale.owner_user_id == claimer.id and stale.owner_claimed_at is not None
    clock = public_sea.compute_clocks(db, [stale], TODAY)[stale.id]
    assert clock.follow_due == public_sea.release_day(TODAY, 1)
    assert clock.order_due < TODAY  # 订单钟不随认领重置

    ok_response = client.post(f"/api/domestic/customers/{recent.id}/claim")
    assert ok_response.json()["data"]["order_expired"] is False
    assert ok_response.json()["data"]["order_due"] == public_sea.release_day(TODAY - timedelta(days=40), 3).isoformat()

    # 久未下单的那家下一次释放会回到公海；近期下过单的留住
    assert customer_service.release_stale_private_customers(db) == 1
    _reload(db, stale, recent)
    assert stale.owner_user_id is None and recent.owner_user_id == claimer.id

    again = client.post(f"/api/domestic/customers/{recent.id}/claim")
    assert again.status_code == 409


def test_reclaiming_own_customer_does_not_extend_the_order_clock(db):
    owner = _user(db, "ps-self-reclaim")
    customer = _customer(db, owner, "自己放掉再认领", age_days=200)
    assert customer_service.release_stale_private_customers(db) == 1
    result = customer_service.claim_customer(db, customer.id, owner.id)
    assert result["order_expired"] is True
    assert customer_service.release_stale_private_customers(db) == 1


def test_claim_rejects_disabled_and_requires_write(db):
    owner, reader = _user(db, "ps-owner6"), _user(db, "ps-reader")
    disabled = _customer(db, owner, "停用公海客户")
    disabled.owner_user_id, disabled.status = None, 0
    db.flush()
    assert _client(db, reader, "domestic:read").post(f"/api/domestic/customers/{disabled.id}/claim").status_code == 403
    writer = _user(db, "ps-writer")
    assert _client(db, writer, "domestic:write").post(f"/api/domestic/customers/{disabled.id}/claim").status_code == 409


def test_paused_customer_survives_the_agreed_day_itself(db):
    owner = _user(db, "ps-owner-day")
    paused = _customer(db, owner, "约定今天联系", age_days=60)
    db.add(FollowupResponsibility(customer_id=paused.id, owner_user_id=owner.id, status="following",
                                  stage="paused", next_plan_date=TODAY))
    db.flush()
    _launch(db, 90)
    assert customer_service.release_stale_private_customers(db) == 0
    assert public_sea.compute_clocks(db, [paused], TODAY)[paused.id].follow_due == TODAY + timedelta(days=1)


def test_preview_counts_from_configured_future_launch(db):
    owner = _user(db, "ps-owner-preview")
    old = _customer(db, owner, "老客户", age_days=40)
    _launch(db, -20)  # 20 天后生效
    clock = public_sea.compute_clocks(db, [old], TODAY)[old.id]
    assert clock.follow_due is None
    assert clock.display() == (public_sea.release_day(TODAY + timedelta(days=20), 1), public_sea.REASON_FOLLOW)


def test_claim_after_follow_release_can_write_followups(db):
    from tests.domestic_followup_helpers import grant
    from app.domestic_followup import visibility
    from app.domestic_followup.collaboration_models import FollowupCollaborationEvent, FollowupHandoff

    old_owner, claimer = _user(db, "ps-loop-old"), _user(db, "ps-loop-claimer")
    grant(db, claimer, "domestic_followup:read", "domestic_followup:write")
    customer = _customer(db, old_owner, "释放后认领", age_days=60)
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=old_owner.id, status="handoff",
                                            stage="contacted")
    db.add(responsibility)
    db.flush()
    handoff = FollowupHandoff(customer_id=customer.id, from_user_id=old_owner.id, recipient_user_id=claimer.id,
                              requester_user_id=old_owner.id, kind="offer", status="pending", pending_marker=1,
                              version=1, responsibility_version=1, reason="交接", tasks=[], selected_record_ids=[])
    db.add(handoff)
    db.flush()
    _launch(db, 90)
    assert customer_service.release_stale_private_customers(db) == 1
    _reload(db, handoff)
    assert (handoff.status, handoff.pending_marker) == ("invalidated", None)

    customer_service.claim_customer(db, customer.id, claimer.id)
    _reload(db, customer, responsibility)
    assert (responsibility.owner_user_id, responsibility.status) == (claimer.id, "following")
    user = {"sub": str(claimer.id), "permissions": ["domestic_followup:read", "domestic_followup:write"], "roles": []}
    assert visibility.can_write_customer(db, user, customer)
    event = db.query(FollowupCollaborationEvent).filter_by(customer_id=customer.id, action="claim").one()
    assert event.actor_user_id == claimer.id


def test_claim_keeps_someone_elses_live_responsibility(db):
    old_owner, follower, claimer = _user(db, "ps-d07-old"), _user(db, "ps-d07-follow"), _user(db, "ps-d07-claim")
    customer = _customer(db, old_owner, "公海仍有人跟")
    customer.owner_user_id = None
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=follower.id, status="following",
                                            stage="contacted")
    db.add(responsibility)
    db.flush()
    customer_service.claim_customer(db, customer.id, claimer.id)
    _reload(db, responsibility)
    assert responsibility.owner_user_id == follower.id


def test_claim_takes_over_a_stopped_responsibility(db):
    from tests.domestic_followup_helpers import grant
    from app.domestic_followup import visibility

    old_owner, claimer = _user(db, "ps-stop-old"), _user(db, "ps-stop-claimer")
    grant(db, claimer, "domestic_followup:read", "domestic_followup:write")
    customer = _customer(db, old_owner, "停止开发后落海", age_days=200)
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=old_owner.id, status="stopped",
                                            stage="contacted", allow_future_contact=True)
    db.add(responsibility)
    db.flush()
    assert customer_service.release_stale_private_customers(db) == 1  # 订单钟
    customer_service.claim_customer(db, customer.id, claimer.id)
    _reload(db, customer, responsibility)
    assert (responsibility.owner_user_id, responsibility.status) == (claimer.id, "following")
    user = {"sub": str(claimer.id), "permissions": ["domestic_followup:read", "domestic_followup:write"], "roles": []}
    assert visibility.can_write_customer(db, user, customer)


def test_saved_past_launch_date_does_not_block_other_settings(db):
    _launch(db, 10)  # 规则已生效 10 天
    saved = (TODAY - timedelta(days=10)).isoformat()
    config = config_service.update_config(db, {"receipt_delay_days": 5, public_sea.LAUNCH_CONFIG_KEY: saved}, None,
                                          commit=False)
    assert config["receipt_delay_days"] == 5 and config[public_sea.LAUNCH_CONFIG_KEY] == saved
    with pytest.raises(ValueError, match="不能早于今天"):
        config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: (TODAY - timedelta(days=3)).isoformat()},
                                     None, commit=False)


def test_launch_date_config_validation(db):
    with pytest.raises(ValueError):
        config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: "2026/12/01"}, None, commit=False)
    with pytest.raises(ValueError):
        config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: "2026-12-1"}, None, commit=False)
    with pytest.raises(ValueError, match="不能早于今天"):
        config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: (TODAY - timedelta(days=1)).isoformat()},
                                     None, commit=False)
    future = (TODAY + timedelta(days=30)).isoformat()
    assert config_service.update_config(db, {public_sea.LAUNCH_CONFIG_KEY: future}, None,
                                        commit=False)[public_sea.LAUNCH_CONFIG_KEY] == future


def test_migration_263_only_rewrites_the_old_c_level_default():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/263_customer_owner_claimed_at.py"
    spec = importlib.util.spec_from_file_location("m263", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    read = "SELECT value FROM ark_domestic_followup_config WHERE key='frequency_days'"
    for saved, expected in (({"S级": 7, "A级": 14, "B级": 30, "C级": 60}, 30),
                            ({"S级": 7, "A级": 14, "B级": 30, "C级": 45}, 45)):
        engine = sa.create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE ark_domestic_customers (id INTEGER PRIMARY KEY)"))
            conn.execute(sa.text("CREATE TABLE ark_domestic_followup_config (key VARCHAR(64) PRIMARY KEY, value JSON, "
                                 "updated_by INTEGER, updated_at DATETIME NOT NULL)"))  # 与 246 建表一致：无库默认值
            conn.execute(sa.text("INSERT INTO ark_domestic_followup_config (key, value, updated_at) "
                                 "VALUES ('frequency_days', :v, '2026-01-01 00:00:00')"),
                         {"v": json.dumps(saved)})
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
                assert json.loads(conn.execute(sa.text(read)).scalar())["C级"] == expected
                module.downgrade()
                assert json.loads(conn.execute(sa.text(read)).scalar())["C级"] == saved["C级"]


def test_claim_uses_beijing_date_across_midnight_on_utc_server(db, monkeypatch):
    """服务器在 UTC：UTC 11-30 16:30 = 北京 12-01 00:30，认领日和倒计时都按北京 12-01 算（红线 23）。"""
    from datetime import datetime as real_datetime, timezone
    import app.core.time as core_time

    instant = real_datetime(2026, 11, 30, 16, 30, tzinfo=timezone.utc)

    class Frozen(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)  # 本地 = UTC

    monkeypatch.setattr(core_time, "datetime", Frozen)
    monkeypatch.setattr(customer_service, "beijing_today", core_time.beijing_today)
    owner = _user(db, "ps-mid-owner")
    customer = _customer(db, owner, "跨日认领")
    customer.owner_user_id = None
    db.flush()

    customer_service.claim_customer(db, customer.id, owner.id)
    _reload(db, customer)
    assert customer.owner_claimed_at == real_datetime(2026, 12, 1, 0, 30)
    today = core_time.beijing_today()
    assert today == date(2026, 12, 1)
    clock = public_sea.compute_clocks(db, [customer], today, launch=date(2026, 11, 1), launch_known=True)[customer.id]
    assert clock.follow_due == date(2027, 1, 1)
