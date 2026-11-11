from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.project_radar import router as module
from app.project_radar.deep_link import issue_detail_token
from app.project_radar.models import RadarIngestJob
from app.project_radar.service import subscribe


@pytest.fixture
def user(db):
    row = ArkUser(username="api-radar", real_name="api", password_hash="x", dingtalk_id="dt-api")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def client(db, user, monkeypatch):
    app = FastAPI()
    app.include_router(module.router, prefix="/api/project-radar")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user.id), "permissions": ["project_radar:read", "project_radar:write", "project_radar:admin"], "roles": [],
    }
    monkeypatch.setattr(module, "run_job_async", lambda job_id: None)
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        PROJECT_RADAR_INBOUND_TOKEN="machine-token", PROJECT_RADAR_DETAIL_SECRET="detail-secret",
        JWT_SECRET_KEY="jwt-secret",
    ))
    with TestClient(app) as test_client:
        yield test_client


def test_ingest_list_patch_and_remove_http_contract(client, db, user):
    response = client.post("/api/project-radar/ingest", json={"raw_input": "https://github.com/a/b #Agent"})
    assert response.status_code == 200 and response.json()["code"] == 200
    job_id = response.json()["data"]["id"]
    assert client.get(f"/api/project-radar/jobs/{job_id}").json()["data"]["status"] == "queued"
    assert db.query(RadarIngestJob).count() == 1

    subscription = subscribe(db, user.id, "https://github.com/a/b", validator=lambda url: True)
    db.commit()
    listed = client.get("/api/project-radar/subscriptions").json()["data"]
    assert listed["total"] == 1 and listed["counts"]["all"] == 1
    patched = client.patch(f"/api/project-radar/subscriptions/{subscription.id}", json={
        "status": "trying", "note": "private note", "overrides": {"one_liner": "locked"}, "mark_read": True,
    })
    assert patched.status_code == 200
    assert patched.json()["data"]["watch_level"] == "key"
    assert patched.json()["data"]["one_liner"] == "locked"
    assert client.delete(f"/api/project-radar/subscriptions/{subscription.id}").status_code == 200
    assert client.get(f"/api/project-radar/subscriptions/{subscription.id}").status_code == 404


def test_cannot_read_another_users_subscription(client, db):
    other = ArkUser(username="other-radar", real_name="other", password_hash="x")
    db.add(other)
    db.flush()
    subscription = subscribe(db, other.id, "https://example.com", note="secret", validator=lambda url: True)
    db.commit()
    assert client.get(f"/api/project-radar/subscriptions/{subscription.id}").status_code == 404


def test_signed_public_detail_is_read_only_and_inbound_fails_closed(client, db, user):
    subscription = subscribe(db, user.id, "https://example.com", note="signed detail", validator=lambda url: True)
    db.commit()
    token = issue_detail_token("detail-secret", user.id, subscription.id)
    valid = client.get(f"/api/project-radar/public/{subscription.id}", params={"user_id": user.id, "token": token})
    assert valid.status_code == 200 and valid.json()["data"]["note"] == "signed detail"
    assert client.get(f"/api/project-radar/public/{subscription.id}", params={"user_id": user.id + 1, "token": token}).status_code == 403
    payload = {"message_id": "m1", "dingtalk_id": "unknown", "text": "帮助"}
    assert client.post("/api/project-radar/inbound/dingtalk", json=payload).status_code == 401
    accepted = client.post("/api/project-radar/inbound/dingtalk", json=payload, headers={"X-Project-Radar-Token": "machine-token"})
    assert accepted.status_code == 200 and "同步钉钉 ID" in accepted.json()["data"]["reply"]
