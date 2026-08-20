"""智能获客 M1 契约：画像、Agent 搜客入库、去重、联系人和研究证据。"""

import ast
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.core.database import Base, get_db
from app.sales_automation import agent_router, enrichment_service, models, public_pool_service, router, service
from app.sales_automation.dependencies import require_sales_agent


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        models.AcquisitionProfile.__table__,
        models.SearchJob.__table__,
        models.LeadCompany.__table__,
        models.SearchResult.__table__,
        models.ResearchSubject.__table__,
        models.PublicPoolBatch.__table__,
        models.PublicPoolTask.__table__,
        models.DealAssessment.__table__,
        models.LeadContact.__table__,
        models.ResearchRun.__table__,
        models.ResearchFact.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(db, permissions):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": permissions,
    }
    return TestClient(app)


def _agent_client(db):
    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_sales_agent] = lambda: {
        "sub": "17", "roles": [], "permissions": ["sales_automation:invoke"],
    }
    return TestClient(app)


def _claim(db, job_id, actor_id=17, agent_id="test-agent"):
    _job, token = service.claim_search_job(db, job_id, actor_id, agent_id)
    return {"actor_id": actor_id, "agent_id": agent_id, "lease_token": token}


def _ingest(db, job_id, payload, request_key, lease):
    return service.ingest_candidates(
        db, job_id, payload, request_key,
        lease["actor_id"], lease["agent_id"], lease["lease_token"],
    )


PROFILE = {
    "company_name": "Leshine Hair",
    "company_website": "https://leshinehair.com",
    "products": ["human hair wigs", "hair toppers"],
    "advantages": ["custom color", "small MOQ"],
    "target_countries": ["United States", "Canada"],
    "target_industries": ["wig retailer", "hair salon"],
    "target_roles": ["owner", "buyer"],
    "exclusions": ["synthetic hair only"],
    "default_language": "en",
}


def test_profile_requires_admin_and_round_trips(db):
    assert _client(db, ["sales_automation:read"]).put("/api/sales-automation/profile", json=PROFILE).status_code == 403
    assert _client(db, ["sales_automation:write"]).put("/api/sales-automation/profile", json=PROFILE).status_code == 403

    response = _client(db, ["sales_automation:admin"]).put("/api/sales-automation/profile", json=PROFILE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["products"] == PROFILE["products"]

    fetched = _client(db, ["sales_automation:read"]).get("/api/sales-automation/profile")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["company_name"] == "Leshine Hair"


def test_agent_candidate_ingestion_is_idempotent_and_domain_deduplicated(db):
    profile = service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {
        "name": "US wig retailers",
        "target_count": 20,
        "keywords": ["wig retailer"],
    }, actor_id=7)
    lease = _claim(db, job.id)

    payload = [{
        "name": "Example Wigs",
        "website": "https://www.Example.com/about?utm_source=agent",
        "country": "United States",
        "industry": "wig retailer",
        "description": "Human hair wig retailer for salons",
        "source_url": "https://directory.example/vendors/example-wigs",
        "source_provider": "codex_web_search",
        "captured_at": "2026-08-09T00:00:00",
    }]
    first = _ingest(db, job.id, payload, "batch-001", lease)
    second = _ingest(db, job.id, payload, "batch-001", lease)

    assert first == {
        "received": 1, "accepted": 1, "created": 1, "updated": 0, "deduplicated": 0,
        "public_pool_deduplicated": 0, "research_queued": 1, "public_pool_duplicates": [],
    }
    assert second == first
    leads, total = service.list_leads(db, page=1, page_size=20)
    assert total == 1
    assert leads[0].normalized_domain == "example.com"
    assert leads[0].match_score > 0
    assert "wig retailer" in leads[0].score_reasons
    assert profile.id == job.profile_id
    queued = db.query(models.PublicPoolTask).one()
    subject = db.query(models.ResearchSubject).one()
    assert queued.status == "pending"
    assert subject.subject_type == "lead_company"
    assert subject.linked_company_id == leads[0].id


