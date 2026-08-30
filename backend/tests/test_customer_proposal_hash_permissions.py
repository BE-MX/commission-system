"""Proposal hash integrity, race handling and live permission contracts."""

from datetime import timedelta

import pytest

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.time import beijing_now
from app.customer import models
from app.customer.proposal_service import (
    ProposalConflict, approve_proposal, create_proposal, execute_proposal,
    rebase_proposal, submit_proposal,
)
from tests.proposal_test_helpers import (
    approved as _approved, basis as _basis, set_dnc_payload as _set_dnc_payload,
)


def test_execute_rejects_inactive_human_before_dispatch(db, monkeypatch):
    actor, customer, profile, fact = _basis(db, suffix="inactive")
    payload = _set_dnc_payload(customer, profile, fact)
    proposal = _approved(
        db, customer=customer, profile=profile, fact=fact, actor=actor,
        action_type="set_dnc", payload=payload,
    )
    actor.is_active = False
    called = []
    monkeypatch.setattr(
        "app.customer.governance_policy_service.execute_governance_policy",
        lambda *_args, **_kwargs: called.append(True),
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_ACTOR_INVALID"):
        execute_proposal(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="inactive-human-1",
        )
    assert called == []


@pytest.mark.parametrize("action_type", ["assign_primary", "transfer_primary"])
def test_execute_rejects_approved_assignment_payload_tampering_without_writes(
    db, monkeypatch, action_type,
):
    actor, customer, profile, fact = _basis(db, suffix=f"tamper-{action_type}")
    target = ArkUser(
        username=f"tamper-target-{action_type}", password_hash="x",
        real_name="Tamper Target", is_active=True,
    )
    db.add(target)
    db.flush()
    proposal = _approved(
        db, customer=customer, profile=profile, fact=fact, actor=actor,
        action_type=action_type,
        payload={"user_id": target.id, "reason": "approved target"},
    )
    proposal.payload_json = {"user_id": actor.id, "reason": "tampered target"}
    db.flush()
    called = []
    monkeypatch.setattr(
        "app.customer.workflow_service.assign_customer",
        lambda *_args, **_kwargs: called.append("assign"),
    )
    monkeypatch.setattr(
        "app.customer.workflow_service.transfer_primary_owner",
        lambda *_args, **_kwargs: called.append("transfer"),
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_ACTION_HASH_INVALID"):
        execute_proposal(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key=f"tampered-{action_type}",
        )
    assert called == []
    assert proposal.status == "approved"
    assert proposal.execution_idempotency_key is None


@pytest.mark.parametrize("boundary", ["submit", "approve"])
@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: setattr(row, "payload_json", {"user_id": 999, "reason": "changed"}),
        lambda row: setattr(row, "customer_id", row.customer_id + 10000),
        lambda row: setattr(row, "target_customer_id", row.customer_id),
        lambda row: setattr(row, "profile_version_id", row.profile_version_id + 10000),
        lambda row: setattr(row, "evidence_fact_ids", [row.evidence_fact_ids[0] + 10000]),
    ],
    ids=["payload", "customer", "target", "profile", "evidence"],
)
def test_submit_and_approve_reject_any_frozen_basis_tampering(db, boundary, mutator):
    actor, customer, profile, fact = _basis(db, suffix=f"{boundary}-{id(mutator)}")
    approver = ArkUser(
        username=f"approver-{boundary}-{id(mutator)}", password_hash="x",
        real_name="Approver", is_active=True,
    )
    db.add(approver)
    db.flush()
    row = create_proposal(
        db, customer_id=customer.id, target_customer_id=None,
        action_type="assign_primary",
        payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": actor.id, "reason": "approved"},
        profile_version_id=profile.id, evidence_fact_ids=[fact.id],
        risk_level="high", expires_at=beijing_now() + timedelta(days=1),
        proposed_by=actor.id,
    )
    if boundary == "approve":
        submit_proposal(db, proposal_id=row.id, actor_user_id=actor.id)
    expected_status = row.status
    mutator(row)
    db.flush()
    with pytest.raises(ProposalConflict, match="PROPOSAL_ACTION_HASH_INVALID"):
        if boundary == "submit":
            submit_proposal(db, proposal_id=row.id, actor_user_id=actor.id)
        else:
            approve_proposal(db, proposal_id=row.id, actor_user_id=approver.id)
    assert row.status == expected_status
    assert row.approved_action_hash is None


def test_new_execution_permissions_are_seeded_as_manual_action_grants():
    from app.auth.service import seed_role_permissions
    constants = seed_role_permissions.__code__.co_consts
    assert any("customer:manage_dnc" in str(value) for value in constants)
    assert any("customer:confirm_material_risk" in str(value) for value in constants)


