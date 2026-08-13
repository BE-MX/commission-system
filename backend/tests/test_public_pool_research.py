"""OKKI 公海分档、Agent 背调、确定性研判和机会投影契约。"""

import importlib.util
from datetime import date, datetime, timedelta
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


@pytest.fixture(autouse=True)
def published_knowledge_reference(monkeypatch):
    monkeypatch.setattr(
        agent_router.knowledge_service,
        "get_published_document",
        lambda _db, _identity, document_id, *, audit_action=None: {
            "document_id": document_id,
            "revision_id": 38,
            "title": "Target buyers",
            "content_text": "Published test content",
            "version_no": 3,
        },
    )


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
        "sub": "17", "roles": [], "permissions": ["sales_automation:invoke", "knowledge:read"],
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


def _admin_client(db):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "9", "roles": [], "permissions": ["sales_automation:admin"],
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
        "score_components": {"industry_fit": 24, "pain_switch_trigger": 12, "intent_reactivation": 18, "buying_capacity": 12, "reachability": 9, "timing": 7, "risk_penalty": 4, "reasons": {"industry_fit": "Official product catalog", "pain_switch_trigger": "Assortment gap is visible", "intent_reactivation": "Historical order seed", "buying_capacity": "Wholesale catalog", "reachability": "Sourced contact page", "timing": "Recent active catalog", "risk_penalty": "Supplier status unknown"}},
        "supplier_status": "unknown", "pain_points": [], "product_fit": ["Human-hair assortment"],
        "industry_relevance": "core", "industry_relevance_reason": "Official catalog shows human-hair products.",
        "research_depth": "deep",
        "social_profiles": [{
            "platform": "instagram", "profile_url": "https://instagram.com/customer",
            "account_name": "Customer", "activity_level": "active",
            "latest_activity_at": "2026-08-10T10:00:00Z", "business_signals": ["hair product posts"],
            "captured_at": "2026-08-11T10:03:00Z", "confidence": 0.85,
        }],
        "knowledge_references": [{
            "document_id": 8, "revision_id": 38, "version_no": 3,
        }],
        "commercial_profile": {
            "customer_type": "wholesaler", "professional_level": "experienced",
            "purchase_stage": "supplier_addition", "volume_band": "stable_medium", "scale_stage": "small_team",
            "educator_influence": "unknown", "usage_scenarios": ["distribution"],
            "product_directions": ["extension_focused"], "exclusion_status": "not_excluded",
            "development_difficulty": 2, "positive_signals": ["active catalog"],
            "negative_signals": [], "unknowns": ["current supplier"],
            "next_validation_questions": ["Are you adding a second supplier?"],
            "qualification_dimensions": {
                "authenticity_maturity": {"score": 5, "reason": "Official site and social profile agree."},
                "purchase_potential": {"score": 3, "reason": "Wholesale catalog, but no verified monthly volume."},
                "demand_readiness": {"score": None, "reason": "No current inquiry details are public."},
                "industry_professionalism": {"score": 4, "reason": "Professional product taxonomy is visible."},
                "product_market_fit": {"score": 5, "reason": "Target extension assortment is explicit."},
                "growth_brand_potential": {"score": 3, "reason": "Active catalog without verified expansion."},
                "decision_authority": {"score": None, "reason": "No verified decision maker."},
                "transaction_compliance": {"score": None, "reason": "No public transaction evidence."},
                "engagement_momentum": {"score": None, "reason": "No current interaction history in the seed."},
                "strategic_value": {"score": 3, "reason": "Potential wholesale channel; reach is unverified."},
            },
        },
        "recommended_strategy": "Ask whether the current assortment needs a small-MOQ custom color extension.",
        "outreach_type": "reactivation", "opening_message_en": "Draft only — noticed your matching assortment.",
        "idempotency_key": "public-pool-test-1",
    }


