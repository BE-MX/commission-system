from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domestic_followup import edit_service, followup_service, task_service
from app.domestic_followup.models import (
    DomesticFollowupAttachment as Attachment, DomesticFollowupDigest as Digest,
    DomesticFollowupItem as Item, DomesticFollowupRevision as Revision, DomesticFollowupTask as Task,
)
from app.domestic_followup.schemas import DirectSaveIn, EditFollowupIn
from tests.domestic_followup_helpers import followup_client, make_customer, make_user, seed_dicts


def context(user, *, root=False, all_scope=False):
    return {"sub": str(user.id), "roles": ["super_admin"] if root else [],
            "permissions": ["domestic_followup:read", "domestic_followup:write"] + (["domestic_followup:read_all"] if all_scope else [])}


@pytest.fixture
def saved(db, monkeypatch):
    seed_dicts(db)
    monkeypatch.setattr(followup_service, "beijing_today", lambda: date(2026, 11, 4))
    owner = make_user(db, "edit_author")
    other = make_user(db, "edit_other")
    customer = make_customer(db, owner, "修改测试店")
    row, _ = followup_service.direct_save(db, context(owner), DirectSaveIn(
        result_code="有效沟通",
        request_id="edit-original", customer_id=customer.id, followup_date=date(2026, 11, 1),
        raw_text="原文", summary="原摘要", next_date=date(2026, 11, 9), next_plan="问补货",
        items=[{"kind": "content", "text": "原要点"}, {"kind": "issue", "text": "色差", "category": "色差"}]))
    return owner, other, customer, row


def payload(db, row, **changes):
    data = followup_service.serialize(db, row)
    values = {key: data[key] for key in (*edit_service.EDIT_FIELDS, *followup_service.OUTCOME_FIELDS)}
    values.update(version=row.version, request_id=str(uuid4()), reason="修正录入错误",
                  attachment_ids=[a["id"] for a in data["attachments"]],
                  items=[{"id": i["id"], "kind": i["kind"], "text": i["text"], "category": i["category"],
                          "severity": i["severity"], "origin": i["origin"], "handler_user_id": i["handler_user_id"],
                          "record_only": i["status"] == "closed_no_action" and (i["resolution"] or "").startswith("仅记录")}
                         for i in data["items"]])
    return EditFollowupIn(**{**values, **changes})


def test_author_edit_audits_before_after_and_does_not_change_author(db, saved):
    owner, _, _, row = saved
    confirmed = row.confirmed_at
    previous_version = row.version
    edit_service.update(db, context(owner), row.id, payload(db, row, raw_text="更正原文", summary="更正摘要"))
    assert row.author_user_id == owner.id and row.confirmed_at == confirmed
    assert row.version == previous_version + 1
    history = edit_service.history(db, context(owner), row.id)
    assert len(history) == 1 and history[0]["before"]["raw_text"] == "原文"
    assert history[0]["after"]["raw_text"] == "更正原文"
    assert history[0]["editor_user_id"] == owner.id


def test_only_author_or_super_admin_can_edit_even_with_all_scope(db, saved):
    owner, other, _, row = saved
    with pytest.raises(PermissionError):
        edit_service.update(db, context(other, all_scope=True), row.id, payload(db, row, summary="非法"))
    assert db.query(Revision).count() == 0
    edit_service.update(db, context(other, root=True), row.id, payload(db, row, summary="管理员更正"))
    assert row.author_user_id == owner.id


def test_original_author_can_correct_after_customer_is_transferred(db, saved):
    owner, other, customer, row = saved
    customer.owner_user_id = other.id
    db.commit()
    plan = db.query(Task).filter_by(task_type="plan").one()
    assert plan.assignee_user_id == other.id
    edit_service.update(db, context(owner), row.id, payload(db, row, next_date=date(2026, 11, 10)))
    assert plan.assignee_user_id == other.id and plan.due_date == date(2026, 11, 10)


def test_idempotent_retry_and_stale_version_conflict(db, saved):
    owner, _, _, row = saved
    first = payload(db, row, summary="第一次修改")
    stale = payload(db, row, summary="过期修改")
    edit_service.update(db, context(owner), row.id, first)
    edit_service.update(db, context(owner), row.id, first)
    assert db.query(Revision).count() == 1
    with pytest.raises(followup_service.ConflictError):
        edit_service.update(db, context(owner), row.id, stale)
    with pytest.raises(followup_service.ConflictError):
        edit_service.update(db, context(owner), row.id, first.model_copy(update={"summary": "重用编号篡改"}))
    assert row.summary == "第一次修改"