def test_public_pool_domain_match_is_blocked_before_lead_creation(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "public duplicate", "target_count": 1}, actor_id=7)
    lease = _claim(db, job.id)
    candidate = {
        "name": "Existing OKKI Customer",
        "website": "https://www.pool-match.example/about",
        "country": "United States",
        "industry": "wig retailer",
        "source_url": "https://pool-match.example/about",
        "captured_at": "2026-08-19T00:00:00",
    }
    public_match = {
        "source_customer_id": "OKKI-9001",
        "display_name": "Existing OKKI Customer",
        "country": "United States",
        "primary_email": "buyer@pool-match.example",
        "email_domain_type": "corporate",
        "primary_phone": None,
        "website": "https://pool-match.example",
        "tier": "T2",
        "completeness_score": 75,
        "order_count": 0,
        "order_amount_usd": 0,
        "last_order_at": None,
        "contact_snapshot": {},
        "source_snapshot": {"company_id": "OKKI-9001", "website": "https://pool-match.example"},
        "selection_reason": ["current public-pool customer"],
        "match_basis": "website",
    }
    summary = service.ingest_candidates(
        db, job.id, [candidate], "public-duplicate-1",
        lease["actor_id"], lease["agent_id"], lease["lease_token"],
        public_pool_lookup=lambda domain: public_match if domain == "pool-match.example" else None,
    )

    assert summary["accepted"] == 0
    assert summary["deduplicated"] == 1
    assert summary["public_pool_deduplicated"] == 1
    assert summary["public_pool_duplicates"][0]["source_customer_id"] == "OKKI-9001"
    assert db.query(models.LeadCompany).count() == 0
    assert db.query(models.SearchResult).count() == 0
    subject = db.query(models.ResearchSubject).one()
    assert subject.source_system == "okki"
    refreshed = service.get_search_job(db, job.id)
    assert refreshed.result_count == 0
    assert refreshed.public_pool_deduplicated_count == 1


def test_ingestion_batches_public_pool_identity_lookup_once(db, monkeypatch):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "batch identity", "target_count": 2}, actor_id=7)
    lease = _claim(db, job.id)
    calls = []

    class FakeGateway:
        def __init__(self, _db):
            pass

        def find_public_customers_by_domains(self, domains):
            calls.append(domains)
            return {}

    monkeypatch.setattr(public_pool_service, "BusinessPoolGateway", FakeGateway)
    summary = _ingest(db, job.id, [
        {
            "name": "First Candidate", "website": "https://first.example",
            "source_url": "https://first.example/about", "captured_at": "2026-08-19T00:00:00",
        },
        {
            "name": "Second Candidate", "website": "https://second.example",
            "source_url": "https://second.example/about", "captured_at": "2026-08-19T00:00:00",
        },
    ], "batch-identity", lease)

    assert summary["accepted"] == 2
    assert calls == [["first.example", "second.example"]]


def test_exact_score_70_queues_public_pool_shaped_research(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "score boundary", "target_count": 1}, actor_id=7)
    lease = _claim(db, job.id)
    summary = _ingest(db, job.id, [{
        "name": "Boundary Retailer",
        "website": "https://score-70.example",
        "country": "Mexico",
        "industry": "wig retailer",
        "description": "Human hair wigs and hair toppers for a wig retailer",
        "source_url": "https://score-70.example/about",
        "captured_at": "2026-08-19T00:00:00",
    }], "score-70", lease)

    company = db.query(models.LeadCompany).one()
    assert company.match_score == 70
    assert summary["research_queued"] == 1
    task = db.query(models.PublicPoolTask).one()
    subject = db.query(models.ResearchSubject).one()
    assert task.status == "pending"
    assert task.tier == "T2"
    assert subject.source_snapshot["match_score"] == 70


