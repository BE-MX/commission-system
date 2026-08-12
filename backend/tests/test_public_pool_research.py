"""OKKI 公海分档、Agent 背调、确定性研判和机会投影契约。"""

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.core.database import Base, get_db
from app.insight import models as insight_models
from app.sales_automation import agent_router, models, public_pool_service, router
from app.sales_automation.dependencies import require_sales_agent


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        models.LeadCompany.__table__,
        models.ResearchSubject.__table__,
        models.PublicPoolBatch.__table__,
        insight_models.CustomerOpportunity.__table__,
        models.PublicPoolTask.__table__,
        models.DealAssessment.__table__,
        models.LeadContact.__table__,
        models.ResearchRun.__table__,
        models.ResearchFact.__table__,
        insight_models.CustomerProfile.__table__,
        insight_models.CustomerProfileEvent.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _candidate(tier: str, index: int) -> dict:
    has_order = tier == "T1"
    website = f"https://customer-{tier.lower()}-{index}.example" if tier == "T2" else None
    email = f"buyer@customer-{index}.example" if tier == "T2" else f"person{index}@gmail.com"
    snapshot = {
        "company_id": f"{tier}-{index}", "company_name": f"Customer {tier} {index}",
        "country_name": "Mexico", "customer_email": email, "website": website,
        "order_count": 2 if has_order else 0,
    }
    return {
        "source_customer_id": f"{tier}-{index}", "display_name": f"Customer {tier} {index}",
        "country": "Mexico", "primary_email": email,
        "email_domain_type": "corporate" if tier == "T2" else "free",
        "primary_phone": "+52 555 0100" if tier == "T3" else None, "website": website,
        "tier": tier, "completeness_score": 75 if tier == "T2" else 35,
        "order_count": 2 if has_order else 0, "order_amount_usd": 1200 if has_order else 0,
        "last_order_at": None, "contact_snapshot": {}, "source_snapshot": snapshot,
        "selection_reason": [f"{tier} test selection"],
    }


class FakeGateway:
    def audit(self):
        return {
            "total_customers": 260000, "private_customers": 2100, "public_customers": 257900,
            "tier_t1": 800, "tier_t2": 95000, "tier_t3": 120000, "cold_storage": 42100,
            "generated_at": "2026-08-11T00:00:00", "business_schema": "lsordertest",
            "website_column": "website", "public_predicate": "owner_user_ids empty",
            "tier_policy_version": "v1",
        }

    def fetch_tier_candidates(self, tier, limit, seed, cooldown_days=180):
        assert seed
        assert cooldown_days == 180
        return [_candidate(tier, index) for index in range(1, min(limit, 30) + 1)]


def _generate(db, quota=2):
    return public_pool_service.generate_batch(
        db, {"batch_date": date(2026, 8, 11), "quota_per_tier": quota, "policy_version": "v1"},
        actor_id=7, gateway=FakeGateway(),
    )


def _agent_client(db):
    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_sales_agent] = lambda: {
        "sub": "17", "roles": [], "permissions": ["sales_automation:invoke"],
    }
    return TestClient(app)


def _human_client(db):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["sales_automation:read", "sales_automation:write"],
    }
    return TestClient(app)


def _research_payload(lease_token: str) -> dict:
    return {
        "agent_id": "pool-agent", "lease_token": lease_token,
        "summary": "The official site confirms a matching wholesale business.",
        "identity_decision": "confirmed",
        "facts": [
            {"fact_type": "business", "claim": "Publishes a wholesale catalog.",
             "source_url": "https://customer.example/catalog", "captured_at": "2026-08-11T10:00:00Z", "confidence": 0.9},
            {"fact_type": "fit", "claim": "Lists human-hair products.",
             "source_url": "https://customer.example/products", "captured_at": "2026-08-11T10:01:00Z", "confidence": 0.85},
        ],
        "contacts": [{"name": "Purchasing Team", "role": "Buyer", "source_url": "https://customer.example/contact", "captured_at": "2026-08-11T10:02:00Z", "confidence": 0.8}],
        "outreach_angles": ["Catalog fit"], "risks": ["Supplier status is not public"],
        "score_components": {"industry_fit": 24, "pain_switch_trigger": 12, "intent_reactivation": 18, "buying_capacity": 12, "reachability": 9, "timing": 7, "risk_penalty": 4, "reasons": {"industry_fit": "Official product catalog"}},
        "supplier_status": "unknown", "pain_points": [], "product_fit": ["Human-hair assortment"],
        "recommended_strategy": "Ask whether the current assortment needs a small-MOQ custom color extension.",
        "outreach_type": "reactivation", "opening_message_en": "Draft only — noticed your matching assortment.",
        "idempotency_key": "public-pool-test-1",
    }


