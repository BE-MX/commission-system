from datetime import timedelta

import pytest

from app.customer import models
from app.customer.ownership_execution_service import OwnershipExecutionError
from tests.test_customer_ownership_execution import NOW, _payload, _seed
from tests.test_customer_ownership_execution_edges import _execute
from tests.test_customer_ownership_execution_review import _approve


def _split_source_redirect(db, *, wrong_profile):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    db.add(models.CustomerChangeProposal(
        id=802, customer_id=source.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id,
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="3" * 64,
        status="draft", expires_at=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split", retain_source=True)
    payload["proposal_redirects"] = [{
        "proposal_id": 802, "target_customer_id": source.id,
        "target_profile_version_id": (
            target.current_profile_version_id if wrong_profile
            else source.current_profile_version_id
        ),
    }]
    _approve(proposal, payload)
    return source, actor, proposal


def test_retained_split_may_redirect_to_frozen_source_profile(db):
    source, actor, proposal = _split_source_redirect(db, wrong_profile=False)

    result = _execute(db, proposal, actor, "9")

    redirect = result.open_proposal_plan["redirect"][0]
    assert (redirect["target_customer_id"], redirect["target_profile_version_id"]) == (
        source.id, 1101,
    )


def test_retained_split_rejects_wrong_source_profile_redirect(db):
    _source, actor, proposal = _split_source_redirect(db, wrong_profile=True)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "0")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID"