def test_later_public_pool_match_blocks_an_existing_candidate_from_approval(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    first_job = service.create_search_job(db, {"name": "first discovery", "target_count": 1}, actor_id=7)
    first_lease = _claim(db, first_job.id)
    payload = [{
        "name": "Later Public Customer",
        "website": "https://later-public.example",
        "country": "Mexico",
        "industry": "other",
        "source_url": "https://later-public.example/about",
        "captured_at": "2026-08-19T00:00:00",
    }]
    _ingest(db, first_job.id, payload, "first", first_lease)
    company = db.query(models.LeadCompany).one()
    assert company.status == "candidate"

    second_job = service.create_search_job(db, {"name": "rediscovery", "target_count": 1}, actor_id=7)
    second_lease = _claim(db, second_job.id)
    public_match = {
        "source_customer_id": "OKKI-9002", "display_name": "Later Public Customer",
        "country": "Mexico", "primary_email": None, "email_domain_type": "unknown",
        "primary_phone": None, "website": "https://later-public.example", "tier": "T2",
        "completeness_score": 50, "order_count": 0, "order_amount_usd": 0,
        "last_order_at": None, "contact_snapshot": {},
        "source_snapshot": {"company_id": "OKKI-9002", "website": "https://later-public.example"},
        "selection_reason": ["current public-pool customer"], "match_basis": "website",
    }
    service.ingest_candidates(
        db, second_job.id, payload, "second",
        second_lease["actor_id"], second_lease["agent_id"], second_lease["lease_token"],
        public_pool_lookup=lambda _domain: public_match,
    )

    db.refresh(company)
    assert company.status == "duplicate"
    with pytest.raises(service.ConflictError, match="公海去重"):
        service.approve_lead(db, company.id, actor_id=7)


def test_approve_contact_and_research_require_traceable_evidence(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "Canada", "target_count": 5}, actor_id=7)
    lease = _claim(db, job.id)
    lead = _ingest(db, job.id, [{
        "name": "Maple Hair",
        "website": "https://maplehair.ca",
        "country": "Canada",
        "industry": "hair salon",
        "source_url": "https://maplehair.ca/about",
        "captured_at": "2026-08-09T00:00:00",
    }], "lead-maple", lease)
    assert lead["created"] == 1
    company = service.list_leads(db, page=1, page_size=20)[0][0]

    approved = service.approve_lead(db, company.id, actor_id=7)
    assert approved.status == "approved"

    enrichment_service.upsert_contacts(db, company.id, [{
        "name": "Alice Buyer",
        "role": "Buyer",
        "email": "ALICE@maplehair.ca",
        "email_status": "valid",
        "verified_at": "2026-08-09T00:11:00",
        "source_url": "https://maplehair.ca/team",
        "captured_at": "2026-08-09T00:10:00",
    }])
    enrichment_service.upsert_contacts(db, company.id, [{
        "name": "Alice Buyer",
        "role": "Purchasing Manager",
        "email": "alice@maplehair.ca",
        "email_status": "valid",
        "verified_at": "2026-08-09T00:21:00",
        "source_url": "https://maplehair.ca/contact",
        "captured_at": "2026-08-09T00:20:00",
    }])
    enrichment_service.upsert_contacts(db, company.id, [{
        "name": "Alice Buyer",
        "role": "Head of Purchasing",
        "email": "alice@maplehair.ca",
        "source_url": "https://maplehair.ca/team",
        "captured_at": "2026-08-09T00:25:00",
    }])
    assert db.query(models.LeadContact).count() == 1
    contact = db.query(models.LeadContact).one()
    assert contact.email_status == "valid"
    assert contact.verified_at.isoformat() == "2026-08-09T00:21:00"

    with pytest.raises(ValueError, match="source_url"):
        enrichment_service.upsert_research(db, company.id, {
            "summary": "Potential distributor",
            "facts": [{"claim": "Operates three stores", "confidence": 0.8}],
            "outreach_angles": ["small MOQ"],
        })

    research = enrichment_service.upsert_research(db, company.id, {
        "summary": "Potential distributor",
        "facts": [{
            "claim": "Operates three stores",
            "source_url": "https://maplehair.ca/stores",
            "captured_at": "2026-08-09T00:30:00",
            "confidence": 0.8,
        }],
        "outreach_angles": ["small MOQ"],
    })
    assert research.status == "completed"
    assert db.query(models.ResearchFact).count() == 1