def test_batch_generation_is_tiered_deterministic_and_idempotent(db):
    first = _generate(db)
    second = _generate(db)
    assert first.id == second.id
    assert first.status == "completed"
    assert first.result_counts == {"selected": {"T1": 2, "T2": 2, "T3": 2}, "total": 6}
    tasks = db.query(models.PublicPoolTask).order_by(models.PublicPoolTask.tier, models.PublicPoolTask.selection_rank).all()
    assert [(row.tier, row.selection_rank) for row in tasks] == [
        ("T1", 1), ("T1", 2), ("T2", 1), ("T2", 2), ("T3", 1), ("T3", 2),
    ]
    assert db.query(models.ResearchSubject).count() == 6
    subjects = db.query(models.ResearchSubject).all()
    assert all(row.external_key == f"okki:{row.source_customer_id}" for row in subjects)
    assert {tier: sum(row.seed_tier == tier for row in subjects) for tier in ("T1", "T2", "T3")} == {
        "T1": 2, "T2": 2, "T3": 2,
    }


def test_failed_batch_can_be_retried_with_same_idempotency_key(db):
    class FailingGateway(FakeGateway):
        def fetch_tier_candidates(self, tier, limit, seed, cooldown_days=180):
            raise RuntimeError("source unavailable")

    with pytest.raises(RuntimeError, match="source unavailable"):
        public_pool_service.generate_batch(
            db, {"batch_date": date(2026, 8, 11), "quota_per_tier": 1, "policy_version": "v1"},
            actor_id=7, gateway=FailingGateway(),
        )
    failed = db.query(models.PublicPoolBatch).one()
    assert failed.status == "failed"
    retried = _generate(db, quota=1)
    assert retried.id == failed.id
    assert retried.status == "completed"
    assert retried.result_counts["total"] == 3


def test_score_is_backend_computed_and_separates_evidence_confidence():
    factors = {"industry_fit": 25, "pain_switch_trigger": 20, "intent_reactivation": 20,
               "buying_capacity": 15, "reachability": 10, "timing": 10, "risk_penalty": 0}
    confirmed = public_pool_service.compute_deal_scores(factors, "confirmed", 2)
    candidate = public_pool_service.compute_deal_scores(factors, "candidate", 1)
    assert confirmed == {"grade": "A", "deal_likelihood": "high", "evidence_confidence": "high", "business_quality_score": 100.0, "deal_score": 100.0, "priority_score": 100.0}
    assert candidate["priority_score"] < confirmed["priority_score"]
    assert candidate["evidence_confidence"] == "medium"
    assert public_pool_service.compute_deal_scores(factors, "unverifiable", 0)["grade"] == "D"


def test_migration_105_contract():
    path = Path(__file__).parents[1] / "alembic/versions/105_public_pool_research.py"
    spec = importlib.util.spec_from_file_location("migration_105_public_pool", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "105_public_pool_research"
    assert migration.down_revision == "101_knowledge_poc"
    source = path.read_text(encoding="utf-8")
    for table in (
        "ark_sales_research_subjects", "ark_sales_public_pool_batches",
        "ark_sales_public_pool_tasks", "ark_sales_deal_assessments",
    ):
        assert table in source


def test_agent_lease_completion_and_conflicting_retry(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T1").one()
    client = _agent_client(db)
    claim = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/claim", json={"agent_id": "pool-agent"})
    assert claim.status_code == 200
    lease = claim.json()["data"]["lease_token"]
    with pytest.raises(ValueError, match="其他Agent"):
        public_pool_service.claim_task(db, task.id, 18, "intruder")
    payload = _research_payload(lease)
    completed = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload)
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["assessment"]["grade"] == "A"
    same = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload)
    assert same.status_code == 200
    changed = {**payload, "summary": "Different result"}
    assert client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=changed).status_code == 409
    assert db.query(models.ResearchRun).count() == 1
    assert db.query(models.ResearchFact).count() == 2
    assert db.query(models.DealAssessment).count() == 1


def test_human_approval_projects_t1_to_reactivation_radar(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T1").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    public_pool_service.complete_task_research(db, task.id, _research_payload(lease), actor_id=17)
    human = _human_client(db)
    detail = human.get(f"/api/sales-automation/public-pool/tasks/{task.id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["research"]["facts"][0]["source_url"].startswith("https://")
    approved = human.post(f"/api/sales-automation/public-pool/tasks/{task.id}/approve")
    assert approved.status_code == 200, approved.text
    opportunity = db.query(insight_models.CustomerOpportunity).one()
    assert opportunity.opportunity_type == "customer_reactivation"
    subject = db.query(models.ResearchSubject).filter_by(id=task.subject_id).one()
    assert opportunity.source_key == f"okki-public:{subject.source_customer_id}"
    event = db.query(insight_models.CustomerProfileEvent).one()
    assert event.event_source == "okki_public_pool"
    assert event.event_type == "reactivation"
    assert db.query(models.PublicPoolTask).filter_by(id=task.id).one().review_status == "approved"
