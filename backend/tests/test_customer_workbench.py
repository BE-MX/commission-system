"""Daily workbench behavior on an isolated SQLite database."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.customer import router as hub_router
from app.customer.models import CustomerAction, CustomerAssignment, CustomerEvent
from tests.test_customer_workflow import _account, _research_task, _user


NOW = datetime(2026, 9, 6, 0, 5)


@pytest.fixture
def hub(db, monkeypatch):
    from app.customer import followup_service, workflow_service
    from app.insight import customer_radar_service

    monkeypatch.setattr(workflow_service, "beijing_now", lambda: NOW)
    monkeypatch.setattr(customer_radar_service, "beijing_now", lambda: NOW)
    monkeypatch.setattr(followup_service, "beijing_now", lambda: NOW)
    _user(db, 1)
    _user(db, 2)
    account, profile = _account(db, code="C-DAILY")
    other, _ = _account(db, code="C-PRIVATE")
    for customer, owner in ((account, 1), (other, 2)):
        db.add(CustomerAssignment(
            customer_id=customer.id, user_id=owner, assignment_role="primary",
            assignment_status="active", assignment_source="manual", effective_from=NOW,
        ))
    db.flush()
    identity = {"sub": "1", "roles": [], "permissions": [
        "customer:read", "customer_radar:read", "customer_radar:write",
        "sales_automation:read", "sales_automation:write", "customer_opportunity:read",
    ]}
    app = FastAPI()
    app.include_router(hub_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    with TestClient(app) as client:
        yield client, identity, account, profile, other


def action(db, account, profile, *, key=1, owner=1, due=None, status="pending", **values):
    row = CustomerAction(
        customer_id=account.id, owner_user_id=owner, profile_version_id=profile.id,
        action_type="email", thread_group="public_pool", channel="email",
        priority="high", reason="官网有接发服务", next_action="确认常用色号",
        action_date=NOW.date(), due_at=due, status=status, policy_version="daily-test",
        source_type="manual", source_event_ids=[], evidence_fact_ids=[], feedback_json={},
        action_fingerprint=f"{key:064x}", evidence_status="valid", generated_at=NOW,
        created_at=NOW, updated_at=NOW, **values,
    )
    db.add(row)
    db.flush()
    return row


def test_workbench_counts_ignore_pagination_and_respect_scope(db, hub, monkeypatch):
    from app.customer import workbench_service

    monkeypatch.setattr(workbench_service, "beijing_now", lambda: NOW)
    client, identity, customer, profile, other = hub
    action(db, customer, profile, key=1, due=NOW - timedelta(minutes=10))
    action(db, customer, profile, key=2, due=NOW + timedelta(hours=1))
    action(db, customer, profile, key=3)
    action(db, customer, profile, key=4, due=NOW + timedelta(days=1))
    action(db, customer, profile, key=5, due=NOW - timedelta(days=1),
           status="snoozed", snoozed_until=NOW + timedelta(hours=2))
    action(db, customer, profile, key=6, status="done", completed_at=NOW)
    action(db, other, profile, key=7, owner=2, due=NOW - timedelta(days=1))
    result = client.get("/api/customer-hub/workbench?page_size=1").json()["data"]
    assert result["total"] == 3
    assert len(result["items"]) == 1
    assert result["summary"]["overdue"] == 1
    assert result["summary"]["today"] == 1
    assert result["summary"]["unscheduled"] == 1
    assert result["summary"]["upcoming"] == 1
    assert result["summary"]["snoozed"] == 1
    assert result["summary"]["completed"] == 1
    assert result["items"][0]["customer_name"] == customer.display_name
    assert result["items"][0]["reason"] == "官网有接发服务"
    assert result["data_as_of"].endswith("+08:00")
    assert client.get("/api/customer-hub/workbench?scope=visible&view=overdue").json()["data"]["total"] == 1
    identity["permissions"].append("customer:read_all")
    assert client.get("/api/customer-hub/workbench?scope=visible&view=overdue").json()["data"]["total"] == 2
    assert client.get("/api/customer-hub/workbench?scope=mine&view=overdue").json()["data"]["total"] == 1


def test_first_contact_excludes_real_contact_but_not_internal_review(db, hub, monkeypatch):
    from app.customer import workbench_service

    monkeypatch.setattr(workbench_service, "beijing_now", lambda: NOW)
    client, _, customer, profile, _ = hub
    customer.relationship_stage = "developing"
    pending = action(db, customer, profile)
    completed = action(db, customer, profile, key=2, status="done", completed_at=NOW)
    completed.channel = "internal"
    completed.outcome_code = "other"
    db.flush()
    assert client.get("/api/customer-hub/workbench?view=first_contact").json()["data"]["total"] == 1
    completed.feedback_json = {"completion": {"channel": "email", "outcome_code": "contacted"}}
    db.flush()
    assert client.get("/api/customer-hub/workbench?view=first_contact").json()["data"]["total"] == 0
    assert pending.status == "pending"


def test_first_contact_excludes_archived_outbound_message(db, hub):
    from app.customer.models import CustomerConversation, CustomerMessage
    from tests.test_customer_workflow import _source_record

    client, _, customer, profile, _ = hub
    action(db, customer, profile)
    source = _source_record(db, customer)
    conversation = CustomerConversation(customer_id=customer.id, source_system="email",
        source_account_key="global", external_conversation_id="first-touch-test", channel="email",
        owner_user_id=1, conversation_status="active", started_at=NOW, last_message_at=NOW,
        latest_source_record_id=source.id, created_at=NOW, updated_at=NOW)
    db.add(conversation)
    db.flush()
    assert client.get("/api/customer-hub/workbench?view=first_contact").json()["data"]["total"] == 1
    db.add(CustomerMessage(conversation_id=conversation.id, external_message_id="out-first",
        direction="out", sender_type="ark_user", sender_user_id=1, content_type="text",
        content_text="Hello", attachment_meta_json=[], source_record_id=source.id,
        content_hash="c" * 64, sent_at=NOW, captured_at=NOW, created_at=NOW))
    db.flush()
    assert client.get("/api/customer-hub/workbench?view=first_contact").json()["data"]["total"] == 0


def test_followup_is_atomic_dated_and_idempotent(db, hub):
    client, _, customer, profile, _ = hub
    original = action(db, customer, profile)
    payload = {
        "operation": "complete", "summary": "客户希望看常用色号", "channel": "email",
        "outcome_code": "replied", "occurred_at": "2026-09-05T16:00:00Z",
        "next_step": "准备色卡后联系", "next_step_due_at": "2026-09-06T16:00:00Z",
        "followup_action_type": "email", "followup_channel": "email",
    }
    response = client.put(f"/api/customer-hub/actions/{original.id}", json=payload)
    assert response.status_code == 200, response.text
    first = response.json()["data"]
    assert first["followup_action_id"]
    assert client.put(f"/api/customer-hub/actions/{original.id}", json=payload).status_code == 200
    rows = db.query(CustomerAction).order_by(CustomerAction.id).all()
    assert len(rows) == 2
    assert rows[0].status == "done"
    followup = rows[1]
    assert followup.id == first["followup_action_id"]
    assert followup.next_action == "准备色卡后联系"
    assert followup.due_at == datetime(2026, 9, 7)
    assert followup.owner_user_id == 1 and followup.status == "pending"
    assert followup.customer_id == customer.id
    assert db.query(CustomerEvent).filter_by(event_type="sales_activity.logged").count() == 1


@pytest.mark.parametrize("change", [
    {"next_step_due_at": "2026-09-05T00:00:00+08:00"},
    {"next_step": "  "},
    {"followup_channel": "invalid"},
])
def test_bad_followup_does_not_complete_original(db, hub, change):
    client, _, customer, profile, _ = hub
    original = action(db, customer, profile)
    db.commit()
    payload = {"operation": "complete", "summary": "已联系", "next_step": "回访",
               "next_step_due_at": "2026-09-07T09:00:00+08:00",
               "followup_action_type": "call", "followup_channel": "phone", **change}
    result = client.put(f"/api/customer-hub/actions/{original.id}", json=payload)
    assert result.status_code in (400, 422), result.text
    db.expire_all()
    assert db.get(CustomerAction, original.id).status == "pending"
    assert db.query(CustomerAction).count() == 1


def test_expired_snooze_is_actionable_without_read_mutation(db, hub, monkeypatch):
    from app.customer import workbench_service

    monkeypatch.setattr(workbench_service, "beijing_now", lambda: NOW)
    client, _, customer, profile, _ = hub
    row = action(db, customer, profile, status="snoozed",
                 snoozed_until=NOW - timedelta(minutes=1), due=NOW - timedelta(days=1))
    result = client.get("/api/customer-hub/workbench").json()["data"]
    assert result["items"][0]["effective_status"] == "pending"
    assert db.get(CustomerAction, row.id).status == "snoozed"
    response = client.put(f"/api/customer-hub/actions/{row.id}", json={"operation": "complete", "summary": "已回访"})
    assert response.status_code == 200, response.text
    assert db.get(CustomerAction, row.id).status == "done"


def test_workbench_requires_action_permission(db, hub):
    client, identity, *_ = hub
    identity["permissions"] = ["customer:read"]
    assert client.get("/api/customer-hub/workbench").status_code == 403


@pytest.mark.parametrize("operation, extra, expected", [
    ("dismiss", {"reason_code": "duplicate"}, "dismissed"),
    ("snooze", {"snoozed_until": "2026-09-07T09:00:00+08:00"}, "snoozed"),
])
def test_mature_snooze_supports_every_pending_operation(db, hub, operation, extra, expected):
    client, _, customer, profile, _ = hub
    row = action(db, customer, profile, status="snoozed", snoozed_until=NOW - timedelta(minutes=1))
    response = client.put(f"/api/customer-hub/actions/{row.id}", json={"operation": operation, **extra})
    assert response.status_code == 200, response.text
    db.refresh(row)
    assert row.status == expected
    if operation == "snooze":
        assert row.snoozed_until == datetime(2026, 9, 7, 9)


def test_followup_failure_rolls_back_activity_and_original(db, hub, monkeypatch):
    from app.customer import followup_service
    from app.customer.workflow_service import CustomerWorkflowConflict

    client, _, customer, profile, _ = hub
    row = action(db, customer, profile)
    db.commit()
    def fail_after_activity(*args, **kwargs):
        assert db.query(CustomerEvent).filter_by(event_type="sales_activity.logged").count() == 1
        raise CustomerWorkflowConflict("PROFILE_NOT_READY")
    monkeypatch.setattr(followup_service, "create_followup", fail_after_activity)
    response = client.put(f"/api/customer-hub/actions/{row.id}", json={
        "operation": "complete", "channel": "email", "outcome_code": "replied", "next_step": "回访",
        "next_step_due_at": "2026-09-07T09:00:00+08:00",
        "followup_action_type": "email", "followup_channel": "email",
    })
    assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(CustomerAction, row.id).status == "pending"
    assert db.query(CustomerEvent).filter_by(event_type="sales_activity.logged").count() == 0
    assert db.query(CustomerAction).count() == 1


def test_stale_session_completion_replays_without_second_followup(db, hub):
    from sqlalchemy.orm import Session
    from app.customer import workflow_service

    _, _, customer, profile, _ = hub
    row = action(db, customer, profile)
    db.commit()
    row_id = row.id
    with Session(db.get_bind(), expire_on_commit=False) as first, Session(db.get_bind()) as stale:
        cached = stale.get(CustomerAction, row_id)
        kwargs = {"completed_by": 1, "outcome_code": "replied", "channel": "email",
                  "occurred_at": NOW, "summary": "客户已回复", "next_step": "发送色卡",
                  "next_step_due_at": NOW + timedelta(days=1),
                  "followup_action_type": "email", "followup_channel": "email"}
        workflow_service.complete_action(first, action_id=row_id, **kwargs)
        first.commit()
        assert cached.status == "pending"
        workflow_service.complete_action(stale, action_id=row_id, **kwargs)
        stale.commit()
        assert stale.query(CustomerAction).count() == 2
        assert stale.query(CustomerEvent).filter_by(event_type="sales_activity.logged").count() == 1
        with pytest.raises(workflow_service.CustomerWorkflowConflict, match="ACTION_COMPLETION_CHANGED"):
            workflow_service.complete_action(stale, action_id=row_id, **{**kwargs, "next_step": "改成另一个动作"})


def test_followup_uses_latest_profile_even_when_account_is_cached(db, hub):
    from sqlalchemy.orm import Session
    from app.customer import workflow_service
    from app.customer.models import CustomerAccount, CustomerProfileVersion

    _, _, customer, profile, _ = hub
    row = action(db, customer, profile)
    db.commit()
    with Session(db.get_bind()) as stale, Session(db.get_bind()) as writer:
        cached = stale.get(CustomerAccount, customer.id)
        values = {column.name: getattr(profile, column.name) for column in CustomerProfileVersion.__table__.columns
                  if column.name != "id"}
        values.update(version_no=2, profile_fingerprint="f" * 64)
        latest = CustomerProfileVersion(**values)
        writer.add(latest)
        writer.flush()
        writer.get(CustomerAccount, customer.id).current_profile_version_id = latest.id
        writer.commit()
        assert cached.current_profile_version_id == profile.id
        result = workflow_service.complete_action(stale, action_id=row.id, completed_by=1,
            occurred_at=NOW, channel="email", outcome_code="contacted", summary="已确认需求", next_step="发送色卡",
            next_step_due_at=NOW + timedelta(days=1))
        followup_id = result.feedback_json["completion"]["followup_action_id"]
        assert stale.get(CustomerAction, followup_id).profile_version_id == latest.id


@pytest.mark.parametrize("stage", ["engaged", "customer", "dormant"])
def test_established_relationship_is_not_first_contact(db, hub, stage):
    client, _, customer, profile, _ = hub
    customer.relationship_stage = stage
    action(db, customer, profile)
    db.flush()
    assert client.get("/api/customer-hub/workbench?view=first_contact").json()["data"]["total"] == 0


def test_moved_action_uses_current_customer_name_and_access(db, hub):
    from app.customer.models import CustomerObjectOwnership

    client, _, customer, profile, other = hub
    row = action(db, other, profile)
    db.add(CustomerObjectOwnership(object_type="action", object_id=row.id, storage_customer_id=other.id,
                                   current_customer_id=customer.id, ownership_version=1,
                                   last_change_proposal_id=1, last_action_type="split", created_at=NOW, updated_at=NOW))
    db.flush()
    result = client.get("/api/customer-hub/workbench").json()["data"]
    assert result["total"] == 1
    assert result["items"][0]["customer_id"] == customer.id
    assert result["items"][0]["customer_name"] == customer.display_name