def _irrelevant_payload(lease_token: str) -> dict:
    return {
        "agent_id": "pool-agent", "lease_token": lease_token,
        "summary": "Official page identifies the entity as an unrelated accounting firm.",
        "identity_decision": "confirmed",
        "facts": [{
            "fact_type": "industry_gate", "claim": "The business offers accounting services only.",
            "source_url": "https://customer.example/services", "captured_at": "2026-08-11T10:00:00Z",
            "confidence": 0.95,
        }],
        "contacts": [], "outreach_angles": [], "risks": [],
        "score_components": {"risk_penalty": 0, "reasons": {"industry_fit": "Unrelated industry"}},
        "supplier_status": "unknown", "pain_points": [], "product_fit": [],
        "industry_relevance": "irrelevant",
        "industry_relevance_reason": "Opened official services page proves an unrelated industry.",
        "research_depth": "gate_only", "stop_reason": "Industry gate failed; deep research stopped.",
        "social_profiles": [], "knowledge_references": [],
        "commercial_profile": {"customer_type": "other", "development_difficulty": 5},
        "recommended_strategy": "Do not allocate sales effort unless new contradictory evidence appears.",
        "outreach_type": "no_outreach", "idempotency_key": "public-pool-irrelevant-1",
    }


def _gate_payload(lease_token: str, *, relevance: str = "core", identity: str = "confirmed") -> dict:
    return {
        "agent_id": "pool-agent", "lease_token": lease_token,
        "summary": "The official catalog establishes the customer identity and target industry.",
        "identity_decision": identity,
        "facts": [{
            "fact_type": "industry_gate", "claim": "The catalog lists target-category products.",
            "source_url": "https://customer.example/catalog", "captured_at": "2026-08-11T10:00:00Z",
            "confidence": 0.9,
        }],
        "industry_relevance": relevance,
        "industry_relevance_reason": "Official catalog matches the target industry.",
        "stop_reason": "Industry gate failed; deep research stopped." if relevance == "irrelevant" else None,
        "knowledge_references": [{"document_id": 8, "revision_id": 38, "version_no": 3}],
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


def test_prepared_batch_is_pending_and_duplicate_does_not_enqueue(db):
    payload = {"batch_date": date(2026, 8, 11), "quota_per_tier": 2, "policy_version": "v1"}
    first, first_should_start = public_pool_service.prepare_batch(db, payload, actor_id=7)
    duplicate, duplicate_should_start = public_pool_service.prepare_batch(db, payload, actor_id=8)

    assert first.status == "pending"
    assert duplicate.id == first.id
    assert first_should_start is True
    assert duplicate_should_start is False


def test_execute_batch_claims_pending_once(db):
    payload = {"batch_date": date(2026, 8, 11), "quota_per_tier": 1, "policy_version": "v1"}
    batch, _ = public_pool_service.prepare_batch(db, payload, actor_id=7)
    completed = public_pool_service.execute_batch(db, batch.id, gateway=FakeGateway())
    second = public_pool_service.execute_batch(db, batch.id, gateway=FakeGateway())

    assert completed.status == "completed"
    assert second.id == completed.id
    assert db.query(models.PublicPoolTask).count() == 3


def test_synchronous_runner_recovers_prepared_pending_batch(db):
    payload = {"batch_date": date(2026, 8, 11), "quota_per_tier": 1, "policy_version": "v1"}
    prepared, _ = public_pool_service.prepare_batch(db, payload, actor_id=7)

    recovered = public_pool_service.generate_batch(db, payload, actor_id=None, gateway=FakeGateway())

    assert recovered.id == prepared.id
    assert recovered.status == "completed"
    assert db.query(models.PublicPoolTask).count() == 3


def test_http_batch_creation_returns_202_and_enqueues_once(db, monkeypatch):
    queued = []
    monkeypatch.setattr(public_pool_service, "run_batch_in_background", lambda batch_id: queued.append(batch_id))
    client = _human_client(db)
    payload = {"batch_date": "2026-08-11", "quota_per_tier": 2, "policy_version": "v1"}

    first = client.post("/api/sales-automation/public-pool/batches", json=payload)
    duplicate = client.post("/api/sales-automation/public-pool/batches", json=payload)

    assert first.status_code == 202
    assert first.json()["data"]["status"] == "pending"
    assert first.json()["data"]["enqueued"] is True
    assert duplicate.status_code == 202
    assert duplicate.json()["data"]["enqueued"] is False
    assert queued == [first.json()["data"]["id"]]


def test_business_pool_cross_table_id_joins_ignore_column_collation():
    gateway = object.__new__(public_pool_service.BusinessPoolGateway)
    gateway.schema = "lsordertest"
    gateway.website_column = None

    contact_sql = gateway._contact_cte
    assert "BINARY ccs.customer_id = BINARY cc.customer_id" in contact_sql

    class RecordingSession:
        def __init__(self):
            self.statement = ""

        def execute(self, statement, _params=None):
            self.statement = str(statement)

            class Result:
                @staticmethod
                def mappings():
                    return Result()

                @staticmethod
                def all():
                    return []

            return Result()

    session = RecordingSession()
    gateway.db = session
    gateway.fetch_tier_candidates("T1", limit=1, seed="test")
    assert "BINARY cr.company_id = BINARY ci.company_id" in session.statement
    assert "BINARY o.company_id = BINARY ci.company_id" in session.statement
    assert "BINARY s.source_customer_id = BINARY CAST(f.company_id AS CHAR)" in session.statement


def test_t1_excludes_customers_with_orders_in_last_60_days():
    gateway = object.__new__(public_pool_service.BusinessPoolGateway)
    gateway.schema = "lsordertest"
    gateway.website_column = None

    class RecordingSession:
        def __init__(self):
            self.statement = ""

        def execute(self, statement, _params=None):
            self.statement = str(statement)

            class Result:
                @staticmethod
                def mappings():
                    return Result()

                @staticmethod
                def all():
                    return []

            return Result()

    session = RecordingSession()
    gateway.db = session
    gateway.fetch_tier_candidates("T1", limit=20, seed="test")

    assert "f.last_order_at <= DATE_SUB(CURDATE(), INTERVAL 60 DAY)" in session.statement
    reasons = gateway._candidate({"company_id": "1", "order_count": 1}, "T1")["selection_reason"]
    assert any("最近 60 天无下单" in reason for reason in reasons)


def test_score_is_backend_computed_and_separates_evidence_confidence():
    factors = {"industry_fit": 25, "pain_switch_trigger": 20, "intent_reactivation": 20,
               "buying_capacity": 15, "reachability": 10, "timing": 10, "risk_penalty": 0}
    confirmed = public_pool_service.compute_deal_scores(factors, "confirmed", 2)
    candidate = public_pool_service.compute_deal_scores(factors, "candidate", 1)
    assert confirmed == {"grade": "A", "deal_likelihood": "high", "evidence_confidence": "high", "business_quality_score": 100.0, "deal_score": 100.0, "priority_score": 100.0}
    assert candidate["priority_score"] < confirmed["priority_score"]
    assert candidate["evidence_confidence"] == "medium"


def test_grade_is_capped_when_qualification_evidence_coverage_is_low():
    factors = {"industry_fit": 25, "pain_switch_trigger": 20, "intent_reactivation": 20,
               "buying_capacity": 15, "reachability": 10, "timing": 10, "risk_penalty": 0}
    assert public_pool_service.compute_deal_scores(factors, "confirmed", 2, 60)["grade"] == "A"
    assert public_pool_service.compute_deal_scores(factors, "confirmed", 2, 40)["grade"] == "B"
    assert public_pool_service.compute_deal_scores(factors, "confirmed", 2, 20)["grade"] == "C"
    assert public_pool_service.compute_deal_scores(factors, "unverifiable", 0)["grade"] == "D"


def test_migration_106_contract():
    path = Path(__file__).parents[1] / "alembic/versions/106_public_pool_research.py"
    spec = importlib.util.spec_from_file_location("migration_106_public_pool", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "106_public_pool_research"
    assert migration.down_revision == "105_knowledge_category"
    source = path.read_text(encoding="utf-8")
    for table in (
        "ark_sales_research_subjects", "ark_sales_public_pool_batches",
        "ark_sales_public_pool_tasks", "ark_sales_deal_assessments",
    ):
        assert table in source


def test_migration_113_adds_gated_research_outputs():
    path = Path(__file__).parents[1] / "alembic/versions/113_public_pool_research_v2.py"
    spec = importlib.util.spec_from_file_location("migration_113_public_pool", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "113_public_pool_research_v2"
    assert migration.down_revision == "112_knowledge_editor_ai"
    source = path.read_text(encoding="utf-8")
    for column in (
        "industry_relevance", "research_depth", "stop_reason", "social_profiles",
        "knowledge_references", "commercial_profile",
    ):
        assert column in source


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
    gated = client.post(
        f"/api/sales-automation/agent/public-pool/tasks/{task.id}/industry-gate",
        json=_gate_payload(lease),
    )
    assert gated.status_code == 200, gated.text
    assert gated.json()["data"]["deep_research_authorized"] is True
    completed = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload)
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["assessment"]["grade"] == "A"
    same = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload)
    assert same.status_code == 200, same.text
    task.lease_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    expired_retry = client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload)
    assert expired_retry.status_code == 200
    original_reference_reader = agent_router.knowledge_service.get_published_document
    agent_router.knowledge_service.get_published_document = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("idempotent retry must not re-read mutable knowledge")
    )
    try:
        assert client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=payload).status_code == 200
    finally:
        agent_router.knowledge_service.get_published_document = original_reference_reader
    changed = {**payload, "summary": "Different result"}
    assert client.post(f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete", json=changed).status_code == 409
    assert db.query(models.ResearchRun).count() == 1
    assert db.query(models.ResearchFact).count() == 2
    assert db.query(models.DealAssessment).count() == 1
    assessment = db.query(models.DealAssessment).one()
    assert assessment.industry_relevance == "core"
    assert assessment.research_depth == "deep"
    assert assessment.social_profiles[0]["platform"] == "instagram"
    assert assessment.knowledge_references[0]["version_no"] == 3
    assert assessment.commercial_profile["customer_type"] == "wholesaler"
    assert assessment.commercial_profile["qualification_score"] == 76.62
    assert assessment.commercial_profile["qualification_coverage"] == 65.0


def test_irrelevant_industry_gate_stops_deep_research_and_forces_zero_grade(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T2").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    client = _agent_client(db)
    gate = _gate_payload(lease, relevance="irrelevant")
    gate["summary"] = "Official page identifies the entity as an unrelated accounting firm."
    gate["facts"][0] = {
        "fact_type": "industry_gate", "claim": "The business offers accounting services only.",
        "source_url": "https://customer.example/services", "captured_at": "2026-08-11T10:00:00Z",
        "confidence": 0.95,
    }
    gate["industry_relevance_reason"] = "Opened official services page proves an unrelated industry."
    completed = client.post(
        f"/api/sales-automation/agent/public-pool/tasks/{task.id}/industry-gate",
        json=gate,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["deep_research_authorized"] is False
    assert completed.json()["data"]["status"] == "completed"
    assessment = db.query(models.DealAssessment).filter_by(task_id=task.id).one()
    assert assessment.industry_relevance == "irrelevant"
    assert assessment.research_depth == "gate_only"
    assert assessment.outreach_type == "no_outreach"
    assert assessment.opening_message_en is None
    assert assessment.social_profiles == []
    assert assessment.risks == []
    assert db.query(models.LeadContact).count() == 0
    with pytest.raises(public_pool_service.ConflictError, match="不能审核"):
        public_pool_service.approve_task(db, task.id, actor_id=9)


def test_irrelevant_industry_gate_rejects_contacts_or_positive_scores():
    payload = _irrelevant_payload("x" * 32)
    payload["contacts"] = [{
        "name": "Owner", "source_url": "https://example.com/team",
        "captured_at": "2026-08-11T10:00:00Z",
    }]
    payload["score_components"]["industry_fit"] = 10
    from app.sales_automation.schemas import PublicPoolResearchSubmit
    with pytest.raises(ValueError, match="行业无关客户"):
        PublicPoolResearchSubmit.model_validate(payload)


def test_full_research_requires_passed_industry_gate(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T2").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    response = _agent_client(db).post(
        f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete",
        json=_research_payload(lease),
    )
    assert response.status_code == 409
    assert "先提交行业门控" in response.text


def test_excluded_product_route_must_use_irrelevant_gate():
    from app.sales_automation.schemas import PublicPoolResearchSubmit
    payload = _research_payload("x" * 32)
    payload["commercial_profile"]["exclusion_status"] = "excluded"
    with pytest.raises(ValueError, match="已排除客户"):
        PublicPoolResearchSubmit.model_validate(payload)


def test_agent_knowledge_routes_reuse_published_acl_service(db, monkeypatch):
    calls = []

    def fake_search(_db, identity, query, *, limit, audit_action):
        calls.append(("search", identity["sub"], query, limit, audit_action))
        return [{"document_id": 8, "revision_id": 38, "title": "Target buyers", "version_no": 3}]

    def fake_get(_db, identity, document_id, *, audit_action):
        calls.append(("read", identity["sub"], document_id, audit_action))
        return {
            "document_id": document_id, "revision_id": 38, "title": "Target buyers",
            "content_text": "Published content", "version_no": 3,
        }

    monkeypatch.setattr(agent_router.knowledge_service, "search_published", fake_search)
    monkeypatch.setattr(agent_router.knowledge_service, "get_published_document", fake_get)
    client = _agent_client(db)

    searched = client.get("/api/sales-automation/agent/knowledge/search", params={"q": "hair buyer", "limit": 5})
    document = client.get("/api/sales-automation/agent/knowledge/documents/8")

    assert searched.status_code == 200
    assert searched.json()["data"][0]["version_no"] == 3
    assert document.status_code == 200
    assert document.json()["data"]["content"] == "Published content"
    assert calls == [
        ("search", "17", "hair buyer", 5, "sales_agent_research_search"),
        ("read", "17", 8, "sales_agent_research_read"),
    ]


def test_agent_completion_rejects_stale_or_invented_knowledge_reference(db, monkeypatch):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T2").one()
    client = _agent_client(db)
    claim = client.post(
        f"/api/sales-automation/agent/public-pool/tasks/{task.id}/claim",
        json={"agent_id": "pool-agent"},
    )
    payload = _research_payload(claim.json()["data"]["lease_token"])
    monkeypatch.setattr(agent_router.knowledge_service, "get_published_document", lambda *_args, **_kwargs: {
        "document_id": 8, "revision_id": 39, "title": "Target buyers", "version_no": 4,
    })

    completed = client.post(
        f"/api/sales-automation/agent/public-pool/tasks/{task.id}/complete",
        json=payload,
    )

    assert completed.status_code == 409
    assert db.query(models.DealAssessment).count() == 0
    assert db.query(models.PublicPoolTask).filter_by(id=task.id).one().status == "running"


def test_human_approval_then_claim_projects_t1_to_reactivation_radar(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T1").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    public_pool_service.submit_industry_gate(db, task.id, _gate_payload(lease), actor_id=17)
    public_pool_service.complete_task_research(db, task.id, _research_payload(lease), actor_id=17)
    human = _human_client(db)
    admin = _admin_client(db)
    detail = human.get(f"/api/sales-automation/public-pool/tasks/{task.id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["research"]["facts"][0]["source_url"].startswith("https://")
    assert human.post(f"/api/sales-automation/public-pool/tasks/{task.id}/approve").status_code == 403
    approved = admin.post(f"/api/sales-automation/public-pool/tasks/{task.id}/approve")
    assert approved.status_code == 200, approved.text
    assert db.query(insight_models.CustomerOpportunity).count() == 0
    approved_task = db.query(models.PublicPoolTask).filter_by(id=task.id).one()
    assert approved_task.review_status == "approved"
    assert approved_task.opportunity_id is None

    claimed = human.post(f"/api/sales-automation/public-pool/tasks/{task.id}/claim")
    assert claimed.status_code == 200, claimed.text
    opportunity = db.query(insight_models.CustomerOpportunity).one()
    assert opportunity.opportunity_type == "customer_reactivation"
    subject = db.query(models.ResearchSubject).filter_by(id=task.subject_id).one()
    assert opportunity.source_key == f"okki-public:{subject.source_customer_id}"
    event = db.query(insight_models.CustomerProfileEvent).one()
    assert event.event_source == "okki_public_pool"
    assert event.event_type == "reactivation"
    assert db.query(models.PublicPoolTask).filter_by(id=task.id).one().review_status == "approved"


def test_public_pool_claim_is_idempotent_for_owner_and_rejects_other_salesperson(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T2").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    public_pool_service.submit_industry_gate(db, task.id, _gate_payload(lease), actor_id=17)
    public_pool_service.complete_task_research(db, task.id, _research_payload(lease), actor_id=17)
    public_pool_service.approve_task(db, task.id, actor_id=7)

    first = public_pool_service.claim_approved_task(db, task.id, actor_id=7)
    same = public_pool_service.claim_approved_task(db, task.id, actor_id=7)
    assert same.id == first.id
    with pytest.raises(public_pool_service.ConflictError, match="其他业务员"):
        public_pool_service.claim_approved_task(db, task.id, actor_id=8)
    assert db.query(insight_models.CustomerOpportunity).count() == 1

    claimable, claimable_total = public_pool_service.list_tasks(
        db, 1, 20, allocation_status="claimable",
    )
    claimed, claimed_total = public_pool_service.list_tasks(
        db, 1, 20, allocation_status="claimed",
    )
    assert claimable_total == 0
    assert claimable == []
    assert claimed_total == 1
    assert claimed[0][0].id == task.id


def test_historical_lost_opportunity_cannot_be_stolen_or_reset(db):
    _generate(db, quota=1)
    task = db.query(models.PublicPoolTask).filter(models.PublicPoolTask.tier == "T2").one()
    _row, lease = public_pool_service.claim_task(db, task.id, 17, "pool-agent")
    public_pool_service.submit_industry_gate(db, task.id, _gate_payload(lease), actor_id=17)
    public_pool_service.complete_task_research(db, task.id, _research_payload(lease), actor_id=17)
    public_pool_service.approve_task(db, task.id, actor_id=9)
    opportunity = public_pool_service.claim_approved_task(db, task.id, actor_id=7)
    opportunity.status = "lost"
    db.commit()

    second_batch = models.PublicPoolBatch(
        batch_date=date(2026, 8, 12),
        policy_version="v2",
        status="completed",
        quota_per_tier=1,
        quotas={"T1": 1, "T2": 1, "T3": 1},
        audit_snapshot={},
        result_counts={},
        idempotency_key="later-batch",
        created_by=9,
        updated_by=9,
    )
    db.add(second_batch)
    db.flush()
    second_task = models.PublicPoolTask(
        batch_id=second_batch.id,
        subject_id=task.subject_id,
        tier="T2",
        selection_rank=99,
        selection_reason=["later batch equivalent"],
        status="completed",
        review_status="approved",
        created_by=9,
        updated_by=9,
    )
    db.add(second_task)
    db.flush()
    db.add(models.DealAssessment(
        task_id=second_task.id,
        subject_id=task.subject_id,
        grade="B",
        deal_likelihood="medium",
        evidence_confidence="medium",
        identity_decision="confirmed",
        business_quality_score=70,
        deal_score=65,
        priority_score=60,
        score_factors={},
        pain_points=[],
        product_fit=[],
        recommended_strategy="Keep historical ownership",
        outreach_type="new_development",
        risks=[],
        evidence_snapshot={},
        completed_at=date(2026, 8, 12),
        created_by=9,
        updated_by=9,
    ))
    db.commit()

    with pytest.raises(public_pool_service.ConflictError, match="其他业务员"):
        public_pool_service.claim_approved_task(db, second_task.id, actor_id=8)
    same_owner = public_pool_service.claim_approved_task(db, second_task.id, actor_id=7)
    assert same_owner.id == opportunity.id
    assert same_owner.status == "lost"
