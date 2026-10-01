"""Real SQLite lifecycle interleavings for preparation-only delegations."""

from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.agent_runtime import artifact_service, projection_service, service, worker_service
from app.agent_runtime.errors import ConflictError, LeaseError, NotFoundError
from app.agent_runtime.models import AgentArtifact, AgentProfile, AgentRun
from app.agent_runtime.schemas import ArtifactInput, WorkerEventInput
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUserRole
from app.core.config import get_settings
from app.core.time import beijing_now, utc_now_naive
from app.customer import delegation_service, pcw_errors
from app.customer.delegation_guard_service import guard_runtime_run
from app.customer.models import CustomerAssignment
from app.customer.workbench_models import CustomerDelegation
from app.customer.work_item_service import freeze_delegations
from tests.test_agent_runtime import _seed_agent_preset
from tests.test_pcw_workitem_service import _customer_with_profile, _open_item


@pytest.fixture
def delegated(db, monkeypatch, request):
    settings = get_settings()
    for key, value in {
        "AGENT_RUNTIME_ENABLED": True, "AGENT_RUNTIME_COPILOT_ENABLED": True,
        "AGENT_RUNTIME_DSH_ENABLED": True,
        "AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON": '{"worker-a":"' + "a" * 64 + '"}',
        "AGENT_RUNTIME_WORKER_RUNTIMES_JSON": '{"worker-a":["dsh"]}',
        "AGENT_RUNTIME_RUN_TOKEN_SECRET": "test-delegation-secret-32-characters",
    }.items():
        monkeypatch.setattr(settings, key, value)
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    if getattr(request, "param", None) == "with_fact":
        from tests.test_agent_runtime import _ark_evidence_fact
        from tests.test_pcw_workitem_service import _action
        fact, _digest = _ark_evidence_fact(db, customer_id=account.id)
        _action(db, account, owner, item, evidence_fact_ids=[fact.id])
    role = ArkRole(name="delegation_tester", label="Delegation Tester")
    db.add(role)
    permissions = ["customer:read", "customer_pcw:read", "customer_pcw:write", "agent_runtime:invoke"]
    db.flush()
    for code in permissions:
        permission = db.query(ArkPermission).filter(ArkPermission.code == code).one_or_none()
        if permission is None:
            permission = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
            db.add(permission)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    db.add(ArkUserRole(user_id=owner.id, role_id=role.id))
    profile = AgentProfile(profile_key="customer_order_copilot", version=99, name="Preparation test",
        runtime="dsh", mode="interactive", model_preset="agent_runtime_copilot", system_prompt="Prepare only",
        prompt_hash="a" * 64, tool_allowlist=["get_customer_profile"], policy_json={"read_only": True}, output_schema={})
    db.add(profile)
    _seed_agent_preset(db)
    user = {"sub": str(owner.id), "permissions": permissions, "roles": [role.name]}
    result = delegation_service.create_delegation(db, user, item.id,
        {"goal": "Prepare factual answer", "scope": "prepare", "expected_item_version": item.row_version}, "delegate-test-create")
    db.commit()
    delegation = db.get(CustomerDelegation, result["delegation"]["id"])
    run = db.get(AgentRun, delegation.last_run_id)
    return account, item, delegation, run, user


def _claim_start(db, run):
    claim = worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"])
    assert claim is not None, run.error_code
    assert claim["run_id"] == run.id
    worker_service.append_worker_events(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        events=[WorkerEventInput(event_id="start", event_type="run.started", actor_type="runtime",
            payload={}, sequence_no=claim["next_sequence_no"])])
    return claim


def _complete(db, run, claim):
    return worker_service.complete_run(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        runtime_run_id=None, artifacts=[ArtifactInput(artifact_type="copilot_answer", content={"summary": "Prepared"})],
        steps_used=1, prompt_tokens=0, completion_tokens=0, cost_usd=Decimal("0"))


def _wait(db, run, claim):
    worker_service.append_worker_events(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        events=[WorkerEventInput(event_id="wait", event_type="run.waiting_input", actor_type="runtime",
            payload={"review_at": (beijing_now() + timedelta(days=1)).isoformat(),
                "resume_condition": "New source evidence or scheduled internal review"},
            sequence_no=claim["next_sequence_no"] + 1)])


def test_readiness_does_not_claim_worker_observed_and_requires_credentials(db, delegated, monkeypatch):
    assert delegation_service.readiness(db)["worker_status"] == "configured_not_observed"
    monkeypatch.setattr(get_settings(), "AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON", "{}")
    assert delegation_service.readiness(db)["status"] == "blocked"


