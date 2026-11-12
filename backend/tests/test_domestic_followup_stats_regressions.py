"""Authorization, statistical denominator and evidence lifecycle regressions."""
import json
from datetime import datetime, timedelta

import pytest

from app.domestic_followup import insight_generation, insight_service, stats_service
from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot
from app.domestic_followup.models import DomesticFollowupConfig, DomesticFollowupTask
from tests.domestic_followup_helpers import followup_client, make_customer, make_user, seed_dicts
from tests.test_domestic_followup_insights import _confirmed, _snapshot, TODAY, SALES, MANAGER
from tests.test_domestic_followup_stats import _record, _roster


@pytest.fixture(autouse=True)
def fixed_business_day(monkeypatch):
    for module in (insight_generation, insight_service, stats_service):
        monkeypatch.setattr(module, "beijing_today", lambda: TODAY)


def _claims(user, permissions=SALES):
    return {"sub": str(user.id), "permissions": list(permissions)}


def _item(record, **kwargs):
    return {"category": "deal", "customer_id": record.customer_id, "title": "报价机会", "body": "客户问价",
            "evidence_followup_ids": [record.id], **kwargs}


def test_drilldown_matches_self_and_team_author_roster(db):
    sales, outsider, manager = [make_user(db, name) for name in ("own", "outsider", "manager")]
    customer = make_customer(db, sales, "共享可见客户")
    own = _record(db, sales, customer, TODAY, result="有效沟通", states=["订单减少"])
    _record(db, outsider, customer, TODAY, result="有效沟通", states=["订单减少"])
    _roster(db, [sales])
    for user, permissions in ((sales, SALES), (manager, MANAGER)):
        data = stats_service.drilldown(db, _claims(user, permissions))
        assert data["total"] == 1
        assert data["items"][0]["id"] == own.id
    with pytest.raises(PermissionError):
        stats_service.drilldown(db, _claims(sales), user_id=outsider.id)


def test_workday_average_excludes_sunday_and_configured_days(db):
    sales = make_user(db, "day_average")
    customer = make_customer(db, sales, "日均店")
    _roster(db, [sales])
    _record(db, sales, customer, TODAY - timedelta(days=4))  # Sunday
    _record(db, sales, customer, TODAY - timedelta(days=3))  # Configured holiday
    db.add(DomesticFollowupConfig(key="stats_non_workdays", value=["2026-11-09"]))
    data = stats_service.personal(db, _claims(sales))
    assert data["people"][0]["kpis"]["count"] == 2
    assert data["people"][0]["rhythm_summary"]["average"] == 0


def test_commitment_drilldown_includes_unfinished_and_snoozed_denominator(db):
    sales = make_user(db, "commitment_drill")
    customer = make_customer(db, sales, "约定店")
    _roster(db, [sales])
    for index, (status, snoozed) in enumerate((("done", 0), ("todo", 0), ("done", 1))):
        db.add(DomesticFollowupTask(task_type="plan", customer_id=customer.id, assignee_user_id=sales.id,
               source_key=f"quality-plan-{index}", title="约定", due_date=TODAY, status=status,
               snooze_count=snoozed, closed_at=datetime(2026, 11, 12) if status == "done" else None))
    data = stats_service.drilldown(db, _claims(sales), kind="plans")
    assert data["total"] == 3
    assert sum(row["on_time"] for row in data["items"]) == 1
    assert stats_service.personal(db, _claims(sales))["people"][0]["quality"]["commitment"]["denominator"] == 3


def test_never_contacted_customer_uses_latest_assignment_date(db):
    from app.domestic_followup.collaboration_models import FollowupResponsibility, FollowupCollaborationEvent
    sales, old = make_user(db, "new_owner"), make_user(db, "old_owner")
    customer = make_customer(db, old, "刚接手店", level="S级")
    db.add(FollowupResponsibility(customer_id=customer.id, owner_user_id=sales.id, status="following",
                                 version=2, created_at=datetime(2026, 8, 1)))
    db.add(FollowupCollaborationEvent(customer_id=customer.id, actor_user_id=sales.id, action="reassign",
                                    from_user_id=old.id, to_user_id=sales.id, responsibility_version=2,
                                    created_at=datetime(2026, 11, 11)))
    assert stats_service.personal(db, _claims(sales))["people"][0]["kpis"]["overdue"] == 0


