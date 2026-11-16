import pytest
from fastapi import HTTPException

from app.client_desk import research, sources
from app.customer import access_service
from app.customer.identity_service import IdentityCandidate, resolve_business_context
from app.sales_automation import public_pool_service
from app.sales_automation.private_research_policy import PRIVATE_RESEARCH_POLICY
from app.sales_automation.service import ConflictError


def test_live_write_scope_rejects_before_any_customer_lookup(monkeypatch):
    def reject(db, user, company_id, *, write):
        assert write is True
        raise HTTPException(404, "客户不存在或已转出")

    monkeypatch.setattr(research.service, "scoped", reject)
    monkeypatch.setattr(research, "research_customer_id", lambda *args: pytest.fail("unexpected lookup"))
    with pytest.raises(HTTPException) as refused:
        research.rerun(None, {"sub": "7"}, 55)
    assert refused.value.status_code == 404


def test_rerun_requires_unique_identity_and_uses_authenticated_owner(monkeypatch):
    monkeypatch.setattr(
        research.service, "scoped", lambda db, user, company_id, write: {"sub": "7"}
    )
    monkeypatch.setattr(research, "research_customer_id", lambda db, company_id: None)
    with pytest.raises(HTTPException) as missing:
        research.rerun(None, {"sub": "7"}, 55)
    assert missing.value.status_code == 409

    monkeypatch.setattr(research, "research_customer_id", lambda db, company_id: 73)
    monkeypatch.setattr(research, "research_sources", lambda db, user, company_id: [])

    def schedule(db, *, customer_id, owner_user_id):
        assert (customer_id, owner_user_id) == (73, 7)
        return {"status": "pending", "can_rerun": False}

    monkeypatch.setattr(
        research.private_research_service, "rerun_private_research", schedule, raising=False
    )
    assert research.rerun(None, {"sub": "7"}, 55) == {
        "status": "pending", "can_rerun": False, "report": {"status": "none"}
    }

    def cool_down(*args, **kwargs):
        raise ConflictError("客户仍在冷却期")

    monkeypatch.setattr(research.private_research_service, "rerun_private_research", cool_down)
    with pytest.raises(HTTPException) as cooldown:
        research.rerun(None, {"sub": "7"}, 55)
    assert cooldown.value.status_code == 409
    assert cooldown.value.detail == "客户仍在冷却期"


def test_sources_show_pending_private_report_using_existing_classification_acl(db, monkeypatch):
    customer = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="company",
        external_context_id="company-55",
        company_name="Company 55",
        identity_candidates=[
            IdentityCandidate(
                identifier_type="company_id", raw_value="55",
                verification_status="verified", confidence=1,
            )
        ],
    ).customer
    monkeypatch.setattr(access_service, "require_customer_access", lambda *args, **kwargs: (
        access_service.CustomerAccess(customer.id, 7, False, "personal_contact", "customer_team", None)
    ))

    def create(policy, classification):
        task, _ = public_pool_service.ensure_research_task(
            db, customer_id=customer.id, task_type="full_research", source_ref_type="manual",
            source_ref_id=classification + policy, research_policy_version=policy,
            input_snapshot={}, selection_reason=[], tier=None, created_by=None,
        )
        task.task_status = "completed"
        task.gate_status = "not_required"
        task.result_review_status = "accepted"
        task.visibility_scope = "customer_team"
        task.data_classification = classification
        return task

    visible = create(PRIVATE_RESEARCH_POLICY, "personal_contact")
    restricted = create(PRIVATE_RESEARCH_POLICY, "restricted_internal")
    public = create("research-v1", "personal_contact")
    for task in (visible, restricted, public):
        task.result_review_status = "pending"
    db.commit()
    assert sources.research_customer_id(db, 55) == customer.id
    results = sources.research_sources(db, {"sub": "7"}, 55)
    assert [(row["id"], row["review_status"]) for row in results] == [(str(visible.id), "pending")]
