from datetime import timedelta

import pytest

from app.core.time import beijing_now
from app.customer import workflow_service as workflow
from app.customer.models import (
    CustomerChangeProposal,
    CustomerConversation,
    CustomerMessage,
    CustomerObjectOwnership,
)
from tests.test_customer_facts import _customer, _source
from tests.test_customer_governance_policy import _digest, _profile


def test_upsert_opportunity_accepts_moved_source_and_message_parent(db):
    storage = _customer(db, "logical-opportunity-storage")
    target = _customer(db, "logical-opportunity-target")
    other = _customer(db, "logical-opportunity-other")
    source = _source(db, storage, external_id="logical-opportunity-source")
    profile = _profile(db, storage)
    conversation = CustomerConversation(
        customer_id=storage.id, source_system="public_web",
        source_account_key="global", external_conversation_id="logical-message",
        channel="email", conversation_status="active",
        latest_source_record_id=source.id,
    )
    message = CustomerMessage(
        conversation_id=conversation.id, external_message_id="logical-message",
        direction="in", sender_type="customer_contact", content_type="text",
        content_text="Need hair products", attachment_meta_json=[],
        source_record_id=source.id, content_hash="a" * 64,
        sent_at=beijing_now(), captured_at=beijing_now(),
    )
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-opportunity"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([conversation, proposal])
    db.flush()
    message.conversation_id = conversation.id
    db.add(message)
    db.flush()
    for object_type, row in (
        ("source_record", source), ("conversation", conversation),
    ):
        db.add(CustomerObjectOwnership(
            object_type=object_type, object_id=row.id,
            storage_customer_id=storage.id, current_customer_id=target.id,
            ownership_version=1, last_change_proposal_id=proposal.id,
            last_action_type="split",
        ))
    db.flush()

    source_opportunity = workflow.upsert_opportunity(
        db, customer_id=target.id, source_system="manual",
        source_account_key="global", source_key="logical-source",
        opportunity_type="manual", source="manual", title="Moved source",
        source_ref_type="source_record", source_ref_id=source.id,
    )
    message_opportunity = workflow.upsert_opportunity(
        db, customer_id=target.id, source_system="manual",
        source_account_key="global", source_key="logical-message",
        opportunity_type="manual", source="manual", title="Moved message",
        source_ref_type="message", source_ref_id=message.id,
    )
    assert source_opportunity.customer_id == target.id
    assert message_opportunity.customer_id == target.id

    with pytest.raises(workflow.CustomerWorkflowConflict):
        workflow.upsert_opportunity(
            db, customer_id=other.id, source_system="manual",
            source_account_key="global", source_key="cross-owner",
            opportunity_type="manual", source="manual", title="Cross owner",
            source_ref_type="message", source_ref_id=message.id,
        )
