"""Real credential + bounded transport + durable receiver HTTP contracts."""
import gzip
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.alibaba_feed.errors import FeedError
from app.alibaba_feed.models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedPilot, AlibabaFeedSource
from app.alibaba_feed.router import router
from app.alibaba_feed.transport import read_json_body
from app.alibaba_feed.worker import process_next_batch
from app.core.config import get_settings
from app.core.database import get_db
from app.integration.schemas import IntegrationAppCreate
from app.integration.service import create_app
from app.alibaba_feed.source_service import SourceCreate, create_source
from tests.test_alibaba_feed_auth import feed, enable  # noqa: F401
from tests.test_alibaba_feed_core import payload, raw


@pytest.fixture
def api(feed):
    db, issued, source, role = feed
    for model in (AlibabaFeedBatch, AlibabaFeedItem):
        model.__table__.create(db.get_bind())
    enable(db, source)
    pilot = db.get(AlibabaFeedPilot, 1)
    pilot.enabled = True
    pilot.source_id = db.query(AlibabaFeedSource.id).filter_by(source_account_uid="shop-a").scalar()
    pilot.user_id = 1
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/alibaba-feed/v1")
    app.dependency_overrides[get_db] = lambda: db
    headers = {"Authorization": "Bearer " + issued["token"], "Idempotency-Key": "run-a", "Content-Type": "application/json"}
    return TestClient(app), db, headers, role


def test_http_roundtrip_replay_conflict_and_safe_receipt(api):
    client, db, headers, _ = api
    first = client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers)
    assert first.status_code == 202, first.text
    receipt = first.json()["data"]
    assert receipt["processing_state"] == "queued" and not receipt["replayed"]
    assert db.query(AlibabaFeedBatch).one().raw_body == raw(payload())
    assert first.headers["location"] == receipt["status_url"]
    replay = client.post("/api/alibaba-feed/v1/batches", content=json.dumps(payload(), indent=2).encode(), headers=headers)
    assert replay.status_code == 200 and replay.json()["data"]["batch_id"] == receipt["batch_id"]
    changed = payload()
    changed["run"]["window"]["start"] = "2026-11-04T04:00:00+08:00"
    assert client.post("/api/alibaba-feed/v1/batches", content=raw(changed), headers=headers).status_code == 409
    assert db.query(AlibabaFeedBatch).count() == 1
    assert process_next_batch(db)
    for path in (receipt["status_url"], "/api/alibaba-feed/v1/runs/run-a"):
        result = client.get(path, headers=headers)
        assert result.status_code == 200
        assert result.json()["data"]["processing_state"] == "completed_with_issues"
        assert result.json()["data"]["outcomes"]["current_updated"] == 1
        assert result.json()["data"]["eligibility"]["ai_eligible"] == 0
        assert "Synthetic" not in result.text


def test_http_scope_and_source_isolation(api):
    client, db, headers, _ = api
    first = client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers).json()["data"]
    second = create_app(db, IntegrationAppCreate(name="Other", owner_user_id=1,
                        scopes=["alibaba_feed:read", "alibaba_feed:write"]), created_by=99)
    create_source(db, SourceCreate(source_account_uid="shop-b", integration_app_id=second["id"],
                                  name="Other", ingest_enabled=True, consent_state="authorized"))
    other = {"Authorization": "Bearer " + second["token"]}
    for path in (first["status_url"], "/api/alibaba-feed/v1/runs/run-a"):
        response = client.get(path, headers=other)
        assert response.status_code == 403 and first["batch_id"] not in response.text
    invoice = create_app(db, IntegrationAppCreate(name="Invoice", owner_user_id=1), created_by=99)
    response = client.post("/api/alibaba-feed/v1/batches", content=raw(payload()),
                           headers={**headers, "Authorization": "Bearer " + invoice["token"]})
    assert response.status_code == 403
    assert client.get(first["status_url"]).status_code == 401