def test_external_evidence_links_must_be_public_http_urls(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "unsafe source", "target_count": 1}, actor_id=7)
    lease = _claim(db, job.id)
    with pytest.raises(ValueError, match="source_url"):
        _ingest(db, job.id, [{
            "name": "Unsafe Co",
            "website": "https://unsafe.example",
            "source_url": "javascript:alert(1)",
            "captured_at": "2026-08-09T00:00:00",
        }], "unsafe-1", lease)
    for numeric_host in ("0177.0.0.1", "0x7f.0.0.1", "127.1"):
        with pytest.raises(ValueError, match="主机地址"):
            service.normalize_domain(f"https://{numeric_host}/company")


def test_completed_job_rejects_late_agent_candidates(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "closed", "target_count": 1}, actor_id=7)
    lease = _claim(db, job.id)
    service.complete_search_job(db, job.id, lease["actor_id"], lease["agent_id"], lease["lease_token"])
    with pytest.raises(ValueError, match="执行中"):
        _ingest(db, job.id, [{
            "name": "Late Co",
            "website": "https://late.example",
            "source_url": "https://late.example/about",
            "captured_at": "2026-08-09T00:00:00",
        }], "late-1", lease)


def test_agent_lease_blocks_takeover_and_terminal_state_regression(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "leased", "target_count": 1}, actor_id=7)
    lease = _claim(db, job.id)
    with pytest.raises(ValueError, match="其他Agent"):
        service.claim_search_job(db, job.id, 18, "intruder")
    with pytest.raises(ValueError, match="租约"):
        service.ingest_candidates(db, job.id, [], "empty", 18, "intruder", lease["lease_token"])
    job.lease_expires_at = service._now() - timedelta(seconds=1)
    db.commit()
    queue = _agent_client(db).get("/api/sales-automation/agent/search-jobs").json()["data"]
    assert [item["id"] for item in queue["items"]] == [job.id]
    reclaimed, reclaimed_token = service.claim_search_job(db, job.id, 18, "intruder")
    with pytest.raises(ValueError, match="租约"):
        service.complete_search_job(db, job.id, lease["actor_id"], lease["agent_id"], lease["lease_token"])
    service.complete_search_job(db, job.id, 18, "intruder", reclaimed_token)
    with pytest.raises(ValueError, match="执行中"):
        service.fail_search_job(
            db, job.id, "late failure",
            18, "intruder", reclaimed_token,
        )
    assert service.get_search_job(db, job.id).status == "completed"


def test_duplicate_batch_rows_are_stable_with_production_autoflush_disabled(db):
    service.upsert_profile(db, PROFILE, actor_id=7)
    job = service.create_search_job(db, {"name": "duplicates", "target_count": 2}, actor_id=7)
    lease = _claim(db, job.id)
    candidates = [{
        "name": "Duplicate Co", "website": "https://duplicate.example",
        "source_url": "https://duplicate.example/about", "captured_at": "2026-08-09T08:00:00+08:00",
    }, {
        "name": "Duplicate Co Updated", "website": "https://www.duplicate.example/contact",
        "source_url": "https://duplicate.example/contact", "captured_at": "2026-08-09T08:10:00+08:00",
    }]
    summary = _ingest(db, job.id, candidates, "duplicates-1", lease)
    assert summary == {
        "received": 2, "accepted": 1, "created": 1, "updated": 0, "deduplicated": 1,
        "public_pool_deduplicated": 0, "research_queued": 0, "public_pool_duplicates": [],
    }
    assert db.query(models.LeadCompany).count() == 1
    result = db.query(models.SearchResult).one()
    assert result.source_url == "https://duplicate.example/contact"
    assert result.captured_at.isoformat() == "2026-08-09T00:10:00"

    company = db.query(models.LeadCompany).one()
    contacts = [{
        "name": "Alice", "email": "ALICE@duplicate.example",
        "source_url": "https://duplicate.example/team", "captured_at": "2026-08-09T00:00:00",
    }, {
        "name": "Alice Updated", "email": "alice@duplicate.example",
        "source_url": "https://duplicate.example/contact", "captured_at": "2026-08-09T00:05:00",
    }]
    enrichment_service.upsert_contacts(db, company.id, contacts)
    assert db.query(models.LeadContact).count() == 1

    changed = [dict(candidates[0], name="Different payload")]
    with pytest.raises(ValueError, match="内容不一致"):
        _ingest(db, job.id, changed, "duplicates-1", lease)