def test_pending_plan_changes_in_place_and_snooze_survives_text_correction(db, saved):
    owner, _, _, row = saved
    plan = db.query(Task).filter_by(task_type="plan").one()
    plan.due_date, plan.snooze_count = date(2026, 11, 12), 1
    db.commit()
    edit_service.update(db, context(owner), row.id, payload(db, row, next_plan="修改补货内容"))
    assert plan.due_date == date(2026, 11, 12) and plan.snooze_count == 1
    assert "修改补货内容" in plan.title
    edit_service.update(db, context(owner), row.id, payload(db, row, next_date=None, next_plan=None))
    assert plan.status == "cancelled" and plan.closed_by_user_id == owner.id
    edit_service.update(db, context(owner), row.id, payload(db, row, next_date=date(2026, 11, 15)))
    assert db.query(Task).filter_by(task_type="plan", status="todo").count() == 1
    assert plan.status == "cancelled"


def test_completed_plans_and_closed_receipts_never_reopen(db, saved):
    owner, _, customer, row = saved
    plan = db.query(Task).filter_by(task_type="plan").one()
    task_service.close_task(plan, "done", "已完成", followup_id=row.id, user_id=owner.id)
    receipt = Task(task_type="receipt", customer_id=customer.id, assignee_user_id=owner.id,
                   source_key="edit-receipt", title="回访", due_date=date(2026, 11, 1), status="done",
                   closed_by_followup_id=row.id, closed_reason="回访完成")
    db.add(receipt)
    db.commit()
    edit_service.update(db, context(owner), row.id, payload(db, row, raw_text="更正"))
    assert plan.status == receipt.status == "done"
    assert db.query(Task).filter_by(task_type="plan").count() == 1
    edit_service.update(db, context(owner), row.id, payload(db, row, next_date=date(2026, 11, 16)))
    assert plan.status == receipt.status == "done"
    assert db.query(Task).filter_by(task_type="plan", status="todo").count() == 1


def test_item_identity_transferred_handler_and_resolution_survive(db, saved):
    owner, other, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    issue.status, issue.handler_user_id = "handling", other.id
    task = db.query(Task).filter_by(source_item_id=issue.id).one()
    task.assignee_user_id = other.id
    db.commit()
    changed = payload(db, row)
    changed.items[1].text = "补充色差描述"
    edit_service.update(db, context(owner), row.id, changed)
    assert issue.status == "handling" and issue.handler_user_id == task.assignee_user_id == other.id
    assert issue.id == changed.items[1].id and "补充色差描述" in task.title
    issue.status, issue.resolution = "resolved", "已补发"
    task_service.close_task(task, "done", "条目已解决", user_id=other.id)
    db.commit()
    changed = payload(db, row)
    changed.items[1].text = "更正拼写"
    edit_service.update(db, context(owner), row.id, changed)
    assert issue.status == "resolved" and issue.resolution == "已补发" and task.status == "done"


def test_removing_open_item_cancels_task_and_preserves_evidence(db, saved):
    owner, _, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    data = payload(db, row)
    data.items = data.items[:1]
    edit_service.update(db, context(owner), row.id, data)
    assert issue.status == "withdrawn"
    assert db.query(Task).filter_by(source_item_id=issue.id).one().status == "cancelled"
    assert all(i["id"] != issue.id for i in followup_service.serialize(db, row)["items"])
    assert any(i["id"] == issue.id for i in db.query(Revision).one().before_snapshot["items"])


def test_record_only_toggle_cancels_then_creates_one_new_task_without_reopening_old(db, saved):
    owner, _, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    original = db.query(Task).filter_by(source_item_id=issue.id).one()
    data = payload(db, row)
    data.items[1].record_only = True
    edit_service.update(db, context(owner), row.id, data)
    assert issue.status == "closed_no_action" and original.status == "cancelled"
    data = payload(db, row)
    data.items[1].record_only = False
    edit_service.update(db, context(owner), row.id, data)
    assert issue.status == "open" and original.status == "cancelled"
    assert db.query(Task).filter_by(source_item_id=issue.id, status="todo").count() == 1


