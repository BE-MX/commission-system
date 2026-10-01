"""Business lifecycle regressions: pausing and stable identity cannot be bypassed."""

import pytest
from datetime import timedelta
from app.core.time import beijing_now

from app.customer import pcw_errors
from app.customer.pcw_workitem_service import ensure_work_item
from tests.test_customer_workflow import _account
from tests.test_pcw_workitem_service import _action, _customer_with_profile as _legacy_customer_with_profile, _open_item


def _customer_with_profile(db):
    from tests.test_customer_workflow import _grant_permission
    account, owner = _legacy_customer_with_profile(db)
    for permission in ("customer:read", "customer_pcw:read", "customer_pcw:write", "agent_runtime:invoke"):
        _grant_permission(db, owner.id, permission)
    return account, owner


def test_paused_item_cannot_generate_new_outbound_action(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    item.state = "paused"
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as caught:
        _action(db, account, owner, item)
    assert caught.value.error_code == "WORK_ITEM_PAUSED"


def test_same_business_identity_cannot_attach_to_another_customer(db):
    account, _owner = _customer_with_profile(db)
    item = _open_item(db, account)
    another, _version = _account(db, code="C-WORKBENCH-OTHER")
    with pytest.raises(pcw_errors.PcwError) as caught:
        ensure_work_item(db, customer_id=another.id, business_key=item.business_key,
                         business_cycle=item.business_cycle, work_type=item.work_type,
                         title="Same source key, wrong customer")
    assert caught.value.error_code == "WORK_ITEM_IDENTITY_CONFLICT"


def test_reversible_dismissal_adds_next_round_without_erasing_history(db):
    from app.customer.action_correction_service import correct_action
    from app.customer.pcw_workitem_service import dismiss_action_v2
    from app.customer.models import CustomerAction
    from app.customer.workbench_models import WorkItemEvent
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    original_due = action.original_due_at
    dismissed = dismiss_action_v2(db, action_id=action.id, actor_user_id=owner.id,
        expected_action_version=action.row_version, expected_work_item_version=item.row_version,
        dismissal_reason="Suggested message missed the customer's question", idempotency_key="dismiss-correction-001")
    result = correct_action(db, _actor(owner), action.id, {"operation": "undo",
        "expected_action_version": dismissed["version"], "expected_work_item_version": dismissed["work_item_version"],
        "reason": "Reviewed source and restored a review task", "correction": "Check real customer question"},
        "undo-correction-0001")
    assert action.status == "dismissed"
    assert action.original_due_at == original_due
    assert result["history_preserved"] is True
    followup = db.get(CustomerAction, result["followup_action_id"])
    assert followup.parent_action_id == action.id
    assert followup.action_round == action.action_round + 1
    assert db.query(WorkItemEvent).filter(WorkItemEvent.item_id == item.id,
        WorkItemEvent.event_type == "action_undo").count() == 1


def test_undo_snooze_replaces_old_reminder_without_two_live_actions(db):
    from app.customer.action_correction_service import correct_action
    from app.customer.pcw_workitem_service import snooze_action_v2
    from app.customer.models import CustomerAction
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    snoozed = snooze_action_v2(db, action_id=action.id, actor_user_id=owner.id,
        expected_action_version=action.row_version, expected_work_item_version=item.row_version,
        snoozed_until=beijing_now() + timedelta(days=1), idempotency_key="undo-snooze-first")
    result = correct_action(db, _actor(owner), action.id, {"operation": "undo",
        "expected_action_version": snoozed["version"], "expected_work_item_version": snoozed["work_item_version"],
        "reason": "Reviewed and replaced reminder", "correction": "Confirm next step"}, "undo-snooze-second")
    assert action.status == "cancelled"
    assert result["followup_action_id"] is not None
    assert db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
        CustomerAction.status.in_(("pending", "snoozed"))).count() == 1


