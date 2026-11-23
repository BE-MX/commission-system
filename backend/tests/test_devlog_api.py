import hashlib
import json
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.core.config import get_settings
from app.core.database import get_db

TOKEN = "t" * 32
BODY = {"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
        "sources": [{"name": "git", "ok": True}], "items": []}


@contextmanager
def client(db, permissions=("devlog:read",)):
    from app.devlog.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/devlog")
    app.dependency_overrides[get_db] = lambda: db
    token = create_access_token({"sub": "1", "username": "u", "real_name": "u", "roles": [], "permissions": list(permissions)})
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


def test_ingest_requires_machine_token(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    with client(db) as c:
        assert c.post("/api/devlog/ingest", json=BODY).status_code == 401
        ok = c.post("/api/devlog/ingest", json=BODY, headers={"X-Devlog-Token": TOKEN})
        assert ok.status_code == 200 and ok.json()["code"] == 200


def test_ingest_rejects_unknown_fields(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    with client(db) as c:
        assert c.post("/api/devlog/ingest", json={**BODY, "transcript": "x"}, headers={"X-Devlog-Token": TOKEN}).status_code == 422


def test_user_endpoints_require_permission(db):
    with client(db, permissions=()) as c:
        assert c.get("/api/devlog/summary", params={"start": "2026-11-17", "end": "2026-11-23"}).status_code == 403
    with client(db) as c:
        assert c.get("/api/devlog/summary", params={"start": "2026-11-17", "end": "2026-11-23"}).json()["data"]["kpis"]["dev"] == 0
        assert c.get("/api/devlog/health").json()["data"]["is_stale"] is True
        assert c.get("/api/devlog/pending").json()["data"]["items"] == []


def test_machine_release_backfill_and_list(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    rel = {"revision": "d" * 40, "release_id": "backfill-dddddddddddd", "scope": "office-and-cloud",
           "released_at": "2026-11-20T21:56:00"}
    with client(db) as c:
        h = {"X-Devlog-Token": TOKEN}
        monkeypatch.setattr(get_settings(), "DEVLOG_BACKFILL_ENABLED", False)
        assert c.post("/api/devlog/machine/releases", json={"items": [rel]}, headers=h).status_code == 403
        monkeypatch.setattr(get_settings(), "DEVLOG_BACKFILL_ENABLED", True)
        assert c.post("/api/devlog/machine/releases", json={"items": [rel]}, headers=h).json()["data"] == {"recorded": 1}
        assert c.get("/api/devlog/machine/releases", headers=h).json()["data"]["items"][0]["source"] == "backfill"