def test_manager_can_feedback_selected_person_but_task_replay_still_checks_owner(db):
    sales, manager, stranger = [make_user(db, name) for name in ("feedback_owner", "feedback_manager", "stranger")]
    customer = make_customer(db, sales, "操作店")
    record = _confirmed(db, sales, customer)
    _, items = _snapshot(db, "personal", sales.id, [_item(record)])
    item_id = items[0].id
    assert insight_service.feedback(db, _claims(manager, MANAGER), item_id, "up")["feedback"] == "up"
    first = insight_service.to_task(db, _claims(sales), item_id, TODAY, "报价")
    with pytest.raises(PermissionError):
        insight_service.to_task(db, _claims(stranger), item_id, TODAY, "重复")
    assert insight_service.to_task(db, _claims(sales), item_id, TODAY, "重复")["task_id"] == first["task_id"]


def test_edited_evidence_hides_old_judgment_and_blocks_task(db):
    sales = make_user(db, "edit_evidence")
    customer = make_customer(db, sales, "证据变更店")
    record = _confirmed(db, sales, customer)
    _, items = _snapshot(db, "personal", sales.id, [_item(record)])
    record.version += 1
    record.summary = "客户已撤回采购计划"
    db.flush()
    assert insight_service.get(db, _claims(sales))["personal"]["items"] == []
    with pytest.raises(LookupError):
        insight_service.to_task(db, _claims(sales), items[0].id, TODAY, "报价")


def test_company_public_read_rechecks_evidence_and_hides_private_note(db):
    sales, author = make_user(db, "public_reader"), make_user(db, "private_author")
    records = [_confirmed(db, author, make_customer(db, author, f"秘密店{i}")) for i in range(3)]
    for row in records:
        row.obstacles = ["价格"]
    snapshot, items = _snapshot(db, "company", None, [{
        "category": "common", "theme_key": "obstacle:价格", "title": "秘密店0老板原话", "body": "私人内容",
        "adoption_note": "联系人私密备注", "evidence_followup_ids": [r.id for r in records], "sample_size": 3,
        "public_summary": {"title": "价格障碍", "body": "涉及 3 家客户", "suggested_action": "完善报价说明"},
    }])
    snapshot.payload = {"highlights": [{"title": "仅秘密店0一家"}]}
    data = insight_service.get(db, _claims(sales))["company"]
    assert data["highlights"] == []
    assert len(data["items"]) == 1
    assert "秘密" not in json.dumps(data, ensure_ascii=False)
    assert "私密" not in json.dumps(data, ensure_ascii=False)
    records[0].status = "discarded"
    db.flush()
    assert insight_service.get(db, _claims(sales))["company"]["items"] == []
    with pytest.raises(PermissionError):
        insight_service.adopt(db, _claims(sales), items[0].id, "采纳")


