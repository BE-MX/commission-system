from datetime import timedelta
from decimal import Decimal

from app.core.time import beijing_now
from app.customer.models import (
    CustomerChangeProposal,
    CustomerObjectOwnership,
    SearchResult,
)
from app.sales_automation import service
from tests.test_customer_facts import _customer
from tests.test_customer_governance_policy import _digest, _profile
from tests.test_sales_automation import _create_job, _seed_user


def test_moved_search_result_replays_logically_and_creates_target_research(db):
    actor = _seed_user(db, 1901)
    storage = _customer(db, "logical-search-storage")
    target = _customer(db, "logical-search-target")
    profile = _profile(db, storage)
    job = _create_job(db, key="9" * 64)
    result = SearchResult(
        job_id=job.id, customer_id=storage.id, best_rank=1,
        best_score=Decimal("95"), aggregated_score_reasons={},
        result_status="active",
    )
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-search-move"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([result, proposal])
    db.flush()
    db.add(CustomerObjectOwnership(
        object_type="search_result", object_id=result.id,
        storage_customer_id=storage.id, current_customer_id=target.id,
        ownership_version=1, last_change_proposal_id=proposal.id,
        last_action_type="split",
    ))
    db.flush()

    replay, created = service._result_for_customer(db, job, target.id)
    assert replay.id == result.id
    assert created is False
    assert db.query(SearchResult).filter_by(job_id=job.id).count() == 1

    task, created = service._ensure_search_research_task(
        db, job=job, result=result, actor_id=actor.id,
    )
    assert created is True
    assert task.customer_id == target.id
    replay_task, created = service._ensure_search_research_task(
        db, job=job, result=result, actor_id=actor.id,
    )
    assert replay_task.id == task.id
    assert created is False
