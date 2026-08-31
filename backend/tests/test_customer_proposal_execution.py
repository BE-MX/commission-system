"""Proposal lifecycle, ownership redirect and explicit rebase contracts."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.time import beijing_now
from app.customer import models
from app.customer.proposal_service import (
    ProposalConflict, canonical_action_hash, create_proposal, execute_proposal,
    rebase_proposal, submit_proposal,
)
from tests.proposal_test_helpers import (
    approved as _approved, basis as _basis, set_dnc_payload as _set_dnc_payload,
)


def test_create_validates_supported_action_schema_and_frozen_bindings(db):
    actor, customer, profile, fact = _basis(db, suffix="create")
    payload = _set_dnc_payload(customer, profile, fact)
    row = create_proposal(
        db, customer_id=customer.id, target_customer_id=None,
        action_type="set_dnc", payload_schema_version="customer_set_dnc_v1",
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[fact.id], risk_level="critical",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=actor.id,
    )
    assert row.action_type == "set_dnc"
    for changes in (
        {"payload_schema_version": "customer_set_dnc_v2"},
        {"payload_json": {**payload, "customer_id": customer.id + 1}},
        {"payload_json": {**payload, "evidence_fact_ids": []}},
        {"target_customer_id": customer.id},
    ):
        kwargs = {
            "customer_id": customer.id, "target_customer_id": None,
            "action_type": "set_dnc",
            "payload_schema_version": "customer_set_dnc_v1",
            "payload_json": payload, "profile_version_id": profile.id,
            "evidence_fact_ids": [fact.id], "risk_level": "critical",
            "expires_at": beijing_now() + timedelta(days=1),
            "proposed_by": actor.id,
        }
        kwargs.update(changes)
        with pytest.raises(ProposalConflict, match="PROPOSAL_PAYLOAD_INVALID"):
            create_proposal(db, **kwargs)


def test_execute_redirects_and_supersedes_declared_proposals_atomically(db, monkeypatch):
    actor, source, source_profile, fact = _basis(db, suffix="source")
    _other_actor, target, target_profile, _target_fact = _basis(db, suffix="target")
    redirected = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type="assign_primary", payload={"user_id": actor.id, "reason": "old"},
    )
    superseded = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type="transfer_primary", payload={"user_id": actor.id, "reason": "old"},
    )
    merge_payload = {
        "source_customer_id": source.id, "target_customer_ids": [target.id],
        "proposal_redirects": [{
            "proposal_id": redirected.id, "target_customer_id": target.id,
            "target_profile_version_id": target_profile.id,
        }],
    }
    executing = _approved(
        db, customer=source, target=target, profile=source_profile, fact=fact,
        actor=actor, action_type="merge", payload=merge_payload,
    )
    db.commit()

    def fake_ownership(db, **kwargs):
        live_redirect = db.get(models.CustomerChangeProposal, redirected.id)
        assert live_redirect.customer_id == target.id
        assert live_redirect.profile_version_id == target_profile.id
        assert live_redirect.status == "draft"
        assert live_redirect.approved_action_hash is None
        live = db.get(models.CustomerChangeProposal, executing.id)
        live.status = "executed"
        live.execution_idempotency_key = kwargs["idempotency_key"]
        live.executed_by = kwargs["actor_user_id"]
        live.executed_at = beijing_now()
        return SimpleNamespace(open_proposal_plan={
            "redirect": merge_payload["proposal_redirects"],
            "supersede": [{"proposal_id": superseded.id, "next_status": "superseded"}],
        })

    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        fake_ownership,
    )
    result = execute_proposal(
        db, proposal_id=executing.id, actor_user_id=actor.id,
        idempotency_key="m" * 64,
    )
    assert result.status == "executed"
    assert db.get(models.CustomerChangeProposal, superseded.id).status == "superseded"
    redirected_row = db.get(models.CustomerChangeProposal, redirected.id)
    assert redirected_row.action_hash == canonical_action_hash(
        action_type=redirected_row.action_type, customer_id=target.id,
        target_customer_id=redirected_row.target_customer_id,
        payload_json=redirected_row.payload_json,
        profile_version_id=target_profile.id,
        evidence_fact_ids=list(redirected_row.evidence_fact_ids),
    )


def test_execute_dispatches_complete_merge_contract_to_clean_executor(db):
    from app.customer.ownership_execution_service import build_execution_basis

    actor, source, source_profile, fact = _basis(db, suffix="real-merge-source")
    _other, target, target_profile, _target_fact = _basis(db, suffix="real-merge-target")
    basis = build_execution_basis(
        db, source_customer_id=source.id, target_customer_ids=[target.id],
    )
    payload = {
        "ownership_registry_version": basis["ownership_registry_version"],
        "source_customer_id": source.id, "target_customer_ids": [target.id],
        "source_profile_version_id": source_profile.id,
        "source_profile_input_seq": source.profile_input_seq,
        "target_profile_versions": [{
            "customer_id": target.id, "profile_version_id": target_profile.id,
            "profile_input_seq": target.profile_input_seq,
        }],
        "evidence_fact_ids": [fact.id], "root_inventory": basis["root_inventory"],
        "ownership_partitions": basis["ownership_partitions"],
        "transition_plan": {
            key: {"source_ids": [], "rebuilds": []}
            for key in (
                "assignments", "contact_relationships", "customer_relationships",
                "dnc", "qualifications", "research_tasks",
            )
        },
        "proposal_redirects": [], "reason_code": "verified_duplicate",
        "reason_text": "Verified duplicate account", "keep_customer_id": target.id,
    }
    proposal = create_proposal(
        db, customer_id=source.id, target_customer_id=target.id,
        action_type="merge", payload_schema_version="customer_merge_v1",
        payload_json=payload, profile_version_id=source_profile.id,
        evidence_fact_ids=[fact.id], risk_level="critical",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=actor.id,
    )
    proposal.status = "approved"
    proposal.approved_action_hash = proposal.action_hash
    proposal.decided_by = actor.id
    proposal.decided_at = beijing_now()
    db.flush()
    result = execute_proposal(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="e" * 64,
    )
    assert result.status == "executed"
    assert source.record_status == "merged"
    assert source.merged_into_customer_id == target.id


def test_ownership_failure_rolls_back_redirects(db, monkeypatch):
    actor, source, source_profile, fact = _basis(db, suffix="rollback-source")
    _other, target, target_profile, _fact = _basis(db, suffix="rollback-target")
    redirected = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type="assign_primary", payload={"user_id": actor.id, "reason": "old"},
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
    redirected_id, source_id, profile_id, executing_id = (
        redirected.id, source.id, source_profile.id, executing.id,
    )
    db.commit()
    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("ownership failed")),
    )
    with pytest.raises(ValueError, match="ownership failed"):
        execute_proposal(
            db, proposal_id=executing_id, actor_user_id=actor.id,
            idempotency_key="r" * 64,
        )
    db.expire_all()
    restored = db.get(models.CustomerChangeProposal, redirected_id)
    assert restored.customer_id == source_id
    assert restored.profile_version_id == profile_id
    assert restored.status == "approved"


def test_ownership_redirect_rejects_unrelated_open_proposal(db, monkeypatch):
    actor, source, source_profile, fact = _basis(db, suffix="scope-source")
    _other, target, target_profile, _target_fact = _basis(db, suffix="scope-target")
    _third, unrelated, unrelated_profile, unrelated_fact = _basis(db, suffix="scope-unrelated")
    unrelated_proposal = _approved(
        db, customer=unrelated, profile=unrelated_profile, fact=unrelated_fact,
        actor=actor, action_type="assign_primary",
        payload={"user_id": actor.id, "reason": "unrelated"},
    )
    payload = {
        "source_customer_id": source.id, "target_customer_ids": [target.id],
        "proposal_redirects": [{
            "proposal_id": unrelated_proposal.id, "target_customer_id": target.id,
            "target_profile_version_id": target_profile.id,
        }],
    }
    executing = _approved(
        db, customer=source, target=target, profile=source_profile, fact=fact,
        actor=actor, action_type="merge", payload=payload,
    )
    called = []
    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        lambda *_args, **_kwargs: called.append(True),
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_REDIRECT_PLAN_INVALID"):
        execute_proposal(
            db, proposal_id=executing.id, actor_user_id=actor.id,
            idempotency_key="s" * 64,
        )
    assert called == []


@pytest.mark.parametrize(
    "redirected_action",
    ["merge", "split", "set_dnc", "remove_dnc", "confirm_material_risk"],
)
def test_redirect_rejects_action_with_embedded_customer_contract(
    db, monkeypatch, redirected_action,
):
    actor, source, source_profile, fact = _basis(
        db, suffix=f"unsupported-source-{redirected_action}",
    )
    _other, target, target_profile, _target_fact = _basis(
        db, suffix=f"unsupported-target-{redirected_action}",
    )
    redirected = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type=redirected_action, payload={"embedded_customer_id": source.id},
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
    called = []
    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        lambda *_args, **_kwargs: called.append(True),
    )
    with pytest.raises(ProposalConflict, match="PROPOSAL_REDIRECT_PLAN_INVALID"):
        execute_proposal(
            db, proposal_id=executing.id, actor_user_id=actor.id,
            idempotency_key="unsupported-redirect",
        )
    assert called == []


def test_redirected_assignment_explicit_rebase_uses_logical_evidence(db, monkeypatch):
    actor, source, source_profile, fact = _basis(db, suffix="rebase-source")
    _other, target, target_profile, _target_fact = _basis(db, suffix="rebase-target")
    redirected = _approved(
        db, customer=source, profile=source_profile, fact=fact, actor=actor,
        action_type="assign_primary", payload={"user_id": actor.id, "reason": "keep"},
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

    def fake_ownership(db, **kwargs):
        db.add(models.CustomerObjectOwnership(
            object_type="fact", object_id=fact.id,
            storage_customer_id=source.id, current_customer_id=target.id,
            ownership_version=1, last_change_proposal_id=executing.id,
            last_action_type="merge",
        ))
        rebuilt = models.CustomerProfileVersion(
            customer_id=target.id, version_no=2,
            profile_schema_version="customer_profile_v1",
            canonicalization_version="jcs_v1", input_seq=2, profile_json={},
            section_hashes={}, section_data_as_of={}, evidence_fact_ids=[fact.id],
            change_summary={}, compiler_version="test",
            profile_fingerprint=(f"{target.id + 99:x}" * 64)[:64],
            compiled_at=beijing_now(), created_at=beijing_now(),
        )
        db.add(rebuilt)
        db.flush()
        target.current_profile_version_id = rebuilt.id
        target.profile_input_seq = 2
        live = db.get(models.CustomerChangeProposal, executing.id)
        live.status = "executed"
        live.execution_idempotency_key = kwargs["idempotency_key"]
        live.executed_by = kwargs["actor_user_id"]
        live.executed_at = beijing_now()
        return SimpleNamespace(open_proposal_plan={
            "redirect": payload["proposal_redirects"], "supersede": [],
        })

    monkeypatch.setattr(
        "app.customer.ownership_execution_service.execute_customer_ownership_change",
        fake_ownership,
    )
    execute_proposal(
        db, proposal_id=executing.id, actor_user_id=actor.id,
        idempotency_key="execute-before-rebase",
    )
    rebuilt_profile_id = target.current_profile_version_id
    rebased = rebase_proposal(
        db, proposal_id=redirected.id, actor_user_id=actor.id,
        profile_version_id=rebuilt_profile_id, evidence_fact_ids=[fact.id],
    )
    assert rebased.customer_id == target.id
    assert rebased.profile_version_id == rebuilt_profile_id
    assert rebased.status == "draft"
    submitted = submit_proposal(
        db, proposal_id=redirected.id, actor_user_id=actor.id,
    )
    assert submitted.status == "pending"