@pytest.mark.parametrize("change", ["write_tool", "write_scope", "disabled_feature"])
def test_prepare_scope_cannot_gain_sending_capability_or_bypass_disabled_gate(db, delegated, monkeypatch, change):
    _account, _item, delegation, run, _user = delegated
    if change == "write_tool":
        profile = db.get(AgentProfile, run.profile_id)
        profile.tool_allowlist = ["get_customer_profile", "send_email"]
    elif change == "write_scope":
        delegation.scope_json = {**delegation.scope_json, "mode": "execute"}
    else:
        monkeypatch.setattr(get_settings(), "AGENT_RUNTIME_COPILOT_ENABLED", False)
    db.commit()
    assert worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"]) is None
    assert run.status == "cancelled" and run.attempt_no == 0
    assert run.error_code == "DELEGATION_SCOPE_INVALID"


def test_real_sqlite_pause_committed_between_queue_read_and_claim(db, delegated):
    _account, item, delegation, run, _user = delegated
    # Deliberately retain a cached queued Run while another real transaction pauses.
    with Session(db.get_bind()) as other:
        other_item = other.get(type(item), item.id)
        other_item.state = "paused"
        freeze_delegations(other, other_item, reason="Hold")
        other.commit()
    assert worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"]) is None
    db.refresh(run)
    assert run.status == "cancelled"
    assert run.attempt_no == 0


def _linked_fact(db, delegated):
    from app.customer.models import CustomerAction, CustomerFact
    _account, item, _delegation, _run, _user = delegated
    action = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id).one()
    return db.get(CustomerFact, action.evidence_fact_ids[0]), action


@pytest.mark.parametrize("delegated", ["with_fact"], indirect=True)
def test_real_fact_withdrawal_is_reconciled_on_claim_before_old_revision_can_execute(db, delegated):
    _account, item, delegation, run, _user = delegated
    fact, action = _linked_fact(db, delegated)
    fact.expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    assert worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"]) is None
    assert item.source_revision == 2 and not item.source_valid
    assert action.evidence_status == "stale" and delegation.status == "blocked"
    assert run.status == "cancelled" and run.attempt_no == 0


@pytest.mark.parametrize("delegated", ["with_fact"], indirect=True)
def test_tool_guard_observes_withdrawal_inside_actual_read_only_session(db, delegated):
    from app.mcp.agent_tools import _reject_flush
    _account, item, _delegation, run, _user = delegated
    fact, action = _linked_fact(db, delegated)
    from app.customer.work_item_evidence_service import evidence_revision
    assert action.feedback_json["source_revisions"]["fact"][str(fact.id)] == evidence_revision(fact)
    _claim_start(db, run)
    with Session(db.get_bind()) as reader:
        event.listen(reader, "before_flush", _reject_flush)
        with reader.no_autoflush:
            assert guard_runtime_run(reader, reader.get(AgentRun, run.id), lock=False)
        assert not reader.dirty and not reader.new
    fact.expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    with Session(db.get_bind()) as reader:
        event.listen(reader, "before_flush", _reject_flush)
        with reader.no_autoflush, pytest.raises(ConflictError, match="SOURCE_INPUT_CHANGED"):
            guard_runtime_run(reader, reader.get(AgentRun, run.id), lock=False)
        assert not reader.dirty and not reader.new
    assert item.source_revision == 1 and action.evidence_status == "valid"


def test_real_sqlite_only_one_claimer_gets_lease(db, delegated):
    _account, _item, _delegation, run, _user = delegated
    with Session(db.get_bind()) as other:
        other.get(AgentRun, run.id)
        first = worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"])
        second = worker_service.claim_run(other, worker_id="worker-b", runtimes=["dsh"])
    assert first and second is None
    db.refresh(run)
    assert run.claimed_by == "worker-a" and run.attempt_no == 1


def test_simultaneous_sqlite_claimers_receive_only_one_lease(db, delegated, tmp_path, monkeypatch):
    from app.customer import delegation_guard_service
    _account, _item, _delegation, run, _user = delegated
    path = tmp_path / "claim-race.sqlite"
    source = db.get_bind().raw_connection()
    target = sqlite3.connect(path)
    try:
        source.driver_connection.backup(target)
    finally:
        target.close()
        source.close()
    race_engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"timeout": 10})
    barrier = Barrier(2)
    original_guard = delegation_guard_service.guard_runtime_run

    def simultaneous_guard(*args, **kwargs):
        result = original_guard(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(delegation_guard_service, "guard_runtime_run", simultaneous_guard)
    def claim(worker):
        with Session(race_engine) as session:
            return worker_service.claim_run(session, worker_id=worker, runtimes=["dsh"])
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ["worker-a", "worker-b"]))
        assert sum(result is not None for result in results) == 1
        with Session(race_engine) as session:
            assert session.get(AgentRun, run.id).attempt_no == 1
    finally:
        race_engine.dispose()