def test_feature_gate_and_backpressure_replay(api, monkeypatch):
    client, db, headers, _ = api
    settings = get_settings()
    monkeypatch.setattr(settings, "ALIBABA_FEED_SOURCE_PENDING_LIMIT", 1)
    assert client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers).status_code == 202
    again = client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers)
    assert again.status_code == 200 and again.json()["data"]["replayed"]
    blocked = client.post("/api/alibaba-feed/v1/batches", content=raw(payload("run-b")), headers={**headers, "Idempotency-Key": "run-b"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    db.get(AlibabaFeedPilot, 1).enabled = False
    db.commit()
    disabled = client.get("/api/alibaba-feed/v1/runs/run-a", headers=headers)
    assert disabled.status_code == 503 and disabled.json()["data"]["error_code"] == "FEED_DISABLED"
    assert settings.CLIENT_DESK_ENABLED is False


@pytest.mark.parametrize("body,extra,status,code", [
    (b'{}', {"Content-Type": "text/plain"}, 415, "JSON_CONTENT_TYPE_REQUIRED"),
    (b'{}', {"Content-Encoding": "br"}, 415, "CONTENT_ENCODING_UNSUPPORTED"),
    (b'not-gzip', {"Content-Encoding": "gzip"}, 400, "GZIP_INVALID"),
    (b'{"secret":"DO_NOT_ECHO","secret":2}', {}, 400, "MALFORMED_JSON"),
    (b'{}', {"Idempotency-Key": "wrong"}, 422, "SCHEMA_UNSUPPORTED"),
])
def test_http_rejects_without_body_echo(api, body, extra, status, code):
    client, db, headers, _ = api
    response = client.post("/api/alibaba-feed/v1/batches", content=body, headers={**headers, **extra})
    assert response.status_code == status
    assert response.json()["data"]["error_code"] == code
    assert "DO_NOT_ECHO" not in response.text and db.query(AlibabaFeedBatch).count() == 0
    assert response.headers["x-request-id"] == response.json()["data"]["request_id"]


def test_gzip_upload(api):
    client, _, headers, _ = api
    response = client.post("/api/alibaba-feed/v1/batches", content=gzip.compress(raw(payload())),
                           headers={**headers, "Content-Encoding": "gzip"})
    assert response.status_code == 202


async def stream_body(body, *, encoding="gzip", chunk_size=7, **limits):
    settings = SimpleNamespace(ALIBABA_FEED_MAX_BODY_BYTES=1000, ALIBABA_FEED_MAX_COMPRESSED_BYTES=1000,
                               ALIBABA_FEED_MAX_RATIO=100)
    for key, value in limits.items():
        setattr(settings, key, value)
    chunks = [body[i:i + chunk_size] for i in range(0, len(body), chunk_size)] or [b""]
    async def receive():
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
    request = Request({"type": "http", "headers": [(b"content-type", b"application/json"),
                      (b"content-encoding", encoding.encode())]}, receive)
    return await read_json_body(request, settings)


@pytest.mark.parametrize("body,limits,code", [
    (gzip.compress(b"a" * 2000), {}, "PAYLOAD_TOO_LARGE"),
    (gzip.compress(b"a" * 500), {"ALIBABA_FEED_MAX_RATIO": 2}, "COMPRESSION_RATIO_EXCEEDED"),
    (gzip.compress(b"a"), {"ALIBABA_FEED_MAX_COMPRESSED_BYTES": 10}, "PAYLOAD_TOO_LARGE"),
    (gzip.compress(b"a")[:-1], {}, "GZIP_INVALID"),
    (gzip.compress(b"a") + gzip.compress(b"b"), {}, "GZIP_INVALID"),
    (gzip.compress(b"a") + b"junk", {}, "GZIP_INVALID"),
])
async def test_streamed_decompression_bounds(body, limits, code):
    with pytest.raises(FeedError, match=code):
        await stream_body(body, **limits)


async def test_streamed_valid_gzip_and_identity():
    assert await stream_body(gzip.compress(b'{"ok":1}')) == b'{"ok":1}'
    assert await stream_body(b'{"ok":1}', encoding="identity") == b'{"ok":1}'


def test_scheduler_does_not_claim_while_pilot_disabled(api):
    client, db, headers, _ = api
    assert client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers).status_code == 202
    db.get(AlibabaFeedPilot, 1).enabled = False
    db.commit()
    assert not process_next_batch(db, pilot_only=True)
    assert db.query(AlibabaFeedBatch).one().status == "queued"


def test_pause_after_claim_requeues_without_quarantining(api, monkeypatch):
    from app.alibaba_feed import worker

    client, db, headers, _ = api
    assert client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers).status_code == 202
    real_claim = worker.claim_batch

    def claim_then_pause(session, **kwargs):
        claim = real_claim(session, **kwargs)
        db.get(AlibabaFeedPilot, 1).enabled = False
        db.commit()
        return claim

    with monkeypatch.context() as patch:
        patch.setattr(worker, "claim_batch", claim_then_pause)
        assert not worker.process_next_batch(db, pilot_only=True)
    batch = db.query(AlibabaFeedBatch).one()
    assert batch.status == "queued" and batch.attempts == 0 and batch.lease_token is None
    assert db.query(AlibabaFeedItem).count() == 0
    db.get(AlibabaFeedPilot, 1).enabled = True
    db.commit()
    assert worker.process_next_batch(db, pilot_only=True)
    assert db.query(AlibabaFeedItem).one().is_current


def test_pause_during_failed_attempt_does_not_write_a_terminal_receipt(api, monkeypatch):
    from app.alibaba_feed import worker

    client, db, headers, _ = api
    assert client.post("/api/alibaba-feed/v1/batches", content=raw(payload()), headers=headers).status_code == 202
    db.query(AlibabaFeedBatch).one().attempts = 2
    db.commit()

    def fail_after_pause(session, *args, **kwargs):
        db.get(AlibabaFeedPilot, 1).enabled = False
        db.commit()
        raise ValueError("Synthetic normalization failure")

    monkeypatch.setattr(worker, "process_item", fail_after_pause)
    assert not worker.process_next_batch(db, pilot_only=True)
    batch = db.query(AlibabaFeedBatch).one()
    assert batch.status == "queued" and batch.attempts == 2 and batch.finished_at is None


def test_production_router_prefixes_and_scheduler_independence(monkeypatch):
    from app.routers import register_routers
    from app.schedulers.registry import _register_jobs
    app = FastAPI()
    register_routers(app)
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", ())}
    assert ("/api/alibaba-feed/v1/batches", "POST") in paths
    assert ("/api/alibaba-feed/v1/runs/{run_id}", "GET") in paths
    assert ("/api/alibaba-feed/v1/batches/{batch_id}", "GET") in paths
    assert ("/api/alibaba-feed/sources", "POST") in paths
    assert ("/api/alibaba-feed/sources/{source_uid}", "PATCH") in paths
    settings = get_settings()
    monkeypatch.setattr(settings, "CLIENT_DESK_ENABLED", False)
    class Collector:
        def __init__(self):
            self.ids = set()
        def add_job(self, *args, **kwargs):
            self.ids.add(kwargs["id"])
    scheduler = Collector()
    _register_jobs(scheduler, outbound_mode="legacy")
    assert "alibaba_feed_worker" in scheduler.ids
    assert not any(job.startswith("client_desk_") for job in scheduler.ids)