def test_invalid_agent_links_return_400_for_all_write_endpoints(db):
    human = _client(db, ["sales_automation:admin"])
    agent = _agent_client(db)
    human.put("/api/sales-automation/profile", json=PROFILE)
    job = human.post("/api/sales-automation/search-jobs", json={"name": "URL guard", "target_count": 1}).json()["data"]
    claimed = agent.post(f"/api/sales-automation/agent/search-jobs/{job['id']}/claim", json={"agent_id": "test-agent"}).json()["data"]
    lease = {"agent_id": "test-agent", "lease_token": claimed["lease_token"]}
    bad_candidate = agent.post(f"/api/sales-automation/agent/search-jobs/{job['id']}/candidates", json={
        **lease,
        "request_key": "bad-url",
        "candidates": [{
            "name": "Unsafe Co", "website": "https://unsafe.example",
            "source_url": "javascript:alert(1)", "captured_at": "2026-08-09T00:00:00",
        }],
    })
    assert bad_candidate.status_code == 400

    agent.post(f"/api/sales-automation/agent/search-jobs/{job['id']}/candidates", json={
        **lease,
        "request_key": "good-url",
        "candidates": [{
            "name": "Safe Co", "website": "https://safe.example",
            "source_url": "https://safe.example/about", "captured_at": "2026-08-09T00:00:00",
        }],
    })
    company_id = human.get("/api/sales-automation/leads").json()["data"]["items"][0]["id"]
    bad_contact = agent.post(f"/api/sales-automation/agent/leads/{company_id}/contacts", json={
        "contacts": [{
            "name": "Alice", "source_url": "file:///etc/passwd", "captured_at": "2026-08-09T00:00:00",
        }],
    })
    assert bad_contact.status_code == 400
    bad_research = agent.post(f"/api/sales-automation/agent/leads/{company_id}/research", json={
        "summary": "Unsafe source",
        "facts": [{
            "claim": "Claim", "source_url": "http://127.0.0.1/admin",
            "captured_at": "2026-08-09T00:00:00", "confidence": 0.5,
        }],
    })
    assert bad_research.status_code == 400


def test_every_route_has_exactly_one_permission_guard():
    for filename, allowed in (
        ("router.py", ("require_permission", "require_any_permission")),
        ("agent_router.py", ("require_sales_agent",)),
    ):
        source = (Path(__file__).parents[1] / f"app/sales_automation/{filename}").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
                for d in node.decorator_list
            ):
                continue
            guards = [
                call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id in allowed
            ]
            if filename == "agent_router.py":
                guards = [
                    call.args[0].id for call in ast.walk(node)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "Depends" and call.args
                    and isinstance(call.args[0], ast.Name) and call.args[0].id in allowed
                ]
            assert len(guards) == 1, f"{filename}:{node.name} 缺少权限 Depends 或重复挂载"