def test_matured_snooze_can_be_resnoozed_or_dismissed_from_item_projection(db):
    from app.customer.pcw_workitem_service import snooze_action_v2, dismiss_action_v2
    from app.customer.work_item_query_service import serialize_item

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    snooze_action_v2(db, action_id=action.id, actor_user_id=owner.id,
        expected_action_version=action.row_version, expected_work_item_version=item.row_version,
        snoozed_until=beijing_now() + timedelta(hours=1), idempotency_key="matured-first-001")
    action.snoozed_until = beijing_now() - timedelta(minutes=1)
    db.flush()
    projected = serialize_item(db, _actor(owner), item)
    assert projected["actions"][0]["effective_status"] == "pending"
    snooze_action_v2(db, action_id=action.id, actor_user_id=owner.id,
        expected_action_version=action.row_version, expected_work_item_version=item.row_version,
        snoozed_until=beijing_now() + timedelta(hours=2), idempotency_key="matured-second-002")
    action.snoozed_until = beijing_now() - timedelta(minutes=1)
    db.flush()
    dismissed = dismiss_action_v2(db, action_id=action.id, actor_user_id=owner.id,
        expected_action_version=action.row_version, expected_work_item_version=item.row_version,
        dismissal_reason="Source no longer needs this reminder", idempotency_key="matured-third-003")
    assert dismissed["status"] == "dismissed"


def _actor(owner):
    return {"sub": str(owner.id), "permissions": ["customer_pcw:read", "customer_pcw:write", "customer:read"], "roles": []}


def test_wait_pause_resume_is_audited_and_does_not_restart_manual_delegation(db):
    from app.customer.work_item_service import transition_item
    from app.customer.workbench_models import WorkItemEvent, CustomerDelegation
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    user = _actor(owner)
    result = transition_item(db, user, item.id, {"operation": "wait", "expected_item_version": 1,
        "reason": "Waiting for confirmed color", "waiting_kind": "customer",
        "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "workbench-wait-0001")
    assert result["item"]["state"] == "waiting"
    db.add(CustomerDelegation(item_id=item.id, actor_user_id=owner.id, goal="Prepare response",
        scope_json={"mode": "prepare"}, status="paused", pause_origin="manual", input_revision=1))
    db.flush()
    transition_item(db, user, item.id, {"operation": "pause", "expected_item_version": 2,
        "reason": "Customer requested hold", "resume_condition": "Customer responds"}, "workbench-pause-001")
    transition_item(db, user, item.id, {"operation": "resume", "expected_item_version": 3,
        "reason": "Customer responded"}, "workbench-resume-01")
    assert item.state == "open"
    assert db.query(WorkItemEvent).count() == 3
    assert db.query(CustomerDelegation).one().status == "paused"


def test_resolve_without_evidence_has_no_side_effect(db):
    from app.customer.work_item_service import transition_item
    from app.customer.workbench_models import WorkItemEvent
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, _actor(owner), item.id, {"operation": "resolve",
            "expected_item_version": 1, "reason": "Done", "evidence_refs": []}, "resolve-no-evidence")
    assert caught.value.error_code == "RESOLUTION_EVIDENCE_REQUIRED"
    assert item.state == "open"
    assert item.row_version == 1
    assert db.query(WorkItemEvent).count() == 0


def test_idempotent_replay_still_requires_current_customer_access(db):
    from app.customer.work_item_service import transition_item
    from app.customer.models import CustomerAssignment
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    payload = {"operation": "pause", "expected_item_version": 1, "reason": "Hold", "resume_condition": "Reply"}
    transition_item(db, _actor(owner), item.id, payload, "pause-and-replay-01")
    db.query(CustomerAssignment).update({"assignment_status": "inactive"})
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, _actor(owner), item.id, payload, "pause-and-replay-01")
    assert caught.value.status_code == 404


def test_daily_capacity_never_replenishes_after_completion(db, monkeypatch):
    from app.core.config import get_settings
    from app.customer.daily_plan_service import get_plan, admit_item
    from app.customer.workbench_models import WorkbenchAdmission
    monkeypatch.setattr(get_settings(), "PCW_DAILY_ITEM_BUDGET", 1)
    account, owner = _customer_with_profile(db)
    first = _open_item(db, account)
    second = _open_item(db, account, business_key="manual:2")
    plan, admitted = get_plan(db, _actor(owner))
    assert admitted == {first.id}
    first.state = "resolved"
    db.flush()
    assert get_plan(db, _actor(owner))[1] == {first.id}
    with pytest.raises(pcw_errors.PcwError) as caught:
        admit_item(db, _actor(owner), {"item_id": second.id, "expected_plan_version": plan.row_version}, "capacity-full-0001")
    assert caught.value.error_code == "DAILY_CAPACITY_EXCEEDED"
    db.rollback()