def test_pause_after_start_blocks_tools_and_late_artifact_but_stop_ack_survives(db, delegated):
    _account, item, delegation, run, _user = delegated
    claim = _claim_start(db, run)
    item.state = "paused"
    freeze_delegations(db, item, reason="Hold")
    db.commit()
    assert delegation_service.serialize_delegation(db, delegation)["stop_requested"] is True
    with pytest.raises(ConflictError):
        guard_runtime_run(db, run, lock=True)
    completed, artifacts = _complete(db, run, claim)
    assert completed.status == "cancelled" and artifacts == []
    assert db.query(AgentArtifact).count() == 0
    assert delegation_service.serialize_delegation(db, delegation)["stop_requested"] is False


def test_stop_heartbeat_does_not_extend_lease_or_disclose_context(db, delegated):
    _account, item, _delegation, run, _user = delegated
    claim = _claim_start(db, run)
    item.state = "paused"
    freeze_delegations(db, item, reason="Hold")
    db.commit()
    expiry = run.lease_expires_at
    heartbeat = worker_service.heartbeat(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        runtime_run_id=None, steps_used=1)
    assert heartbeat.cancel_requested and heartbeat.lease_expires_at == expiry
    with pytest.raises(ConflictError):
        worker_service.get_context(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"])


def test_old_jwt_cannot_replay_create_after_real_invoke_permission_is_revoked(db, delegated):
    _account, item, _delegation, run, user = delegated
    permission = db.query(ArkPermission).filter(ArkPermission.code == "agent_runtime:invoke").one()
    db.query(ArkRolePermission).filter(ArkRolePermission.permission_id == permission.id).delete()
    db.commit()
    with pytest.raises(pcw_errors.PcwError) as caught:
        delegation_service.create_delegation(db, user, item.id,
            {"goal": "Prepare factual answer", "scope": "prepare", "expected_item_version": 1}, "delegate-test-create")
    assert caught.value.error_code == "AGENT_INVOKE_REQUIRED"
    assert db.query(AgentRun).count() == 1


@pytest.mark.parametrize("change", ["source", "profile", "permission", "assignment"])
def test_prepared_output_cannot_be_adopted_after_current_input_or_auth_change(db, delegated, change):
    account, item, delegation, run, user = delegated
    claim = _claim_start(db, run)
    _finished, artifacts = _complete(db, run, claim)
    assert delegation.status == "needs_decision"
    if change == "source":
        item.source_revision += 1
    elif change == "profile":
        account.profile_input_seq += 1
    elif change == "permission":
        permission = db.query(ArkPermission).filter(ArkPermission.code == "agent_runtime:invoke").one()
        db.query(ArkRolePermission).filter(ArkRolePermission.permission_id == permission.id).delete()
    else:
        db.query(CustomerAssignment).filter(CustomerAssignment.customer_id == account.id).update({"assignment_status": "inactive"})
    db.commit()
    with pytest.raises(NotFoundError if change == "assignment" else ConflictError):
        artifact_service.decide_artifact(db, artifacts[0].id, user_id=int(user["sub"]),
            decision="accepted", note=None, can_read_all=False)
    assert artifacts[0].decision_status == "draft"


def test_normal_completed_run_artifact_can_be_human_adopted(db, delegated):
    _account, _item, delegation, run, user = delegated
    _finished, artifacts = _complete(db, run, _claim_start(db, run))
    approved = artifact_service.decide_artifact(db, artifacts[0].id, user_id=int(user["sub"]),
        decision="accepted", note="Reviewed", can_read_all=False)
    assert approved.decision_status == "accepted"
    assert run.status == "completed" and delegation.status == "needs_decision"


def test_sqlite_pause_between_approval_check_and_write_rolls_back_adoption(db, delegated, monkeypatch):
    from app.customer import delegation_guard_service
    _account, item, _delegation, run, user = delegated
    _finished, artifacts = _complete(db, run, _claim_start(db, run))
    original = delegation_guard_service.guard_runtime_run
    paused = False
    def pause_after_check(*args, **kwargs):
        nonlocal paused
        result = original(*args, **kwargs)
        if kwargs.get("adoption") and not paused:
            paused = True
            with Session(db.get_bind()) as other:
                other_item = other.get(type(item), item.id)
                other_item.state = "paused"
                freeze_delegations(other, other_item, reason="Hold during approval")
                other.commit()
        return result
    monkeypatch.setattr(delegation_guard_service, "guard_runtime_run", pause_after_check)
    with pytest.raises(ConflictError):
        artifact_service.decide_artifact(db, artifacts[0].id, user_id=int(user["sub"]),
            decision="accepted", note=None, can_read_all=False)
    db.rollback()
    db.refresh(artifacts[0])
    assert paused and artifacts[0].decision_status == "draft"


def test_runtime_read_all_flag_does_not_substitute_for_live_business_approval_access(db, delegated):
    from tests.test_customer_workflow import _user
    _account, _item, _delegation, run, _owner = delegated
    _finished, artifacts = _complete(db, run, _claim_start(db, run))
    other = _user(db, 9102)
    db.commit()
    with pytest.raises(NotFoundError):
        artifact_service.decide_artifact(db, artifacts[0].id, user_id=other.id,
            decision="accepted", note=None, can_read_all=True)
    assert artifacts[0].decision_status == "draft"


def test_direct_projection_cannot_bypass_stale_generation_even_for_audit_only_type(db, delegated):
    _account, _item, delegation, run, user = delegated
    _finished, artifacts = _complete(db, run, _claim_start(db, run))
    delegation.generation += 1
    db.commit()
    with pytest.raises(ConflictError):
        projection_service.project_accepted_artifact(db, artifacts[0], run, actor_user_id=int(user["sub"]))


def test_lost_permission_blocks_tool_execution_but_worker_can_ack_stop(db, delegated):
    _account, _item, _delegation, run, _user = delegated
    claim = _claim_start(db, run)
    db.query(ArkUserRole).filter(ArkUserRole.user_id == run.owner_user_id).delete()
    db.commit()
    with pytest.raises(ConflictError):
        guard_runtime_run(db, run)
    stopped = worker_service.fail_run(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        error_code="AUTH_REVOKED", error_message="Stopped", ambiguous=False)
    assert stopped.status == "cancelled"


def test_revoked_assignment_hides_run_events_and_artifacts_even_from_old_owner(db, delegated):
    _account, _item, _delegation, run, user = delegated
    _complete(db, run, _claim_start(db, run))
    db.query(CustomerAssignment).update({"assignment_status": "inactive"})
    db.commit()
    for read in [service.get_run, service.list_events, service.list_artifacts]:
        with pytest.raises(NotFoundError):
            kwargs = {"user_id": int(user["sub"]), "can_read_all": False}
            if read == service.list_events:
                kwargs["include_admin"] = False
            read(db, run.id, **kwargs)
    assert service.list_runs(db, user_id=int(user["sub"]), can_read_all=False,
        status=None, runtime=None, page=1, page_size=20) == ([], 0)


def test_cross_day_wait_creates_one_new_run_without_resurrecting_terminal_run(db, delegated):
    _account, _item, delegation, run, _user = delegated
    claim = _claim_start(db, run)
    _wait(db, run, claim)
    assert run.status == "completed" and delegation.status == "waiting"
    assert delegation.review_at and delegation.scope_json["resume_condition"]
    assert delegation_service.enqueue_waiting_delegations(db) == 0
    delegation.review_at = beijing_now() - timedelta(days=1)
    db.commit()
    assert delegation_service.enqueue_waiting_delegations(db) == 1
    db.commit()
    assert delegation.last_run_id != run.id and delegation.generation == 2
    assert run.status == "completed"
    assert delegation_service.enqueue_waiting_delegations(db) == 0
    assert db.query(AgentRun).count() == 2
    with pytest.raises((LeaseError, ConflictError)):
        worker_service.heartbeat(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
            runtime_run_id=None, steps_used=1)


def test_wait_new_input_reenters_before_review_date_with_fresh_snapshot(db, delegated):
    account, item, delegation, run, _user = delegated
    _wait(db, run, _claim_start(db, run))
    item.source_revision += 1
    account.profile_input_seq += 1
    db.commit()
    assert delegation_service.enqueue_waiting_delegations(db) == 1
    db.commit()
    fresh = db.get(AgentRun, delegation.last_run_id)
    assert fresh.id != run.id and fresh.input_json["work_item_input_revision"] == item.source_revision
    assert fresh.input_json["customer_input_seq"] == account.profile_input_seq
    assert run.status == "completed"


def test_wait_without_review_condition_rejects_and_cannot_queue_background_run(db, delegated):
    _account, _item, _delegation, run, _user = delegated
    claim = _claim_start(db, run)
    with pytest.raises(ConflictError):
        worker_service.append_worker_events(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
            events=[WorkerEventInput(event_id="wait-invalid", event_type="run.waiting_input", actor_type="runtime",
                payload={"review_at": (beijing_now() + timedelta(days=1)).isoformat()},
                sequence_no=claim["next_sequence_no"] + 1)])
    db.rollback()
    assert run.status == "running"
    assert delegation_service.enqueue_waiting_delegations(db) == 0


@pytest.mark.parametrize("state", ["paused", "cancelled", "resolved"])
def test_wait_scheduler_never_restarts_paused_or_terminal_items(db, delegated, state):
    _account, item, delegation, run, _user = delegated
    _wait(db, run, _claim_start(db, run))
    delegation.review_at = beijing_now() - timedelta(days=1)
    item.state = state
    db.commit()
    assert delegation_service.enqueue_waiting_delegations(db) == 0
    assert run.status == "completed" and db.query(AgentRun).count() == 1


def test_ambiguous_after_cancel_stays_uncertain_and_cannot_auto_or_manual_retry(db, delegated):
    _account, item, delegation, run, user = delegated
    claim = _claim_start(db, run)
    run.cancel_requested = True
    db.commit()
    worker_service.fail_run(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        error_code="UNKNOWN_EFFECT", error_message="Receipt unavailable", ambiguous=True)
    assert run.status == "ambiguous"
    status = delegation_service.serialize_delegation(db, delegation)
    assert status["outcome_uncertain"] and status["stop_requested"] and not status["stop_confirmed"]
    delegation.status = "waiting"
    delegation.scope_json = {**delegation.scope_json, "resume_condition": "Recheck original receipt"}
    delegation.review_at = beijing_now() - timedelta(days=1)
    db.commit()
    assert delegation_service.enqueue_waiting_delegations(db) == 0
    assert delegation.status == "blocked"
    with pytest.raises(pcw_errors.PcwError) as caught:
        delegation_service.transition_delegation(db, user, delegation.id,
            {"operation": "resume", "reason": "Try again", "expected_delegation_version": delegation.row_version}, "resume-ambiguous-test")
    assert caught.value.error_code == "DELEGATION_PREVIOUS_RUN_UNCERTAIN"
    assert run.status == "ambiguous" and db.query(AgentRun).count() == 1


def test_expired_running_lease_becomes_ambiguous_never_requeued(db, delegated):
    _account, _item, _delegation, run, _user = delegated
    _claim_start(db, run)
    run.lease_expires_at = utc_now_naive() - timedelta(seconds=1)
    db.commit()
    assert worker_service.reconcile_expired_runs(db) == 1
    db.commit()
    assert run.status == "ambiguous"
    assert worker_service.claim_run(db, worker_id="worker-a", runtimes=["dsh"]) is None


def test_failed_prepare_becomes_blocked_and_resume_allocates_new_terminal_safe_run(db, delegated):
    _account, _item, delegation, run, user = delegated
    claim = _claim_start(db, run)
    worker_service.fail_run(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        error_code="MODEL_UNAVAILABLE", error_message="No output created", ambiguous=False)
    assert run.status == "failed" and delegation.status == "blocked"
    delegation_service.transition_delegation(db, user, delegation.id,
        {"operation": "resume", "reason": "Preset recovered", "expected_delegation_version": delegation.row_version}, "resume-failed-test")
    db.commit()
    assert delegation.status == "active" and delegation.last_run_id != run.id
    assert run.status == "failed" and db.query(AgentRun).count() == 2


@pytest.mark.parametrize("delegated", ["with_fact"], indirect=True)
def test_resume_reconciles_withdrawn_source_before_allocating_another_run(db, delegated):
    _account, _item, delegation, run, user = delegated
    fact, _action = _linked_fact(db, delegated)
    claim = _claim_start(db, run)
    worker_service.fail_run(db, run.id, worker_id="worker-a", lease_token=claim["lease_token"],
        error_code="MODEL_UNAVAILABLE", error_message="No output created", ambiguous=False)
    fact.expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(pcw_errors.PcwError) as caught:
        delegation_service.transition_delegation(db, user, delegation.id,
            {"operation": "resume", "reason": "Try current facts", "expected_delegation_version": delegation.row_version}, "resume-source-test")
    assert caught.value.error_code == "WORK_ITEM_NOT_EXECUTABLE"
    db.rollback()
    assert run.status == "failed" and db.query(AgentRun).count() == 1
