"""Customer-development handoff state, authorization and task invariants."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import time as platform_time
from app.domestic_followup import collaboration_access as access, collaboration_admin as admin
from app.domestic_followup import collaboration_projection as views
from app.domestic_followup import collaboration_service as service
from app.domestic_followup.collaboration_models import (
    FollowupCollaborationEvent, FollowupHandoff, FollowupResponsibility, FollowupScope,
)
from app.domestic_followup.collaboration_schemas import CollaborationActionIn, InitializationEntry, ScopeIn
from app.domestic_followup.collaboration_service import apply_action
from app.domestic_followup.collaboration_tasks import ConflictError
from app.domestic_followup.task_service import upsert_task
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user


def _claims(person, *permissions):
    return {"sub": str(person.id), "permissions": [access.READ, *permissions]}


def _act(db, person, customer, version, action, **kwargs):
    return apply_action(db, person, customer.id, CollaborationActionIn(
        action=action, version=version, idempotency_key=kwargs.pop("key", f"action-{action}-{version}"), **kwargs,
    ))


def _task(db, customer, owner, kind, purpose=None, suffix=None):
    task, _ = upsert_task(db, source_key=f"t-{customer.id}-{kind}-{suffix or purpose}", customer_id=customer.id,
                          task_type=kind, assignee_user_id=owner.id, due_date=date(2026, 12, 1), title=kind,
                          purpose=purpose)
    return task


@pytest.fixture
def setup_collaboration(db):
    manager = make_user(db, "coord-manager")
    owner = make_user(db, "coord-owner")
    receiver = make_user(db, "coord-receiver")
    peer = make_user(db, "coord-peer")
    outside = make_user(db, "coord-outside")
    for person in (owner, receiver, peer, outside):
        grant(db, person, access.READ, access.WRITE)
    grant(db, manager, access.READ, access.COORDINATE, access.ADMIN)
    customer = make_customer(db, owner, "Sustained customer", commission_users=[owner])
    customer.province, customer.city = "福建", "泉州"
    sibling = make_customer(db, owner, "Outside exact grants")
    sibling.province, sibling.city = "福建", "厦门"
    manager_claims = _claims(manager, access.COORDINATE, access.ADMIN)
    for member in (owner, receiver, peer):
        admin.add_scope(db, manager_claims, ScopeIn(user_id=member.id, customer_id=customer.id))
    admin.add_scope(db, manager_claims, ScopeIn(user_id=manager.id, province="福建"))
    db.flush()
    return manager_claims, owner, receiver, peer, outside, customer, sibling


def _initialize(db, manager, customer):
    preview = admin.preview_initialization(db, manager, 1, 50)
    selected = next(row for row in preview["items"] if row["customer_id"] == customer.id)
    entry = InitializationEntry(customer_id=customer.id, token=selected["token"])
    result = admin.apply_initialization(db, manager, [entry])
    assert result["items"][0]["status"] == "initialized"
    return entry


def test_direct_claim_checks_state_versions_and_read_all_cannot_reassign(db, setup_collaboration):
    manager, owner, receiver, peer, outside, customer, sibling = setup_collaboration
    assert set(db.scalars(access.scoped_ids(receiver.id))) == {customer.id}
    assert set(db.scalars(access.managed_customer_ids())) == {customer.id, sibling.id}
    assert access.has_summary_access(db, _claims(peer, access.WRITE), customer)
    assert not access.can_develop(db, _claims(peer, access.WRITE), customer)
    assert not access.has_history_access(db, _claims(peer, access.WRITE), customer)
    assert not access.has_summary_access(db, _claims(outside, access.WRITE), customer)
    assert list(db.scalars(access.history_customer_ids(receiver.id))) == []
    assert set(db.scalars(access.history_customer_ids(int(manager["sub"]), coordinate=True))) == {
        customer.id, sibling.id,
    }
    opened = _act(db, manager, customer, 0, "open", reason="经主管审查")
    assert opened["state"] == "open"
    accepted = _act(db, _claims(receiver, access.WRITE), customer, 1, "claim")
    assert accepted["owner_user_id"] == receiver.id and accepted["version"] == 2
    assert _act(db, _claims(receiver, access.WRITE), customer, 1, "claim") == accepted
    assert set(db.scalars(access.history_customer_ids(receiver.id))) == {customer.id}
    with pytest.raises(ConflictError, match="责任已变化"):
        _act(db, _claims(peer, access.WRITE), customer, 1, "claim")
    with pytest.raises(PermissionError):
        _act(db, _claims(outside, access.WRITE, "domestic_followup:read_all"), customer, 2,
             "reassign", recipient_user_id=peer.id, reason="Attempt")
    assert customer.owner_user_id == owner.id
    events = db.scalars(select(FollowupCollaborationEvent).where(
        FollowupCollaborationEvent.customer_id == customer.id,
    )).all()
    assert [event.action for event in events] == ["open", "claim"]


def test_handoff_moves_selected_tasks_and_rejects_task_drift(db, setup_collaboration):
    manager, owner, receiver, peer, _, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    owner_claims, receiver_claims, peer_claims = (_claims(person, access.WRITE) for person in (owner, receiver, peer))
    development = _task(db, customer, owner, "plan", "development")
    legacy = _task(db, customer, owner, "plan", suffix="legacy")
    receipt = _task(db, customer, owner, "receipt")
    issue = _task(db, customer, owner, "issue")
    _task(db, customer, peer, "plan", "development", suffix="other-owner")
    offered = _act(db, owner_claims, customer, 1, "offer_handoff", recipient_user_id=receiver.id, reason="转岗",
                   summary="寄样后联系", transfer_task_ids=[receipt.id], keep_task_ids=[legacy.id])
    assert offered["owner_user_id"] == owner.id
    assert views.project(db, peer_claims, customer)["handoff"] is None
    incoming = views.project(db, receiver_claims, customer)["handoff"]
    assert {task["id"] for task in incoming["tasks"]} == {development.id, receipt.id}
    assert not access.has_history_access(db, receiver_claims, customer)
    assert not access.can_develop(db, receiver_claims, customer)

    with pytest.raises(ConflictError, match="待办已变化"):
        with db.begin_nested():
            development.due_date += timedelta(days=1)
            db.flush()
            _act(db, receiver_claims, customer, 2, "accept_handoff", handoff_id=incoming["id"], handoff_version=1)
    assert development.assignee_user_id == owner.id
    assert access.responsibility_for(db, customer.id).version == 2
    assert db.get(FollowupHandoff, incoming["id"]).status == "pending"


def test_handoff_accept_and_revoke_old_qualification(db, setup_collaboration):
    manager, owner, receiver, peer, _, customer, _ = setup_collaboration
    entry = _initialize(db, manager, customer)
    owner_claims, receiver_claims = (_claims(person, access.WRITE) for person in (owner, receiver))
    tasks = [_task(db, customer, owner, "plan", "development"), _task(db, customer, owner, "receipt"),
             _task(db, customer, owner, "issue"), _task(db, customer, owner, "plan", suffix="legacy")]
    offered = _act(db, owner_claims, customer, 1, "offer_handoff", recipient_user_id=receiver.id, reason="换区",
                   summary="接续原计划", transfer_task_ids=[tasks[1].id], keep_task_ids=[tasks[3].id])
    payload = dict(handoff_id=offered["handoff"]["id"], handoff_version=1)
    accepted = _act(db, receiver_claims, customer, 2, "accept_handoff", **payload)
    assert accepted["owner_user_id"] == receiver.id and accepted["state"] == "following"
    assert [task.assignee_user_id for task in tasks] == [receiver.id, receiver.id, owner.id, owner.id]
    assert tasks[3].purpose == "other"
    assert access.has_history_access(db, receiver_claims, customer)
    assert not access.has_history_access(db, owner_claims, customer)
    assert not access.can_develop(db, owner_claims, customer)
    assert views.events(db, owner_claims, customer, 1, 20)["items"][0]["handoff_outcome"]["status"] == "accepted"
    assert _act(db, receiver_claims, customer, 2, "accept_handoff", **payload) == accepted
    assert admin.apply_initialization(db, manager, [entry])["items"][0]["status"] == "existing"

    scope = db.scalar(select(FollowupScope).where(
        FollowupScope.customer_id == customer.id, FollowupScope.user_id == receiver.id,
    ))
    admin.delete_scope(db, manager, scope.id)
    assert not access.can_develop(db, receiver_claims, customer)
    assert access.responsibility_for(db, customer.id).owner_user_id == receiver.id
    assert "owner_ineligible" in views.project(db, manager, customer)["coordination_reasons"]


def test_request_owner_accepts_and_failed_reassignment_keeps_old_owner(db, setup_collaboration):
    manager, owner, receiver, _, outside, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    owner_claims, receiver_claims = (_claims(person, access.WRITE) for person in (owner, receiver))
    plan = _task(db, customer, owner, "plan", "development")
    requested = _act(db, receiver_claims, customer, 1, "request_handoff", reason="本月负责开发")
    assert requested["handoff"]["kind"] == "request" and requested["handoff"]["tasks"] == []
    owner_preview = views.project(db, owner_claims, customer)
    accepted = _act(db, owner_claims, customer, 2, "accept_handoff", summary="按原计划继续",
                    handoff_id=owner_preview["handoff"]["id"], handoff_version=1)
    assert plan.assignee_user_id == receiver.id and accepted["owner_user_id"] == receiver.id
    with pytest.raises(PermissionError, match="接收人"):
        with db.begin_nested():
            _act(db, manager, customer, 3, "reassign", recipient_user_id=outside.id, reason="错误范围")
    assert access.responsibility_for(db, customer.id).owner_user_id == receiver.id


def test_stop_and_coordinator_threshold_keep_responsibility(db, monkeypatch, setup_collaboration):
    manager, owner, receiver, _, _, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    owner_claims = _claims(owner, access.WRITE)
    task = _task(db, customer, owner, "plan", "development")
    responsibility = db.get(FollowupResponsibility, customer.id)
    responsibility.last_progress_at = datetime(2026, 1, 1, 0, 1)
    task.due_date = date(2026, 1, 1)
    db.flush()
    monkeypatch.setattr(views, "beijing_today", lambda: date(2026, 1, 31))
    assert set(views.coordination_reasons(db, customer, responsibility, None)) == {
        "no_progress", "development_task_overdue",
    }
    commitment_task = _task(db, customer, owner, "plan", "development", suffix="future-agreed")
    commitment_task.due_date = date(2026, 2, 1)
    responsibility.next_plan_date = date(2026, 2, 1)
    assert views.coordination_reasons(db, customer, responsibility, None) == []
    commitment_task.status = "done"
    assert set(views.coordination_reasons(db, customer, responsibility, None)) == {
        "no_progress", "development_task_overdue",
    }
    commitment_task.status = "todo"
    offered = _act(db, owner_claims, customer, 1, "offer_handoff", recipient_user_id=receiver.id,
                   reason="换区", summary="交接")
    handoff = db.get(FollowupHandoff, offered["handoff"]["id"])
    handoff.created_at = datetime(2026, 1, 28, 23, 59)
    assert views.coordination_reasons(db, customer, responsibility, handoff) == ["handoff_overdue"]
    assert admin.coordination_settings(db, manager, 4)["pending_handoff_days"] == 4
    assert views.coordination_reasons(db, customer, responsibility, handoff) == []
    assert admin.coordination_settings(db, manager, 2)["pending_handoff_days"] == 2
    assert views.coordination_reasons(db, customer, responsibility, handoff) == ["handoff_overdue"]
    stopped = _act(db, owner_claims, customer, 2, "stop", reason="客户明确拒绝",
                   allow_future_contact=False, cancel_task_ids=[task.id, commitment_task.id])
    assert stopped["state"] == "stopped" and stopped["owner_user_id"] == owner.id
    assert handoff.status == "invalidated" and task.status == "cancelled"
    assert not access.can_develop(db, owner_claims, customer)
    assert _act(db, owner_claims, customer, 3, "reopen", reason="客户主动要求继续")["state"] == "following"


def test_release_requires_task_closure_and_explicit_coordinator_open(db, setup_collaboration):
    manager, owner, receiver, _, _, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    owner_claims, receiver_claims = (_claims(person, access.WRITE) for person in (owner, receiver))
    development = _task(db, customer, owner, "plan", "development")
    maintenance = _task(db, customer, owner, "plan", "maintenance")
    receipt = _task(db, customer, owner, "receipt")
    with pytest.raises(ValueError, match="继续进行"):
        with db.begin_nested():
            _act(db, owner_claims, customer, 1, "release", reason="人事调整", recipient_user_id=receiver.id,
                 transfer_task_ids=[development.id])
    released = _act(db, owner_claims, customer, 1, "release", reason="停止本轮联系", cancel_task_ids=[development.id])
    assert released["owner_user_id"] is None and released["state"] == "unassigned"
    assert development.status == "cancelled"
    assert maintenance.status == receipt.status == "todo"
    with pytest.raises(PermissionError):
        _act(db, receiver_claims, customer, 2, "claim")
    _act(db, manager, customer, 2, "open", reason="已确认新的开发范围")
    assert _act(db, receiver_claims, customer, 3, "claim")["owner_user_id"] == receiver.id


def test_pending_days_follow_beijing_midnight_not_utc(db, monkeypatch, setup_collaboration):
    manager, owner, receiver, _, _, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    offered = _act(db, _claims(owner, access.WRITE), customer, 1, "offer_handoff", recipient_user_id=receiver.id,
                   reason="调整", summary="继续开发")
    handoff = db.get(FollowupHandoff, offered["handoff"]["id"])
    handoff.created_at = datetime(2026, 1, 1, 23, 59)
    responsibility = access.responsibility_for(db, customer.id)
    responsibility.last_progress_at = datetime(2026, 1, 1, 23, 59)
    utc_time = datetime(2026, 1, 3, 15, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(platform_time, "beijing_now_aware", lambda: utc_time.astimezone(platform_time.BEIJING_TIMEZONE))
    assert views.coordination_reasons(db, customer, responsibility, handoff) == []
    utc_time += timedelta(minutes=1)
    assert utc_time.date() == date(2026, 1, 3)
    assert views.coordination_reasons(db, customer, responsibility, handoff) == ["handoff_overdue"]


def test_coordinator_cannot_expand_own_scope_or_edit_global_settings(db, setup_collaboration):
    manager, owner, _, _, _, customer, sibling = setup_collaboration
    coordinator = make_user(db, "scoped-coordinator")
    grant(db, coordinator, access.READ, access.COORDINATE)
    admin.add_scope(db, manager, ScopeIn(user_id=coordinator.id, customer_id=customer.id))
    claims = _claims(coordinator, access.COORDINATE)
    assert access.can_coordinate(db, claims, customer)
    assert not access.can_coordinate(db, claims, sibling)
    assert [row["customer_id"] for row in admin.preview_initialization(db, claims, 1, 50)["items"]] == [customer.id]
    with pytest.raises(PermissionError):
        admin.add_scope(db, claims, ScopeIn(user_id=coordinator.id, customer_id=sibling.id))
    with pytest.raises(PermissionError):
        admin.coordination_settings(db, claims, 10)
    assert not access.can_coordinate(db, claims, sibling)


def test_failed_acceptance_rolls_back_tasks_owner_and_handoff(db, monkeypatch, setup_collaboration):
    manager, owner, receiver, _, _, customer, _ = setup_collaboration
    _initialize(db, manager, customer)
    plan = _task(db, customer, owner, "plan", "development")
    offered = _act(db, _claims(owner, access.WRITE), customer, 1, "offer_handoff", recipient_user_id=receiver.id,
                   reason="改派", summary="按计划回访")

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(service, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        with db.begin_nested():
            _act(db, _claims(receiver, access.WRITE), customer, 2, "accept_handoff",
                 handoff_id=offered["handoff"]["id"], handoff_version=1)
    assert plan.assignee_user_id == owner.id
    assert access.responsibility_for(db, customer.id).owner_user_id == owner.id
    assert db.get(FollowupHandoff, offered["handoff"]["id"]).status == "pending"


def test_initialized_conflict_is_unassigned_and_authorized_routes_do_not_expose_outside_customers(
    db, setup_collaboration,
):
    manager, owner, receiver, _, outside, customer, sibling = setup_collaboration
    _task(db, customer, receiver, "plan", "development")
    _initialize(db, manager, customer)
    responsibility = access.responsibility_for(db, customer.id)
    assert responsibility.owner_user_id is None and responsibility.status == "unassigned"
    db.commit()
    with followup_client(db, outside, permissions=(access.READ, access.WRITE)) as client:
        response = client.get(f"/api/domestic-followup/collaboration/{customer.id}")
        assert response.status_code == 404
        response = client.get("/api/domestic-followup/collaboration/settings/scopes")
        assert response.status_code == 403
    with followup_client(db, receiver, permissions=(access.READ, access.WRITE)) as client:
        response = client.get(f"/api/domestic-followup/collaboration/{customer.id}")
        assert response.status_code == 200
        assert response.json()["data"]["available_actions"] == []
        assert client.get(f"/api/domestic-followup/collaboration/{sibling.id}").status_code == 404