def test_extra_capacity_has_audit_and_replay_does_not_increase_budget(db, monkeypatch):
    from app.core.config import get_settings
    from app.customer.daily_plan_service import get_plan, admit_item
    from app.customer.workbench_models import WorkbenchAdmission
    monkeypatch.setattr(get_settings(), "PCW_DAILY_ITEM_BUDGET", 1)
    account, owner = _customer_with_profile(db)
    first = _open_item(db, account)
    second = _open_item(db, account, business_key="manual:2")
    plan, _ = get_plan(db, _actor(owner))
    payload = {"item_id": second.id, "expected_plan_version": plan.row_version,
        "allow_one_extra": True, "reason": "Customer appointment"}
    result = admit_item(db, _actor(owner), payload, "capacity-extra-001")
    assert result["capacity"]["budget"] == 2
    assert admit_item(db, _actor(owner), payload, "capacity-extra-001")["capacity"]["budget"] == 2
    entries = db.query(WorkbenchAdmission).order_by(WorkbenchAdmission.id).all()
    assert len(entries) == 2
    assert (entries[-1].admission_type, entries[-1].budget_before, entries[-1].budget_after) == ("manual_extra", 1, 2)


def test_work_item_views_are_mutually_exclusive_and_stale_result_requires_review(db):
    from app.customer.work_item_query_service import list_items
    account, owner = _customer_with_profile(db)
    active = _open_item(db, account)
    waiting = _open_item(db, account, business_key="waiting:2")
    waiting.state, waiting.review_at = "waiting", beijing_now() + timedelta(days=1)
    stale = _open_item(db, account, business_key="resolved:3")
    stale.state, stale.result_validity = "resolved", "review_required"
    valid = _open_item(db, account, business_key="resolved:4")
    valid.state, valid.result_validity = "resolved", "verified"
    db.flush()
    results = {view: list_items(db, _actor(owner), view=view) for view in ("need_me", "in_progress", "ended")}
    assert {row["item_id"] for row in results["need_me"]["items"]} == {active.id, stale.id}
    assert {row["item_id"] for row in results["in_progress"]["items"]} == {waiting.id}
    assert {row["item_id"] for row in results["ended"]["items"]} == {valid.id}
    assert results["ended"]["summary"]["items_resolved"] == 1


def test_item_http_requires_key_and_preserves_versions(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer.router import router
    from app.customer.pcw_errors import register_pcw_error_handler
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    app = FastAPI()
    app.include_router(router, prefix="/api/customer-hub")
    register_pcw_error_handler(app)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _actor(owner)
    with TestClient(app) as client:
        response = client.get("/api/customer-hub/workbench/items")
        assert response.status_code == 200
        assert response.json()["data"]["count_unit"] == "work_item"
        version = response.json()["data"]["items"][0]["row_version"]
        payload = {"operation": "pause", "expected_item_version": version,
            "reason": "Customer requested hold", "resume_condition": "Customer responds"}
        rejected = client.post(f"/api/customer-hub/work-items/{item.id}/transitions", json=payload)
        assert rejected.status_code == 400
        assert rejected.json()["data"]["error_code"] == "IDEMPOTENCY_KEY_INVALID"
        success = client.post(f"/api/customer-hub/work-items/{item.id}/transitions", json=payload,
            headers={"Idempotency-Key": "http-pause-test-01"})
        assert success.status_code == 200
        assert success.json()["data"]["item"]["state"] == "paused"
        assert success.json()["data"]["item"]["row_version"] == version + 1
        replay = client.post(f"/api/customer-hub/work-items/{item.id}/transitions", json=payload,
            headers={"Idempotency-Key": "http-pause-test-01"})
        assert replay.json() == success.json()


def test_disabled_delegation_is_explicitly_blocked_without_fake_run(db):
    from app.customer.delegation_service import create_delegation
    from app.agent_runtime.models import AgentRun
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    user = _actor(owner)
    user["permissions"].append("agent_runtime:invoke")
    result = create_delegation(db, user, item.id, {"goal": "Prepare response", "scope": "prepare",
        "expected_item_version": 1}, "disabled-delegation-01")
    assert result["delegation"]["state"] == "blocked"
    assert result["delegation"]["readiness"]["status"] == "blocked"
    assert result["delegation"]["last_run_id"] is None
    assert db.query(AgentRun).count() == 0