def test_api_agent_round_trip_returns_page_contract(db):
    human = _client(db, ["sales_automation:admin"])
    agent = _agent_client(db)
    assert human.put("/api/sales-automation/profile", json=PROFILE).status_code == 200
    created = human.post("/api/sales-automation/search-jobs", json={
        "name": "North America retailers",
        "target_count": 10,
        "idempotency_key": "job-001",
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["data"]["id"]
    claimed = agent.post(f"/api/sales-automation/agent/search-jobs/{job_id}/claim", json={"agent_id": "test-agent"})
    assert claimed.status_code == 200, claimed.text
    lease = {"agent_id": "test-agent", "lease_token": claimed.json()["data"]["lease_token"]}
    submitted = agent.post(f"/api/sales-automation/agent/search-jobs/{job_id}/candidates", json={
        **lease,
        "request_key": "batch-001",
        "candidates": [{
            "name": "North Star Wigs",
            "website": "northstarwigs.com",
            "country": "Canada",
            "industry": "wig retailer",
            "source_url": "https://northstarwigs.com/about",
            "captured_at": "2026-08-09T00:00:00",
        }],
    })
    assert submitted.status_code == 200, submitted.text
    assert agent.post(f"/api/sales-automation/agent/search-jobs/{job_id}/complete", json=lease).status_code == 200

    page = human.get("/api/sales-automation/leads?page=1&page_size=20").json()["data"]
    assert page["total"] == 1
    assert page["items"][0]["domain"] == "northstarwigs.com"
    assert page["page"] == 1
    assert page["page_size"] == 20


def test_module_wiring_permissions_and_migration_contract():
    backend = Path(__file__).parents[1]
    routers = (backend / "app/routers.py").read_text(encoding="utf-8")
    auth = (backend / "app/auth/service.py").read_text(encoding="utf-8")
    models_init = (backend / "app/models/__init__.py").read_text(encoding="utf-8")
    assert 'prefix="/api/sales-automation"' in routers
    for permission in ("sales_automation:read", "sales_automation:write", "sales_automation:admin", "sales_automation:invoke"):
        assert permission in auth
    assert "ResearchFact" in models_init

    migration_path = backend / "alembic/versions/099_sales_automation.py"
    spec = importlib.util.spec_from_file_location("migration_099_sales", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "099_sales_automation"
    assert migration.down_revision == "098_salary_leave_source"
    assert "idx_sales_job_claim" in migration_path.read_text(encoding="utf-8")


def test_model_identity_audit_and_user_fk_contract():
    from sqlalchemy.dialects import mysql

    domain_models = (
        models.AcquisitionProfile,
        models.SearchJob,
        models.LeadCompany,
        models.SearchResult,
        models.LeadContact,
        models.ResearchRun,
        models.ResearchFact,
    )
    assert {model.__tablename__ for model in domain_models} == {
        "ark_sales_target_profiles",
        "ark_sales_search_jobs",
        "ark_sales_companies",
        "ark_sales_search_results",
        "ark_sales_contacts",
        "ark_sales_research_runs",
        "ark_sales_research_facts",
    }
    for model in domain_models:
        assert {"created_by", "updated_by", "created_at", "updated_at", "deleted_at"} <= {
            column.name for column in model.__table__.columns
        }
    owner = models.LeadCompany.__table__.c.owner_user_id
    assert owner.type.compile(dialect=mysql.dialect()) == "INTEGER UNSIGNED"
    fk = next(iter(owner.foreign_keys))
    assert fk.target_fullname == "ark_users.id"
    assert fk.ondelete == "SET NULL"
    assert models.SearchJob.profile.property.lazy == "noload"
    assert models.SearchJob.results.property.lazy == "noload"


def test_migration_117_tracks_public_pool_deduplication():
    path = Path(__file__).parents[1] / "alembic/versions/117_sales_pool_dedupe.py"
    spec = importlib.util.spec_from_file_location("migration_117_sales_pool_dedupe", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "117_sales_pool_dedupe"
    assert migration.down_revision == "116_domestic_order_opt"
    assert "public_pool_deduplicated_count" in path.read_text(encoding="utf-8")