def test_rebase_route_requires_live_admin_and_strict_body(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer import router

    actor, customer, profile, fact = _basis(db, suffix="rebase-api")
    permission = ArkPermission(
        code="customer:admin", module="customer", action="admin",
        label="Customer Admin", kind="action", is_legacy=0, sort=10,
    )
    actor.roles.append(ArkRole(
        name="rebase-admin", label="Rebase Admin", permissions=[permission],
    ))
    db.add(models.CustomerAssignment(
        customer_id=customer.id, user_id=actor.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual",
        effective_from=beijing_now(),
    ))
    row = create_proposal(
        db, customer_id=customer.id, target_customer_id=None,
        action_type="assign_primary",
        payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": actor.id, "reason": "route"},
        profile_version_id=profile.id, evidence_fact_ids=[fact.id],
        risk_level="high", expires_at=beijing_now() + timedelta(days=1),
        proposed_by=actor.id,
    )
    db.commit()
    identity = {"sub": str(actor.id), "roles": [], "permissions": ["customer:admin"]}
    app = FastAPI()
    app.include_router(router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    body = {"profile_version_id": profile.id, "evidence_fact_ids": [fact.id]}
    with TestClient(app) as client:
        assert client.post(
            f"/api/customer-hub/change-proposals/{row.id}/rebase",
            json={**body, "unexpected": True},
        ).status_code == 422
        assert client.post(
            f"/api/customer-hub/change-proposals/{row.id}/rebase", json=body,
        ).status_code == 200
        actor.roles.clear()
        db.commit()
        assert client.post(
            f"/api/customer-hub/change-proposals/{row.id}/rebase", json=body,
        ).status_code == 403


def test_customer_router_registers_all_proposal_routes():
    from app.customer import router
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.router.routes}
    assert ("/change-proposals", ("GET",)) in routes
    assert ("/change-proposals", ("POST",)) in routes
    for action in ("submit", "rebase", "approve", "reject", "execute"):
        assert (f"/change-proposals/{{proposal_id}}/{action}", ("POST",)) in routes


def _add_collision_fact(db, customer, *, key, fingerprint):
    fact = models.CustomerFact(
        customer_id=customer.id, subject_type="customer", fact_key=key,
        fact_layer="confirmed", value_type="string", value_json={"value": "Collision"},
        verification_status="verified", confidence=1,
        confidence_method_version="test", confidence_components_json={},
        data_classification="restricted_internal", visibility_scope="management",
        classification_reason="proposal evidence", evidence_json={},
        fact_fingerprint=fingerprint, observed_at=beijing_now(),
    )
    db.add(fact)
    db.flush()
    return fact


def _collision_kwargs(db, actor, customer, profile, reason):
    return dict(
        db=db, customer_id=customer.id, target_customer_id=None,
        action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": actor.id, "reason": reason},
        profile_version_id=profile.id, risk_level="high",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=actor.id,
    )


def test_rebase_action_hash_collision_is_409_safe_and_session_remains_usable(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer import router

    actor, customer, profile, first_fact = _basis(db, suffix="rebase-collision")
    second_fact = _add_collision_fact(
        db, customer, key="identity.legal_name", fingerprint="b" * 64,
    )
    kwargs = _collision_kwargs(db, actor, customer, profile, "collision")
    original = create_proposal(evidence_fact_ids=[first_fact.id], **kwargs)
    winner = create_proposal(evidence_fact_ids=[second_fact.id], **kwargs)
    permission = ArkPermission(
        code="customer:admin", module="customer", action="admin",
        label="Customer Admin", kind="action", is_legacy=0, sort=10,
    )
    actor.roles.append(ArkRole(
        name="collision-admin", label="Collision Admin", permissions=[permission],
    ))
    db.add(models.CustomerAssignment(
        customer_id=customer.id, user_id=actor.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual",
        effective_from=beijing_now(),
    ))
    db.commit()
    app = FastAPI()
    app.include_router(router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(actor.id), "roles": [], "permissions": [],
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/customer-hub/change-proposals/{original.id}/rebase",
            json={"profile_version_id": profile.id, "evidence_fact_ids": [second_fact.id]},
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "PROPOSAL_ACTION_HASH_CONFLICT"
    db.expire_all()
    assert db.get(models.CustomerChangeProposal, original.id).evidence_fact_ids == [first_fact.id]
    assert db.get(models.CustomerChangeProposal, winner.id).status == "draft"
    assert db.query(models.CustomerChangeProposal).count() == 2


def test_rebase_catches_database_race_after_clean_precheck(db, monkeypatch):
    actor, customer, profile, first_fact = _basis(db, suffix="rebase-race")
    second_fact = _add_collision_fact(
        db, customer, key="identity.trade_name", fingerprint="c" * 64,
    )
    kwargs = _collision_kwargs(db, actor, customer, profile, "race")
    original = create_proposal(evidence_fact_ids=[first_fact.id], **kwargs)
    create_proposal(evidence_fact_ids=[second_fact.id], **kwargs)
    db.commit()
    monkeypatch.setattr(
        "app.customer.proposal_hash_service._action_hash_conflict_exists",
        lambda *_args, **_kwargs: False,
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_ACTION_HASH_CONFLICT"):
        rebase_proposal(
            db, proposal_id=original.id, actor_user_id=actor.id,
            profile_version_id=profile.id, evidence_fact_ids=[second_fact.id],
        )
    assert db.query(models.CustomerChangeProposal).count() == 2


def test_redirect_database_race_rolls_back_before_ownership(db, monkeypatch):
    actor, source, source_profile, fact = _basis(db, suffix="redirect-collision-source")
    _other, target, target_profile, _target_fact = _basis(
        db, suffix="redirect-collision-target",
    )
    assignment_payload = {"user_id": actor.id, "reason": "collision"}
    redirected = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type="assign_primary", payload=assignment_payload,
    )
    winner = _approved(
        db, customer=target, profile=target_profile, fact=fact, actor=actor,
        action_type="assign_primary", payload=assignment_payload,
    )
    payload = {
        "source_customer_id": source.id, "target_customer_ids": [target.id],
        "proposal_redirects": [{
            "proposal_id": redirected.id, "target_customer_id": target.id,
            "target_profile_version_id": target_profile.id,
        }],
    }
    executing = _approved(
        db, customer=source, target=target, profile=source_profile, fact=fact,
        actor=actor, action_type="merge", payload=payload,
    )
    original_hash = redirected.action_hash
    db.commit()
    called = []
    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        lambda *_args, **_kwargs: called.append(True),
    )
    monkeypatch.setattr(
        "app.customer.proposal_hash_service._action_hash_conflict_exists",
        lambda *_args, **_kwargs: False,
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_ACTION_HASH_CONFLICT"):
        execute_proposal(
            db, proposal_id=executing.id, actor_user_id=actor.id,
            idempotency_key="redirect-collision",
        )
    db.expire_all()
    restored = db.get(models.CustomerChangeProposal, redirected.id)
    assert (restored.customer_id, restored.action_hash, restored.status) == (
        source.id, original_hash, "approved",
    )
    assert db.get(models.CustomerChangeProposal, winner.id).status == "approved"
    assert called == []


def test_execute_route_uses_live_action_permission_not_jwt_snapshot(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer import proposal_router, router

    actor, customer, profile, fact = _basis(db, suffix="live-permission")
    permission = ArkPermission(
        code="customer:manage_dnc", module="customer", action="manage_dnc",
        label="Manage DNC", kind="action", is_legacy=0, sort=10,
    )
    actor.roles.append(ArkRole(
        name="dnc-manager", label="DNC Manager", permissions=[permission],
    ))
    db.add(models.CustomerAssignment(
        customer_id=customer.id, user_id=actor.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual",
        effective_from=beijing_now(),
    ))
    proposal = _approved(
        db, customer=customer, profile=profile, fact=fact, actor=actor,
        action_type="set_dnc", payload=_set_dnc_payload(customer, profile, fact),
    )
    db.commit()
    identity = {
        "sub": str(actor.id), "roles": [],
        "permissions": ["customer:manage_dnc"],
    }
    called = []

    def fake_execute(db, **kwargs):
        called.append(kwargs["proposal_id"])
        row = db.get(models.CustomerChangeProposal, kwargs["proposal_id"])
        row.status = "executed"
        row.execution_idempotency_key = kwargs["idempotency_key"]
        row.executed_by = kwargs["actor_user_id"]
        row.executed_at = beijing_now()
        return row

    monkeypatch.setattr(proposal_router.proposal_service, "execute_proposal", fake_execute)
    app = FastAPI()
    app.include_router(router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    body = {"idempotency_key": "live-permission-key"}
    with TestClient(app) as client:
        allowed = client.post(
            f"/api/customer-hub/change-proposals/{proposal.id}/execute", json=body,
        )
        assert allowed.status_code == 200
        assert called == [proposal.id]
        proposal.status = "approved"
        proposal.execution_idempotency_key = None
        proposal.executed_by = None
        proposal.executed_at = None
        actor.roles.clear()
        db.commit()
        denied = client.post(
            f"/api/customer-hub/change-proposals/{proposal.id}/execute", json=body,
        )
        assert denied.status_code == 403
        assert called == [proposal.id]
