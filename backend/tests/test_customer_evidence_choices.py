"""Evidence choices honor live source ACL, ownership and validity at submission."""

from datetime import timedelta

from app.customer import evidence_service
from app.customer.models import CustomerFact
from app.customer.workflow_service import CustomerWorkflowConflict
from tests.test_customer_workbench import NOW, hub
from tests.test_customer_workflow import _source_record
import pytest


def fact(db, customer, *, key=1, source=None, **values):
    row = CustomerFact(customer_id=customer.id, subject_type="customer", fact_key="business.industry",
        value_type="string", value_json={"value": "专业接发沙龙"}, fact_layer="source",
        verification_status="verified", confidence=0.9, confidence_method_version="test-v1",
        confidence_components_json={}, data_classification="internal_business", visibility_scope="customer_team",
        classification_reason="isolated fixture", source_record_id=source.id if source else None,
        evidence_json={}, fact_fingerprint=f"{key:064x}", observed_at=NOW, created_at=NOW, **values)
    db.add(row)
    db.flush()
    return row


def test_evidence_choices_exclude_private_sources_and_other_customers(db, hub):
    client, identity, customer, _, other = hub
    public = _source_record(db, customer)
    public.source_url = "https://example.com/products"
    allowed = fact(db, customer, source=public)
    secret = _source_record(db, customer, record_id=9002)
    secret.data_classification = "restricted_internal"
    secret.visibility_scope = "management"
    hidden = fact(db, customer, key=2, source=secret)
    foreign = fact(db, other, key=3)
    expired = fact(db, customer, key=4, expires_at=NOW - timedelta(days=1))
    response = client.get(f"/api/customer-hub/customers/{customer.id}/evidence?page_size=1")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 2
    rows = client.get(f"/api/customer-hub/customers/{customer.id}/evidence").json()["data"]["items"]
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {allowed.id, expired.id}
    assert by_id[allowed.id]["source_url"] == public.source_url
    assert by_id[allowed.id]["selectable"] is True
    assert by_id[expired.id]["selectable"] is False
    access = evidence_service.access_for(db, identity, customer.id)
    for unavailable in (hidden, foreign, expired):
        with pytest.raises(CustomerWorkflowConflict, match="EVIDENCE_NOT_AVAILABLE"):
            evidence_service.require_visible_selection(db, access, fact_ids=[unavailable.id])
    evidence_service.require_visible_selection(db, access, fact_ids=[allowed.id])
    db.commit()
    assert client.get(f"/api/customer-hub/customers/{other.id}/evidence").status_code == 404


def test_source_acl_change_invalidates_previous_choice(db, hub):
    _, identity, customer, *_ = hub
    source = _source_record(db, customer)
    item = fact(db, customer, source=source)
    access = evidence_service.access_for(db, identity, customer.id)
    evidence_service.require_visible_selection(db, access, fact_ids=[item.id])
    source.visibility_scope = "management"
    db.flush()
    with pytest.raises(CustomerWorkflowConflict, match="EVIDENCE_NOT_AVAILABLE"):
        evidence_service.require_visible_selection(db, access, fact_ids=[item.id])


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://name:password@example.com", "https://[bad"])
def test_evidence_source_link_does_not_expose_unsafe_urls(url):
    assert evidence_service._safe_url(url) is None


def test_moved_opportunity_accepts_current_customer_followup_evidence(db, hub):
    from app.customer import workflow_service as workflow
    from app.customer.models import CustomerAction, CustomerEvent, CustomerObjectOwnership
    from tests.test_customer_workbench import action

    client, _, customer, profile, other = hub
    opportunity = workflow.upsert_opportunity(
        db, customer_id=other.id, source_system="internal", source_account_key="global",
        source_key="moved-followup", opportunity_type="manual", source="manual",
        title="Moved opportunity", owner_user_id=2, actor_user_id=2,
    )
    opportunity.owner_user_id = 1
    original = action(db, other, profile, opportunity_id=opportunity.id)
    for kind, row in (("opportunity", opportunity), ("action", original)):
        db.add(CustomerObjectOwnership(object_type=kind, object_id=row.id,
            storage_customer_id=other.id, current_customer_id=customer.id, ownership_version=1,
            last_change_proposal_id=1, last_action_type="split", created_at=NOW, updated_at=NOW))
    db.flush()
    response = client.put(f"/api/customer-hub/actions/{original.id}", json={
        "operation": "complete", "summary": "首次联系", "channel": "email", "outcome_code": "contacted",
        "next_step": "寄送色卡", "next_step_due_at": "2026-09-07T09:00:00+08:00",
    })
    assert response.status_code == 200, response.text
    followup = db.get(CustomerAction, response.json()["data"]["followup_action_id"])
    assert followup.customer_id == customer.id and opportunity.customer_id == other.id
    response = client.put(f"/api/customer-hub/actions/{followup.id}", json={
        "operation": "complete", "summary": "客户已确认色号", "channel": "email", "outcome_code": "contacted",
    })
    assert response.status_code == 200, response.text
    activity = db.query(CustomerEvent).filter_by(source_ref_type="action", source_ref_id=str(followup.id),
                                                 event_type="sales_activity.logged").one()
    choices = client.get(f"/api/customer-hub/customers/{customer.id}/evidence", params={
        "kind": "event", "opportunity_id": opportunity.id, "target_status": "contacted",
    }).json()["data"]["items"]
    assert next(item for item in choices if item["id"] == activity.id)["selectable"] is True
    transitioned = workflow.transition_opportunity(db, opportunity_id=opportunity.id,
        new_status="contacted", actor_user_id=1, evidence_event_ids=[activity.id], occurred_at=NOW)
    assert transitioned.status == "contacted"

    foreign = action(db, other, profile, key=900, opportunity_id=opportunity.id)
    activity.source_ref_id = str(foreign.id)
    db.flush()
    assert workflow._event_binds_opportunity(db, event=activity, opportunity=opportunity) is False
