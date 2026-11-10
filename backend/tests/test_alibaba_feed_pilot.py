"""Pilot setup, activation and tenant-bound behavior through the real HTTP routes."""
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.alibaba_feed.business_router import router as business_router
from app.alibaba_feed.models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedMessage, AlibabaFeedLink, AlibabaFeedPilot, AlibabaFeedSource
from app.alibaba_feed.router import router as collector_router
from app.alibaba_feed.source_router import router as admin_router
from app.alibaba_feed.worker import process_next_batch
from app.auth.models import ArkPermission, ArkRole, ArkUserExternalBinding
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.integration.schemas import IntegrationAppCreate
from app.integration.service import create_app
from tests.test_alibaba_feed_auth import enable, feed  # noqa: F401
from tests.test_alibaba_feed_core import payload, raw


def jwt(uid):
    claims = {"sub": str(uid), "permissions": ["client_desk:read"] if uid == 1 else [],
              "roles": ["super_admin"] if uid == 2 else []}
    return {"Authorization": "Bearer " + create_access_token(claims)}


def collector(issued):
    return {"Authorization": "Bearer " + issued["token"], "Content-Type": "application/json", "Idempotency-Key": "run-a"}


@pytest.fixture
def pilot_api(feed):
    db, existing_credential, existing_source, role = feed
    for model in (ArkUserExternalBinding, AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedMessage, AlibabaFeedLink):
        model.__table__.create(db.get_bind())
    role.permissions.append(ArkPermission(code="client_desk:read", module="client_desk", action="read", label="Read"))
    operator = db.query(ArkRole).filter_by(name="integration_admin").one()
    operator.permissions.append(ArkPermission(code="alibaba_feed:admin", module="alibaba_feed", action="admin", label="Pilot admin"))
    db.commit()
    issued = create_app(db, IntegrationAppCreate(
        name="Pilot collector", owner_user_id=1, scopes=["alibaba_feed:read", "alibaba_feed:write"]
    ), created_by=99)
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(business_router, prefix="/business")
    app.include_router(collector_router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: db
    draft = {"expected_version": 1, "source_account_uid": "shop-pilot", "name": "Pilot shop",
             "integration_app_id": issued["id"], "user_id": 1, "owner_alias": " AW Seller "}
    return TestClient(app), db, issued, draft, existing_credential, existing_source


def test_dark_setup_then_manual_activation_and_pause(pilot_api):
    client, db, issued, draft, _, _ = pilot_api
    assert client.get("/pilot", headers=jwt(1)).status_code == 403
    assert client.get("/pilot", headers=collector(issued)).status_code == 401
    assert client.put("/pilot", headers=jwt(1), json=draft).status_code == 403
    assert client.post("/pilot/activation", headers=collector(issued),
                       json={"enabled": True, "expected_version": 1}).status_code == 401

    config = client.get("/pilot", headers=jwt(99)).json()["data"]
    assert config["source"] is None and not config["enabled"]
    assert any(app["id"] == issued["id"] for app in config["collectors"])
    assert 4 not in {user["id"] for user in config["users"]}
    assert issued["token"] not in str(config)
    assert client.put("/pilot", headers=jwt(99), json={**draft, "ingest_enabled": True}).status_code == 422

    saved = client.put("/pilot", headers=jwt(99), json=draft)
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["version"] == 2 and data["owner_alias"] == " AW Seller " and not data["enabled"]
    assert data["source"]["owner_aliases"] == {" AW Seller ": 1}
    assert not data["source"]["ingest_enabled"] and data["source"]["consent_state"] == "pending"
    assert client.get("/v1/runs/run-a", headers=collector(issued)).json()["data"]["error_code"] == "FEED_DISABLED"
    assert client.get("/business/records", headers=jwt(1)).status_code == 503
    assert client.put("/pilot", headers=jwt(99), json=draft).status_code == 409
    assert client.post("/pilot/activation", headers=jwt(99),
                       json={"enabled": True, "expected_version": 2}).status_code == 422

    activated = client.post("/pilot/activation", headers=jwt(99),
                            json={"enabled": True, "expected_version": 2, "consent_confirmed": True})
    assert activated.status_code == 200, activated.text
    source = activated.json()["data"]["source"]
    assert source["consent_state"] == "authorized" and source["ingest_enabled"] and source["crm_shared"]
    assert not source["ai_egress_allowed"] and not source["private_feed_enabled"]
    assert client.put("/pilot", headers=jwt(99), json={**draft, "expected_version": 3}).status_code == 409
    assert client.patch("/sources/shop-pilot", headers=jwt(99),
                        json={"expected_version": source["version"], "ai_egress_allowed": True}).status_code == 409
    data = payload()
    data["records"][0]["assignee_name"] = " AW Seller "
    data["by_assignee"][0]["assignee_name"] = " AW Seller "
    assert client.post("/v1/batches", headers=collector(issued), content=raw(data)).status_code == 202
    assert process_next_batch(db, pilot_only=True)
    assert client.get("/business/records", headers=jwt(1)).json()["data"]["total"] == 1
    assert client.get("/business/records", headers=jwt(2)).status_code == 403

    paused = client.post("/pilot/activation", headers=jwt(99), json={"enabled": False, "expected_version": 3})
    assert paused.status_code == 200
    assert not paused.json()["data"]["source"]["ingest_enabled"]
    assert client.get("/v1/runs/run-a", headers=collector(issued)).status_code == 503
    assert client.get("/business/records", headers=jwt(1)).status_code == 503
    assert db.query(AlibabaFeedBatch).count() == db.query(AlibabaFeedItem).count() == 1


def test_second_source_and_wrong_account_are_blocked(pilot_api):
    client, db, issued, draft, other, original = pilot_api
    enable(db, original)
    auth = jwt(99)
    for invalid in ({"integration_app_id": other["id"]}, {"user_id": 4}):
        result = client.put("/pilot", headers=auth, json={**draft, **invalid})
        assert result.status_code in (409, 422)
    assert client.get("/pilot", headers=auth).json()["data"]["source"] is None
    assert db.query(AlibabaFeedSource).count() == 1
    assert client.put("/pilot", headers=auth, json=draft).status_code == 200
    assert client.post("/pilot/activation", headers=auth,
                       json={"enabled": True, "expected_version": 2, "consent_confirmed": True}).status_code == 200
    response = client.post("/v1/batches", headers=collector(other), content=raw(payload()))
    assert response.status_code == 403 and response.json()["data"]["error_code"] == "SOURCE_SCOPE_DENIED"
    assert db.query(AlibabaFeedBatch).count() == 0


def test_migration_creates_only_one_empty_pilot_and_preserves_sources(feed):
    db, _, source, _ = feed
    engine = db.get_bind()
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "alembic/versions/256_alibaba_feed_pilot.py"
    spec = spec_from_file_location("feed_pilot_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.close()
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
        migration._create_table()
        migration.upgrade()
        migration.upgrade()
        row = conn.execute(text("SELECT source_id, user_id, enabled, version FROM ark_alibaba_feed_pilot")).one()
        assert tuple(row) == (None, None, 0, 1)
        assert conn.execute(text("SELECT source_account_uid FROM ark_alibaba_feed_sources")).scalar() == source["source_account_uid"]
        assert {fk["referred_table"] for fk in inspect(conn).get_foreign_keys("ark_alibaba_feed_pilot")} == {
            "ark_alibaba_feed_sources", "ark_users"
        }
