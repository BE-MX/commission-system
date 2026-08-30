"""Acquisition profile, search-job, and HTTP boundary contracts."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.customer.identity_service import (
    CustomerDomainError,
    CustomerTransactionRetryRequired,
)
from app.customer.models import CustomerAccount, CustomerSourceRecord, SearchJob, SearchResult
from app.sales_automation import agent_router, router, service
from app.sales_automation.dependencies import require_sales_agent
from app.sales_automation.models import AcquisitionProfile


POLICY = {
    "schema_version": "target_profile_policy_v1",
    "thresholds": {
        "research_threshold": 70,
        "qualification_threshold": 80,
        "tier_1_min_score": 90,
        "tier_2_min_score": 75,
        "tier_3_min_score": 60,
    },
    "weights": {"provider_score": 1},
    "research_rules": {
        "minimum_independent_sources": 2,
        "evidence_freshness_days": 90,
        "auto_research_enabled": True,
        "gate_required": True,
    },
    "claim_rules": {
        "cooldown_days": 30,
        "requires_qualification": True,
        "per_user_quota": 20,
        "per_team_quota": 100,
        "block_identity_conflict": True,
        "block_do_not_contact": True,
    },
}


def _seed_user(db, user_id: int = 1) -> ArkUser:
    user = ArkUser(
        id=user_id,
        username=f"sales-automation-{user_id}",
        password_hash="test-only",
        real_name=f"User {user_id}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _profile_payload(*, policy_version: str = "profile-v1") -> dict:
    return {
        "company_name": "Ark Hair",
        "company_website": "https://ark.example",
        "products": ["hair extensions"],
        "advantages": ["quality"],
        "target_countries": ["US"],
        "target_industries": ["salon"],
        "target_roles": ["buyer"],
        "exclusions": [],
        "default_language": "en",
        "policy_version": policy_version,
        "policy_json": POLICY,
    }


def _create_job(db, *, key: str = "1" * 64) -> SearchJob:
    if db.get(ArkUser, 1) is None:
        _seed_user(db)
    if service.get_profile(db) is None:
        service.upsert_profile(db, _profile_payload(), actor_id=1)
    return service.create_search_job(
        db,
        {
            "name": "US salons",
            "target_count": 20,
            "adapter": "agent",
            "criteria_json": {"countries": ["US"]},
            "idempotency_key": key,
        },
        actor_id=1,
    )


def _candidate() -> dict:
    return {
        "source_system": "public_web",
        "source_account_key": "global",
        "source_entity_type": "company_page",
        "external_record_id": "company-page-1",
        "external_context_id": "example.com",
        "source_provider": "google",
        "source_url": "https://example.com/about",
        "captured_at": datetime(2026, 8, 30, 9, 0),
        "company_name": "Example Hair LLC",
        "website": "https://example.com",
        "score": 90,
        "score_reasons": [{"dimension": "fit", "score": 90}],
    }


def test_profile_policy_is_versioned_and_hashes_the_complete_snapshot(db):
    _seed_user(db)
    first = service.upsert_profile(db, _profile_payload(), actor_id=1)
    first_hash = first.policy_snapshot_hash
    replay = service.upsert_profile(db, _profile_payload(), actor_id=1)

    assert replay.id == first.id
    assert len(first_hash) == 64
    assert first.policy_applied_at is not None
    with pytest.raises(service.ConflictError, match="policy_version"):
        service.upsert_profile(
            db,
            {**_profile_payload(), "target_countries": ["US", "CA"]},
            actor_id=1,
        )

    changed = service.upsert_profile(
        db,
        {
            **_profile_payload(policy_version="profile-v2"),
            "target_countries": ["US", "CA"],
        },
        actor_id=1,
    )
    assert changed.policy_version == "profile-v2"
    assert changed.policy_snapshot_hash != first_hash


def test_target_profile_added_fields_have_explicit_database_comments():
    table = AcquisitionProfile.__table__

    assert table.comment
    for field in (
        "policy_version",
        "policy_json",
        "policy_snapshot_hash",
        "last_improvement_artifact_id",
        "policy_applied_at",
    ):
        assert table.c[field].comment


def test_search_job_creation_and_request_replay_freeze_one_profile_snapshot(db):
    job = _create_job(db)
    replay = _create_job(db)

    assert replay.id == job.id
    assert db.query(SearchJob).count() == 1
    assert job.profile_snapshot["schema_version"] == "target_profile_snapshot_v1"
    assert job.profile_snapshot["policy_version"] == "profile-v1"
    assert job.profile_snapshot_hash == replay.profile_snapshot_hash


def test_explicit_search_job_idempotency_key_rejects_changed_request_material(db):
    job = _create_job(db, key="a" * 64)

    with pytest.raises(service.ConflictError, match="idempotency_key"):
        service.create_search_job(
            db,
            {
                "name": job.name,
                "target_count": job.target_count + 1,
                "adapter": job.adapter,
                "criteria_json": {"countries": ["CA"]},
                "idempotency_key": "a" * 64,
            },
            actor_id=1,
        )


def test_search_job_lease_is_fenced_and_terminal_job_rejects_late_candidates(db):
    job = _create_job(db)
    running, token = service.claim_search_job(db, job.id, 1, "search-agent")

    with pytest.raises(service.ConflictError, match="租约不属于"):
        service.heartbeat_search_job(db, job.id, 1, "other-agent", token)
    completed = service.complete_search_job(db, running.id, 1, "search-agent", token)
    assert completed.claimed_by is None
    assert completed.lease_token_hash is None
    assert completed.lease_expires_at is None
    with pytest.raises(service.ConflictError, match="租约|执行中"):
        service.ingest_candidates(
            db,
            job.id,
            [_candidate()],
            request_key="late-batch",
            actor_id=1,
            agent_id="search-agent",
            lease_token=token,
        )
    assert db.query(CustomerAccount).count() == 0
    assert db.query(SearchResult).count() == 0


def test_search_job_lease_uses_beijing_business_clock(db, monkeypatch):
    job = _create_job(db)
    now = datetime(2026, 8, 30, 14, 0)
    monkeypatch.setattr(service, "beijing_now", lambda: now)

    running, _token = service.claim_search_job(db, job.id, 1, "search-agent")

    assert running.started_at == now
    assert running.lease_expires_at == now + timedelta(minutes=service.LEASE_MINUTES)


def test_identity_transaction_retry_rolls_back_source_and_requires_new_transaction(
    db, monkeypatch,
):
    job = _create_job(db)
    running, token = service.claim_search_job(db, job.id, 1, "search-agent")
    monkeypatch.setattr(
        service,
        "_resolve_candidate_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CustomerTransactionRetryRequired()
        ),
    )

    with pytest.raises(service.ConflictError, match="RETRY_NEW_TRANSACTION"):
        service.ingest_candidates(
            db, running.id, [_candidate()], "retry-batch", 1, "search-agent", token,
        )

    assert db.query(CustomerSourceRecord).count() == 0
    assert db.get(SearchJob, job.id).ingestion_receipts == {}


def test_identity_resolution_conflict_is_quarantined_with_specific_code(db, monkeypatch):
    job = _create_job(db)
    running, token = service.claim_search_job(db, job.id, 1, "search-agent")
    monkeypatch.setattr(
        service,
        "_resolve_candidate_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CustomerDomainError("IDENTITY_RESOLUTION_CONFLICT")
        ),
    )

    summary = service.ingest_candidates(
        db, running.id, [_candidate()], "conflict-batch", 1, "search-agent", token,
    )

    assert summary["quarantined_sources"] == 1
    source = db.query(CustomerSourceRecord).one()
    assert source.processing_error_code == "identity_resolution_conflict"


def _human_client(db, identity: dict) -> TestClient:
    app = FastAPI()
    app.include_router(router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    return TestClient(app)


def test_human_http_uses_ok_envelope_permissions_and_new_identifiers(db):
    _seed_user(db)
    identity = {
        "sub": "1",
        "roles": [],
        "permissions": ["sales_automation:admin", "sales_automation:read"],
    }
    with _human_client(db, identity) as client:
        saved = client.put("/api/sales-automation/profile", json=_profile_payload())
        assert saved.status_code == 200
        assert saved.json()["data"]["policy_version"] == "profile-v1"

        identity["permissions"] = ["sales_automation:write"]
        created = client.post("/api/sales-automation/search-jobs", json={
            "name": "US salons",
            "target_count": 20,
            "adapter": "agent",
            "criteria_json": {"countries": ["US"]},
            "idempotency_key": "2" * 64,
        })
        assert created.status_code == 201
        assert created.json()["code"] == 200
        assert set(created.json()["data"]) >= {"job_id", "profile_id", "policy_version"}
        assert "lead_id" not in created.json()["data"]

        identity["permissions"] = ["sales_automation:read"]
        forbidden = client.post("/api/sales-automation/search-jobs", json={
            "name": "forbidden", "target_count": 1, "idempotency_key": "3" * 64,
        })
        assert forbidden.status_code == 403
        listed = client.get("/api/sales-automation/search-jobs")
        assert listed.status_code == 200
        assert listed.json()["data"]["items"][0]["job_id"] == created.json()["data"]["job_id"]
        assert client.get("/api/sales-automation/leads").status_code == 404


def test_agent_http_context_exposes_customer_id_contract_only(db):
    job = _create_job(db)
    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_sales_agent] = lambda: {
        "sub": "1",
        "permissions": ["sales_automation:invoke", "knowledge:read"],
    }

    with TestClient(app) as client:
        response = client.get(f"/api/sales-automation/agent/search-jobs/{job.id}/context")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_id"] == job.id
    assert data["output_contract"] == {
        "identifier": "customer_id",
        "source_record_first": True,
        "company_name_nullable": True,
    }
    assert "lead" not in str(data).lower()