def test_editing_item_with_expired_task_does_not_restart_it(db, saved):
    owner, _, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    task = db.query(Task).filter_by(source_item_id=issue.id).one()
    task.status = "expired"
    db.commit()
    data = payload(db, row)
    data.items[1].text = "仅更正文案"
    edit_service.update(db, context(owner), row.id, data)
    assert task.status == "expired"
    assert db.query(Task).filter_by(source_item_id=issue.id).count() == 1


@pytest.mark.parametrize("status", ["handling", "resolved", "closed_no_action"])
def test_processed_item_cannot_be_removed_and_entire_edit_rolls_back(db, saved, status):
    owner, _, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    issue.status, issue.resolution = status, "处理记录"
    db.commit()
    data = payload(db, row, raw_text="不应保存")
    data.items = data.items[:1]
    with pytest.raises(ValueError, match="不能删除"):
        edit_service.update(db, context(owner), row.id, data)
    assert row.raw_text == "原文" and db.query(Revision).count() == 0


def test_attachments_are_archived_not_rebound_and_remain_authorized(db, saved):
    owner, other, _, row = saved
    old = Attachment(uploader_user_id=owner.id, followup_id=row.id, seq=1, file_path="fu/old.png", ocr_status="done")
    fresh = Attachment(uploader_user_id=other.id, file_path="fu/new.png", ocr_status="done")
    db.add_all([old, fresh])
    db.commit()
    edit_service.update(db, context(other, root=True), row.id, payload(db, row, attachment_ids=[fresh.id]))
    assert old.followup_id == row.id and old.archived_at is not None
    assert fresh.followup_id == row.id
    assert [a["id"] for a in attachment_service_list(db, row.id)] == [fresh.id]
    assert db.query(Revision).one().before_snapshot["attachments"][0]["id"] == old.id


def attachment_service_list(db, record_id):
    from app.domestic_followup.attachment_service import list_for
    return list_for(db, [record_id])[record_id]


def test_new_attachment_cannot_be_stolen_and_noop_has_no_history(db, saved):
    owner, other, _, row = saved
    alien = Attachment(uploader_user_id=other.id, file_path="alien.png")
    db.add(alien)
    db.commit()
    with pytest.raises(PermissionError):
        edit_service.update(db, context(owner), row.id, payload(db, row, attachment_ids=[alien.id]))
    with pytest.raises(ValueError, match="未修改"):
        edit_service.update(db, context(owner), row.id, payload(db, row))
    assert db.query(Revision).count() == 0


def test_inactive_dictionary_values_can_be_kept_but_not_added(db, saved):
    from app.system.models import SysDict
    owner, _, _, row = saved
    row.channel, row.next_method, row.state_changes = "微信", "电话", ["稳定没变化"]
    db.query(SysDict).update({SysDict.is_active: False})
    db.commit()
    edit_service.update(db, context(owner), row.id, payload(db, row, raw_text="旧字典停用后更正"))
    assert row.channel == "微信" and row.state_changes == ["稳定没变化"]
    changed = payload(db, row, channel="其他")
    with pytest.raises(ValueError, match="不在字典"):
        edit_service.update(db, context(owner), row.id, changed)
    changed = payload(db, row)
    changed.items.append(changed.items[1].model_copy(update={"id": None}))
    with pytest.raises(ValueError, match="不在字典"):
        edit_service.update(db, context(owner), row.id, changed)


def test_route_permissions_history_and_identity_fields(db, saved, monkeypatch):
    owner, other, _, row = saved
    with followup_client(db, other, permissions=["domestic_followup:read", "domestic_followup:write", "domestic_followup:read_all"]) as client:
        assert client.get(f"/api/domestic-followup/followups/{row.id}").json()["data"]["can_edit"] is False
        assert client.put(f"/api/domestic-followup/followups/{row.id}", json=payload(db, row, summary="bad").model_dump(mode="json")).status_code == 403
    with followup_client(db, owner) as client:
        data = payload(db, row, summary="route changed").model_dump(mode="json")
        assert client.put(f"/api/domestic-followup/followups/{row.id}", json={**data, "customer_id": 999}).status_code == 422
        assert client.put(f"/api/domestic-followup/followups/{row.id}", json=data).status_code == 200
        assert len(client.get(f"/api/domestic-followup/followups/{row.id}/history").json()["data"]) == 1
    with followup_client(db, other) as client:
        assert client.get(f"/api/domestic-followup/followups/{row.id}/history").status_code == 404