def test_public_ai_prompt_contains_aggregates_only(db, monkeypatch):
    seed_dicts(db)
    prompts = []
    def chat(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return {"content": json.dumps({"items": [{"theme_key": "obstacle:价格", "title": "价格障碍",
                           "body": "涉及 {customer_count} 家", "suggested_action": "梳理报价说明"}]})}
    monkeypatch.setattr(insight_generation, "chat", chat)
    result = insight_generation._public_summaries(db, {"obstacle:价格": {
        "label": "障碍：价格", "customer_count": 3, "record_ids": [123],
        "evidence": [{"raw_text": "绝不能发给匿名分析的原话", "shop_name": "秘密店"}],
    }}, [], set())
    assert "秘密" not in prompts[0] and "原话\"" not in prompts[0] and "123" not in prompts[0]
    assert result["obstacle:价格"]["body"] == "涉及 3 家"


def test_stale_refresh_is_recoverable_and_late_worker_cannot_publish(db, monkeypatch):
    from app.domestic_followup import insight_queue
    sales = make_user(db, "stale_generation")
    customer = make_customer(db, sales, "队列店")
    record = _confirmed(db, sales, customer)
    stale = DomesticFollowupInsightSnapshot(scope="personal", user_id=sales.id, status="running", trigger="test",
        period_start=TODAY-timedelta(days=30), period_end=TODAY, updated_at=datetime(2020, 1, 1), run_token="old")
    db.add(stale); db.flush()
    result = insight_service.refresh(db, _claims(sales))
    db.commit(); db.refresh(stale)
    assert stale.status == "failed" and result["started"]
    target = result["snapshot_ids"][0]
    def stale_during_chat(**kwargs):
        job = db.get(DomesticFollowupInsightSnapshot, target)
        job.updated_at = datetime(2020, 1, 1)
        db.flush(); insight_queue.recover_stale(db); db.commit()
        return {"content": json.dumps({"items": [{**_item(record), "suggested_action": "报价", "suggested_date": str(TODAY)}]})}
    monkeypatch.setattr(insight_generation, "chat", stale_during_chat)
    assert insight_generation.generate_snapshot(db, target) is False
    db.expire_all()
    assert db.get(DomesticFollowupInsightSnapshot, target).status == "failed"
    assert db.query(DomesticFollowupInsight).filter_by(snapshot_id=target).count() == 0


@pytest.mark.parametrize("value", [[{}], ["20261112"], ["2026-W46-4"], ["2026-11-12", "2026-11-12"]])
def test_nonworkdays_reject_invalid_or_noncanonical_dates(db, value):
    from app.domestic_followup import config_service
    with pytest.raises(ValueError):
        config_service.update_config(db, {"stats_non_workdays": value}, None)


def test_numeric_slots_reject_fabricated_counts_but_allow_product_dimensions():
    assert insight_generation._fill("讨论 35cm 产品，涉及 {count} 家", {"count": 3}) == "讨论 35cm 产品，涉及 3 家"
    with pytest.raises(ValueError):
        insight_generation._fill("已经触达 999 家", {})


def test_personal_and_manager_feedback_survive_daily_carry_and_do_not_overwrite(db):
    sales, manager = make_user(db, "carry_sales"), make_user(db, "carry_manager")
    record = _confirmed(db, sales, make_customer(db, sales, "评语店"))
    _, items = _snapshot(db, "personal", sales.id, [_item(record, category="method", customer_id=None)])
    original = items[0]
    insight_service.feedback(db, _claims(sales), original.id, "up")
    later = DomesticFollowupInsightSnapshot(scope="personal", user_id=sales.id, status="running", trigger="daily",
        period_start=TODAY-timedelta(days=59), period_end=TODAY)
    db.add(later); db.flush()
    insight_generation._copy_carried_items(db, later, ("deal", "cold"))
    later.status = "done"; db.commit()
    carried = db.query(DomesticFollowupInsight).filter_by(snapshot_id=later.id).one()
    insight_service.feedback(db, _claims(manager, MANAGER), carried.id, "down")
    assert insight_service.get(db, _claims(sales))["personal"]["items"][0]["feedback"] == "up"
    assert insight_service.get(db, _claims(manager, MANAGER), user_id=sales.id)["personal"]["items"][0]["feedback"] == "down"
    insight_service.feedback(db, _claims(sales), original.id, None)  # old open page still addresses the same feedback
    assert insight_service.get(db, _claims(manager, MANAGER), user_id=sales.id)["personal"]["items"][0]["feedback"] == "down"


def test_handoff_hides_old_opportunity_even_when_archive_owner_is_unchanged(db):
    from app.domestic_followup.collaboration_models import FollowupResponsibility
    sales, new_owner = make_user(db, "handoff_sales"), make_user(db, "handoff_receiver")
    customer = make_customer(db, sales, "交接店")
    record = _confirmed(db, sales, customer)
    _snapshot(db, "personal", sales.id, [_item(record)])
    db.add(FollowupResponsibility(customer_id=customer.id, owner_user_id=new_owner.id, status="following", version=2))
    db.flush()
    assert insight_service.get(db, _claims(sales))["personal"]["items"] == []


def test_behavior_suggestion_cannot_expose_arbitrary_customer_metadata(db):
    sales, other = make_user(db, "metadata_sales"), make_user(db, "metadata_other")
    record = _confirmed(db, sales, make_customer(db, sales, "自己的店"))
    hidden = make_customer(db, other, "绝不能泄露的客户")
    _snapshot(db, "personal", sales.id, [_item(record, category="method", customer_id=hidden.id)])
    data = insight_service.get(db, _claims(sales))["personal"]
    assert data["items"][0]["customer_id"] is None
    assert "绝不能" not in json.dumps(data, ensure_ascii=False)


def test_unsubmitted_persisted_queue_can_be_resumed_after_restart(db, monkeypatch):
    from contextlib import nullcontext
    sales = make_user(db, "restart_queue")
    result = insight_service.refresh(db, _claims(sales))
    db.commit()
    monkeypatch.setattr(insight_generation, "SessionLocal", lambda: nullcontext(db))
    assert insight_generation.pending_snapshots() == result["snapshot_ids"]


def test_disabled_generation_does_not_start_persisted_work(db, monkeypatch):
    from contextlib import nullcontext
    sales = make_user(db, "paused_queue")
    result = insight_service.refresh(db, _claims(sales))
    db.add(DomesticFollowupConfig(key="insight_generation_enabled", value=False))
    db.commit()
    monkeypatch.setattr(insight_generation, "SessionLocal", lambda: nullcontext(db))
    assert insight_generation.pending_snapshots() == []
    assert insight_generation.generate_snapshot(db, result["snapshot_ids"][0]) is False
    assert db.get(DomesticFollowupInsightSnapshot, result["snapshot_ids"][0]).status == "queued"


def test_practice_rechecks_uncited_sample_records_and_exact_won_set(db, monkeypatch):
    from app.domestic_followup import insight_evidence
    manager = make_user(db, "practice_manager")
    records = [_confirmed(db, manager, make_customer(db, manager, f"样本店{i}")) for i in range(11)]
    sample = {row.customer_id for row in records}
    won = set(sample)
    monkeypatch.setattr(insight_evidence, "won_customer_ids", lambda db, ids, today: set(ids) & won)
    _snapshot(db, "company", None, [{"category": "practice", "title": "成交观察", "body": "样本观察",
        "evidence_followup_ids": [records[0].id], "sample_customer_ids": sorted(sample), "sample_size": 11}])
    assert len(insight_service.get(db, _claims(manager, MANAGER))["company"]["items"]) == 1
    won.remove(records[-1].customer_id)  # Still ten wins, but the saved count of eleven is invalid.
    assert insight_service.get(db, _claims(manager, MANAGER))["company"]["items"] == []
    won.update(sample)
    records[-1].status = "discarded"  # A non-cited sample is no longer part of the analysis input.
    db.flush()
    assert insight_service.get(db, _claims(manager, MANAGER))["company"]["items"] == []


@pytest.mark.parametrize("hour, expected", [(15, "2026-11-11"), (16, "2026-11-12")])
def test_midnight_period_and_refresh_quota_use_beijing_on_non_china_server(db, monkeypatch, hour, expected):
    from datetime import timezone
    from app.core import time as business_time
    class ServerDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 11, 11, hour, 0, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(business_time, "datetime", ServerDateTime)
    monkeypatch.setattr(stats_service, "beijing_today", business_time.beijing_today)
    monkeypatch.setattr(insight_service, "beijing_today", business_time.beijing_today)
    sales = make_user(db, f"midnight_{hour}")
    result = insight_service.refresh(db, _claims(sales))
    assert str(stats_service._period()["end"]) == expected
    snapshot = db.get(DomesticFollowupInsightSnapshot, result["snapshot_ids"][0])
    assert str(snapshot.request_day) == expected
    assert str(snapshot.created_at.date()) == expected