def test_pending_urgent_is_cancelled_but_sent_digest_is_immutable(db, saved):
    owner, _, _, row = saved
    issue = db.query(Item).filter_by(kind="issue").one()
    issue.severity = "紧急"
    pending = Digest(user_id=owner.id, digest_date=date(2026, 11, 3), kind="urgent", ref_key=f"item:{issue.id}", title="old", markdown="old")
    sent = Digest(user_id=owner.id, digest_date=date(2026, 11, 2), kind="urgent", ref_key=f"item:{issue.id}", title="sent", markdown="sent", pushed_at=datetime(2026, 11, 2, 9))
    db.add_all([pending, sent])
    db.commit()
    data = payload(db, row)
    data.items[1].severity = "一般"
    edit_service.update(db, context(owner), row.id, data)
    assert pending.attempts == 5 and pending.last_error == "跟进修改后取消紧急提醒"
    assert sent.markdown == "sent" and sent.pushed_at is not None


def test_prepared_urgent_cancelled_by_edit_is_not_sent_and_updates_are_fresh(db, saved, monkeypatch):
    import asyncio
    from app.domestic_followup import digest_service
    from unittest.mock import AsyncMock
    owner, _, _, row = saved
    owner.dingtalk_id = "local-fake"
    issue = db.query(Item).filter_by(kind="issue").one()
    issue.severity = "紧急"
    pending = Digest(user_id=owner.id, digest_date=date(2026, 11, 3), kind="urgent", ref_key=f"item:{issue.id}", title="old", markdown="old")
    db.add(pending)
    db.commit()
    pushes = digest_service.pending(db, "urgent", date(2026, 11, 4))
    data = payload(db, row)
    data.items[1].severity = "一般"
    edit_service.update(db, context(owner), row.id, data)
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()
    monkeypatch.setattr("app.dingtalk.work_notify.get_work_notifier", lambda: notifier)
    async def claim_message(message):
        return digest_service.claim(db, message["digest_id"])
    assert asyncio.run(digest_service.send(pushes, claim_message)) == ([], [])
    notifier.send_to_users.assert_not_awaited()
    # Prepare old text, edit it, and claim the current text at the actual send boundary.
    pending.attempts, pending.last_error = 0, None
    issue.severity = "紧急"
    db.commit()
    pushes = digest_service.pending(db, "urgent", date(2026, 11, 4))
    data = payload(db, row)
    data.items[1].text = "新紧急内容"
    edit_service.update(db, context(owner), row.id, data)
    assert asyncio.run(digest_service.send(pushes, claim_message)) == ([pending.id], [])
    assert "新紧急内容" in notifier.send_to_users.await_args.kwargs["markdown_text"]


@pytest.mark.parametrize("instant,expected", [
    ("2026-11-03T15:59:00+00:00", datetime(2026, 11, 3, 23, 59)),
    ("2026-11-03T16:01:00+00:00", datetime(2026, 11, 4, 0, 1)),
])
def test_edit_archive_revision_close_and_claim_use_beijing_across_midnight(db, saved, monkeypatch, instant, expected):
    from zoneinfo import ZoneInfo
    from app.core import time as time_service
    from app.domestic_followup import digest_service
    fixed = datetime.fromisoformat(instant)
    class ServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz or ZoneInfo("America/Los_Angeles"))
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(time_service, "datetime", ServerClock)
    owner, _, _, row = saved
    owner.dingtalk_id = "clock-local"
    old = Attachment(uploader_user_id=owner.id, followup_id=row.id, seq=1, file_path="clock.png", ocr_status="done")
    digest = Digest(user_id=owner.id, digest_date=expected.date(), kind="daily", ref_key="", title="t", markdown="m")
    db.add_all([old, digest]); db.commit()
    edit_service.update(db, context(owner), row.id, payload(db, row, raw_text="clock correction", attachment_ids=[], next_date=None))
    assert db.query(Revision).one().created_at == expected
    assert old.archived_at == expected
    assert db.query(Task).filter_by(task_type="plan").one().closed_at == expected
    assert digest_service.claim(db, digest.id) is not None
    assert digest.send_claimed_at == expected and digest.send_claimed_at.tzinfo is None
